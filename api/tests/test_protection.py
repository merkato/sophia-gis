"""Obiekty chronione: reguły z manifestu wtyczki, dopasowanie warstwy, warunek SQL, bezpiecznik w kontekście."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import plugins
from app.permissions import ProjectContext
from app.protection import Rule, flag_sql, parse_rules, rule_for
from app.qgsproject import LayerDef, PgSource
from app.security import CurrentUser

RULE = {"table": "egib.v_dzialka", "field": "zrodlo", "values": ["EGiB"], "message": "Z importu GML"}


def lyr(schema="egib", table="v_dzialka"):
    return LayerDef(id="d", name="Działki", short_name=None, type="vector", provider="postgres", crs=None,
                    geometry_type="Polygon", pg=PgSource("service=x", schema, table, "geom", "klucz", 2180,
                                                         "MultiPolygon", None))


def test_parse_rules():
    (r,) = parse_rules([RULE], "egib")
    assert r == Rule("egib.v_dzialka", "zrodlo", ("EGiB",), "Z importu GML", "egib")
    assert parse_rules(None, "x") == []
    for bad in ([{"table": "bez_schematu", "field": "f", "values": ["a"]}], [{"table": "a.b", "field": "f", "values": []}],
                ["napis"]):
        with pytest.raises(ValueError):
            parse_rules(bad, "x")


def test_rule_for_and_sql():
    rules = parse_rules([RULE], "egib")
    assert rule_for(lyr(), rules).field == "zrodlo"
    assert rule_for(lyr("egib", "v_uzytek"), rules) is None
    assert "zrodlo" in repr(flag_sql(rules[0], ("t",))) and "EGiB" in repr(flag_sql(rules[0], ("t",)))


def test_manifest_protected(tmp_path):
    d = tmp_path / "egib"
    d.mkdir()
    (d / "sophia-plugin.json").write_text(json.dumps({"id": "egib", "version": "1", "protected": [RULE]}), "utf-8")
    p = plugins.read_manifest(d)
    assert p.error is None and p.protected[0].table == "egib.v_dzialka"
    (d / "sophia-plugin.json").write_text(json.dumps({"id": "egib", "protected": [{"table": "x"}]}), "utf-8")
    assert "protected" in (plugins.read_manifest(d).error or "")


def ctx(role, admin=False, until=None):
    user = CurrentUser(1, "u", None, admin, [], [], False)
    return ProjectContext(1, "p", "P", None, None, role, user, {}, unlock_until=until)


def test_can_edit_protected():
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert not ctx("manager").can_edit_protected                       # bez odblokowania nikt
    assert ctx("manager", until=soon).can_edit_protected                # zarządzający w czasie odblokowania
    assert ctx("viewer", admin=True, until=soon).can_edit_protected     # administrator
    assert not ctx("editor", until=soon).can_edit_protected             # edytor — nie
    assert not ctx("manager", until=past).can_edit_protected            # po czasie — nie


def test_combine_layer_access():
    from app.permissions import combine_layer_access, LayerPerms
    row = lambda g, l, i=False, u=False, d=False, v=True: {"group_id": g, "layer_id": l, "can_view": v,  # noqa: E731
                                                           "can_insert": i, "can_update": u, "can_delete": d}
    # nadleśnictwa (edycja): lustracje — dodawanie i zmiana, kontury — tylko podgląd
    rows = [row(1, "lustracje", True, True), row(1, "kontury")]
    p = combine_layer_access({1: "editor"}, rows)
    assert p["lustracje"] == LayerPerms(True, True, True, False)
    assert p["kontury"] == LayerPerms(True, False, False, False)
    assert "dzialki" not in p                                            # bez ustawienia — z roli
    # druga grupa z rolą „edycja” bez ustawień dla konturów — suma: kontury edytowalne
    p = combine_layer_access({1: "editor", 2: "editor"}, rows)
    assert p["kontury"] == LayerPerms(True, True, True, True)
    # druga grupa tylko „podgląd” — kontury nadal tylko podgląd
    p = combine_layer_access({1: "editor", 2: "viewer"}, rows)
    assert p["kontury"] == LayerPerms(True, False, False, False)
    # wpis grupy, do której użytkownik nie należy — pomijany
    assert combine_layer_access({1: "editor"}, [row(9, "kontury")]) == {}
