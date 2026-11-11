"""Źródła „pobierz obiekt z usługi zewnętrznej i dodaj do warstwy” (narzędzia pobierania).

Każde źródło: zapytanie po punkcie, normalizacja wyniku do stałego zestawu pól (klucze niezależne
od usługi), geometria jako EWKT. Mapowanie pól źródła na pola warstwy docelowej ustawia autor
projektu w Fii (zakładka „Narzędzia pobierania”) — docs/user/uldk.md.

Nowe źródło (np. PRG adresy, BDOT10k) = nowy wpis w SOURCES + funkcja zapytania; Fia ma tę samą
listę pól (fia/tools.py).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import httpx
from pyproj import Transformer

log = logging.getLogger("sophia.fetch")

ULDK_URL = "https://uldk.gugik.gov.pl/"
TIMEOUT = 25.0


class FetchError(Exception):
    """Błąd usługi zewnętrznej (komunikat dla użytkownika)."""


class NotFound(FetchError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    geometry_type: str                          # typ geometrii wyniku (zgodność z warstwą docelową)
    fields: tuple[tuple[str, str], ...]         # (klucz, etykieta) — kolejność jak w Fii
    request: str = ""
    uldk_result: tuple[str, ...] = ()           # pola ULDK w kolejności odpowiedzi (bez geom_wkt)
    key_field: str = "teryt"                    # identyfikator do wykrywania duplikatów


@dataclass
class Fetched:
    properties: dict[str, str | None]
    ewkt: str                                   # "SRID=2180;POLYGON(...)"
    meta: dict = field(default_factory=dict)


_UDLK_ADMIN = ("voivodeship", "county", "commune", "region")

SOURCES: dict[str, Source] = {
    "uldk_dzialka": Source(
        "uldk_dzialka", "Działka ewidencyjna (ULDK)", "Polygon",
        (("teryt", "Identyfikator działki (TERYT)"), ("numer", "Numer działki"), ("obreb", "Obręb (nazwa)"),
         ("obreb_nr", "Obręb (numer)"), ("gmina", "Gmina"), ("gmina_teryt", "Gmina (TERYT)"),
         ("powiat", "Powiat"), ("wojewodztwo", "Województwo")),
        request="GetParcelByXY", uldk_result=("id", *_UDLK_ADMIN, "parcel")),
    "uldk_budynek": Source(
        "uldk_budynek", "Budynek (ULDK)", "Polygon",
        (("teryt", "Identyfikator budynku"), ("obreb", "Obręb (nazwa)"), ("obreb_nr", "Obręb (numer)"),
         ("gmina", "Gmina"), ("gmina_teryt", "Gmina (TERYT)"), ("powiat", "Powiat"),
         ("wojewodztwo", "Województwo")),
        request="GetBuildingByXY", uldk_result=("id", *_UDLK_ADMIN)),
}


# --------------------------------------------------------------------------- ULDK


def parse_uldk(text: str, result: tuple[str, ...]) -> dict[str, str]:
    """Odpowiedź ULDK: linia 1 = status („0” albo „-1 komunikat”), linia 2 = pola rozdzielone „|”
    w kolejności z parametru result (geom_wkt na końcu)."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        raise FetchError("Pusta odpowiedź ULDK")
    status = lines[0]
    if status.startswith("-1") or not status.startswith("0"):
        msg = status[2:].strip() if status.startswith("-1") else status
        if "brak wynik" in msg.lower():
            raise NotFound("W tym miejscu ULDK nie zwraca obiektu")
        raise FetchError(f"ULDK: {msg or 'błąd'}")
    if len(lines) < 2:
        raise NotFound("W tym miejscu ULDK nie zwraca obiektu")
    values = lines[1].split("|")
    keys = (*result, "geom_wkt")
    if len(values) != len(keys):
        raise FetchError("Nieoczekiwany format odpowiedzi ULDK")
    return dict(zip(keys, values, strict=True))


def normalize_uldk(raw: dict[str, str]) -> dict[str, str | None]:
    """Pola ULDK -> klucze Sophii; z identyfikatora WWPPGG_R.OOOO.NR wyliczamy gminę i numer obrębu."""
    ident = raw.get("id") or None
    parts = ident.split(".") if ident else []
    out: dict[str, str | None] = {
        "teryt": ident,
        "wojewodztwo": raw.get("voivodeship") or None,
        "powiat": raw.get("county") or None,
        "gmina": raw.get("commune") or None,
        "obreb": raw.get("region") or None,
        "gmina_teryt": parts[0] if parts else None,
        "obreb_nr": parts[1] if len(parts) > 1 else None,
    }
    if "parcel" in raw:
        out["numer"] = raw.get("parcel") or None
    return out


_to_2180: dict[int, Transformer] = {}


def to_2180(x: float, y: float, srid: int) -> tuple[float, float]:
    if srid == 2180:
        return x, y
    t = _to_2180.get(srid) or _to_2180.setdefault(srid, Transformer.from_crs(srid, 2180, always_xy=True))
    return t.transform(x, y)


async def fetch_by_point(source: Source, x: float, y: float, srid: int) -> Fetched:
    px, py = to_2180(x, y, srid)
    params = {"request": source.request, "xy": f"{px:.2f},{py:.2f},2180",
              "result": ",".join((*source.uldk_result, "geom_wkt")), "srid": "2180"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            r = await client.get(ULDK_URL, params=params)
    except httpx.HTTPError as e:
        raise FetchError("Usługa ULDK nie odpowiada — spróbuj za chwilę") from e
    log.info("%s %.0f,%.0f -> HTTP %s w %.1fs", source.id, px, py, r.status_code, time.monotonic() - started)
    if r.status_code != 200:
        raise FetchError(f"ULDK: HTTP {r.status_code}")
    raw = parse_uldk(r.text, source.uldk_result)
    ewkt = raw["geom_wkt"]
    if not ewkt.upper().startswith("SRID="):
        ewkt = "SRID=2180;" + ewkt
    return Fetched(normalize_uldk(raw), ewkt, {"point_2180": [round(px, 2), round(py, 2)]})


# --------------------------------------------------------------------------- limit zapytań


class RateLimiter:
    """Prosty limit w pamięci procesu: N zapytań na okno czasu na użytkownika (ochrona usług GUGiK)."""

    def __init__(self, limit: int = 30, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> bool:
        now = time.monotonic()
        q = self._hits[user_id]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


limiter = RateLimiter()
