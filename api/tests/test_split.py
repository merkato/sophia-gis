"""Podział obiektów (POST …/features/split): które kolumny trafiają do nowych części i jak."""
from app.qgsproject import FieldDef, LayerDef, PgSource
from app.routers.features import split_plan


def _parcels() -> LayerDef:
    lyr = LayerDef(id="dzialki", name="Działki", short_name=None, type="vector", provider="postgres", crs=None,
                   geometry_type="Polygon",
                   pg=PgSource("service=sophia", "dane", "dzialki", "geom", "fid", 2180, "MultiPolygon", None))
    lyr.fields = [FieldDef("fid", split_policy="DefaultValue"), FieldDef("nr_decyzji"),
                  FieldDef("pow_ha", split_policy="GeometryRatio"), FieldDef("uwagi", split_policy="UnsetField"),
                  FieldDef("utworzono", split_policy="DefaultValue"), FieldDef("opis", split_policy="GeometryRatio")]
    return lyr


def test_split_plan():
    cols = [("fid", "N"), ("geom", "U"), ("nr_decyzji", "S"), ("pow_ha", "N"), ("uwagi", "S"),
            ("utworzono", "D"), ("opis", "S"), ("oddzial", "S")]
    assert split_plan(_parcels(), cols) == [
        ("nr_decyzji", "Duplicate"),
        ("pow_ha", "GeometryRatio"),
        ("uwagi", "UnsetField"),
        ("opis", "Duplicate"),          # proporcja tylko dla liczb
        ("oddzial", "Duplicate"),       # kolumna spoza formularza QGIS — kopiowana
    ]
