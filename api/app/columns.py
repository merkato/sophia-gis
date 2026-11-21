"""Typy kolumn warstw PostGIS (z bazy) — do układu formularza w WebUI.

QGIS nie zapisuje w projekcie typów pól, więc pobieramy je z katalogu bazy: `format_type`
(np. "character varying(20)", "integer", "timestamp with time zone") oraz średnią szerokość
wartości z `pg_stats` (dla `text` bez zadeklarowanej długości). Wynik trzymamy w pamięci
kilka minut — konfiguracja projektu jest pobierana przy każdym otwarciu mapy.
"""
import logging
import time
from collections import defaultdict

import psycopg
from psycopg import sql

from .db import layer_conn
from .qgsproject import LayerDef

log = logging.getLogger(__name__)

TTL = 600.0
_cache: dict[tuple[str, str, str], tuple[float, dict[str, dict]]] = {}


async def column_info(layers: list[LayerDef]) -> dict[tuple[str, str, str], dict[str, dict]]:
    """(conninfo, schemat, tabela) → {kolumna: {"type": str, "avg_width": int | None}}."""
    now = time.monotonic()
    out: dict[tuple[str, str, str], dict[str, dict]] = {}
    missing: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for lyr in layers:
        if not lyr.pg:
            continue
        key = (lyr.pg.conninfo, lyr.pg.schema, lyr.pg.table)
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            out[key] = hit[1]
        else:
            missing[lyr.pg.conninfo].add((lyr.pg.schema, lyr.pg.table))
    for conninfo, tables in missing.items():
        schemas, names = zip(*sorted(tables))
        try:
            async with layer_conn(conninfo) as conn:
                rows = await (await conn.execute(
                    """SELECT n.nspname AS s, c.relname AS t, a.attname AS name,
                              format_type(a.atttypid, a.atttypmod) AS type, st.avg_width
                         FROM unnest(%s::text[], %s::text[]) AS q(s, t)
                         JOIN pg_namespace n ON n.nspname = q.s
                         JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = q.t
                         JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                         LEFT JOIN pg_stats st ON st.schemaname = n.nspname AND st.tablename = c.relname
                                              AND st.attname = a.attname""",
                    (list(schemas), list(names)))).fetchall()
        except (psycopg.Error, OSError) as e:   # brak bazy nie może blokować otwarcia mapy
            log.warning("Typy kolumn (%s): %s", conninfo, e)
            continue
        found: dict[tuple[str, str, str], dict[str, dict]] = {(conninfo, s, t): {} for s, t in tables}
        for r in rows:
            found[(conninfo, r["s"], r["t"])][r["name"]] = {"type": r["type"], "avg_width": r["avg_width"]}
        for (_, s, t), cols in found.items():
            await _sample_widths(conninfo, s, t, cols)
        for key, cols in found.items():
            _cache[key] = (now, cols)
            out[key] = cols
    return out


async def _sample_widths(conninfo: str, schema: str, table: str, cols: dict[str, dict]) -> None:
    """Widok (albo tabela bez ANALYZE) nie ma pg_stats: średnia długość tekstów z próbki 200 wierszy."""
    names = [c for c, i in cols.items() if i["avg_width"] is None and i["type"] in ("text", "character varying")]
    if not names:
        return
    query = sql.SQL("SELECT {} FROM (SELECT {} FROM {}.{} LIMIT 200) q").format(
        sql.SQL(", ").join(sql.SQL("avg(octet_length({}))::int AS {}").format(sql.Identifier(c), sql.Identifier(c))
                           for c in names),
        sql.SQL(", ").join(sql.Identifier(c) for c in names), sql.Identifier(schema), sql.Identifier(table))
    try:
        async with layer_conn(conninfo) as conn:
            row = await (await conn.execute(query)).fetchone()
    except (psycopg.Error, OSError) as e:
        log.warning("Próbka kolumn %s.%s: %s", schema, table, e)
        return
    for c in names:
        cols[c]["avg_width"] = row[c] if row else None
