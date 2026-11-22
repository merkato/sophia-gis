"""Źródła warstw QGIS dla podkładów z katalogu Sophii (bez zależności od QGIS — testowane w API).

Fia („Dodaj podkłady Sophii”) dodaje te warstwy do projektu jako „Tylko w QGIS”: QGIS Server drukuje tylko
warstwy projektu, a API dopasowuje podkład z katalogu do warstwy po adresie usługi i nazwie warstwy
(api/app/routers/reports.py, project_basemap_layer). Format jak zapisuje QGIS (dostawca „wms”).
"""
from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlsplit


def _q(v: str) -> str:
    return quote(str(v), safe="")


def _join(params: list[tuple[str, str]]) -> str:
    return "&".join(f"{k}={_q(v)}" if v != "" else k for k, v in params)


def layer_source(kind: str, config: dict, project_crs: str) -> tuple[str, str] | None:
    """(dostawca, źródło) warstwy QGIS dla podkładu z katalogu; None — rodzaj nieobsługiwany (np. „sophia”)."""
    url = str(config.get("url") or "").strip()
    if kind == "wmts" and url:
        base = url.split("?")[0]
        crs = (config.get("tile_grid") or {}).get("crs") or project_crs
        return "wms", _join([
            ("contextualWMSLegend", "0"), ("crs", crs), ("dpiMode", "7"), ("format", config.get("format") or "image/png"),
            ("layers", config["layer"]), ("styles", config.get("style") or "default"),
            ("tileMatrixSet", config["matrix_set"]), ("url", f"{base}?service=WMTS&request=getCapabilities"),
        ])
    if kind == "xyz" and url:
        return "wms", _join([("type", "xyz"), ("url", url), ("zmax", str(int(config.get("max_zoom") or 19))), ("zmin", "0")])
    if kind == "wms" and url:
        return "wms", _join([
            ("crs", project_crs), ("dpiMode", "7"), ("format", config.get("format") or "image/png"),
            ("layers", config["layers"]), ("styles", ""), ("url", url.split("?")[0]),
        ])
    return None


def _norm_url(url: str) -> str:
    u = urlsplit(url.strip())
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/?").lower()


def matches(kind: str, config: dict, source: str) -> bool:
    """Czy warstwa o źródle `source` to ten podkład — ta sama reguła co project_basemap_layer w API."""
    p = {k.lower(): v for k, v in parse_qsl(source, keep_blank_values=True)}
    url = str(config.get("url") or "")
    if kind == "wmts":
        return bool(p.get("tilematrixset") and p.get("url") and _norm_url(p["url"]) == _norm_url(url)
                    and p.get("layers", "").lower() == str(config.get("layer", "")).lower())
    if kind == "xyz":
        return p.get("type") == "xyz" and p.get("url", "").lower() == url.lower()
    if kind == "wms":
        return bool(not p.get("tilematrixset") and p.get("type") != "xyz" and p.get("url")
                    and _norm_url(p["url"]) == _norm_url(url)
                    and p.get("layers", "").lower() == str(config.get("layers", "")).lower())
    return False
