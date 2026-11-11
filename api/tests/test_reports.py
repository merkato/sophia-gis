from types import SimpleNamespace

from lxml import etree

from app.qgsproject import LayerDef, layout_items
from app.routers.reports import _label_text, project_basemap_layer

# Fragment układu w formacie zapisywanym przez QGIS 4 (typy: 65639 mapa, 65641 etykieta, 65638 strona)
LAYOUT = """<Layout name="Mapa A4 pozioma">
  <PageCollection><LayoutItem type="65638" id="" size="297,210,mm"/></PageCollection>
  <LayoutItem type="65641" id="tytul" labelText="Tytuł" size="200,10,mm"/>
  <LayoutItem type="65639" id="glowna" size="27.7,16,cm"><Extent xmin="0" ymin="0" xmax="1" ymax="1"/></LayoutItem>
  <LayoutItem type="65639" id="przegladowa" size="50,40,mm"><Extent xmin="0" ymin="0" xmax="1" ymax="1"/></LayoutItem>
  <LayoutItem type="65641" id="opis" labelText="" size="200,7,mm"/>
  <LayoutItem type="65641" id="" labelText="bez id"/>
</Layout>"""


def test_layout_items_first_map_in_mm_and_label_ids():
    map_mm, labels = layout_items(etree.fromstring(LAYOUT))
    assert map_mm == [277.0, 160.0]            # pierwsza mapa (= map0 w GetPrint), cm -> mm
    assert labels == ["tytul", "opis"]


def _raster(lid: str, short: str, source: str) -> LayerDef:
    lyr = LayerDef(id=lid, name=lid, short_name=short, type="raster", provider="wms", crs=None, geometry_type=None,
                   display_expression=None)
    lyr.source = source
    return lyr


def test_catalog_basemap_matches_project_layer():
    orto = _raster("o", "orto", "contextualWMSLegend=0&crs=EPSG%3A2180&format=image%2Fjpeg&layers=ORTOFOTOMAPA"
                   "&styles=default&tileMatrixSet=EPSG%3A2180&url=https%3A%2F%2Fmapy.geoportal.gov.pl%2Fwss%2Fservice"
                   "%2FPZGIK%2FORTO%2FWMTS%2FStandardResolution%3Fservice%3DWMTS%26request%3DgetCapabilities")
    osm = _raster("x", "osm", "type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19")
    project = SimpleNamespace(layers={"o": orto, "x": osm})
    wmts = {"url": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution?", "layer": "ORTOFOTOMAPA"}
    assert project_basemap_layer(project, "wmts", wmts) == "orto"
    assert project_basemap_layer(project, "wmts", {**wmts, "layer": "INNA"}) is None
    assert project_basemap_layer(project, "xyz", {"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}) == "osm"


def test_label_text_strips_expressions():
    assert _label_text("Mapa [% env('PGPASSWORD') %] obszaru") == "Mapa  env('PGPASSWORD')  obszaru"
