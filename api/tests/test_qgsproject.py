import json
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from app.qgsproject import _parse_fields, get_project, layer_attribution, parse_pg_datasource

QGS = """<!DOCTYPE qgis>
<qgis projectname="Ewidencja testowa" version="4.2.3">
  <projectCrs><spatialrefsys><authid>EPSG:2180</authid></spatialrefsys></projectCrs>
  <layer-tree-group>
    <layer-tree-group name="Ewidencja" checked="Qt::Checked" expanded="1">
      <layer-tree-layer id="dzialki_1" name="Działki" checked="Qt::Checked"/>
      <layer-tree-layer id="wlasciciele_1" name="Właściciele" checked="Qt::Unchecked"/>
    </layer-tree-group>
    <layer-tree-group name="Ortofotomapa 2024" checked="Qt::Checked">
      <layer-tree-layer id="orto_a" name="arkusz_A"/>
      <layer-tree-layer id="orto_b" name="arkusz_B"/>
    </layer-tree-group>
  </layer-tree-group>
  <relations>
    <relation id="rel_dz_wl" name="Właściciele działki" referencedLayer="dzialki_1"
              referencingLayer="wlasciciele_1" strength="Composition">
      <fieldRef referencedField="id" referencingField="dzialka_id"/>
    </relation>
  </relations>
  <projectlayers>
    <maplayer type="vector" geometry="Polygon">
      <id>dzialki_1</id>
      <datasource>service='sophia' key='id' srid=2180 type=MultiPolygon checkPrimaryKeyUnicity='1' table="ewid"."dzialki" (geom) sql="status" = 'aktywna'</datasource>
      <layername>Działki</layername>
      <shortname>dzialki</shortname>
      <srs><spatialrefsys><authid>EPSG:2180</authid></spatialrefsys></srs>
      <provider encoding="UTF-8">postgres</provider>
      <fieldConfiguration>
        <field name="id"><editWidget type="Hidden"><config><Option/></config></editWidget></field>
        <field name="numer"><editWidget type="TextEdit"><config><Option/></config></editWidget></field>
        <field name="uzytek"><editWidget type="ValueMap"><config><Option type="Map">
          <Option type="List" name="map">
            <Option type="Map"><Option type="QString" name="Grunty orne" value="R"/></Option>
            <Option type="Map"><Option type="QString" name="Las" value="Ls"/></Option>
          </Option></Option></config></editWidget></field>
      </fieldConfiguration>
      <aliases><alias field="numer" name="Numer działki" index="1"/></aliases>
      <constraints><constraint field="numer" notnull_strength="1" unique_strength="0" constraints="1"/></constraints>
      <editable><field name="id" editable="0"/><field name="numer" editable="1"/></editable>
    </maplayer>
    <maplayer type="vector" geometry="No geometry">
      <id>wlasciciele_1</id>
      <datasource>service='sophia' key='id' table="ewid"."wlasciciele"</datasource>
      <layername>Właściciele</layername>
      <provider>postgres</provider>
    </maplayer>
    <maplayer type="vector" geometry="Point">
      <id>bez_service</id>
      <datasource>dbname='x' host=localhost port=5432 user='u' password='p' key='id' table="public"."pkt" (geom)</datasource>
      <layername>Punkty</layername>
      <provider>postgres</provider>
    </maplayer>
    <maplayer type="raster"><id>orto_a</id><layername>arkusz_A</layername><provider>gdal</provider></maplayer>
    <maplayer type="raster"><id>orto_b</id><layername>arkusz_B</layername><provider>gdal</provider></maplayer>
  </projectlayers>
  <Layouts>
    <Layout name="Karta działki"><Atlas enabled="1" coverageLayer="dzialki_1"/></Layout>
    <Layout name="Mapa A4"/>
  </Layouts>
</qgis>
"""


def test_parse_pg_datasource_with_filter():
    src = parse_pg_datasource(
        """service='sophia' key='id' srid=2180 type=MultiPolygon table="ewid"."dzialki" (geom) sql="a" = 'b'""")
    assert (src.schema, src.table, src.geometry_column, src.key, src.srid) == ("ewid", "dzialki", "geom", "id", 2180)
    assert src.conninfo == "service=sophia"
    assert src.sql_filter == "\"a\" = 'b'"


def test_parse_pg_datasource_requires_service():
    with pytest.raises(ValueError):
        parse_pg_datasource("""dbname='x' host=h key='id' table="public"."t" (geom)""")


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    path = tmp_path / "ewid.qgz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ewid.qgs", QGS)
    (tmp_path / "ewid.portal.json").write_text(json.dumps({
        "layers": {"dzialki_1": {"editable": True},
                   "bez_service": {"editable": True}},
        "raster_groups": ["Ortofotomapa 2024"],
        "reports": [{"layout": "Mapa A4", "enabled": False}],
    }), "utf-8")
    return path


def test_load_project(project_path: Path):
    p = get_project(project_path)
    assert p.title == "Ewidencja testowa" and p.crs == "EPSG:2180"

    dz = p.layers["dzialki_1"]
    assert dz.editable and dz.wms_name == "dzialki" and dz.geometry_type == "Polygon"
    numer = next(f for f in dz.fields if f.name == "numer")
    assert numer.alias == "Numer działki" and numer.not_null
    uzytek = next(f for f in dz.fields if f.name == "uzytek")
    assert uzytek.widget == "ValueMap" and uzytek.widget_config["map"][1] == {"Las": "Ls"}
    assert not next(f for f in dz.fields if f.name == "id").editable

    # Warstwa bez service= nie może być edytowalna mimo ustawienia w .portal.json
    assert p.layers["bez_service"].pg is None and not p.layers["bez_service"].editable
    assert p.layers["wlasciciele_1"].geometry_type is None

    rel = p.relations[0]
    assert rel.parent_layer == "dzialki_1" and rel.pairs == [("id", "dzialka_id")] and rel.strength == "Composition"

    kinds = {c.name: c.kind for c in p.tree.children}
    assert kinds == {"Ewidencja": "group", "Ortofotomapa 2024": "raster_group"}
    assert [(r.layout, r.layer_id) for r in p.reports] == [("Karta działki", "dzialki_1")]


def test_raster_tile_format():
    from app.qgsproject import TILE_JPEG, TILE_PNG8, raster_tile_format

    assert raster_tile_format("wms", "crs=EPSG%3A2180&format=image%2Fjpeg&layers=ORTO") == TILE_JPEG
    assert raster_tile_format("wms", "format=image/png&layers=dzialki") == TILE_PNG8
    assert raster_tile_format("gdal", "./rastry/arkusz.tif") == TILE_PNG8


def test_start_extent_priority():
    from lxml import etree

    from app.qgsproject import start_extent

    view = '<ProjectViewSettings><DefaultViewExtent xmin="1" ymin="2" xmax="3" ymax="4"/></ProjectViewSettings>'
    wms = "<properties><WMSExtent><value>10</value><value>20</value><value>30</value><value>40</value></WMSExtent></properties>"
    canvas = "<mapcanvas><extent><xmin>5</xmin><ymin>6</ymin><xmax>7</xmax><ymax>8</ymax></extent></mapcanvas>"
    assert start_extent(etree.fromstring(f"<qgis>{view}{wms}{canvas}</qgis>"), "EPSG:2180") == [1, 2, 3, 4]
    assert start_extent(etree.fromstring(f"<qgis>{wms}{canvas}</qgis>"), "EPSG:2180") == [10, 20, 30, 40]
    assert start_extent(etree.fromstring(f"<qgis>{canvas}</qgis>"), "EPSG:2180") == [5, 6, 7, 8]
    assert start_extent(etree.fromstring("<qgis/>"), "EPSG:2180") is None


def test_layer_attribution():
    ml = etree.fromstring(
        '<maplayer><resourceMetadata><rights>Domena publiczna</rights></resourceMetadata>'
        '<attribution href="https://example.org/zbiory">Biblioteka Przykładowa</attribution></maplayer>')
    assert layer_attribution(ml) == ("Biblioteka Przykładowa", "https://example.org/zbiory")
    ml = etree.fromstring(
        '<maplayer><resourceMetadata><rights>Domena publiczna</rights></resourceMetadata>'
        '<attribution href="javascript:alert(1)"></attribution></maplayer>')
    assert layer_attribution(ml) == ("Domena publiczna", None)
    assert layer_attribution(etree.fromstring("<maplayer/>")) == (None, None)


def test_split_policies():
    ml = etree.fromstring(
        '<maplayer><fieldConfiguration><field name="id"/><field name="nazwa"/><field name="pow"/>'
        '<field name="nr"/></fieldConfiguration><splitPolicies>'
        '<policy field="id" policy="DefaultValue"/><policy field="pow" policy="GeometryRatio"/>'
        '<policy field="nr" policy="Nieznana"/></splitPolicies></maplayer>')
    pol = {f.name: f.split_policy for f in _parse_fields(ml)}
    assert pol == {"id": "DefaultValue", "nazwa": "Duplicate", "pow": "GeometryRatio", "nr": "Duplicate"}
