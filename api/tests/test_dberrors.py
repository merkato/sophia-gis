"""Komunikaty błędów zapisu z bazy (bez bazy: opis ogólny i podstawianie wartości klucza)."""
from types import SimpleNamespace

import psycopg

from app import dberrors


class _Diag(SimpleNamespace):
    message_primary = None
    message_detail = None
    column_name = None
    constraint_name = None
    table_name = None
    schema_name = None


def _err(cls, **diag):
    e = cls("x")
    d = _Diag(**diag)
    type(e).diag = property(lambda self: d)  # noqa: B023 — tylko w teście
    return e


def test_unique_with_key_values():
    e = _err(psycopg.errors.UniqueViolation, message_primary="duplicate key value violates unique constraint \"l_key\"",
             message_detail="Key (kontur_id, nr)=(12, 1) already exists.", constraint_name="l_key")
    assert dberrors._klucz(e.diag.message_detail) == {"kontur_id": "12", "nr": "1"}
    t = dberrors.opis_ogolny(e)
    assert "już istnieje" in t and "„nr” = 1" in t and "duplicate" not in t


def test_not_null_and_fk_and_length():
    assert "uzupełnij pole „nr”" in dberrors.opis_ogolny(_err(
        psycopg.errors.NotNullViolation, message_primary='null value in column "nr" violates not-null constraint', column_name="nr"))
    assert "najpierw usuń" in dberrors.opis_ogolny(_err(
        psycopg.errors.ForeignKeyViolation, message_primary="update or delete violates",
        message_detail='Key (id)=(5) is still referenced from table "lustracja".'))
    assert "najwyżej 10 znaków" in dberrors.opis_ogolny(_err(
        psycopg.errors.StringDataRightTruncation, message_primary="value too long for type character varying(10)"))


def test_trigger_message_unchanged():
    e = _err(psycopg.errors.RaiseException, message_primary="Okres sprawozdawczy 2026-I jest zamknięty")
    assert dberrors.opis_ogolny(e) == "Okres sprawozdawczy 2026-I jest zamknięty"


def test_invalid_input_in_polish():
    t = dberrors.opis_ogolny(_err(psycopg.errors.InvalidTextRepresentation,
                                  message_primary='invalid input syntax for type integer: "zly"'))
    assert t == "niepoprawna wartość „zly” — wpisz liczbę całkowitą"
