"""Parser WMTS GetCapabilities (1.0.0) dla edytora podkładów w panelu administratora.

Z dokumentu wyciąga to, czego potrzebuje OpenLayers, żeby pobierać kafle bezpośrednio z serwisu
(przeglądarka -> serwis, bez naszego serwera):
  - warstwy (identyfikator, tytuł, formaty, style, powiązane macierze, zasięg WGS84),
  - macierze kafli jako gotowa siatka: początek (x, y) w kolejności osi OpenLayers, rozdzielczości,
    identyfikatory poziomów, rozmiar kafla,
  - adres pobierania kafli: szablon REST (ResourceURL) albo adres KVP (GetTile).

Kolejność osi: WMTS podaje TopLeftCorner w kolejności osi układu (EPSG:2180 i EPSG:4326 to
północ/wschód, czyli "y x"), a OpenLayers zawsze oczekuje x, y — o zamianie decyduje pyproj.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pyproj
from lxml import etree

NS = {
    "w": "http://www.opengis.net/wmts/1.0",
    "ows": "http://www.opengis.net/ows/1.1",
    "xlink": "http://www.w3.org/1999/xlink",
}
PIXEL_SIZE_M = 0.00028                                   # "standardized rendering pixel" WMTS
METERS_PER_DEGREE = 2 * math.pi * 6378137 / 360          # wg specyfikacji WMTS 1.0.0


class CapabilitiesError(ValueError):
    pass


@dataclass
class TileGrid:
    crs: str                                # "EPSG:2180"
    origin: list[float]                     # [x, y] lewego górnego narożnika (kolejność OpenLayers)
    resolutions: list[float]
    matrix_ids: list[str]
    tile_size: list[int]                    # [szerokość, wysokość]
    origins: list[list[float]] | None = None  # gdy poziomy mają różne narożniki


@dataclass
class WmtsLayer:
    identifier: str
    title: str
    formats: list[str]
    styles: list[str]
    default_style: str | None
    matrix_sets: list[str]
    wgs84_bbox: list[float] | None
    resource_urls: dict[str, str] = field(default_factory=dict)   # format -> szablon REST


@dataclass
class Capabilities:
    title: str | None
    kvp_url: str | None
    layers: list[WmtsLayer]
    matrix_sets: dict[str, TileGrid]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "kvp_url": self.kvp_url,
            "layers": [asdict(lyr) for lyr in self.layers],
            "matrix_sets": {k: asdict(v) for k, v in self.matrix_sets.items()},
        }


def normalize_crs(value: str) -> str:
    """'urn:ogc:def:crs:EPSG::2180', 'urn:ogc:def:crs:EPSG:6.18:3:3857', '.../EPSG/0/2180' -> 'EPSG:2180'.
    'urn:ogc:def:crs:OGC:1.3:CRS84' -> 'OGC:CRS84'."""
    v = value.strip()
    if re.search(r"CRS:?84$", v, re.IGNORECASE):
        return "OGC:CRS84"
    m = re.search(r"EPSG\W.*?(\d+)$", v, re.IGNORECASE)        # kod EPSG = ostatnia liczba
    if m:
        return f"EPSG:{m.group(1)}"
    raise CapabilitiesError(f"Nieobsługiwany zapis układu: {value}")


def _axis_info(crs: str) -> tuple[bool, float]:
    """(czy TopLeftCorner jest w kolejności y,x; metrów na jednostkę układu)."""
    c = pyproj.CRS.from_user_input(crs)
    axes = c.axis_info
    swap = bool(axes) and axes[0].direction.lower() in ("north", "south")
    unit = (axes[0].unit_name or "").lower() if axes else "metre"
    if unit.startswith("degree"):
        mpu = METERS_PER_DEGREE
    else:
        mpu = axes[0].unit_conversion_factor if axes else 1.0
    return swap, mpu


def _text(el: etree._Element | None, path: str) -> str | None:
    if el is None:
        return None
    v = el.findtext(path, namespaces=NS)
    return v.strip() if v else None


def _matrix_set(ms: etree._Element) -> tuple[str, TileGrid]:
    ident = _text(ms, "ows:Identifier") or ""
    crs = normalize_crs(_text(ms, "ows:SupportedCRS") or "")
    swap, mpu = _axis_info(crs)
    resolutions, ids, origins = [], [], []
    tile_size = [256, 256]
    for tm in ms.findall("w:TileMatrix", NS):
        scale = float(_text(tm, "w:ScaleDenominator") or "nan")
        a, b = (float(v) for v in (_text(tm, "w:TopLeftCorner") or "").split()[:2])
        origins.append([b, a] if swap else [a, b])
        resolutions.append(scale * PIXEL_SIZE_M / mpu)
        ids.append(_text(tm, "ows:Identifier") or str(len(ids)))
        tile_size = [int(_text(tm, "w:TileWidth") or 256), int(_text(tm, "w:TileHeight") or 256)]
    if not resolutions:
        raise CapabilitiesError(f"Macierz {ident} nie ma poziomów")
    # OpenLayers wymaga malejących rozdzielczości
    order = sorted(range(len(resolutions)), key=lambda i: -resolutions[i])
    resolutions = [resolutions[i] for i in order]
    ids = [ids[i] for i in order]
    origins = [origins[i] for i in order]
    same = all(o == origins[0] for o in origins)
    return ident, TileGrid(crs=crs, origin=origins[0], resolutions=resolutions, matrix_ids=ids,
                           tile_size=tile_size, origins=None if same else origins)


def _kvp_url(root: etree._Element) -> str | None:
    for op in root.findall(".//ows:OperationsMetadata/ows:Operation", NS):
        if op.get("name") != "GetTile":
            continue
        for get in op.findall(".//ows:HTTP/ows:Get", NS):
            values = [v.text for v in get.findall(".//ows:Value", NS)]
            if not values or "KVP" in values:
                return get.get(f"{{{NS['xlink']}}}href")
    return None


def parse_capabilities(xml: bytes | str) -> Capabilities:
    try:
        root = etree.fromstring(xml.encode() if isinstance(xml, str) else xml,
                                parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise CapabilitiesError(f"To nie jest poprawny XML: {exc}") from exc
    if etree.QName(root).localname != "Capabilities" or root.find("w:Contents", NS) is None:
        if "WMS_Capabilities" in etree.QName(root).localname or "WMT_MS" in etree.QName(root).localname:
            raise CapabilitiesError("To GetCapabilities usługi WMS, a edytor obsługuje WMTS")
        raise CapabilitiesError("To nie jest GetCapabilities usługi WMTS")

    contents = root.find("w:Contents", NS)
    matrix_sets: dict[str, TileGrid] = {}
    for ms in contents.findall("w:TileMatrixSet", NS):
        try:
            ident, grid = _matrix_set(ms)
            matrix_sets[ident] = grid
        except (CapabilitiesError, ValueError, pyproj.exceptions.CRSError):
            continue                                    # macierz w nieznanym układzie pomijamy

    layers = []
    for ly in contents.findall("w:Layer", NS):
        bbox = None
        bb = ly.find("ows:WGS84BoundingBox", NS)
        if bb is not None:
            lo = [float(v) for v in (_text(bb, "ows:LowerCorner") or "0 0").split()]
            hi = [float(v) for v in (_text(bb, "ows:UpperCorner") or "0 0").split()]
            bbox = lo[:2] + hi[:2]
        styles = [_text(s, "ows:Identifier") or "" for s in ly.findall("w:Style", NS)]
        default_style = next((_text(s, "ows:Identifier") for s in ly.findall("w:Style", NS)
                              if s.get("isDefault") == "true"), styles[0] if styles else None)
        resource_urls = {
            r.get("format"): r.get("template") for r in ly.findall("w:ResourceURL", NS)
            if r.get("resourceType") == "tile" and r.get("template")
        }
        layers.append(WmtsLayer(
            identifier=_text(ly, "ows:Identifier") or "",
            title=_text(ly, "ows:Title") or _text(ly, "ows:Identifier") or "",
            formats=[f.text.strip() for f in ly.findall("w:Format", NS) if f.text],
            styles=styles,
            default_style=default_style,
            matrix_sets=[s for s in (_text(link, "w:TileMatrixSet") for link in ly.findall("w:TileMatrixSetLink", NS))
                         if s in matrix_sets],
            wgs84_bbox=bbox,
            resource_urls=resource_urls,
        ))
    if not layers:
        raise CapabilitiesError("Usługa nie publikuje żadnych warstw")
    title = _text(root, "ows:ServiceIdentification/ows:Title")
    return Capabilities(title=title, kvp_url=_kvp_url(root), layers=layers, matrix_sets=matrix_sets)


def strip_capabilities_query(url: str) -> str:
    """'https://x/wmts?service=WMTS&request=getCapabilities' -> 'https://x/wmts?' (adres KVP)."""
    base, _, query = url.partition("?")
    keep = [p for p in query.split("&") if p and p.split("=")[0].lower() not in ("service", "request", "version")]
    return base + "?" + "&".join(keep)
