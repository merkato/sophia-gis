"""Narzędzia edycji geometrii: podział (polityki pól), pierścienie (walidacja szkicu)."""
import pytest
from fastapi import HTTPException

from app.qgsproject import FieldDef, LayerDef, PgSource
from app.routers.features import _is_multi, _ring_sql, split_plan


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


def test_ring_sketch_must_be_polygon():
    lyr = _parcels()
    assert _is_multi(lyr)
    with pytest.raises(HTTPException) as e:
        _ring_sql(lyr, {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, 2180)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        _ring_sql(lyr, {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]}, 2180)
    _ring_sql(lyr, {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, 2180)


def test_reshape_mode():
    from app.routers.features import reshape_mode
    assert reshape_mode(10.0, 0.0) == "outside"
    assert reshape_mode(10.0, 10.0) == "inside"
    assert reshape_mode(10.0, 4.0) == "mixed"


def test_copy_plan_uses_duplicate_policy():
    lyr = _parcels()
    lyr.fields[1].duplicate_policy = "UnsetField"          # nr_decyzji
    lyr.fields[2].duplicate_policy = "DefaultValue"        # pow_ha
    assert split_plan(lyr, [("nr_decyzji", "S"), ("pow_ha", "N"), ("uwagi", "S")], "duplicate_policy") == [
        ("nr_decyzji", "UnsetField"), ("uwagi", "Duplicate")]
