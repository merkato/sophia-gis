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
