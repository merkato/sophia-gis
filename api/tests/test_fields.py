from app.qgsproject import FieldDef, LayerDef, PgSource
from app.routers.fields import label_field


def _layer(display: str | None) -> LayerDef:
    lyr = LayerDef(id="projekty", name="Projekty", short_name=None, type="vector", provider="postgres",
                   crs=None, geometry_type=None, display_expression=display,
                   pg=PgSource("service=sophia", "dane", "projekty_kolejowe", None, "fid", None, None, None))
    lyr.fields = [FieldDef("fid", type="integer"), FieldDef("nazwa", type="varchar(255)"), FieldDef("url", type="text")]
    return lyr


def test_label_field():
    assert label_field(_layer('"url"')) == "url"            # wyrażenie wyświetlane = pole
    assert label_field(_layer("nazwa")) == "nazwa"
    assert label_field(_layer("concat(nazwa, url)")) == "nazwa"   # wyrażenie -> pierwsze pole tekstowe
    assert label_field(_layer(None)) == "nazwa"              # nigdy klucz główny
    assert label_field(_layer("COALESCE( \"nazwa\", '<NULL>' )")) == "nazwa"   # pole z wyrażenia
    assert label_field(_layer("\"url\" || ' ' || \"nazwa\"")) == "url"


def test_label_field_without_types():
    # QGIS nie zapisuje typów pól w projekcie — wtedy pierwsze pole poza kluczem
    lyr = _layer(None)
    lyr.fields = [FieldDef("fid"), FieldDef("nazwa"), FieldDef("url")]
    assert label_field(lyr) == "nazwa"


def test_empty_widget_config_is_dict():
    """QGIS zapisuje czasem pustą konfigurację widżetu (<Option/>) — API zawsze daje obiekt, nie null."""
    from lxml import etree

    from app.qgsproject import _parse_fields
    ml = etree.fromstring(
        '<maplayer><fieldConfiguration>'
        '<field name="gmina"><editWidget type="TextEdit"><config><Option/></config></editWidget></field>'
        '<field name="obreb"><editWidget type="TextEdit"><config><Option type="Map">'
        '<Option name="IsMultiline" type="bool" value="false"/></Option></config></editWidget></field>'
        '</fieldConfiguration></maplayer>')
    fields = {f.name: f for f in _parse_fields(ml)}
    assert fields["gmina"].widget_config == {}
    assert fields["obreb"].widget_config == {"IsMultiline": False}
