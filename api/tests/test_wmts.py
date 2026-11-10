from pathlib import Path

import pytest

from app.routers.basemaps import BasemapIn, _prefer_https
from app.wmts import CapabilitiesError, normalize_crs, parse_capabilities, strip_capabilities_query

DATA = Path(__file__).parent / "data"


def test_geoportal_topo_capabilities():
    caps = parse_capabilities((DATA / "wmts_topo_geoportal.xml").read_bytes())
    layer = caps.layers[0]
    assert layer.identifier == "MAPA TOPOGRAFICZNA"
    assert layer.formats == ["image/jpeg"]
    assert set(layer.matrix_sets) == {"EPSG:2180", "EPSG:4326"}

    g = caps.matrix_sets["EPSG:2180"]
    assert g.crs == "EPSG:2180"
    # TopLeftCorner "850000.0 100000.0" (północ, wschód) -> OpenLayers x=100000, y=850000
    assert g.origin == [100000.0, 850000.0]
    assert g.tile_size == [512, 512]
    assert g.resolutions[0] == pytest.approx(2116.6709, rel=1e-6)
    assert g.resolutions[-1] == pytest.approx(0.264584, rel=1e-5)
    assert g.resolutions == sorted(g.resolutions, reverse=True)
    assert g.matrix_ids[0] == "EPSG:2180:0"

    # EPSG:4326: "56.0 12.0" (szerokość, długość) -> x=12, y=56, rozdzielczość w stopniach
    g4 = caps.matrix_sets["EPSG:4326"]
    assert g4.origin == [12.0, 56.0]
    assert g4.resolutions[0] < 1

    assert caps.kvp_url.endswith("/wmts/TOPO?")


def test_normalize_crs():
    assert normalize_crs("urn:ogc:def:crs:EPSG::2180") == "EPSG:2180"
    assert normalize_crs("urn:ogc:def:crs:EPSG:6.18:3:3857") == "EPSG:3857"
    assert normalize_crs("http://www.opengis.net/def/crs/EPSG/0/4326") == "EPSG:4326"
    assert normalize_crs("urn:ogc:def:crs:OGC:1.3:CRS84") == "OGC:CRS84"


def test_rejects_wms_and_garbage():
    with pytest.raises(CapabilitiesError, match="WMS"):
        parse_capabilities(b'<WMS_Capabilities version="1.3.0"><Service/></WMS_Capabilities>')
    with pytest.raises(CapabilitiesError):
        parse_capabilities(b"<html>nie to</html>")
    with pytest.raises(CapabilitiesError):
        parse_capabilities(b"to nie XML")


def test_urls():
    assert strip_capabilities_query("https://x/wmts?service=WMTS&request=getCapabilities") == "https://x/wmts?"
    assert strip_capabilities_query("https://x/wmts?key=1&REQUEST=GetCapabilities") == "https://x/wmts?key=1"
    src = "https://mapy.geoportal.gov.pl/wss/service/WMTS/guest/wmts/TOPO?service=WMTS&request=getCapabilities"
    assert _prefer_https("http://mapy.geoportal.gov.pl/wss/x?", src) == "https://mapy.geoportal.gov.pl/wss/x?"
    assert _prefer_https("http://inny.host/x?", src) == "http://inny.host/x?"


def test_basemap_validation():
    grid = {"crs": "EPSG:2180", "origin": [0, 0], "resolutions": [1.0], "matrix_ids": ["0"], "tile_size": [256, 256]}
    ok = {"url": "https://a/wmts?", "layer": "L", "matrix_set": "EPSG:2180", "format": "image/png", "tile_grid": grid}
    BasemapIn(name="Orto", kind="wmts", config=ok)
    with pytest.raises(ValueError, match="https"):
        BasemapIn(name="Orto", kind="wmts", config={**ok, "url": "http://a/wmts?"})
    with pytest.raises(ValueError, match="layer"):
        BasemapIn(name="Orto", kind="wmts", config={k: v for k, v in ok.items() if k != "layer"})
    BasemapIn(name="TK25", kind="sophia", config={"project": "_podklady", "layers": "tk25"})
