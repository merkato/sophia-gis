"""Sophia: filtr zakresu danych w QGIS Server (mapa, identyfikacja, wydruk).

API Sophii (forward_auth z Caddy dla /ows, wywołanie GetPrint z raportów) dodaje do żądania nagłówek
X-Sophia-Filter = base64url(zlib(JSON {id_warstwy: warunek SQL})). Warunek trafia do warstwy jako
subset string (QgsAccessControlFilter.layerFilterSubsetString) — QGIS dokleja go do zapytania
dostawcy PostgreSQL, więc obraz mapy, GetFeatureInfo i GetPrint widzą tylko rekordy z zakresu
użytkownika (api/app/scope.py). Caddy usuwa nagłówek przysłany przez klienta.

Brak nagłówka = brak filtrów (wywołania wewnętrzne). Uszkodzony nagłówek = nic nie widać (fail closed).
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import zlib

from qgis.core import Qgis, QgsMessageLog, QgsVectorLayer
from qgis.server import QgsAccessControlFilter

HEADER = "X-Sophia-Filter"
ENV = "HTTP_X_SOPHIA_FILTER"       # FastCGI (Apache mod_fcgid) przekazuje nagłówki jako zmienne środowiska
DENY = "1 = 0"

try:  # getenv z libc widzi środowisko bieżącego żądania FastCGI (os.environ to kopia ze startu procesu)
    _libc = ctypes.CDLL(None)
    _libc.getenv.restype = ctypes.c_char_p
    _libc.getenv.argtypes = [ctypes.c_char_p]
except OSError:  # pragma: no cover
    _libc = None


def _log(msg: str, level=Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(msg, "sophia_filter", level)


def decode(raw: str) -> dict[str, str]:
    data = zlib.decompress(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    filters = json.loads(data.decode("utf-8"))
    if not isinstance(filters, dict):
        raise ValueError("oczekiwano obiektu JSON")
    return {str(k): str(v) for k, v in filters.items()}


class SophiaAccessControl(QgsAccessControlFilter):
    def __init__(self, server_iface):
        super().__init__(server_iface)
        self._iface = server_iface
        self._raw_cache: str | None = None
        self._filters_cache: dict[str, str] | None = None

    def _raw(self) -> str:
        raw = ""
        try:
            handler = self._iface.requestHandler()
            if handler is not None:
                raw = handler.requestHeader(HEADER) or ""
        except Exception:  # noqa: BLE001 — API różni się między wersjami QGIS
            raw = ""
        if not raw and _libc is not None:
            v = _libc.getenv(ENV.encode())
            raw = v.decode("ascii", "ignore") if v else ""
        return raw.strip()

    def _filters(self) -> dict[str, str] | None:
        """None = nagłówek uszkodzony (odmowa); {} = bez filtrów."""
        raw = self._raw()
        if raw == self._raw_cache:
            return self._filters_cache
        self._raw_cache = raw
        if not raw:
            self._filters_cache = {}
        else:
            try:
                self._filters_cache = decode(raw)
            except Exception as e:  # noqa: BLE001
                _log(f"Nieprawidłowy nagłówek {HEADER}: {e}")
                self._filters_cache = None
        return self._filters_cache

    def layerFilterSubsetString(self, layer):  # noqa: N802 — API QGIS
        filters = self._filters()
        if filters is None:
            return DENY if isinstance(layer, QgsVectorLayer) else ""
        return filters.get(layer.id(), "")

    def layerFilterExpression(self, layer):  # noqa: N802
        return ""

    def cacheKey(self):  # noqa: N802 — różne zakresy = różne wpisy w cache serwera
        raw = self._raw()
        return hashlib.sha1(raw.encode()).hexdigest() if raw else ""


class SophiaFilterPlugin:
    def __init__(self, server_iface):
        self.access_control = SophiaAccessControl(server_iface)
        server_iface.registerAccessControl(self.access_control, 100)
        _log("Filtr zakresu danych Sophii aktywny", Qgis.MessageLevel.Info)


def serverClassFactory(server_iface):  # noqa: N802 — wymagane przez QGIS Server
    return SophiaFilterPlugin(server_iface)
