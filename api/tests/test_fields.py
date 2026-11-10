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
