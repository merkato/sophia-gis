import pytest

from app import fetchers
from app.qgsproject import FieldDef, LayerDef, PgSource, parse_tools

PARCEL = fetchers.SOURCES["uldk_dzialka"]

# Odpowiedź w formacie ULDK (GetParcelByXY, result=id,voivodeship,county,commune,region,parcel,geom_wkt);
# wartości fikcyjne
OK = ("0\n999901_1.0001.123|przykładowe|powiat przykładowy|Przykładowo|Przykładowo|721|"
      "SRID=2180;POLYGON((500000 450000,500100 450000,500100 450100,500000 450000))\n")


def test_parse_and_normalize_parcel():
    raw = fetchers.parse_uldk(OK, PARCEL.uldk_result)
    assert raw["geom_wkt"].startswith("SRID=2180;POLYGON")
    p = fetchers.normalize_uldk(raw)
    assert p == {"teryt": "999901_1.0001.123", "wojewodztwo": "przykładowe", "powiat": "powiat przykładowy",
                 "gmina": "Przykładowo", "obreb": "Przykładowo", "gmina_teryt": "999901_1", "obreb_nr": "0001",
                 "numer": "721"}
    assert set(p) == {k for k, _ in PARCEL.fields}           # Fia i API znają te same pola


def test_parse_uldk_errors():
    with pytest.raises(fetchers.NotFound):
        fetchers.parse_uldk("-1 brak wyników\nbłędny format odpowiedzi XML", PARCEL.uldk_result)
    with pytest.raises(fetchers.FetchError, match="format"):
        fetchers.parse_uldk("0\n1|2|3", PARCEL.uldk_result)
    with pytest.raises(fetchers.FetchError):
        fetchers.parse_uldk("", PARCEL.uldk_result)


def test_building_fields_without_number():
    b = fetchers.SOURCES["uldk_budynek"]
    raw = fetchers.parse_uldk("0\n999901_1.0001.45_BUD|przykładowe|powiat przykładowy|Przykładowo|Przykładowo|POLYGON((1 1,2 2,3 1,1 1))",
                              b.uldk_result)
    p = fetchers.normalize_uldk(raw)
    assert p["teryt"] == "999901_1.0001.45_BUD" and "numer" not in p
    assert set(p) == {k for k, _ in b.fields}


def test_to_2180_identity_and_transform():
    assert fetchers.to_2180(500000, 450000, 2180) == (500000, 450000)
    x, y = fetchers.to_2180(19.0, 52.0, 4326)        # południk osiowy PUWG 1992
    assert abs(x - 500000.0) < 0.01 and abs(y - 459309.2) < 1


def test_rate_limiter():
    lim = fetchers.RateLimiter(limit=2, window=60)
    assert lim.check(1) and lim.check(1) and not lim.check(1)
    assert lim.check(2)


def test_parse_tools_skips_unknown_layers_and_fields():
    lyr = LayerDef(id="dz", name="Działki", short_name=None, type="vector", provider="postgres", crs=None,
                   geometry_type="Polygon", display_expression=None,
                   pg=PgSource("service=sophia", "dane", "dzialki", "geom", "fid", None, None, None))
    lyr.fields = [FieldDef("fid"), FieldDef("teryt"), FieldDef("nr")]
    cfg = {"tools": [
        {"id": "uldk", "source": "uldk_dzialka", "label": "Działka z ULDK", "layer": "dz",
         "fields": {"teryt": "teryt", "numer": "nr", "gmina": "nie_ma_takiego_pola"}, "open_form": False},
        {"id": "x", "source": "uldk_dzialka", "layer": "brak"},
    ]}
    tools = parse_tools(cfg, {"dz": lyr})
    assert len(tools) == 1
    t = tools[0]
    assert (t.id, t.layer_id, t.open_form) == ("uldk", "dz", False)
    assert t.fields == {"teryt": "teryt", "numer": "nr"}
