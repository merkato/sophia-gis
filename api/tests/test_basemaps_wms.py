"""Rodzaj podkładu „wms” (zewnętrzna usługa WMS) — walidacja konfiguracji."""
import pytest
from pydantic import ValidationError

from app.routers.basemaps import BasemapIn


def test_wms_basemap_config():
    b = BasemapIn(name="Plany", kind="wms", is_overlay=True,
                  config={"url": "https://example.test/wms", "layers": "a,b", "format": "image/png"})
    assert b.kind == "wms"
    with pytest.raises(ValidationError):
        BasemapIn(name="x", kind="wms", config={"url": "https://example.test/wms"})          # brak warstw
    with pytest.raises(ValidationError):
        BasemapIn(name="x", kind="wms", config={"url": "http://example.test/wms", "layers": "a"})   # bez https
