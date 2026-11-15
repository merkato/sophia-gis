"""Wydruki z szablonów (układów wydruku) projektu QGIS, renderowane przez QGIS Server GetPrint.

Szablon z włączonym atlasem staje się raportem "dla obiektu" (ATLAS_PK = klucz obiektu),
bez atlasu — wydrukiem widoku mapy: środek z WebUI, skala z listy skal albo cały widok,
warstwy widoczne w WebUI, podkład z katalogu (jeśli projekt zawiera warstwę z tej samej usługi),
tytuł i opis do etykiet o identyfikatorach `tytul` / `opis`. docs/user/wydruki.md

QGIS Server adresuje mapy szablonu kolejnością: map0 = pierwsza mapa układu. map0:LAYERS — pierwsza
warstwa na spodzie (jak w GetMap); podkład z katalogu idzie więc na początek listy.

map0:EXTENT musi mieć proporcje ramki mapy szablonu — QGIS Server dopasowuje wysokość ramki do
proporcji zasięgu (zasięg ekranu: ramka wychodzi poza kartkę albo się spłaszcza), patrz fit_extent.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from psycopg import sql

from ..config import get_settings
from ..db import layer_conn, portal_conn
from ..permissions import ProjectContext, load_project_context
from ..qgsproject import Project, ReportDef
from ..scope import FILTER_HEADER, T, col, row_filter, wms_filter_header
from ..scope import table as _table
from ..security import CurrentUser, optional_user

router = APIRouter(prefix="/api/projects/{slug}/reports", tags=["reports"])

TITLE_LABELS = ("tytul", "title")
NOTE_LABELS = ("opis", "description")
SOURCES_LABELS = ("zrodla", "sources")      # atrybucje widocznych warstw i podkładu (z WebUI)
AUTHOR_LABELS = ("autor", "author")         # zalogowany użytkownik (z serwera, nie z przeglądarki)


def _label(report: ReportDef, ids: tuple[str, ...]) -> str | None:
    return next((x for x in ids if x in report.labels), None)


def opacities(names: list[str], given: dict[str, int]) -> str | None:
    """OPACITIES do GetPrint w kolejności map0:LAYERS (0–255); None, gdy wszystko w pełni kryjące."""
    vals = [round(max(0, min(100, given.get(n, 100))) * 255 / 100) for n in names]
    return ",".join(map(str, vals)) if any(v < 255 for v in vals) else None


def _percents(names: list[str], values: str | None) -> dict[str, int]:
    """„70,100,…” z WebUI (kolejność jak names) → {nazwa: krycie w %}; błędne wpisy pomijane."""
    out: dict[str, int] = {}
    for n, v in zip(names, (values or "").split(",")):
        try:
            out[n] = int(float(v))
        except ValueError:
            continue
    return out


def _label_text(text: str) -> str:
    """Tekst od użytkownika do etykiety szablonu — bez wyrażeń QGIS [% … %] (wykonałyby się na serwerze)."""
    return re.sub(r"\[%|%\]", "", text)[:500]


def _norm_url(url: str) -> str:
    u = urlsplit(url.strip())
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/?").lower()


def project_basemap_layer(project: Project, kind: str, config: dict) -> str | None:
    """Warstwa projektu (np. „Tylko w QGIS”) z tej samej usługi co podkład z katalogu —
    QGIS Server 4.2 nie drukuje warstw spoza projektu, więc wydruk z szablonu używa tej warstwy."""
    for lyr in project.layers.values():
        if not lyr.source:
            continue
        p = {k.lower(): v for k, v in parse_qsl(lyr.source, keep_blank_values=True)}
        same_wmts = (kind == "wmts" and p.get("tilematrixset") and p.get("url")
                     and _norm_url(p["url"]) == _norm_url(config.get("url", ""))
                     and p.get("layers", "").lower() == str(config.get("layer", "")).lower())
        if same_wmts:
            return lyr.wms_name
        if kind == "xyz" and p.get("type") == "xyz" and p.get("url", "").lower() == str(config.get("url", "")).lower():
            return lyr.wms_name
    return None


async def _basemaps(project: Project, ids: list[int]) -> list[dict]:
    """Podkłady z katalogu w podanej kolejności (podkład, potem nakładki) z dopasowaną warstwą projektu."""
    if not ids:
        return []
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            "SELECT id, name, kind, config FROM portal.basemaps WHERE enabled AND id = ANY(%s)", (ids,))).fetchall()
    by_id = {r["id"]: r for r in rows}
    out = []
    for i in ids:
        r = by_id.get(i)
        if r:
            out.append({"id": r["id"], "name": r["name"],
                        "layer": project_basemap_layer(project, r["kind"], r["config"]) if r["kind"] != "sophia" else None})
    return out


def fit_extent(extent: list[float], map_mm: list[float] | None, scale: float | None) -> list[float]:
    """Zasięg o proporcjach ramki mapy szablonu wokół środka widoku: przy stałej skali rozmiar
    ramki × skala, bez skali — widok powiększony do proporcji ramki (cały widok na wydruku)."""
    if not map_mm or map_mm[0] <= 0 or map_mm[1] <= 0:
        return extent
    minx, miny, maxx, maxy = extent
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    if scale:
        w, h = map_mm[0] * scale / 1000, map_mm[1] * scale / 1000
    else:
        w, h = maxx - minx, maxy - miny
        ratio = map_mm[0] / map_mm[1]
        if w / h > ratio:
            h = w / ratio
        else:
            w = h * ratio
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def _ids(s: str | None) -> list[int]:
    return [int(x) for x in (s or "").split(",") if x.strip().isdigit()]


def _report(ctx: ProjectContext, layout: str) -> ReportDef:
    report = next((r for r in ctx.project.reports if r.layout == layout), None)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznany szablon wydruku")
    return report


@router.get("/{layout}/info")
async def report_info(slug: str, layout: str, basemaps: str | None = None,
                      user: CurrentUser | None = Depends(optional_user)):
    """Dla panelu wydruku: rozmiar mapy szablonu (ramka na mapie), etykiety tytułu/opisu,
    czy wybrany podkład da się wydrukować z tym projektem."""
    ctx = await load_project_context(slug, user)
    report = _report(ctx, layout)
    return {
        "layout": report.layout, "map_mm": report.map_mm, "labels": report.labels,
        "title_label": _label(report, TITLE_LABELS),
        "note_label": _label(report, NOTE_LABELS),
        "sources_label": _label(report, SOURCES_LABELS),
        "author_label": _label(report, AUTHOR_LABELS),
        "basemaps": await _basemaps(ctx.project, _ids(basemaps)),
    }


@router.get("/{layout}")
async def render_report(
    slug: str, layout: str,
    pk: str | None = Query(None, description="Klucz obiektu dla raportu z atlasem"),
    extent: str | None = Query(None, description="minx,miny,maxx,maxy w układzie projektu (środek widoku)"),
    scale: float | None = Query(None, gt=0, description="Skala mapy (mianownik); bez — cały zasięg extent"),
    layers: str | None = Query(None, description="Widoczne warstwy (nazwy WMS) od spodu, przecinkami"),
    basemaps: str | None = Query(None, description="Id podkładów z katalogu (podkład, nakładki)"),
    dpi: int = Query(200, ge=72, le=400),
    title: str | None = Query(None, max_length=300),
    note: str | None = Query(None, max_length=500),
    sources: str | None = Query(None, max_length=1000, description="Źródła (atrybucje) do etykiety zrodla"),
    opacity: str | None = Query(None, description="Krycie 0–100 warstw z `layers`, w tej samej kolejności"),
    basemap_opacity: str | None = Query(None, description="Krycie 0–100 podkładów z `basemaps`"),
    user: CurrentUser | None = Depends(optional_user),
):
    ctx = await load_project_context(slug, user)
    report = _report(ctx, layout)

    allowed = {lyr.wms_name for lid, lyr in ctx.project.layers.items() if ctx.perms(lid).view}
    params = {
        # WMS 1.1.1: zasięg zawsze x,y (w 1.3.0 EPSG:2180 ma kolejność osi y,x — wydruk trafiał obok)
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetPrint", "MAP": str(ctx.path),
        "TEMPLATE": layout, "FORMAT": "pdf", "SRS": ctx.project.crs, "CRS": ctx.project.crs, "DPI": str(dpi),
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
            try:
                box = [float(v) for v in extent.split(",")]
                if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Błędny zasięg (extent)") from exc
            params["map0:EXTENT"] = ",".join(f"{v:.3f}" for v in fit_extent(box, report.map_mm, scale))
        if scale:
            params["map0:SCALE"] = str(round(scale))
        requested = [n for n in (layers or "").split(",") if n]
        if set(requested) - allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak dostępu do części warstw")
        # podkład z katalogu -> warstwa projektu z tej samej usługi (pod warstwami z WebUI)
        bms = await _basemaps(ctx.project, _ids(basemaps))
        under = [b["layer"] for b in bms if b["layer"]]
        given = _percents([str(b["id"]) for b in bms], basemap_opacity)
        given = {b["layer"]: given[str(b["id"])] for b in bms if b["layer"] and str(b["id"]) in given}
        given.update(_percents(requested, opacity))
        if requested or under:
            names = list(dict.fromkeys([*under, *requested]))
            params["map0:LAYERS"] = ",".join(names)
            if op := opacities(names, given):
                params["OPACITIES"] = op

    # tytuł, opis, źródła -> etykiety szablonu o umówionych identyfikatorach; autor — z sesji
    author = (user.full_name or user.login) if user else None
    for text, ids in ((title, TITLE_LABELS), (note, NOTE_LABELS), (sources, SOURCES_LABELS), (author, AUTHOR_LABELS)):
        label = _label(report, ids)
        if text is not None and label:
            params[label] = _label_text(text)

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(get_settings().qgis_server_url, params=params,
                             headers={FILTER_HEADER: wms_filter_header(ctx)})
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"QGIS Server: {r.text[:500]}")
    fname = f"{(title or report.title).strip() or report.title}{'_' + pk if pk else ''}.pdf".replace("/", "_")
    return Response(r.content, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(fname)}"})
