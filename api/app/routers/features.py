"""CRUD obiektów warstw PostGIS (GeoJSON).

Zapis idzie bezpośrednio do PostGIS (nie przez WFS-T), co pozwala:
  * wymusić zasięg przestrzenny użytkownika (ST_CoveredBy) przy insert/update/delete,
  * walidować pola wg konfiguracji formularza z projektu QGIS (tylko edytowalne pola),
  * obsłużyć relacje rodzic–dziecko i dziennik zmian w jednej transakcji.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import sql
from pydantic import BaseModel

from ..config import get_settings
from ..db import layer_conn, portal_conn
from ..permissions import ProjectContext, load_project_context, user_extent_ewkb
from ..qgsproject import LayerDef
from ..security import CurrentUser, optional_user, require_user

router = APIRouter(prefix="/api/projects/{slug}/layers/{layer_id}/features", tags=["features"])

MAX_FEATURES = 5000


class FeatureIn(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = {}


def _srid(crs: str | None) -> int:
    if crs and crs.upper().startswith("EPSG:"):
        return int(crs.split(":")[1])
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nieobsługiwany układ: {crs}")


def _table(lyr: LayerDef) -> sql.Composed:
    return sql.Identifier(lyr.pg.schema, lyr.pg.table)


def _select_list(lyr: LayerDef, out_srid: int) -> sql.Composed:
    names = [f.name for f in lyr.fields if f.widget != "Hidden" and f.name != lyr.pg.geometry_column]
    parts = [sql.SQL("{}::text AS __pk").format(sql.Identifier(lyr.pg.key))]
    if lyr.pg.geometry_column:
        parts.append(sql.SQL("ST_AsGeoJSON(ST_Transform({g}, {s}), 9)::json AS __geom").format(
            g=sql.Identifier(lyr.pg.geometry_column), s=sql.Literal(out_srid)))
    if names:
        # jsonb_build_object nie ma limitu 100 argumentów jak json_build_object — łączymy po 50 pól
        chunks = [names[i:i + 50] for i in range(0, len(names), 50)]
        objs = [sql.SQL("jsonb_build_object({})").format(sql.SQL(", ").join(
            sql.SQL("{}, {}").format(sql.Literal(n), sql.Identifier(n)) for n in chunk)) for chunk in chunks]
        parts.append(sql.SQL(" || ").join(objs) + sql.SQL(" AS __props"))
    return sql.SQL(", ").join(parts)


def _row_to_feature(row: dict) -> dict:
    return {"type": "Feature", "id": row["__pk"], "geometry": row.get("__geom"),
            "properties": row.get("__props") or {}}


def _base_filter(lyr: LayerDef) -> sql.Composable:
    # Filtr z definicji warstwy QGIS (sql=...) — zaufany, bo pochodzi z projektu administratora.
    return sql.SQL("({})").format(sql.SQL(lyr.pg.sql_filter)) if lyr.pg.sql_filter else sql.SQL("true")


def _extent_condition(lyr: LayerDef, geom_expr: sql.Composable, extent: bytes | None) -> sql.Composable:
    if extent is None or not lyr.pg.geometry_column:
        return sql.SQL("true")
    return sql.SQL("ST_Intersects(ST_Transform({g}, {es}), ST_GeomFromEWKB({e}))").format(
        g=geom_expr, es=sql.Literal(get_settings().extents_srid), e=sql.Literal(extent))


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


async def _check_geometry_in_extent(conn, lyr: LayerDef, geom: sql.Composable, extent: bytes | None):
    if extent is None:
        return
    ok = await (await conn.execute(sql.SQL(
        "SELECT ST_CoveredBy(ST_Transform({g}, {es}), ST_GeomFromEWKB({e})) AS ok").format(
        g=geom, es=sql.Literal(get_settings().extents_srid), e=sql.Literal(extent)))).fetchone()
    if not ok["ok"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Geometria wykracza poza przydzielony zasięg")


async def _audit(ctx: ProjectContext, layer_id: str, pk: str, action: str, old: Any, new: Any):
    async with portal_conn() as conn:
        await conn.execute(
            """INSERT INTO portal.audit_log (user_id, project_id, layer_id, feature_pk, action, old_data, new_data)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ctx.user.id if ctx.user else None, ctx.id, layer_id, pk, action,
             json.dumps(old, default=str) if old is not None else None,
             json.dumps(new, default=str) if new is not None else None),
        )


async def _fetch_one(conn, lyr: LayerDef, pk: str, srid: int, extent: bytes | None) -> dict | None:
    g = sql.Identifier(lyr.pg.geometry_column) if lyr.pg.geometry_column else sql.SQL("NULL")
    q = sql.SQL("SELECT {cols} FROM {t} WHERE {k}::text = {pk} AND {f} AND {ext}").format(
        cols=_select_list(lyr, srid), t=_table(lyr), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk),
        f=_base_filter(lyr), ext=_extent_condition(lyr, g, extent))
    return await (await conn.execute(q)).fetchone()


# ---------------------------------------------------------------------------- endpointy


@router.get("")
async def list_features(
    slug: str, layer_id: str,
    bbox: str | None = Query(None, description="minx,miny,maxx,maxy w układzie crs"),
    crs: str = Query("EPSG:3857"),
    limit: int = Query(1000, le=MAX_FEATURES),
    user: CurrentUser | None = Depends(optional_user),
):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    if not lyr.pg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa nie jest warstwą PostGIS")
    srid = _srid(crs)
    extent = await user_extent_ewkb(user, "view")
    g = sql.Identifier(lyr.pg.geometry_column) if lyr.pg.geometry_column else None

    where = [_base_filter(lyr), _extent_condition(lyr, g, extent) if g else sql.SQL("true")]
    if bbox and g:
        try:
            minx, miny, maxx, maxy = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Błędny bbox") from exc
        where.append(sql.SQL("{g} && ST_Transform(ST_MakeEnvelope({a},{b},{c},{d},{s}), {ls})").format(
            g=g, a=sql.Literal(minx), b=sql.Literal(miny), c=sql.Literal(maxx), d=sql.Literal(maxy),
            s=sql.Literal(srid), ls=sql.Literal(lyr.pg.srid or srid)))

    q = sql.SQL("SELECT {cols} FROM {t} WHERE {w} LIMIT {lim}").format(
        cols=_select_list(lyr, srid), t=_table(lyr), w=sql.SQL(" AND ").join(where), lim=sql.Literal(limit))
    async with layer_conn(lyr.pg.conninfo) as conn:
        rows = await (await conn.execute(q)).fetchall()
    return {"type": "FeatureCollection", "features": [_row_to_feature(r) for r in rows],
            "truncated": len(rows) >= limit}


@router.get("/{pk}")
async def get_feature(slug: str, layer_id: str, pk: str, crs: str = "EPSG:3857",
                      user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    async with layer_conn(lyr.pg.conninfo) as conn:
        row = await _fetch_one(conn, lyr, pk, _srid(crs), await user_extent_ewkb(user, "view"))
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
    extent = await user_extent_ewkb(user, "edit")

    cols = [sql.Identifier(k) for k in values]
    vals: list[sql.Composable] = [sql.Literal(v) for v in values.values()]
    if lyr.pg.geometry_column:
        if body.geometry is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak geometrii")
        geom = _geom_sql(lyr, body.geometry, srid)
        cols.append(sql.Identifier(lyr.pg.geometry_column))
        vals.append(geom)

    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        if lyr.pg.geometry_column:
            await _check_geometry_in_extent(conn, lyr, geom, extent)
        q = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) RETURNING {k}::text AS pk").format(
            t=_table(lyr), c=sql.SQL(", ").join(cols), v=sql.SQL(", ").join(vals), k=sql.Identifier(lyr.pg.key))
        if not cols:
            q = sql.SQL("INSERT INTO {t} DEFAULT VALUES RETURNING {k}::text AS pk").format(
                t=_table(lyr), k=sql.Identifier(lyr.pg.key))
        pk = (await (await conn.execute(q)).fetchone())["pk"]
        row = await _fetch_one(conn, lyr, pk, srid, None)
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
    extent = await user_extent_ewkb(user, "edit")

    sets = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Literal(v)) for k, v in values.items()]
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        old = await _fetch_one(conn, lyr, pk, srid, extent)   # istniejący obiekt musi być w zasięgu
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu lub poza zasięgiem")
        if body.geometry is not None and lyr.pg.geometry_column:
            geom = _geom_sql(lyr, body.geometry, srid)
            await _check_geometry_in_extent(conn, lyr, geom, extent)
            sets.append(sql.SQL("{} = {}").format(sql.Identifier(lyr.pg.geometry_column), geom))
        if sets:
            await conn.execute(sql.SQL("UPDATE {t} SET {s} WHERE {k}::text = {pk}").format(
                t=_table(lyr), s=sql.SQL(", ").join(sets), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk)))
        new = await _fetch_one(conn, lyr, pk, srid, None)
    await _audit(ctx, layer_id, pk, "update", _row_to_feature(old), _row_to_feature(new))
    return _row_to_feature(new)


@router.delete("/{pk}", status_code=204)
async def delete_feature(slug: str, layer_id: str, pk: str, user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "delete")
    extent = await user_extent_ewkb(user, "edit")
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        old = await _fetch_one(conn, lyr, pk, 3857, extent)
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu lub poza zasięgiem")
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
    extent = await user_extent_ewkb(user, "view")
    out = []
    async with layer_conn(lyr.pg.conninfo) as conn:
        g = sql.Identifier(lyr.pg.geometry_column) if lyr.pg.geometry_column else sql.SQL("NULL")
        me = await (await conn.execute(sql.SQL("SELECT * FROM {t} WHERE {k}::text = {pk} AND {f} AND {e}").format(
            t=_table(lyr), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk), f=_base_filter(lyr),
            e=_extent_condition(lyr, g, extent)))).fetchone()
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
                sql.SQL("{} = {}").format(sql.Identifier(c if as_parent else p), sql.Literal(me[p if as_parent else c]))
                for p, c in rel.pairs)
            og = sql.Identifier(other.pg.geometry_column) if other.pg.geometry_column else None
            q = sql.SQL("SELECT {cols} FROM {t} WHERE {c} AND {f} AND {e} LIMIT 500").format(
                cols=_select_list(other, srid), t=_table(other), c=cond, f=_base_filter(other),
                e=_extent_condition(other, og, extent) if og else sql.SQL("true"))
            rows = await (await conn.execute(q)).fetchall()
            out.append({"relation": rel.id, "name": rel.name, "direction": "child" if as_parent else "parent",
                        "layer_id": other_id, "pairs": rel.pairs,
                        "features": [_row_to_feature(r) for r in rows]})
    return out
