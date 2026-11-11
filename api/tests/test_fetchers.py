import pytest

from app import fetchers
from app.qgsproject import FieldDef, LayerDef, PgSource, parse_tools

PARCEL = fetchers.SOURCES["uldk_dzialka"]

# Odpowiedź ULDK (GetParcelByXY, result=id,voivodeship,county,commune,region,parcel,geom_wkt)
OK = ("0\n160805_2.0065.721|opolskie|powiat oleski|Radłów|Radłów|721|"
      "SRID=2180;POLYGON((466527.6 339829.4,466445.3 339592.6,466434.5 339561.6,466527.6 339829.4))\n")


def test_parse_and_normalize_parcel():
    raw = fetchers.parse_uldk(OK, PARCEL.uldk_result)
    assert raw["geom_wkt"].startswith("SRID=2180;POLYGON")
    p = fetchers.normalize_uldk(raw)
    assert p == {"teryt": "160805_2.0065.721", "wojewodztwo": "opolskie", "powiat": "powiat oleski",
                 "gmina": "Radłów", "obreb": "Radłów", "gmina_teryt": "160805_2", "obreb_nr": "0065",
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
    raw = fetchers.parse_uldk("0\n160803_4.0068.5045_BUD|opolskie|powiat oleski|Olesno|Olesno|POLYGON((1 1,2 2,3 1,1 1))",
                              b.uldk_result)
    p = fetchers.normalize_uldk(raw)
    assert p["teryt"] == "160803_4.0068.5045_BUD" and "numer" not in p
    assert set(p) == {k for k, _ in b.fields}


def test_to_2180_identity_and_transform():
    assert fetchers.to_2180(466300, 338700, 2180) == (466300, 338700)
    x, y = fetchers.to_2180(18.4205, 50.8759, 4326)
    assert abs(x - 459240.7) < 1 and abs(y - 334493.1) < 1


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
