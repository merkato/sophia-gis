from types import SimpleNamespace

from lxml import etree

from app.qgsproject import LayerDef, layout_items
from app.routers.reports import _label_text, _percents, fit_extent, opacities, project_basemap_layer

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


def test_fit_extent_keeps_frame_proportions():
    frame = [200.0, 250.0]                                   # mm, pion 4:5
    # stała skala: rozmiar ramki × skala wokół środka widoku (proporcje ekranu bez znaczenia)
    assert fit_extent([0, 0, 1000, 200], frame, 1000) == [400.0, -25.0, 600.0, 225.0]
    # cały widok, ekran szeroki: wysokość dociągnięta do proporcji ramki
    assert fit_extent([0, 0, 1000, 200], frame, None) == [0.0, -525.0, 1000.0, 725.0]
    # cały widok, ekran wysoki: szerokość dociągnięta
    assert fit_extent([0, 0, 100, 1000], frame, None) == [-350.0, 0.0, 450.0, 1000.0]
    assert fit_extent([0, 0, 10, 10], None, 500) == [0, 0, 10, 10]


def test_opacities_follow_layer_order():
    names = ["orto", "skan", "dzialki"]
    assert opacities(names, {}) is None                                  # wszystko kryjące — bez parametru
    assert opacities(names, {"skan": 60, "orto": 100}) == "255,153,255"
    assert opacities(names, {"orto": 150, "dzialki": -5}) == "255,255,0"   # przycięte do 0–100
    assert _percents(["a", "b", "c"], "70,x,30") == {"a": 70, "c": 30}
    assert _percents(["a"], None) == {}
