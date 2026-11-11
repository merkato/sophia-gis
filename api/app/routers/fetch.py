"""Narzędzia pobierania: kliknięcie na mapie -> obiekt z usługi zewnętrznej (ULDK…) -> podgląd
z atrybutami zmapowanymi na pola warstwy docelowej (konfiguracja z Fii). Zapis idzie zwykłym
tworzeniem obiektu (features.create_feature) — z tymi samymi uprawnieniami i kontrolą zasięgu.

Zapytania do usług zewnętrznych przechodzą przez API: bez CORS w przeglądarce, z logiem i limitem.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import sql

from .. import fetchers
from ..db import layer_conn, portal_conn
from ..permissions import load_project_context, user_extent_ewkb
from ..security import CurrentUser, require_user
from .features import _srid, _table
from .photos import T, visible_condition

log = logging.getLogger("sophia.fetch")

router = APIRouter(prefix="/api/projects/{slug}/tools", tags=["tools"])


@router.get("/{tool_id}/fetch")
async def fetch_feature(slug: str, tool_id: str, x: float, y: float, crs: str = "EPSG:2180",
                        user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    tool = next((t for t in ctx.project.tools if t.id == tool_id), None)
    if tool is None or tool.source not in fetchers.SOURCES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznane narzędzie")
    lyr = ctx.require(tool.layer_id, "insert")
    source = fetchers.SOURCES[tool.source]
    if lyr.geometry_type not in ("Polygon", "Point"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa docelowa musi być poligonowa albo punktowa")
    if not fetchers.limiter.check(user.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Za dużo zapytań — odczekaj chwilę")
    srid = _srid(crs)
    try:
        found = await fetchers.fetch_by_point(source, x, y, srid)
    except fetchers.NotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except fetchers.FetchError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    log.info("%s: %s %s -> %s", user.login, slug, tool.id, found.properties.get(source.key_field))

    # Geometria w układzie mapy; do warstwy punktowej — punkt wewnątrz obiektu (np. środek działki)
    geom_expr = "ST_PointOnSurface(ST_GeomFromEWKT(%s))" if lyr.geometry_type == "Point" else "ST_GeomFromEWKT(%s)"
    async with portal_conn() as conn:
        row = await (await conn.execute(
            f"SELECT ST_AsGeoJSON(ST_Transform({geom_expr}, %s), 3)::json AS g", (found.ewkt, srid))).fetchone()

    mapped = {dst: found.properties.get(src) for src, dst in tool.fields.items()}

    # Ten sam obiekt już w warstwie? (po polu, do którego trafia identyfikator TERYT)
    existing_pk = None
    key_dst = tool.fields.get(source.key_field)
    key_val = found.properties.get(source.key_field)
    if key_dst and key_val:
        extent = await user_extent_ewkb(user, "view")
        async with layer_conn(lyr.pg.conninfo) as conn:
            hit = await (await conn.execute(sql.SQL(
                "SELECT {k}::text AS pk FROM {t} AS {a} WHERE {f}::text = {v} AND {vis} LIMIT 1").format(
                k=sql.Identifier(T, lyr.pg.key), t=_table(lyr), a=sql.Identifier(T),
                f=sql.Identifier(T, key_dst), v=sql.Literal(key_val),
                vis=visible_condition(ctx, lyr, extent)))).fetchone()
        existing_pk = hit["pk"] if hit else None

    return {
        "tool_id": tool.id, "layer_id": lyr.id, "source": source.id, "source_name": source.name,
        "key": key_val, "properties": found.properties, "labels": dict(source.fields),
        "mapped": mapped, "geometry": row["g"], "existing_pk": existing_pk, "open_form": tool.open_form,
    }
