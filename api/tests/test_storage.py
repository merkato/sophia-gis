"""Przechowywanie plików: zbiory z pól „Załącznik”, sprawdzanie limitów (panel i Fia)."""
from types import SimpleNamespace

import pytest

from app import storage
from app.qgsproject import FieldDef, LayerDef


def _layer(lid: str, name: str, fields: list[FieldDef], pg: bool = True, hidden: bool = False) -> LayerDef:
    lyr = LayerDef(id=lid, name=name, short_name=None, type="vector", provider="postgres", crs="EPSG:2180",
                   geometry_type="Point", display_expression=None)
    lyr.pg = SimpleNamespace(table=lid) if pg else None
    lyr.fields = fields
    lyr.hidden = hidden
    return lyr


def test_layer_sets_from_attachment_fields():
    foto = FieldDef("plik", alias="Zdjęcie", widget="ExternalResource", widget_config={"DocumentViewer": 1})
    dok = FieldDef("skan", widget="ExternalResource", widget_config={"FileWidgetFilter": "PDF (*.pdf)"})
    project = SimpleNamespace(layers={
        "z": _layer("z", "Zdjęcia", [FieldDef("opis"), foto]),
        "d": _layer("d", "Dokumenty", [dok]),
        "plik": _layer("plik", "Plik GPKG", [dok], pg=False),          # nie PostGIS — bez wysyłania z WebUI
        "ukryta": _layer("ukryta", "Ukryta", [foto], hidden=True),      # „Tylko w QGIS”
    })
    sets = storage.layer_sets(project)
    assert [(s["id"], s["kind"]) for s in sets] == [("d:skan", "file"), ("z:plik", "photo")]
    assert sets[1]["title"] == "Zdjęcia — Zdjęcie"


def test_clean_limits(monkeypatch):
    monkeypatch.setattr(storage, "global_mb", lambda kind: 40 if kind == "photo" else 50)
    allowed = {"z:plik": "photo", "d:skan": "file"}
    out = storage.clean_limits({"z:plik": 10, "d:skan": None}, allowed)
    assert {k: float(v) for k, v in out.items()} == {"z:plik": 10.0}
    assert storage.clean_limits({"z:plik": 40}, allowed) == {}          # równy globalnemu = domyślny
    assert float(storage.clean_limits({"d:skan": "2.55"}, allowed)["d:skan"]) == 2.6
    for zle in ({"z:plik": 41}, {"z:plik": 0}, {"z:plik": "dużo"}, {"inny:pole": 5}):
        with pytest.raises(ValueError):
            storage.clean_limits(zle, allowed)
