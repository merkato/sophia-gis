"""Wtyczki: manifest, zgodność wersji, zależności, ładowanie routera."""
import json
from pathlib import Path

from fastapi import FastAPI

from app import plugins


def _plugin(root: Path, pid: str, **manifest) -> Path:
    d = root / pid
    d.mkdir()
    (d / "sophia-plugin.json").write_text(json.dumps({"id": pid, "name": pid, "version": "1.0", **manifest}),
                                          encoding="utf-8")
    return d


def test_version_ok():
    assert plugins.version_ok("", "0.1.0")
    assert plugins.version_ok(">=0.1", "0.1.0")
    assert plugins.version_ok(">=1.0, <2", "1.4.2")
    assert not plugins.version_ok(">=1.0, <2", "2.0")
    assert not plugins.version_ok("==1.0", "1.1")
    assert not plugins.version_ok("~1.0", "1.0")


def test_discover_checks_manifest_and_dependencies(tmp_path):
    _plugin(tmp_path, "baza", capabilities=[{"id": "baza.podglad", "title": "Podgląd"}])
    _plugin(tmp_path, "nad", requires={"baza": ">=1.0"})
    _plugin(tmp_path, "zla_wersja", requires={"baza": ">=2"})
    _plugin(tmp_path, "brak", requires={"nieistniejaca": ""})
    _plugin(tmp_path, "lancuch", requires={"brak": ""})
    _plugin(tmp_path, "obca", capabilities=[{"id": "inna.cos"}])
    _plugin(tmp_path, "sophia_za_stara", sophia=">=99")
    d = tmp_path / "zly_katalog"
    d.mkdir()
    (d / "sophia-plugin.json").write_text('{"id": "inna_nazwa"}', encoding="utf-8")
    found = plugins.discover(tmp_path)
    assert found["baza"].error is None and found["nad"].error is None
    assert "nie spełnia" in found["zla_wersja"].error
    assert "brak wtyczki" in found["brak"].error
    assert "nie działa" in found["lancuch"].error
    assert "zaczynać się" in found["obca"].error
    assert "Wymaga Sophii" in found["sophia_za_stara"].error
    assert "nazwa katalogu" in found["zly_katalog"].error


def test_load_mounts_router_under_plugin_prefix(tmp_path):
    d = _plugin(tmp_path, "demo_ladowania", api={"package": "demo_ladowania_api"}, web={"entry": "web/index.js"})
    pkg = d / "api" / "demo_ladowania_api"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/ping')\nasync def ping():\n    return 'pong'\n",
        encoding="utf-8")
    _plugin(tmp_path, "zepsuta", api={"package": "nie_ma_takiego_pakietu"})
    app = FastAPI()
    plugins.load_into(app, tmp_path)
    paths = set(app.openapi()["paths"])
    assert "/api/plugins/demo_ladowania/ping" in paths
    assert plugins.REGISTRY["demo_ladowania"].error is None
    assert "Błąd ładowania" in plugins.REGISTRY["zepsuta"].error
    assert plugins.REGISTRY["demo_ladowania"].web_entry == "web/index.js"
