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
import uuid
from contextvars import ContextVar
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


class SplitIn(BaseModel):
    line: dict[str, Any]                 # linia podziału (GeoJSON LineString w układzie crs)
    pks: list[str] | None = None         # None = wszystkie obiekty, które linia dzieli (w zakresie edycji)
    dry_run: bool = False                # tylko lista obiektów do podziału (potwierdzenie w WebUI)


SPLIT_LIMIT = 50


class FeatureIn(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = {}


# Dziennik zmian: wpisy jednego żądania (np. podział: zmiana + nowe części) dostają wspólny `op`
# (cofanie całej operacji), a `srid` mówi, w jakim układzie zapisano geometrię w old/new_data.
# Każde żądanie FastAPI działa we własnej kopii kontekstu, więc wartości nie przeciekają między żądaniami.
_AUDIT_OP: ContextVar[str | None] = ContextVar("audit_op", default=None)
AUDIT_SRID: ContextVar[int | None] = ContextVar("audit_srid", default=None)


def _srid(crs: str | None) -> int:
    if crs and crs.upper().startswith("EPSG:"):
        srid = int(crs.split(":")[1])
        AUDIT_SRID.set(srid)
        return srid
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


def _writable_values(lyr: LayerDef, props: dict[str, Any], with_key: bool = False) -> dict[str, Any]:
    """Pola do zapisu. with_key (nowy obiekt): podana wartość klucza trafia do INSERT — klucz naturalny
    (np. identyfikator działki z wtyczki); pusty klucz zostaje dla domyślnej wartości z bazy (serial)."""
    allowed = {f.name: f for f in lyr.fields if f.editable and f.name != lyr.pg.key}
    unknown = set(props) - set(allowed) - {lyr.pg.key}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Pola niedozwolone: {sorted(unknown)}")
    values = {k: v for k, v in props.items() if k in allowed}
    if with_key and props.get(lyr.pg.key) not in (None, ""):
        values[lyr.pg.key] = props[lyr.pg.key]
    return values


def _geom_sql(lyr: LayerDef, geometry: dict, in_srid: int, multi: bool = True) -> sql.Composable:
    """GeoJSON z klienta → geometria w układzie warstwy; multi=False dla szkiców (linia podziału)."""
    target = lyr.pg.srid or 0
    g = sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON({}), {})").format(
        sql.Literal(json.dumps(geometry)), sql.Literal(in_srid))
    if target:
        g = sql.SQL("ST_Transform({}, {})").format(g, sql.Literal(target))
    # Ujednolicenie typu (Polygon -> MultiPolygon itp.), jeśli kolumna jest typu Multi*
    if multi:
        g = _as_column_type(lyr, g)
    return g


def _as_column_type(lyr: LayerDef, g: sql.Composable) -> sql.Composable:
    if (lyr.pg.geometry_type or "").upper().startswith("MULTI"):
        return sql.SQL("ST_Multi({})").format(g)
    return g


def _pk_is(lyr: LayerDef, pk: str) -> sql.Composable:
    return sql.SQL("{}::text = {}").format(col(T, lyr.pg.key), sql.Literal(pk))


async def _audit(ctx: ProjectContext, layer_id: str, pk: str, action: str, old: Any, new: Any):
    op = _AUDIT_OP.get()
    if op is None:
        op = str(uuid.uuid4())
        _AUDIT_OP.set(op)
    async with portal_conn() as conn:
        await conn.execute(
            """INSERT INTO portal.audit_log (user_id, project_id, layer_id, feature_pk, action, old_data, new_data,
                                             op, srid)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ctx.user.id if ctx.user else None, ctx.id, layer_id, pk, action,
             json.dumps(old, default=str) if old is not None else None,
             json.dumps(new, default=str) if new is not None else None,
             op if action in ("insert", "update", "delete") else None, AUDIT_SRID.get()),
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


@router.get("/{pk:path}")
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
                         cut_from: str | None = Query(None, description="Pierścień wypełniony: obiekt, w którym "
                                                      "nowy obiekt wycina dziurę (ta sama transakcja)"),
                         user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "insert")
    if cut_from is not None:
        lyr = _editable_geometry(ctx, layer_id, "insert", "update", kinds=("Polygon",))
    srid = _srid(crs)
    values = _writable_values(lyr, body.properties, with_key=True)
    _autofill_scope(ctx, lyr, values)

    cols = [sql.Identifier(k) for k in values]
    vals: list[sql.Composable] = [sql.Literal(v) for v in values.values()]
    if lyr.pg.geometry_column:
        if body.geometry is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak geometrii")
        cols.append(sql.Identifier(lyr.pg.geometry_column))
        vals.append(_geom_sql(lyr, body.geometry, srid))

    cut = None
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        if cut_from is not None:
            await ring_target(conn, ctx, lyr, _ring_sql(lyr, body.geometry or {}, srid), cut_from)
        q = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) RETURNING {k}::text AS pk").format(
            t=_table(lyr), c=sql.SQL(", ").join(cols), v=sql.SQL(", ").join(vals), k=sql.Identifier(lyr.pg.key))
        if not cols:
            q = sql.SQL("INSERT INTO {t} DEFAULT VALUES RETURNING {k}::text AS pk").format(
                t=_table(lyr), k=sql.Identifier(lyr.pg.key))
        pk = (await (await conn.execute(q)).fetchone())["pk"]
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise _scope_error(ctx, lyr)          # wyjątek w transakcji = wycofanie wstawienia
        if cut_from is not None:
            hole = sql.SQL("(SELECT {g} FROM {t} AS n WHERE n.{k}::text = {pk})").format(
                g=sql.Identifier(lyr.pg.geometry_column), t=_table(lyr), k=sql.Identifier(lyr.pg.key),
                pk=sql.Literal(pk))
            cut = await _set_geometry(conn, ctx, lyr, cut_from, _as_column_type(lyr, sql.SQL("ST_Difference({}, {})").format(
                col(T, lyr.pg.geometry_column), hole)), srid)
        await check_overlap(conn, ctx, lyr, pk)   # po wycięciu dziury (wypełniony pierścień nie nachodzi na obiekt)
        row = await _fetch_one(conn, None, lyr, pk, srid, None)
    feature = _row_to_feature(row)
    await _audit(ctx, layer_id, pk, "insert", None, feature)
    if cut:
        await _audit(ctx, layer_id, cut_from, "update", *cut)
    return feature


@router.patch("/{pk:path}")
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
            if body.geometry is not None:
                await check_overlap(conn, ctx, lyr, pk)
        new = await _fetch_one(conn, None, lyr, pk, srid, None)
    await _audit(ctx, layer_id, pk, "update", _row_to_feature(old), _row_to_feature(new))
    return _row_to_feature(new)


@router.delete("/{pk:path}", status_code=204)
async def delete_feature(slug: str, layer_id: str, pk: str, user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "delete")
    AUDIT_SRID.set(3857)
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


@router.get("/{pk:path}/related")
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


# ---------------------------------------------------------------------------- podział obiektów


def _measure(g: sql.Composable) -> sql.Composable:
    """Miara części do polityki „proporcjonalnie do geometrii”: powierzchnia albo długość."""
    return sql.SQL("CASE WHEN ST_Dimension({g}) = 2 THEN ST_Area({g}) ELSE ST_Length({g}) END").format(g=g)


def _from_ewkb(lyr: LayerDef, wkb: bytes) -> sql.Composable:
    return _as_column_type(lyr, sql.SQL("ST_GeomFromEWKB({})").format(sql.Literal(wkb)))


async def split_columns(conn, lyr: LayerDef, attr: str = "split_policy") -> list[tuple[str, str]]:
    """Kolumny kopiowane do nowych części: (nazwa, polityka). Bez klucza, geometrii, kolumn
    identity/generowanych/z sekwencją; polityka DefaultValue = kolumna pominięta (domyślna z bazy)."""
    rows = await (await conn.execute(
        """SELECT a.attname AS name, t.typcategory AS cat
             FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
             LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = to_regclass(format('%%I.%%I', %s::text, %s::text)) AND a.attnum > 0
              AND NOT a.attisdropped AND a.attgenerated = '' AND a.attidentity = ''
              AND coalesce(pg_get_expr(d.adbin, d.adrelid), '') NOT LIKE 'nextval(%%'
            ORDER BY a.attnum""", (lyr.pg.schema, lyr.pg.table))).fetchall()
    return split_plan(lyr, [(r["name"], r["cat"]) for r in rows], attr)


def split_plan(lyr: LayerDef, columns: list[tuple[str, str]], attr: str = "split_policy") -> list[tuple[str, str]]:
    """(kolumna, kategoria typu z pg_type) → (kolumna, polityka) dla nowych części / kopii."""
    policy = {f.name: getattr(f, attr) for f in lyr.fields}
    out = []
    for name, cat in columns:
        if name in (lyr.pg.key, lyr.pg.geometry_column):
            continue
        p = policy.get(name, "Duplicate")
        if p == "GeometryRatio" and cat != "N":
            p = "Duplicate"                  # proporcja tylko dla liczb
        if p != "DefaultValue":
            out.append((name, p))
    return out


@router.post("/split")
async def split_features(slug: str, layer_id: str, body: SplitIn, crs: str = "EPSG:3857",
                         user: CurrentUser = Depends(require_user)):
    """Podział obiektów linią (QGIS: „Podziel obiekty”). Największa część zostaje pod starym kluczem
    (zdjęcia, dokumenty i rekordy powiązane przy niej), pozostałe są nowymi obiektami z atrybutami
    według polityk podziału pól z projektu QGIS. Jedna transakcja, kontrola zakresu po zmianie."""
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "update")
    if not ctx.perms(layer_id).insert:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Podział wymaga prawa dodawania obiektów")
    if not lyr.pg or not lyr.pg.geometry_column or lyr.geometry_type not in ("Polygon", "Line"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Podział działa dla warstw poligonowych i liniowych")
    if body.line.get("type") != "LineString" or len(body.line.get("coordinates") or []) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia podziału musi mieć co najmniej dwa punkty")
    srid = _srid(crs)
    g = col(T, lyr.pg.geometry_column)
    blade = _geom_sql(lyr, body.line, srid, multi=False)
    alias = sql.Identifier(*T)

    created: list[str] = []
    updated: list[str] = []
    old_rows: dict[str, dict] = {}
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        if body.pks is None:
            rows = await (await conn.execute(sql.SQL(
                """SELECT {k}::text AS pk FROM {t} AS {a}
                    WHERE {f} AND {g} && {b} AND ST_Intersects({g}, {b}) AND ST_NumGeometries(ST_Split({g}, {b})) > 1
                    ORDER BY 1 LIMIT {n}""").format(
                k=col(T, lyr.pg.key), t=_table(lyr), a=alias, f=row_filter(ctx, lyr, T, "edit"), g=g, b=blade,
                n=sql.Literal(SPLIT_LIMIT + 1)))).fetchall()
            pks = [r["pk"] for r in rows]
            if len(pks) > SPLIT_LIMIT:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Linia dzieli ponad {SPLIT_LIMIT} obiektów — zaznacz obiekt albo skróć linię")
        else:
            pks = list(dict.fromkeys(body.pks))
        if body.dry_run:
            return {"pks": pks}
        if not pks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Linia nie dzieli żadnego obiektu — musi przeciąć obiekt na wylot")

        columns = await split_columns(conn, lyr)
        names = [*(n for n, _ in columns), lyr.pg.geometry_column]

        def values(ratio: float) -> list[sql.Composable]:
            out: list[sql.Composable] = []
            for name, p in columns:
                if p == "UnsetField":
                    out.append(sql.NULL)
                elif p == "GeometryRatio":
                    out.append(sql.SQL("{} * {}").format(col(T, name), sql.Literal(ratio)))
                else:
                    out.append(col(T, name))
            return out

        for pk in pks:
            old = await _fetch_one(conn, ctx, lyr, pk, srid, "view")
            if old is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Brak obiektu #{pk}")
            if not await in_scope(conn, ctx, lyr, pk, "edit"):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} (#{pk}) — tylko podgląd")
            parts = await (await conn.execute(sql.SQL(
                """SELECT ST_AsEWKB(p.geom) AS wkb, {mp} AS m, p.total
                     FROM (SELECT (ST_Dump(ST_Split({g}, {b}))).geom AS geom, {mt} AS total
                             FROM {t} AS {a} WHERE {pk}) AS p
                    WHERE {mp} > 0 ORDER BY 2 DESC""").format(
                mp=_measure(sql.SQL("p.geom")), mt=_measure(g), g=g, b=blade, t=_table(lyr),
                a=alias, pk=_pk_is(lyr, pk)))).fetchall()
            if len(parts) < 2:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Linia nie dzieli obiektu #{pk} — musi przeciąć go na wylot")
            total = parts[0]["total"] or sum(p["m"] for p in parts)
            old_rows[pk] = old

            # nowe części (atrybuty z oryginału, zanim zmieni się jego wartość proporcjonalna)
            for part in parts[1:]:
                q = sql.SQL("INSERT INTO {t} ({c}) SELECT {v} FROM {t} AS {a} WHERE {pk} RETURNING {k}::text AS pk").format(
                    t=_table(lyr), c=sql.SQL(", ").join(sql.Identifier(n) for n in names),
                    v=sql.SQL(", ").join([*values(part["m"] / total), _from_ewkb(lyr, part["wkb"])]),
                    a=alias, pk=_pk_is(lyr, pk), k=sql.Identifier(lyr.pg.key))
                created.append((await (await conn.execute(q)).fetchone())["pk"])
            # oryginał: największa część
            ratio = parts[0]["m"] / total
            sets = [sql.SQL("{} = {}").format(sql.Identifier(lyr.pg.geometry_column), _from_ewkb(lyr, parts[0]["wkb"]))]
            sets += [sql.SQL("{n} = {n} * {r}").format(n=sql.Identifier(n), r=sql.Literal(ratio))
                     for n, p in columns if p == "GeometryRatio"]
            await conn.execute(sql.SQL("UPDATE {t} SET {s} WHERE {k}::text = {pk}").format(
                t=_table(lyr), s=sql.SQL(", ").join(sets), k=sql.Identifier(lyr.pg.key), pk=sql.Literal(pk)))
            updated.append(pk)

        for pk in [*updated, *created]:
            if not await in_scope(conn, ctx, lyr, pk, "edit"):
                raise _scope_error(ctx, lyr)  # wyjątek w transakcji = wycofanie całego podziału
        new = {pk: _row_to_feature(await _fetch_one(conn, None, lyr, pk, srid, None)) for pk in [*updated, *created]}

    for pk in updated:
        await _audit(ctx, layer_id, pk, "update", _row_to_feature(old_rows[pk]), new[pk])
    for pk in created:
        await _audit(ctx, layer_id, pk, "insert", None, new[pk])
    return {"updated": [new[pk] for pk in updated], "created": [new[pk] for pk in created]}


# ---------------------------------------------------------------------------- pierścienie, części, łączenie


class RingIn(BaseModel):
    ring: dict[str, Any]                 # GeoJSON Polygon w układzie crs
    pk: str | None = None                # None = obiekt, w którym pierścień leży w całości
    dry_run: bool = False                # tylko klucz obiektu (pierścień wypełniony: formularz nowego obiektu)


class PointIn(BaseModel):
    point: list[float]                   # [x, y] w układzie crs
    tolerance: float = 0                 # promień kliknięcia w jednostkach crs (części linii i punktów)
    pk: str | None = None
    dry_run: bool = False


class MergeIn(BaseModel):
    pks: list[str]
    keep: str                            # obiekt, który zostaje (klucz, atrybuty, zdjęcia)


def _is_multi(lyr: LayerDef) -> bool:
    return (lyr.pg.geometry_type or "").upper().startswith("MULTI")


def _editable_geometry(ctx: ProjectContext, layer_id: str, *actions: str,
                       kinds: tuple[str, ...] = ("Point", "Line", "Polygon")) -> LayerDef:
    lyr = ctx.require(layer_id, actions[0])
    for a in actions[1:]:
        if not getattr(ctx.perms(layer_id), a):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Brak uprawnienia '{a}' do warstwy")
    if not lyr.pg or not lyr.pg.geometry_column or lyr.geometry_type not in kinds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Narzędzie nie obsługuje tej warstwy")
    return lyr


def _point_sql(lyr: LayerDef, point: list[float], srid: int) -> sql.Composable:
    if len(point) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak punktu kliknięcia")
    return _geom_sql(lyr, {"type": "Point", "coordinates": point[:2]}, srid, multi=False)


def _single_or_multi(lyr: LayerDef, collection: sql.Composable) -> sql.Composable:
    """Kolekcja części → typ kolumny (Multi* albo pierwsza i jedyna część)."""
    if _is_multi(lyr):
        return sql.SQL("ST_Multi({})").format(collection)
    return sql.SQL("ST_GeometryN({}, 1)").format(collection)


async def _pick(conn, ctx: ProjectContext, lyr: LayerDef, where: sql.Composable, order: sql.Composable,
                pk: str | None) -> str | None:
    """Pierwszy obiekt w zakresie edycji spełniający warunek (opcjonalnie: tylko wskazany)."""
    conds = [row_filter(ctx, lyr, T, "edit"), where]
    if pk is not None:
        conds.append(_pk_is(lyr, pk))
    row = await (await conn.execute(sql.SQL("SELECT {k}::text AS pk FROM {t} AS {a} WHERE {w} ORDER BY {o} LIMIT 1").format(
        k=col(T, lyr.pg.key), t=_table(lyr), a=sql.Identifier(*T), w=sql.SQL(" AND ").join(conds), o=order))).fetchone()
    return row["pk"] if row else None


OVERLAP_TOLERANCE_M = 0.01      # część wspólna węższa niż 2 cm (bufor do środka 1 cm znika) — nie jest nakładaniem


async def check_overlap(conn, ctx: ProjectContext, lyr: LayerDef, pk: str) -> None:
    """Kontrola topologii przy zapisie: obiekt warstwy z listy „unikaj nakładania” projektu QGIS nie może nachodzić
    na inne obiekty tej warstwy (szerzej niż 2 cm). Błąd 409 z miejscami nakładania (EPSG:4326) do pokazania na mapie;
    wyjątek w transakcji wycofuje zapis."""
    snap = getattr(ctx.project, "snapping", None)
    if snap is None or lyr.id not in snap.avoid_overlap or lyr.geometry_type != "Polygon" or not lyr.pg.geometry_column:
        return
    g, k = sql.Identifier(lyr.pg.geometry_column), sql.Identifier(lyr.pg.key)
    rows = await (await conn.execute(sql.SQL("""
        SELECT o.{k}::text AS pk, ST_AsGeoJSON(ST_Transform(x.czesc, 4326), 7)::json AS geometry,
               round(ST_Area(x.czesc)::numeric, 2) AS m2
          FROM {t} AS o
          JOIN (SELECT {g} AS geom FROM {t} WHERE {k}::text = {pk}) AS n ON o.{g} && n.geom
          CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_Intersection(o.{g}, n.geom), 3) AS czesc) AS x
         WHERE o.{k}::text <> {pk} AND ST_SRID(n.geom) <> 4326 AND ST_Intersects(o.{g}, n.geom)
           AND NOT ST_IsEmpty(ST_Buffer(x.czesc, {tol}))
         LIMIT 5""").format(k=k, g=g, t=_table(lyr), pk=sql.Literal(pk), tol=sql.Literal(-OVERLAP_TOLERANCE_M)))).fetchall()
    if rows:
        razem = sum(float(r["m2"]) for r in rows)
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": f"Obiekt nachodzi na {len(rows)}{'+' if len(rows) == 5 else ''} inny(ch) obiekt(y) warstwy "
                       f"„{lyr.name}” ({razem:.2f} m²) — popraw granicę (miejsca zaznaczone na mapie na czerwono)",
            "overlap": [{"geometry": r["geometry"], "kind": "uwaga", "label": f"{float(r['m2']):.1f} m²"} for r in rows],
            "with": [r["pk"] for r in rows]})


async def _set_geometry(conn, ctx: ProjectContext, lyr: LayerDef, pk: str, expr: sql.Composable, srid: int):
    """UPDATE geometrii wyrażeniem nad wierszem (alias T) + kontrola zakresu; zwraca (stary, nowy)."""
    old = await _fetch_one(conn, ctx, lyr, pk, srid, "view")
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
    await conn.execute(sql.SQL("UPDATE {t} AS {a} SET {g} = {e} WHERE {pk}").format(
        t=_table(lyr), a=sql.Identifier(*T), g=sql.Identifier(lyr.pg.geometry_column), e=expr, pk=_pk_is(lyr, pk)))
    if not await in_scope(conn, ctx, lyr, pk, "edit"):
        raise _scope_error(ctx, lyr)
    await check_overlap(conn, ctx, lyr, pk)
    return _row_to_feature(old), _row_to_feature(await _fetch_one(conn, None, lyr, pk, srid, None))


def _ring_sql(lyr: LayerDef, ring: dict, srid: int) -> sql.Composable:
    if ring.get("type") != "Polygon" or len((ring.get("coordinates") or [[]])[0]) < 4:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pierścień musi być poligonem (co najmniej 3 wierzchołki)")
    return _geom_sql(lyr, {"type": "Polygon", "coordinates": ring["coordinates"][:1]}, srid, multi=False)


async def ring_target(conn, ctx: ProjectContext, lyr: LayerDef, ring: sql.Composable, pk: str | None) -> str:
    """Obiekt, w którym pierścień leży w całości (najmniejszy, gdy obiekty na siebie zachodzą)."""
    g = col(T, lyr.pg.geometry_column)
    found = await _pick(conn, ctx, lyr, sql.SQL("{g} && {r} AND ST_Within({r}, {g})").format(g=g, r=ring),
                        sql.SQL("ST_Area({})").format(g), pk)
    if found is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Pierścień musi leżeć w całości wewnątrz obiektu{f' #{pk}' if pk else ''} "
                            "(nie może przecinać granicy ani istniejącego pierścienia)")
    return found


@router.post("/ring")
async def add_ring(slug: str, layer_id: str, body: RingIn, crs: str = "EPSG:3857",
                   user: CurrentUser = Depends(require_user)):
    """Dziura w poligonie (QGIS: „Dodaj pierścień”). dry_run — tylko obiekt docelowy."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update", kinds=("Polygon",))
    srid = _srid(crs)
    ring = _ring_sql(lyr, body.ring, srid)
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        pk = await ring_target(conn, ctx, lyr, ring, body.pk)
        if body.dry_run:
            return {"pk": pk}
        diff = _as_column_type(lyr, sql.SQL("ST_Difference({}, {})").format(col(T, lyr.pg.geometry_column), ring))
        old, new = await _set_geometry(conn, ctx, lyr, pk, diff, srid)
    await _audit(ctx, layer_id, pk, "update", old, new)
    return new


@router.post("/delete-ring")
async def delete_ring(slug: str, layer_id: str, body: PointIn, crs: str = "EPSG:3857",
                      user: CurrentUser = Depends(require_user)):
    """Usunięcie pierścienia (dziury), w który kliknięto (QGIS: „Usuń pierścień”)."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update", kinds=("Polygon",))
    srid = _srid(crs)
    pt = _point_sql(lyr, body.point, srid)
    g = col(T, lyr.pg.geometry_column)
    filled = sql.SQL("(SELECT ST_Collect(ST_MakePolygon(ST_ExteriorRing(d.geom))) FROM ST_Dump({g}) d)").format(g=g)
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        pk = await _pick(conn, ctx, lyr, sql.SQL("{g} && {p} AND NOT ST_Intersects({g}, {p}) AND ST_Intersects({f}, {p})")
                         .format(g=g, p=pt, f=filled), sql.SQL("ST_Area({})").format(g), body.pk)
        if pk is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kliknij wewnątrz pierścienia (dziury) obiektu")
        if body.dry_run:
            return {"pk": pk}
        rebuilt = sql.SQL(
            """(SELECT ST_Collect(ST_MakePolygon(ST_ExteriorRing(d.geom), ARRAY(
                   SELECT ST_InteriorRingN(d.geom, n) FROM generate_series(1, ST_NumInteriorRings(d.geom)) AS n
                    WHERE NOT ST_Intersects(ST_MakePolygon(ST_InteriorRingN(d.geom, n)), {p}) ORDER BY n))
                   ORDER BY d.path) FROM ST_Dump({g}) d)""").format(g=g, p=pt)
        old, new = await _set_geometry(conn, ctx, lyr, pk, _single_or_multi(lyr, rebuilt), srid)
    await _audit(ctx, layer_id, pk, "update", old, new)
    return new


@router.post("/delete-part")
async def delete_part(slug: str, layer_id: str, body: PointIn, crs: str = "EPSG:3857",
                      user: CurrentUser = Depends(require_user)):
    """Usunięcie części obiektu wieloczęściowego najbliższej kliknięciu (QGIS: „Usuń część”)."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update")
    if not _is_multi(lyr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa nie ma obiektów wieloczęściowych")
    srid = _srid(crs)
    pt = _point_sql(lyr, body.point, srid)
    g = col(T, lyr.pg.geometry_column)
    tol = sql.Literal(max(body.tolerance, 0.0))
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        pk = await _pick(conn, ctx, lyr, sql.SQL("ST_DWithin({g}, {p}, {t})").format(g=g, p=pt, t=tol),
                         sql.SQL("ST_Distance({g}, {p})").format(g=g, p=pt), body.pk)
        if pk is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kliknij część obiektu warstwy edycyjnej")
        info = await (await conn.execute(sql.SQL(
            """SELECT count(*) AS n, (array_agg(d.path[1] ORDER BY ST_Distance(d.geom, {p})))[1] AS part
                 FROM {t} AS {a}, ST_Dump({g}) d WHERE {pk}""").format(
            p=pt, t=_table(lyr), a=sql.Identifier(*T), g=g, pk=_pk_is(lyr, pk)))).fetchone()
        if info["n"] < 2:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Obiekt #{pk} ma tylko jedną część — usuń cały obiekt")
        if body.dry_run:
            return {"pk": pk, "parts": info["n"]}
        rest = sql.SQL("(SELECT ST_Collect(d.geom ORDER BY d.path) FROM ST_Dump({g}) d WHERE d.path[1] <> {i})").format(
            g=g, i=sql.Literal(info["part"]))
        old, new = await _set_geometry(conn, ctx, lyr, pk, sql.SQL("ST_Multi({})").format(rest), srid)
    await _audit(ctx, layer_id, pk, "update", old, new)
    return new


@router.post("/merge")
async def merge_features(slug: str, layer_id: str, body: MergeIn, crs: str = "EPSG:3857",
                         user: CurrentUser = Depends(require_user)):
    """Połączenie obiektów (QGIS: „Połącz zaznaczone obiekty”): geometria = suma, zostaje obiekt
    `keep` z atrybutami; zdjęcia, dokumenty i rekordy powiązane pozostałych przechodzą do niego,
    pozostałe obiekty są usuwane. Jedna transakcja."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update", "delete")
    pks = list(dict.fromkeys(body.pks))
    if body.keep not in pks or len(pks) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wskaż co najmniej dwa obiekty, w tym obiekt, który zostaje")
    if len(pks) > SPLIT_LIMIT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Najwyżej {SPLIT_LIMIT} obiektów naraz")
    others = [p for p in pks if p != body.keep]
    srid = _srid(crs)
    g = col(T, lyr.pg.geometry_column)
    dim = {"Point": 1, "Line": 2, "Polygon": 3}[lyr.geometry_type]
    in_pks = sql.SQL("{}::text IN ({})").format(col(T, lyr.pg.key), sql.SQL(", ").join(sql.Literal(p) for p in pks))
    union = sql.SQL("ST_Union({g})").format(g=g)
    if lyr.geometry_type == "Line":
        union = sql.SQL("ST_LineMerge({})").format(union)
    union = sql.SQL("ST_CollectionExtract({}, {})").format(union, sql.Literal(dim))

    old_rows: dict[str, dict] = {}
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        for pk in pks:
            old = await _fetch_one(conn, ctx, lyr, pk, srid, "view")
            if old is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Brak obiektu #{pk}")
            if not await in_scope(conn, ctx, lyr, pk, "edit"):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} (#{pk}) — tylko podgląd")
            old_rows[pk] = old
        merged = await (await conn.execute(sql.SQL(
            "SELECT ST_AsEWKB(m) AS wkb, ST_NumGeometries(m) AS n FROM (SELECT {u} AS m FROM {t} AS {a} WHERE {w}) s").format(
            u=union, t=_table(lyr), a=sql.Identifier(*T), w=in_pks))).fetchone()
        if not merged["wkb"] or (merged["n"] > 1 and not _is_multi(lyr)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Obiekty nie stykają się — wynik byłby wieloczęściowy, a warstwa przyjmuje tylko "
                                "obiekty jednoczęściowe")

        # dzieci (zdjęcia, dokumenty, rekordy powiązane) usuwanych obiektów → obiekt, który zostaje
        moved: list[tuple[str, str, dict, dict]] = []
        for rel in ctx.project.relations:
            if rel.parent_layer != layer_id:
                continue
            child = ctx.layer(rel.child_layer)
            if not child.pg or child.pg.conninfo != lyr.pg.conninfo:
                continue
            keep_vals = await (await conn.execute(sql.SQL("SELECT {c} FROM {t} AS {a} WHERE {pk}").format(
                c=sql.SQL(", ").join(col(T, p) for p, _ in rel.pairs), t=_table(lyr), a=sql.Identifier(*T),
                pk=_pk_is(lyr, body.keep)))).fetchone()
            for pk in others:
                vals = await (await conn.execute(sql.SQL("SELECT {c} FROM {t} AS {a} WHERE {pk}").format(
                    c=sql.SQL(", ").join(col(T, p) for p, _ in rel.pairs), t=_table(lyr), a=sql.Identifier(*T),
                    pk=_pk_is(lyr, pk)))).fetchone()
                cond = sql.SQL(" AND ").join(
                    sql.SQL("{} = {}").format(sql.Identifier(c), sql.Literal(vals[p])) for p, c in rel.pairs)
                n = (await (await conn.execute(sql.SQL("SELECT count(*) AS n FROM {t} WHERE {c}").format(
                    t=_table(child), c=cond))).fetchone())["n"]
                if not n:
                    continue
                if not ctx.perms(rel.child_layer).update:
                    raise HTTPException(status.HTTP_403_FORBIDDEN,
                                        f"Obiekt #{pk} ma rekordy w „{child.name}” — brak prawa ich zmiany")
                child_pks = []
                if child.pg.key:
                    child_pks = [r["pk"] for r in await (await conn.execute(sql.SQL(
                        "SELECT {k}::text AS pk FROM {t} WHERE {c}").format(
                        k=sql.Identifier(child.pg.key), t=_table(child), c=cond))).fetchall()]
                await conn.execute(sql.SQL("UPDATE {t} SET {s} WHERE {c}").format(
                    t=_table(child), c=cond, s=sql.SQL(", ").join(
                        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Literal(keep_vals[p])) for p, c in rel.pairs)))
                for c in child_pks:      # do dziennika: same pola relacji (bywają ukryte w formularzu)
                    moved.append((rel.child_layer, c,
                                  {"type": "Feature", "id": c, "properties": {k: vals[p] for p, k in rel.pairs}},
                                  {"type": "Feature", "id": c, "properties": {k: keep_vals[p] for p, k in rel.pairs}}))

        await conn.execute(sql.SQL("DELETE FROM {t} AS {a} WHERE {w}").format(
            t=_table(lyr), a=sql.Identifier(*T), w=sql.SQL("{}::text IN ({})").format(
                col(T, lyr.pg.key), sql.SQL(", ").join(sql.Literal(p) for p in others))))
        _, new = await _set_geometry(conn, ctx, lyr, body.keep, _single_or_multi(
            lyr, sql.SQL("ST_GeomFromEWKB({})").format(sql.Literal(merged["wkb"]))), srid)

    for child_id, c, before_f, after_f in moved:   # najpierw dzieci: cofanie idzie od końca
        await _audit(ctx, child_id, c, "update", before_f, after_f)
    await _audit(ctx, layer_id, body.keep, "update", _row_to_feature(old_rows[body.keep]), new)
    for pk in others:
        await _audit(ctx, layer_id, pk, "delete", _row_to_feature(old_rows[pk]), None)
    return new


# ---------------------------------------------------------------- dodaj część, przekształć, kopiuj


class PartIn(BaseModel):
    part: dict[str, Any]                 # GeoJSON (Polygon / LineString / Point) w układzie crs
    pk: str                              # obiekt, do którego dochodzi część


class ReshapeIn(BaseModel):
    line: dict[str, Any]                 # linia przekształcenia (GeoJSON LineString)
    pk: str | None = None                # None = obiekt, który linia przekształca (jedyny)


class CopyIn(BaseModel):
    geometry: dict[str, Any]             # geometria kopii (np. przesunięta)


SINGLE_TYPE = {"Point": "Point", "Line": "LineString", "Polygon": "Polygon"}


def _dims_like(g: sql.Composable, x: sql.Composable) -> sql.Composable:
    """Wymiar współrzędnych jak w kolumnie (szkic z WebUI jest 2D; kolumna może mieć Z)."""
    return sql.SQL("CASE WHEN ST_CoordDim({g}) > 2 THEN ST_Force3D({x}) ELSE ST_Force2D({x}) END").format(g=g, x=x)


@router.post("/add-part")
async def add_part(slug: str, layer_id: str, body: PartIn, crs: str = "EPSG:3857",
                   user: CurrentUser = Depends(require_user)):
    """Nowa część obiektu wieloczęściowego (QGIS: „Dodaj część”)."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update")
    if not _is_multi(lyr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa nie ma obiektów wieloczęściowych")
    if body.part.get("type") != SINGLE_TYPE[lyr.geometry_type]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Część musi mieć typ geometrii warstwy")
    srid = _srid(crs)
    g = col(T, lyr.pg.geometry_column)
    part = _dims_like(g, _geom_sql(lyr, body.part, srid, multi=False))
    new = sql.SQL("ST_Multi(ST_Collect(ARRAY(SELECT d.geom FROM ST_Dump({g}) d ORDER BY d.path) || {p}))").format(g=g, p=part)
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        if not await in_scope(conn, ctx, lyr, body.pk, "edit"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} — tylko podgląd")
        ok = await (await conn.execute(sql.SQL("SELECT ST_IsValid({n}) AS ok FROM {t} AS {a} WHERE {pk}").format(
            n=new, t=_table(lyr), a=sql.Identifier(*T), pk=_pk_is(lyr, body.pk)))).fetchone()
        if ok is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        if not ok["ok"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Nowa część nachodzi na obiekt albo styka się z nim krawędzią — narysuj ją obok")
        old, feature = await _set_geometry(conn, ctx, lyr, body.pk, new, srid)
    await _audit(ctx, layer_id, body.pk, "update", old, feature)
    return feature


def reshape_mode(length: float, inside: float) -> str:
    """Linia przekształcenia (odcinek między skrajnymi przecięciami z granicą) biegnie na zewnątrz
    obiektu (dokłada powierzchnię), wewnątrz (odcina mniejszą część) albo raz tu, raz tam."""
    tol = max(length, 1.0) * 1e-9
    if inside <= tol:
        return "outside"
    if length - inside <= tol:
        return "inside"
    return "mixed"


async def _reshape_polygon(conn, lyr: LayerDef, pk: str, blade: sql.Composable) -> sql.Composable:
    g = col(T, lyr.pg.geometry_column)
    hits = await (await conn.execute(sql.SQL(
        """SELECT i, ST_AsEWKB(geom) AS wkb, fr FROM (
             SELECT coalesce(d.path[1], 1) AS i, d.geom,
                    ARRAY(SELECT ST_LineLocatePoint(b.l, p.geom) FROM ST_DumpPoints(ST_Intersection(b.l, ST_Boundary(d.geom))) p
                          ORDER BY 1) AS fr
               FROM {t} AS {a}, ST_Dump(ST_Force2D({g})) d, (SELECT ST_Force2D({b}) AS l) b WHERE {pk}) s
            WHERE cardinality(fr) >= 2""").format(
        t=_table(lyr), a=sql.Identifier(*T), g=g, b=blade, pk=_pk_is(lyr, pk)))).fetchall()
    hits = [h for h in hits if h["fr"][-1] - h["fr"][0] > 1e-12]
    if not hits:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Linia musi dwa razy przeciąć granicę obiektu (wejść i wyjść)")
    if len(hits) > 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia przecina kilka części obiektu — narysuj krótszą")
    h = hits[0]
    r = await (await conn.execute(sql.SQL(
        """WITH m AS (SELECT p, l, ST_Length(l) AS len, ST_Length(ST_Intersection(l, p)) AS inlen
                        FROM (SELECT ST_GeomFromEWKB({w}) AS p, ST_LineSubstring(ST_Force2D({b}), {f0}, {f1}) AS l) x),
                faces AS (SELECT (ST_Dump(ST_Polygonize(lw))).geom AS geom
                            FROM (SELECT ST_Union(ST_Boundary(p), l) AS lw FROM m) n)
           SELECT m.len, m.inlen,
                  (SELECT ST_AsEWKB(ST_Union(m.p, ST_Union(f.geom))) FROM faces f
                    WHERE NOT ST_Within(ST_PointOnSurface(f.geom), m.p) AND ST_Length(ST_Intersection(f.geom, m.l)) > 0)
                    AS grown,
                  (SELECT ST_AsEWKB(s.geom) FROM ST_Dump(ST_Split(m.p, m.l)) s ORDER BY ST_Area(s.geom) DESC LIMIT 1)
                    AS cut
             FROM m""").format(w=sql.Literal(h["wkb"]), b=blade, f0=sql.Literal(h["fr"][0]),
                               f1=sql.Literal(h["fr"][-1])))).fetchone()
    mode = reshape_mode(r["len"], r["inlen"])
    wkb = r["grown"] if mode == "outside" else r["cut"] if mode == "inside" else None
    if wkb is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Linia przekształcenia musi biec w całości na zewnątrz albo w całości wewnątrz obiektu")
    others = sql.SQL("ARRAY(SELECT d.geom FROM ST_Dump(ST_Force2D({g})) d WHERE coalesce(d.path[1], 1) <> {i} ORDER BY d.path)").format(
        g=g, i=sql.Literal(h["i"]))
    parts = sql.SQL("ST_Collect({o} || ARRAY(SELECT (ST_Dump(ST_GeomFromEWKB({w}))).geom))").format(o=others, w=sql.Literal(wkb))
    return _dims_like(g, _single_or_multi(lyr, parts))


async def _reshape_line(conn, lyr: LayerDef, pk: str, blade: sql.Composable) -> sql.Composable:
    g = col(T, lyr.pg.geometry_column)
    hits = await (await conn.execute(sql.SQL(
        """SELECT coalesce(d.path[1], 1) AS i,
                  ARRAY(SELECT ARRAY[ST_LineLocatePoint(d.geom, p.geom), ST_LineLocatePoint(b.l, p.geom)]
                          FROM ST_DumpPoints(ST_Intersection(b.l, d.geom)) p ORDER BY 1) AS fr
             FROM {t} AS {a}, ST_Dump(ST_Force2D({g})) d, (SELECT ST_Force2D({b}) AS l) b WHERE {pk}""").format(
        t=_table(lyr), a=sql.Identifier(*T), g=g, b=blade, pk=_pk_is(lyr, pk)))).fetchall()
    hits = [h for h in hits if len(h["fr"]) >= 2 and h["fr"][-1][0] - h["fr"][0][0] > 1e-12]
    if len(hits) != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Linia przekształcenia musi dwa razy przeciąć jedną część linii obiektu")
    h = hits[0]
    (a, la), (b, lb) = h["fr"][0], h["fr"][-1]
    piece = sql.SQL("ST_LineSubstring(ST_Force2D({bl}), {x}, {y})").format(
        bl=blade, x=sql.Literal(min(la, lb)), y=sql.Literal(max(la, lb)))
    if la > lb:
        piece = sql.SQL("ST_Reverse({})").format(piece)
    part = sql.SQL("(SELECT d.geom FROM ST_Dump(ST_Force2D({g})) d WHERE coalesce(d.path[1], 1) = {i})").format(
        g=g, i=sql.Literal(h["i"]))
    chain = []
    if a > 0:
        chain.append(sql.SQL("ST_LineSubstring({p}, 0, {a})").format(p=part, a=sql.Literal(a)))
    chain.append(piece)
    if b < 1:
        chain.append(sql.SQL("ST_LineSubstring({p}, {b}, 1)").format(p=part, b=sql.Literal(b)))
    merged = sql.SQL("ST_LineMerge(ST_Collect(ARRAY[{}]))").format(sql.SQL(", ").join(chain))
    others = sql.SQL("ARRAY(SELECT d.geom FROM ST_Dump(ST_Force2D({g})) d WHERE coalesce(d.path[1], 1) <> {i} ORDER BY d.path)").format(
        g=g, i=sql.Literal(h["i"]))
    ok = await (await conn.execute(sql.SQL("SELECT GeometryType({m}) AS t FROM {t} AS {a} WHERE {pk}").format(
        m=merged, t=_table(lyr), a=sql.Identifier(*T), pk=_pk_is(lyr, pk)))).fetchone()
    if ok["t"] != "LINESTRING":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Przekształcenie rozerwałoby linię — narysuj inaczej")
    return _dims_like(g, _single_or_multi(lyr, sql.SQL("ST_Collect({o} || {m})").format(o=others, m=merged)))


@router.post("/reshape")
async def reshape_feature(slug: str, layer_id: str, body: ReshapeIn, crs: str = "EPSG:3857",
                          user: CurrentUser = Depends(require_user)):
    """Przekształcenie obiektu linią (QGIS: „Przekształć obiekty”). Poligon: linia na zewnątrz dokłada
    powierzchnię, wewnątrz odcina mniejszą część. Linia: odcinek między przecięciami zastępuje szkic."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "update", kinds=("Line", "Polygon"))
    if body.line.get("type") != "LineString" or len(body.line.get("coordinates") or []) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia przekształcenia musi mieć co najmniej dwa punkty")
    srid = _srid(crs)
    g = col(T, lyr.pg.geometry_column)
    blade = _geom_sql(lyr, body.line, srid, multi=False)
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        pk = body.pk or await _pick(conn, ctx, lyr, sql.SQL("{g} && {b} AND ST_Intersects({g}, {b})").format(g=g, b=blade),
                                    sql.SQL("ST_Distance(ST_StartPoint({b}), {g})").format(g=g, b=blade), None)
        if pk is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia nie przecina żadnego obiektu warstwy")
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{OUT_OF_SCOPE} — tylko podgląd")
        expr = await (_reshape_polygon if lyr.geometry_type == "Polygon" else _reshape_line)(conn, lyr, pk, blade)
        old, new = await _set_geometry(conn, ctx, lyr, pk, expr, srid)
    await _audit(ctx, layer_id, pk, "update", old, new)
    return new


@router.post("/{pk:path}/copy", status_code=201)
async def copy_feature(slug: str, layer_id: str, pk: str, body: CopyIn, crs: str = "EPSG:3857",
                       user: CurrentUser = Depends(require_user)):
    """Kopia obiektu w nowym miejscu: atrybuty według polityk duplikowania pól z projektu QGIS
    (zdjęcia i rekordy powiązane zostają przy oryginale)."""
    ctx = await load_project_context(slug, user)
    lyr = _editable_geometry(ctx, layer_id, "insert")
    srid = _srid(crs)
    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        if await _fetch_one(conn, ctx, lyr, pk, srid, "view") is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        columns = await split_columns(conn, lyr, "duplicate_policy")
        names = [*(n for n, _ in columns), lyr.pg.geometry_column]
        vals = [sql.NULL if p == "UnsetField" else col(T, n) for n, p in columns]
        q = sql.SQL("INSERT INTO {t} ({c}) SELECT {v} FROM {t} AS {a} WHERE {pk} RETURNING {k}::text AS pk").format(
            t=_table(lyr), c=sql.SQL(", ").join(sql.Identifier(n) for n in names),
            v=sql.SQL(", ").join([*vals, _geom_sql(lyr, body.geometry, srid)]), a=sql.Identifier(*T),
            pk=_pk_is(lyr, pk), k=sql.Identifier(lyr.pg.key))
        new_pk = (await (await conn.execute(q)).fetchone())["pk"]
        if not await in_scope(conn, ctx, lyr, new_pk, "edit"):
            raise _scope_error(ctx, lyr)
        feature = _row_to_feature(await _fetch_one(conn, None, lyr, new_pk, srid, None))
    await _audit(ctx, layer_id, new_pk, "insert", None, feature)
    return feature


# Klucz obiektu może zawierać „/” (np. identyfikator działki 999901_1.0001.12/1) — serwer dekoduje %2F, więc
# ścieżki używają {pk:path}. Trasy z przyrostkiem (…/related, …/copy) muszą być sprawdzane przed ogólnymi.
router.routes.sort(key=lambda r: getattr(r, "path", "").endswith("{pk:path}"))
