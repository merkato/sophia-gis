"""Obiekty chronione: wiersze, których nie zmienia się na mapie (np. działki i użytki z importu GML — zmienia je
tylko kolejny import). Regułę podaje wtyczka właściciela danych w manifeście (`protected`, docs/WTYCZKI.md):

    "protected": [{"table": "egib.v_dzialka", "field": "zrodlo", "values": ["EGiB"],
                   "message": "Działka z importu GML — dane EGiB zmienia tylko kolejny import"}]

Rdzeń: obiekt dostaje w API `protected` (komunikat), WebUI pokazuje go tylko do odczytu (bez narzędzi edycji),
a każdy zapis istniejącego obiektu (zmiana atrybutów i geometrii, usunięcie, podział, łączenie…) jest odrzucany.

Bezpiecznik: administrator odblokowuje obiekty chronione projektu na określony czas (panel → Projekty), z podaniem
powodu. W tym czasie zmieniać je mogą tylko administrator i zarządzający projektem (rola „manager”); rdzeń ustawia
wtedy w transakcji `sophia.odblokowanie = 'on'` — wyzwalacze wtyczki mogą na tej podstawie przyjąć zapis.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from .qgsproject import LayerDef

UNLOCK_GUC = "sophia.odblokowanie"
MAX_UNLOCK_HOURS = 24


@dataclass(frozen=True)
class Rule:
    table: str                  # schemat.tabela (warstwa w projekcie z tej tabeli albo widoku)
    field: str
    values: tuple[str, ...]
    message: str
    plugin: str = ""


def parse_rules(raw, plugin_id: str) -> list[Rule]:
    """Reguły z manifestu wtyczki; błędne wpisy — ValueError z opisem."""
    rules = []
    for i, r in enumerate(raw or []):
        if not isinstance(r, dict):
            raise ValueError(f"protected[{i}]: oczekiwano obiektu")
        table, fld, values = r.get("table"), r.get("field"), r.get("values")
        if not (isinstance(table, str) and table.count(".") == 1 and isinstance(fld, str) and fld
                and isinstance(values, list) and values and all(isinstance(v, (str, int)) for v in values)):
            raise ValueError(f"protected[{i}]: wymagane table (schemat.tabela), field i niepusta lista values")
        rules.append(Rule(table, fld, tuple(str(v) for v in values),
                          str(r.get("message") or "Obiekt chroniony — tylko do odczytu"), plugin_id))
    return rules


def all_rules() -> list[Rule]:
    from .plugins import REGISTRY
    return [r for p in REGISTRY.values() if not p.error for r in p.protected]


def rule_for(lyr: LayerDef, rules: list[Rule] | None = None) -> Rule | None:
    if lyr.pg is None:
        return None
    name = f"{lyr.pg.schema}.{lyr.pg.table}"
    return next((r for r in (all_rules() if rules is None else rules) if r.table == name), None)


def flag_sql(rule: Rule, alias: tuple[str, ...]) -> sql.Composable:
    """Warunek SQL: wiersz chroniony (wartość pola na liście reguły)."""
    return sql.SQL("coalesce({c}::text = ANY({v}), false)").format(
        c=sql.Identifier(*alias, rule.field), v=sql.Literal(list(rule.values)))
