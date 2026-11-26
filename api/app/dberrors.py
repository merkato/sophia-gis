"""Błędy zapisu z bazy jako komunikaty dla użytkownika — po polsku, z tym, co trzeba poprawić.

Kolejność:
1. komentarz ograniczenia w bazie (`COMMENT ON CONSTRAINT nazwa ON tabela IS '…'`) — własny komunikat warstwy albo
   wtyczki; może zawierać `{kolumna}` — wartość z klucza, który się powtórzył (np. „Ten kontur ma już lustrację nr {nr}”);
2. ogólny opis rodzaju błędu (powtórzona wartość, brak wymaganego pola, powiązane rekordy, za długi tekst…);
3. komunikat wyzwalacza (`RAISE EXCEPTION '…'`) — bez zmian, pisze go autor wyzwalacza.

Komentarze czytane są z bazy portalu (tam są tabele wtyczek); dla innych baz zostaje ogólny opis.
Wtyczki: `await komunikat_bazy(e)` daje ten sam tekst co rdzeń (np. do własnego HTTPException).
"""
from __future__ import annotations

import logging
import re

import psycopg

log = logging.getLogger("sophia")

_KLUCZ = re.compile(r"Key \((?P<kol>.+?)\)=\((?P<wart>.*)\)")
_FK_BRAK = re.compile(r'is not present in table "(?P<tab>[^"]+)"')
_FK_UZYTY = re.compile(r'is still referenced from table "(?P<tab>[^"]+)"')
_DLUGOSC = re.compile(r"character varying\((\d+)\)")
_SKLADNIA = re.compile(r'(?:invalid input syntax|invalid input value) for (?:type )?(?P<typ>[\w ]+?): "(?P<wart>[^"]*)"')
_TYPY = {"integer": "liczbę całkowitą", "bigint": "liczbę całkowitą", "smallint": "liczbę całkowitą",
         "numeric": "liczbę (część dziesiętną po kropce, np. 0.25)", "double precision": "liczbę", "real": "liczbę",
         "date": "datę w postaci RRRR-MM-DD", "timestamp": "datę i godzinę", "boolean": "tak albo nie", "uuid": "identyfikator"}


def _klucz(detail: str | None) -> dict[str, str]:
    """„Key (kontur_id, nr)=(12, 1) already exists.” → {"kontur_id": "12", "nr": "1"} (proste wartości bez przecinków)."""
    m = _KLUCZ.search(detail or "")
    if not m:
        return {}
    kol = [k.strip().strip('"') for k in m.group("kol").split(",")]
    wart = [w.strip() for w in m.group("wart").split(",")]
    return dict(zip(kol, wart)) if len(kol) == len(wart) else {}


def _pola(nazwy) -> str:
    return ", ".join(f"„{n}”" for n in nazwy)


def opis_ogolny(e: psycopg.Error) -> str:
    """Opis błędu bez dostępu do bazy — rodzaj błędu i wskazówka, co poprawić."""
    d = e.diag
    pierwotny = (d.message_primary if d else None) or str(e).splitlines()[0]
    detail = d.message_detail if d else None
    if isinstance(e, psycopg.errors.UniqueViolation):
        klucz = _klucz(detail)
        if klucz:
            wartosci = ", ".join(f"„{k}” = {v}" for k, v in klucz.items())
            return f"taki zapis już istnieje ({wartosci}) — zmień {'tę wartość' if len(klucz) == 1 else 'jedną z tych wartości'}"
        return "taki zapis już istnieje — zmień wartość, która musi być niepowtarzalna"
    if isinstance(e, psycopg.errors.NotNullViolation):
        if d and d.column_name and pierwotny.startswith("null value"):
            return f"uzupełnij pole „{d.column_name}” — jest wymagane"
        return pierwotny
    if isinstance(e, psycopg.errors.ForeignKeyViolation):
        if m := _FK_UZYTY.search(detail or ""):
            return f"są z tym powiązane inne rekordy (tabela „{m.group('tab')}”) — najpierw usuń albo przenieś je"
        if m := _FK_BRAK.search(detail or ""):
            pola = _pola(_klucz(detail)) or "powiązania"
            return f"wartość pola {pola} nie wskazuje istniejącego rekordu (tabela „{m.group('tab')}”) — wybierz inną"
        return pierwotny
    if isinstance(e, psycopg.errors.CheckViolation) and d and d.constraint_name:
        return f"niedozwolona wartość (warunek „{d.constraint_name}”) — popraw wartości pól"
    if isinstance(e, psycopg.errors.ExclusionViolation) and d and d.constraint_name:
        return "zapis koliduje z istniejącym (np. nakładające się zakresy lub obszary) — popraw wartości"
    if isinstance(e, psycopg.errors.StringDataRightTruncation):
        m = _DLUGOSC.search(pierwotny)
        return f"za długi tekst — najwyżej {m.group(1)} znaków" if m else "za długi tekst"
    if isinstance(e, psycopg.errors.NumericValueOutOfRange):
        return "liczba poza dopuszczalnym zakresem — popraw wartość"
    if isinstance(e, (psycopg.errors.InvalidTextRepresentation, psycopg.errors.InvalidDatetimeFormat,
                      psycopg.errors.DatetimeFieldOverflow)):
        m = _SKLADNIA.search(pierwotny)
        if m:
            oczekiwano = next((t for k, t in _TYPY.items() if m.group("typ").startswith(k)), None)
            return (f"niepoprawna wartość „{m.group('wart')}”" + (f" — wpisz {oczekiwano}" if oczekiwano else " — popraw ją"))
        return "niepoprawny zapis wartości — popraw format (liczba, data RRRR-MM-DD)"
    return pierwotny


async def komentarz_ograniczenia(e: psycopg.Error) -> str | None:
    """Komunikat z komentarza ograniczenia w bazie portalu (z podstawionymi wartościami klucza) albo None."""
    d = e.diag
    if not (d and d.constraint_name and d.table_name):
        return None
    from .db import portal_conn
    try:
        async with portal_conn() as conn:
            row = await (await conn.execute(
                """SELECT obj_description(c.oid, 'pg_constraint') AS opis
                     FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                     JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE c.conname = %s AND t.relname = %s AND (%s::text IS NULL OR n.nspname = %s)""",
                (d.constraint_name, d.table_name, d.schema_name, d.schema_name))).fetchone()
    except Exception:  # noqa: BLE001 — komunikat ma się pojawić także bez dostępu do bazy portalu
        log.debug("komentarz ograniczenia %s niedostępny", d.constraint_name, exc_info=True)
        return None
    opis = (row["opis"] if row else None) or None
    if opis:  # {kolumna} → wartość z klucza; brak wartości (np. tekst z przecinkiem) → „…”
        wart = _klucz(d.message_detail)
        opis = re.sub(r"\{(\w+)\}", lambda m: wart.get(m.group(1), "…"), opis)
    return opis


async def komunikat_bazy(e: psycopg.Error) -> str:
    """Pełny komunikat dla użytkownika: komentarz ograniczenia albo opis ogólny."""
    return await komentarz_ograniczenia(e) or opis_ogolny(e)
