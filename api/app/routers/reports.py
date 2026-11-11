"""Raporty PDF = wydruki (layouty) z projektu QGIS, renderowane przez QGIS Server GetPrint.

Layout z włączonym atlasem staje się raportem "dla obiektu" (ATLAS_PK = klucz obiektu),
bez atlasu — wydrukiem bieżącego widoku mapy (EXTENT/SCALE z WebUI).
"""
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from psycopg import sql

from ..config import get_settings
from ..db import layer_conn
from ..permissions import load_project_context
from ..scope import FILTER_HEADER, T, col, row_filter, wms_filter_header
from ..scope import table as _table
from ..security import CurrentUser, optional_user

router = APIRouter(prefix="/api/projects/{slug}/reports", tags=["reports"])


@router.get("/{layout}")
async def render_report(
    slug: str, layout: str,
    pk: str | None = Query(None, description="Klucz obiektu dla raportu z atlasem"),
    extent: str | None = Query(None, description="minx,miny,maxx,maxy w układzie projektu"),
    scale: float | None = None,
    layers: str | None = Query(None, description="Widoczne warstwy (nazwy WMS), przecinkami"),
    user: CurrentUser | None = Depends(optional_user),
):
    ctx = await load_project_context(slug, user)
    report = next((r for r in ctx.project.reports if r.layout == layout), None)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznany raport")

    allowed = {lyr.wms_name for lid, lyr in ctx.project.layers.items() if ctx.perms(lid).view}
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetPrint", "MAP": str(ctx.path),
        "TEMPLATE": layout, "FORMAT": "pdf", "CRS": ctx.project.crs, "DPI": "200",
    }
    if report.layer_id:
        if not pk:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Raport wymaga parametru pk")
        lyr = ctx.require(report.layer_id, "view")
        if lyr.pg:   # obiekt raportu musi być w zakresie danych użytkownika
            async with layer_conn(lyr.pg.conninfo) as conn:
                ok = await (await conn.execute(sql.SQL(
                    "SELECT 1 FROM {t} AS __t WHERE {k}::text = {pk} AND {f}").format(
                    t=_table(lyr), k=col(T, lyr.pg.key), pk=sql.Literal(pk), f=row_filter(ctx, lyr)))).fetchone()
            if not ok:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
        params["ATLAS_PK"] = pk
    else:
        if extent:
            params["map0:EXTENT"] = extent
        if scale:
            params["map0:SCALE"] = str(scale)
        if layers:
            requested = [n for n in layers.split(",") if n]
            if set(requested) - allowed:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak dostępu do części warstw")
            params["map0:LAYERS"] = ",".join(requested)

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(get_settings().qgis_server_url, params=params,
                             headers={FILTER_HEADER: wms_filter_header(ctx)})
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"QGIS Server: {r.text[:500]}")
    fname = f"{report.title}{'_' + pk if pk else ''}.pdf".replace("/", "_")
    return Response(r.content, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(fname)}"})
