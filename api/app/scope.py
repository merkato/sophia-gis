"""Zakres danych: które rekordy warstwy widzi i edytuje użytkownik (docs/user/uprawnienia.md).

Autor projektu definiuje w Fii **wymiar zakresu** — warstwę granic z polem kodu (np. oddziały
terenowe, pole `kod` = od01) — i regułę dla każdej warstwy:
  * spatial   — obiekt w granicy obszaru (dokładna geometria). Podgląd: przecina obszar;
                edycja: punkt wewnętrzny obiektu leży w obszarze (każdy obiekt ma jednego „właściciela”),
  * attribute — wskazane pole ma jeden z kodów użytkownika,
  * relation  — rekord dziedziczy widoczność po obiekcie nadrzędnym (relacja z projektu QGIS),
  * none      — bez ograniczeń (słowniki, sama warstwa granic).
Administrator nadaje grupie w projekcie „cały obszar” albo listę kodów; kilka grup = suma kodów.

Jeden warunek SQL służy wszystkim ścieżkom: API (lista, odczyt, edycja, powiązane, zdjęcia, pliki,
narzędzia) i QGIS Server (filtr warstw dla mapy, identyfikacji i wydruku — subset string).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from psycopg import sql

if TYPE_CHECKING:
    from .permissions import ProjectContext
    from .qgsproject import LayerDef

log = logging.getLogger("sophia.scope")

Alias = tuple[str, ...]
T: Alias = ("__t",)                 # alias tabeli w zapytaniach API
Mode = Literal["view", "edit"]
MAX_DEPTH = 3                       # relacje rodzic -> dziadek -> pradziadek


def table(lyr: LayerDef) -> sql.Composed:
    return sql.Identifier(lyr.pg.schema, lyr.pg.table)


def base_filter(lyr: LayerDef) -> sql.Composable:
    # Filtr z definicji warstwy QGIS (sql=...) — zaufany, bo pochodzi z projektu autora.
    return sql.SQL("({})").format(sql.SQL(lyr.pg.sql_filter)) if lyr.pg.sql_filter else sql.SQL("true")


def col(alias: Alias, name: str) -> sql.Identifier:
    return sql.Identifier(*alias, name)


def _codes(codes: list[str]) -> sql.Composable:
    return sql.SQL("{}::text[]").format(sql.Literal(list(codes)))


def _geom_in(lyr: LayerDef, alias: Alias, target_srid: int | None) -> sql.Composable:
    g = col(alias, lyr.pg.geometry_column)
    if target_srid and lyr.pg.srid and lyr.pg.srid != target_srid:
        return sql.SQL("ST_Transform({}, {})").format(g, sql.Literal(target_srid))
    return g


def scope_condition(ctx: ProjectContext, lyr: LayerDef, alias: Alias = T, mode: Mode = "view",
                    depth: int = 0) -> sql.Composable:
    """Warunek zakresu dla rekordu `alias` warstwy `lyr` (bez filtra warstwy z QGIS)."""
    codes = ctx.scope_codes
    dim = ctx.project.scope
    if codes is None or dim is None:
        return sql.SQL("true")
    rule = lyr.scope_mode
    if rule == "none":
        return sql.SQL("true")
    if rule == "attribute":
        if not lyr.scope_field:
            return sql.SQL("false")
        return sql.SQL("{}::text = ANY({})").format(col(alias, lyr.scope_field), _codes(codes))
    if rule == "spatial":
        b = ctx.project.layers.get(dim.layer_id)
        if not b or not b.pg or not b.pg.geometry_column or not lyr.pg.geometry_column \
                or b.pg.conninfo != lyr.pg.conninfo:
            log.warning("Zakres przestrzenny %s: brak warstwy granic w tej samej bazie", lyr.id)
            return sql.SQL("false")
        ba = (f"__b{depth}",)
        g = _geom_in(lyr, alias, b.pg.srid)
        pred = (sql.SQL("ST_Covers({b}, ST_PointOnSurface({g}))") if mode == "edit"
                else sql.SQL("ST_Intersects({b}, {g})")).format(b=col(ba, b.pg.geometry_column), g=g)
        return sql.SQL("EXISTS (SELECT 1 FROM {bt} AS {ba} WHERE {bf}::text = ANY({c}) AND {p})").format(
            bt=table(b), ba=sql.Identifier(*ba), bf=col(ba, dim.field), c=_codes(codes), p=pred)
    if rule == "relation":
        if depth >= MAX_DEPTH:
            return sql.SQL("false")
        parts = []
        for rel in ctx.project.relations:
            parent = ctx.project.layers.get(rel.parent_layer) if rel.child_layer == lyr.id else None
            if not parent or not parent.pg or parent.pg.conninfo != lyr.pg.conninfo or parent.id == lyr.id:
                continue
            pa = (f"__p{depth}",)
            join = sql.SQL(" AND ").join(
                sql.SQL("{} = {}").format(col(pa, p), col(alias, c)) for p, c in rel.pairs)
            parts.append(sql.SQL("EXISTS (SELECT 1 FROM {pt} AS {pa} WHERE {j} AND {f} AND {s})").format(
                pt=table(parent), pa=sql.Identifier(*pa), j=join, f=base_filter(parent),
                s=scope_condition(ctx, parent, pa, mode, depth + 1)))
        return sql.SQL("({})").format(sql.SQL(" OR ").join(parts)) if parts else sql.SQL("false")
    return sql.SQL("true")


def row_filter(ctx: ProjectContext, lyr: LayerDef, alias: Alias = T, mode: Mode = "view") -> sql.Composable:
    """Pełny warunek widoczności/edytowalności rekordu: filtr warstwy z QGIS + zakres użytkownika."""
    return sql.SQL("{} AND {}").format(base_filter(lyr), scope_condition(ctx, lyr, alias, mode))


def restricted(ctx: ProjectContext, lyr: LayerDef) -> bool:
    return ctx.scope_codes is not None and ctx.project.scope is not None and lyr.scope_mode != "none"


def wms_subset(ctx: ProjectContext, lyr: LayerDef) -> str | None:
    """Filtr warstwy dla QGIS Server (subset string): odwołania do kolumn przez nazwę tabeli,
    bo dostawca PostgreSQL QGIS dokleja warunek do własnego zapytania bez aliasu."""
    if not lyr.pg or not restricted(ctx, lyr):
        return None
    return scope_condition(ctx, lyr, (lyr.pg.schema, lyr.pg.table), "view").as_string(None)


FILTER_HEADER = "X-Sophia-Filter"


def wms_filter_header(ctx: ProjectContext) -> str:
    """Nagłówek dla wtyczki QGIS Server (qgis-server-plugins/sophia_filter):
    base64url(zlib(JSON {id_warstwy: subset string})). Pusty obiekt = bez filtrów.
    Kompresja i base64: SQL zawiera cudzysłowy i polskie znaki, nagłówek musi być ASCII
    i krótki (Apache/nginx: ~8 KB na nagłówek)."""
    import base64
    import json
    import zlib
    filters = {lid: f for lid, lyr in ctx.project.layers.items() if (f := wms_subset(ctx, lyr))}
    packed = zlib.compress(json.dumps(filters, ensure_ascii=False).encode(), 9)
    return base64.urlsafe_b64encode(packed).decode().rstrip("=")


def single_code(ctx: ProjectContext) -> str | None:
    codes = ctx.scope_codes
    return codes[0] if codes is not None and len(codes) == 1 else None
