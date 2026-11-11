"""Autoryzacja żądań OWS (forward_auth z Caddy) przed przekazaniem do QGIS Server."""
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..permissions import load_project_context
from ..qgsproject import TreeNode
from ..scope import FILTER_HEADER, wms_filter_header
from ..security import CurrentUser, optional_user

router = APIRouter(prefix="/api/ows", tags=["ows"])

ALLOWED_REQUESTS = {
    "getcapabilities", "getmap", "getfeatureinfo", "getlegendgraphic", "getstyles",
    "gettile",                                  # WMTS
    "describefeaturetype", "getfeature",        # WFS tylko do odczytu
}
LAYER_PARAMS = ("layers", "layer", "query_layers", "typename", "typenames")


def _raster_group_names(node: TreeNode) -> set[str]:
    names = {node.name} if node.kind == "raster_group" else set()
    for ch in node.children:
        names |= _raster_group_names(ch)
    return names


def ows_params(request: Request) -> dict[str, str]:
    """Parametry oryginalnego żądania /ows (klucze małymi literami).

    Caddy forward_auth zawsze ustawia (nadpisując wartość od klienta) nagłówek X-Forwarded-Uri
    z oryginalnym URI — to jednoznaczne źródło, niezależne od przepisywania ścieżki autoryzacji.
    Bez nagłówka (wywołanie bezpośrednie) używamy własnego query stringu.
    """
    fwd = request.headers.get("x-forwarded-uri")
    items = (parse_qsl(urlsplit(fwd).query, keep_blank_values=True) if fwd
             else request.query_params.multi_items())
    return {k.lower(): v for k, v in items}


@router.get("/authorize")
async def authorize(request: Request, user: CurrentUser | None = Depends(optional_user)):
    q = ows_params(request)
    slug = q.get("project")
    if not slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Brak parametru PROJECT")
    req = q.get("request", "").lower()
    if req not in ALLOWED_REQUESTS:
        # Transakcje WFS-T i GetPrint są zablokowane — edycja i raporty idą przez API.
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Żądanie {req or '?'} niedozwolone")

    ctx = await load_project_context(slug, user)
    allowed = {lyr.wms_name for lid, lyr in ctx.project.layers.items() if ctx.perms(lid).view}
    allowed |= _raster_group_names(ctx.project.tree)

    for param in LAYER_PARAMS:
        if q.get(param):
            requested = {n.strip() for n in q[param].split(",") if n.strip()}
            denied = requested - allowed
            if denied:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"Brak dostępu do warstw: {sorted(denied)}")

    return Response(status_code=200, headers={
        "X-Portal-Map": str(ctx.path),
        "X-Portal-User": user.login if user else "",
        "X-Portal-Groups": ",".join(user.group_names) if user else "",
        # zakres danych użytkownika — QGIS Server filtruje nim obraz mapy i identyfikację
        FILTER_HEADER: wms_filter_header(ctx),
    })
