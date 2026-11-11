"""CRUD obiektów warstw PostGIS (GeoJSON).

Zapis idzie bezpośrednio do PostGIS (nie przez WFS-T), co pozwala:
  * wymusić zakres danych użytkownika (app/scope.py) przy odczycie i przy insert/update/delete —
    edycja sprawdzana przed zmianą i po niej, w tej samej transakcji (przesunięcie obiektu albo
    zmiana kodu poza własny zakres cofa zapis),
  * walidować pola wg konfiguracji formularza z projektu QGIS (tylko edytowalne pola),
  * obsłużyć relacje rodzic–dziecko i dziennik zmian w jednej transakcji.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import sql
from pydantic import BaseModel

from ..db import layer_conn, portal_conn
from ..permissions import ProjectContext, load_project_context
from ..qgsproject import LayerDef
from ..scope import Mode, T, col, row_filter, single_code
from ..scope import base_filter as _base_filter
from ..scope import table as _table
from ..security import CurrentUser, optional_user, require_user

router = APIRouter(prefix="/api/projects/{slug}/layers/{layer_id}/features", tags=["features"])

MAX_FEATURES = 5000
OUT_OF_SCOPE = "Obiekt poza Twoim zakresem danych"


class FeatureIn(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = {}


def _srid(crs: str | None) -> int:
    if crs and crs.upper().startswith("EPSG:"):
        return int(crs.split(":")[1])
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nieobsługiwany układ: {crs}")


def _visible_names(lyr: LayerDef) -> list[str]:
    return [f.name for f in lyr.fields if f.widget != "Hidden" and f.name != lyr.pg.geometry_column]


def _select_list(lyr: LayerDef, out_srid: int, geometry: bool = True) -> sql.Composed:
    names = _visible_names(lyr)
    parts = [sql.SQL("{}::text AS __pk").format(col(T, lyr.pg.key))]
    if lyr.pg.geometry_column and geometry:
        parts.append(sql.SQL("ST_AsGeoJSON(ST_Transform({g}, {s}), 9)::json AS __geom").format(
            g=col(T, lyr.pg.geometry_column), s=sql.Literal(out_srid)))
    if names:
        # jsonb_build_object nie ma limitu 100 argumentów jak json_build_object — łączymy po 50 pól
        chunks = [names[i:i + 50] for i in range(0, len(names), 50)]
        objs = [sql.SQL("jsonb_build_object({})").format(sql.SQL(", ").join(
            sql.SQL("{}, {}").format(sql.Literal(n), col(T, n)) for n in chunk)) for chunk in chunks]
        parts.append(sql.SQL(" || ").join(objs) + sql.SQL(" AS __props"))
    return sql.SQL(", ").join(parts)


def _row_to_feature(row: dict) -> dict:
    return {"type": "Feature", "id": row["__pk"], "geometry": row.get("__geom"),
            "properties": row.get("__props") or {}}


def _writable_values(lyr: LayerDef, props: dict[str, Any]) -> dict[str, Any]:
    allowed = {f.name: f for f in lyr.fields if f.editable and f.name != lyr.pg.key}
    unknown = set(props) - set(allowed) - {lyr.pg.key}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Pola niedozwolone: {sorted(unknown)}")
    return {k: v for k, v in props.items() if k in allowed}


def _geom_sql(lyr: LayerDef, geometry: dict, in_srid: int) -> sql.Composable:
    target = lyr.pg.srid or 0
    g = sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON({}), {})").format(
        sql.Literal(json.dumps(geometry)), sql.Literal(in_srid))
    if target:
        g = sql.SQL("ST_Transform({}, {})").format(g, sql.Literal(target))
    # Ujednolicenie typu (Polygon -> MultiPolygon itp.), jeśli kolumna jest typu Multi*
    if (lyr.pg.geometry_type or "").upper().startswith("MULTI"):
        g = sql.SQL("ST_Multi({})").format(g)
    return g


def _pk_is(lyr: LayerDef, pk: str) -> sql.Composable:
    return sql.SQL("{}::text = {}").format(col(T, lyr.pg.key), sql.Literal(pk))


async def _audit(ctx: ProjectContext, layer_id: str, pk: str, action: str, old: Any, new: Any):
    async with portal_conn() as conn:
        await conn.execute(
            """INSERT INTO portal.audit_log (user_id, project_id, layer_id, feature_pk, action, old_data, new_data)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ctx.user.id if ctx.user else None, ctx.id, layer_id, pk, action,
             json.dumps(old, default=str) if old is not None else None,
             json.dumps(new, default=str) if new is not None else None),
        )


async def _fetch_one(conn, ctx: ProjectContext | None, lyr: LayerDef, pk: str, srid: int,
                     mode: Mode | None = "view") -> dict | None:
    """Jeden obiekt; mode=None — bez zakresu (odczyt własnego, właśnie zapisanego rekordu)."""
    cond = row_filter(ctx, lyr, T, mode) if ctx is not None and mode else _base_filter(lyr)
    q = sql.SQL("SELECT {cols} FROM {t} AS {a} WHERE {pk} AND {c}").format(
        cols=_select_list(lyr, srid), t=_table(lyr), a=sql.Identifier(*T), pk=_pk_is(lyr, pk), c=cond)
    return await (await conn.execute(q)).fetchone()


async def in_scope(conn, ctx: ProjectContext, lyr: LayerDef, pk: str, mode: Mode = "edit") -> bool:
    q = sql.SQL("SELECT 1 FROM {t} AS {a} WHERE {pk} AND {c}").format(
        t=_table(lyr), a=sql.Identifier(*T), pk=_pk_is(lyr, pk), c=row_filter(ctx, lyr, T, mode))
    return await (await conn.execute(q)).fetchone() is not None


def _autofill_scope(ctx: ProjectContext, lyr: LayerDef, values: dict[str, Any]) -> None:
    """Reguła „atrybut”: puste pole kodu przy jednym kodzie użytkownika — wpisujemy go sami."""
    if lyr.scope_mode == "attribute" and lyr.scope_field and values.get(lyr.scope_field) in (None, ""):
        code = single_code(ctx)
        if code:
            values[lyr.scope_field] = code


def _scope_error(ctx: ProjectContext, lyr: LayerDef) -> HTTPException:
    if lyr.scope_mode == "attribute" and ctx.scope_codes is not None:
        return HTTPException(status.HTTP_403_FORBIDDEN,
                             f"Pole „{lyr.scope_field}” musi mieć jedną z wartości: {', '.join(ctx.scope_codes) or '—'}")
    if lyr.scope_mode == "spatial":
        return HTTPException(status.HTTP_403_FORBIDDEN, "Obiekt musi leżeć w Twoim obszarze (punkt wewnątrz obiektu)")
    return HTTPException(status.HTTP_403_FORBIDDEN, OUT_OF_SCOPE)


# ---------------------------------------------------------------------------- endpointy


@router.get("")
async def list_features(
    slug: str, layer_id: str,
    bbox: str | None = Query(None, description="minx,miny,maxx,maxy w układzie crs"),
    crs: str = Query("EPSG:3857"),
    limit: int = Query(1000, le=MAX_FEATURES),
    offset: int = Query(0, ge=0, description="Stronicowanie (tabela atrybutów)"),
    sort: str | None = Query(None, description="Pole sortowania (widoczne pole warstwy)"),
    desc: bool = False,
    q: str | None = Query(None, max_length=200, description="Szukaj w polach (fragment tekstu)"),
    geometry: bool = Query(True, description="false = bez geometrii (tabela atrybutów)"),
    total: bool = Query(False, description="Zwróć łączną liczbę rekordów spełniających warunki"),
    user: CurrentUser | None = Depends(optional_user),
):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    if not lyr.pg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa nie jest warstwą PostGIS")
    srid = _srid(crs)
    names = _visible_names(lyr)
    where = [row_filter(ctx, lyr)]
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(sql.SQL("({})").format(sql.SQL(" OR ").join(
            sql.SQL("{}::text ILIKE {}").format(col(T, n), sql.Literal(pattern))
            for n in [lyr.pg.key, *names])))
    if bbox and lyr.pg.geometry_column:
        try:
            minx, miny, maxx, maxy = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Błędny bbox") from exc
        where.append(sql.SQL("{g} && ST_Transform(ST_MakeEnvelope({a},{b},{c},{d},{s}), {ls})").format(
            g=col(T, lyr.pg.geometry_column), a=sql.Literal(minx), b=sql.Literal(miny), c=sql.Literal(maxx),
            d=sql.Literal(maxy), s=sql.Literal(srid), ls=sql.Literal(lyr.pg.srid or srid)))

    if sort is not None and sort not in names and sort != lyr.pg.key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nie można sortować po polu {sort}")
    order = [sql.SQL("{} {} NULLS LAST").format(col(T, sort), sql.SQL("DESC" if desc else "ASC"))] if sort else []
    order.append(col(T, lyr.pg.key))                  # stała kolejność przy stronicowaniu
    cond = sql.SQL(" AND ").join(where)
    query = sql.SQL("SELECT {cols} FROM {t} AS {a} WHERE {w} ORDER BY {o} LIMIT {lim} OFFSET {off}").format(
        cols=_select_list(lyr, srid, geometry), t=_table(lyr), a=sql.Identifier(*T), w=cond,
        o=sql.SQL(", ").join(order), lim=sql.Literal(limit), off=sql.Literal(offset))
    async with layer_conn(lyr.pg.conninfo) as conn:
        rows = await (await conn.execute(query)).fetchall()
        count = None
        if total:
            count = (await (await conn.execute(sql.SQL("SELECT count(*) AS n FROM {t} AS {a} WHERE {w}").format(
                t=_table(lyr), a=sql.Identifier(*T), w=cond))).fetchone())["n"]
    out = {"type": "FeatureCollection", "features": [_row_to_feature(r) for r in rows],
           "truncated": len(rows) >= limit}
    if count is not None:
        out["total"] = count
    return out


@router.get("/{pk}")
async def get_feature(slug: str, layer_id: str, pk: str, crs: str = "EPSG:3857",
                      user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    async with layer_conn(lyr.pg.conninfo) as conn:
        row = await _fetch_one(conn, ctx, lyr, pk, _srid(crs))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
    return _row_to_feature(row)


@router.post("", status_code=201)
async def create_feature(slug: str, layer_id: str, body: FeatureIn, crs: str = "EPSG:3857",
                         user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "insert")
    srid = _srid(crs)
    values = _writable_values(lyr, body.properties)
    _autofill_scope(ctx, lyr, values)

    cols = [sql.Identifier(k) for k in values]
    vals: list[sql.Composable] = [sql.Literal(v) for v in values.values()]
    if lyr.pg.geometry_column:
        if body.geometry is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak geometrii")
        cols.append(sql.Identifier(lyr.pg.geometry_column))
        vals.append(_geom_sql(lyr, body.geometry, srid))

    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        q = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) RETURNING {k}::text AS pk").format(
            t=_table(lyr), c=sql.SQL(", ").join(cols), v=sql.SQL(", ").join(vals), k=sql.Identifier(lyr.pg.key))
        if not cols:
            q = sql.SQL("INSERT INTO {t} DEFAULT VALUES RETURNING {k}::text AS pk").format(
                t=_table(lyr), k=sql.Identifier(lyr.pg.key))
        pk = (await (await conn.execute(q)).fetchone())["pk"]
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise _scope_error(ctx, lyr)          # wyjątek w transakcji = wycofanie wstawienia
        row = await _fetch_one(conn, None, lyr, pk, srid, None)
    feature = _row_to_feature(row)
    await _audit(ctx, layer_id, pk, "insert", None, feature)
    return feature


@router.patch("/{pk}")
async def update_feature(slug: str, layer_id: str, pk: str, body: FeatureIn, crs: str = "EPSG:3857",
                         user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "update")
    srid = _srid(crs)
    values = _writable_values(lyr, body.properties)

    sets = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Literal(v)) for k, v in values.items()]
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        old = await _fetch_one(conn, ctx, lyr, pk, srid, "view")
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} — tylko podgląd")
        if body.geometry is not None and lyr.pg.geometry_column:
            sets.append(sql.SQL("{} = {}").format(sql.Identifier(lyr.pg.geometry_column),
                                                 _geom_sql(lyr, body.geometry, srid)))
        if sets:
            await conn.execute(sql.SQL("UPDATE {t} SET {s} WHERE {k}::text = {pk}").format(
                t=_table(lyr), s=sql.SQL(", ").join(sets), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk)))
            if not await in_scope(conn, ctx, lyr, pk, "edit"):
                raise _scope_error(ctx, lyr)
        new = await _fetch_one(conn, None, lyr, pk, srid, None)
    await _audit(ctx, layer_id, pk, "update", _row_to_feature(old), _row_to_feature(new))
    return _row_to_feature(new)


@router.delete("/{pk}", status_code=204)
async def delete_feature(slug: str, layer_id: str, pk: str, user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "delete")
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        old = await _fetch_one(conn, ctx, lyr, pk, 3857, "view")
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} — tylko podgląd")
        # Relacje typu "Composition" z projektu QGIS: usuń dzieci razem z rodzicem.
        for rel in ctx.project.relations:
            if rel.parent_layer != layer_id or rel.strength != "Composition":
                continue
            child = ctx.require(rel.child_layer, "delete")
            parent_vals = await (await conn.execute(sql.SQL("SELECT {c} FROM {t} WHERE {k}::text = {pk}").format(
                c=sql.SQL(", ").join(sql.Identifier(p) for p, _ in rel.pairs), t=_table(lyr),
                k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk)))).fetchone()
            cond = sql.SQL(" AND ").join(
                sql.SQL("{} = {}").format(sql.Identifier(c), sql.Literal(parent_vals[p])) for p, c in rel.pairs)
            await conn.execute(sql.SQL("DELETE FROM {t} WHERE {c}").format(t=_table(child), c=cond))
        await conn.execute(sql.SQL("DELETE FROM {t} WHERE {k}::text = {pk}").format(
            t=_table(lyr), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk)))
    await _audit(ctx, layer_id, pk, "delete", _row_to_feature(old), None)


@router.get("/{pk}/related")
async def related_features(slug: str, layer_id: str, pk: str, crs: str = "EPSG:3857",
                           user: CurrentUser | None = Depends(optional_user)):
    """Obiekty powiązane relacjami z projektu QGIS (dzieci i rodzice) — do formularza z zakładkami."""
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    srid = _srid(crs)
    out = []
    async with layer_conn(lyr.pg.conninfo) as conn:
        me = await (await conn.execute(sql.SQL("SELECT {a}.* FROM {t} AS {a} WHERE {pk} AND {c}").format(
            t=_table(lyr), a=sql.Identifier(*T), pk=_pk_is(lyr, pk), c=row_filter(ctx, lyr)))).fetchone()
        if me is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        for rel in ctx.project.relations:
            if layer_id not in (rel.parent_layer, rel.child_layer):
                continue
            as_parent = rel.parent_layer == layer_id
            other_id = rel.child_layer if as_parent else rel.parent_layer
            if not ctx.perms(other_id).view:
                continue
            other = ctx.layer(other_id)
            if not other.pg or other.pg.conninfo != lyr.pg.conninfo:
                continue  # relacje między bazami — poza zakresem v1
            cond = sql.SQL(" AND ").join(
                sql.SQL("{} = {}").format(col(T, c if as_parent else p), sql.Literal(me[p if as_parent else c]))
                for p, c in rel.pairs)
            q = sql.SQL("SELECT {cols} FROM {t} AS {a} WHERE {c} AND {f} LIMIT 500").format(
                cols=_select_list(other, srid), t=_table(other), a=sql.Identifier(*T), c=cond,
                f=row_filter(ctx, other))
            rows = await (await conn.execute(q)).fetchall()
            out.append({"relation": rel.id, "name": rel.name, "direction": "child" if as_parent else "parent",
                        "layer_id": other_id, "pairs": rel.pairs,
                        "features": [_row_to_feature(r) for r in rows]})
    return out
