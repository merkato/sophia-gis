"""Cofanie ostatniej operacji edycji z dziennika zmian (portal.audit_log).

Operacja = wpisy jednego żądania (wspólne `op`): np. podział to zmiana oryginału i nowe części,
połączenie — przeniesienie zdjęć, zmiana obiektu, który zostaje, i usunięcie pozostałych.
Cofamy od ostatniego wpisu, w jednej transakcji: dodanie → usunięcie, zmiana → poprzednie
wartości i geometria, usunięcie → ponowne wstawienie pod tym samym kluczem. Warunek: obiekty są
dziś takie, jak po operacji (nikt ich potem nie zmienił) — inaczej 409 i nic się nie dzieje.
Każdy użytkownik cofa tylko własne operacje, kolejne cofnięcia idą dalej wstecz.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import sql
from pydantic import BaseModel

from ..db import layer_conn, portal_conn
from ..dberrors import komunikat_bazy
from ..permissions import ProjectContext, load_project_context
from ..qgsproject import LayerDef
from ..scope import T, col
from ..scope import table as _table
from ..security import CurrentUser, require_user
from .features import AUDIT_SRID, _audit, _geom_sql, _pk_is, _scope_error, in_scope

router = APIRouter(prefix="/api/projects/{slug}/undo", tags=["features"])

ACTIONS = ("insert", "update", "delete")
MAX_AGE = "7 days"           # starszych operacji nie cofamy (projekt mógł się zmienić)

LABEL = {"insert": "dodanie", "update": "zmiana", "delete": "usunięcie"}


class UndoIn(BaseModel):
    op: str                  # operacja z GET (potwierdzenie dotyczy tej, nie nowszej)


async def _last_op(ctx: ProjectContext) -> list[dict]:
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            f"""SELECT id, at, op::text AS op, layer_id, feature_pk, action, old_data, new_data, srid
                 FROM portal.audit_log
                WHERE op = (SELECT op FROM portal.audit_log
                             WHERE project_id = %s AND user_id = %s AND op IS NOT NULL AND undone_at IS NULL
                               AND action IN ('insert', 'update', 'delete') AND at > now() - interval '{MAX_AGE}'
                             ORDER BY id DESC LIMIT 1)
                ORDER BY id DESC""", (ctx.id, ctx.user.id))).fetchall()
    return rows


def describe(rows: list[dict], ctx: ProjectContext) -> list[dict]:
    out = []
    for r in rows:
        try:
            name = ctx.layer(r["layer_id"]).name
        except Exception:  # noqa: BLE001 — warstwy nie ma już w projekcie
            name = r["layer_id"]
        out.append({"layer_id": r["layer_id"], "layer": name, "pk": r["feature_pk"], "action": r["action"],
                    "label": f"{LABEL[r['action']]} #{r['feature_pk']} ({name})"})
    return out


@router.get("")
async def last_operation(slug: str, user: CurrentUser = Depends(require_user)):
    """Ostatnia operacja do cofnięcia (null = brak)."""
    ctx = await load_project_context(slug, user)
    rows = await _last_op(ctx)
    if not rows:
        return None
    return {"op": rows[0]["op"], "at": rows[-1]["at"].isoformat(), "items": describe(list(reversed(rows)), ctx)}


def _text(v: Any) -> str | None:
    """Wartość z JSON dziennika → tekst do rzutowania na typ kolumny w SQL."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


async def _column_types(conn, lyr: LayerDef) -> dict[str, str]:
    rows = await (await conn.execute(
        """SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a
            WHERE a.attrelid = to_regclass(format('%%I.%%I', %s::text, %s::text)) AND a.attnum > 0
              AND NOT a.attisdropped""", (lyr.pg.schema, lyr.pg.table))).fetchall()
    return {r["name"]: r["type"] for r in rows}


def _typed(types: dict[str, str], name: str, v: Any) -> sql.Composable:
    return sql.SQL("CAST({} AS {})").format(sql.Literal(_text(v)), sql.SQL(types[name]))


def _props(lyr: LayerDef, data: dict, types: dict[str, str]) -> dict[str, Any]:
    """Pola z wpisu, które warstwa nadal ma (bez klucza i geometrii)."""
    return {k: v for k, v in (data.get("properties") or {}).items()
            if k in types and k not in (lyr.pg.key, lyr.pg.geometry_column)}


async def _matches(conn, lyr: LayerDef, pk: str, data: dict, srid: int, types: dict[str, str]) -> bool:
    """Obiekt jest dziś taki, jak po operacji (pola z wpisu i geometria)."""
    conds = [_pk_is(lyr, pk)]
    conds += [sql.SQL("{} IS NOT DISTINCT FROM {}").format(col(T, k), _typed(types, k, v))
              for k, v in _props(lyr, data, types).items()]
    if lyr.pg.geometry_column and data.get("geometry") is not None:
        conds.append(sql.SQL("ST_AsGeoJSON(ST_Transform({g}, {s}), 9)::jsonb = {v}::jsonb").format(
            g=col(T, lyr.pg.geometry_column), s=sql.Literal(srid), v=sql.Literal(json.dumps(data["geometry"]))))
    row = await (await conn.execute(sql.SQL("SELECT 1 FROM {t} AS {a} WHERE {w}").format(
        t=_table(lyr), a=sql.Identifier(*T), w=sql.SQL(" AND ").join(conds)))).fetchone()
    return row is not None


@router.post("")
async def undo(slug: str, body: UndoIn, user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    rows = await _last_op(ctx)
    if not rows or rows[0]["op"] != body.op:
        raise HTTPException(status.HTTP_409_CONFLICT, "To nie jest już Twoja ostatnia operacja — odśwież i spróbuj ponownie")
    layers: dict[str, LayerDef] = {}
    for r in rows:
        try:
            lyr = ctx.layer(r["layer_id"])
        except Exception as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "Warstwy z tej operacji nie ma już w projekcie") from exc
        need = {"insert": "delete", "update": "update", "delete": "insert"}[r["action"]]
        if not lyr.pg or not lyr.pg.key or not getattr(ctx.perms(r["layer_id"]), need):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Brak uprawnienia do cofnięcia zmian w „{lyr.name}”")
        layers[r["layer_id"]] = lyr
    conninfos = {lyr.pg.conninfo for lyr in layers.values()}
    if len(conninfos) > 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Operacja obejmuje kilka baz — nie da się jej cofnąć jednym krokiem")

    conflict = HTTPException(status.HTTP_409_CONFLICT,
                             "Obiekty zmieniły się po tej operacji — cofnięcie nadpisałoby późniejsze zmiany")
    done: list[tuple[str, str, str, Any, Any]] = []
    try:
        await _revert(ctx, rows, layers, conninfos.pop(), conflict, done)
    except psycopg.errors.IntegrityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Nie można cofnąć: {await komunikat_bazy(e)}") from e

    async with portal_conn() as pconn:
        await pconn.execute("UPDATE portal.audit_log SET undone_at = now() WHERE op = %s::uuid", (body.op,))
    for layer_id, pk, action, before, after in done:
        AUDIT_SRID.set(next(r["srid"] for r in rows if r["feature_pk"] == pk and r["layer_id"] == layer_id))
        await _audit(ctx, layer_id, pk, f"undo_{action}", before, after)
    return {"undone": describe(rows, ctx)}


async def _revert(ctx: ProjectContext, rows: list[dict], layers: dict[str, LayerDef], conninfo: str,
                  conflict: HTTPException, done: list) -> None:
    async with layer_conn(conninfo) as conn, conn.transaction():
        types = {lid: await _column_types(conn, lyr) for lid, lyr in layers.items()}
        for r in rows:                                    # od ostatniego wpisu
            lyr, pk, srid, ty = layers[r["layer_id"]], r["feature_pk"], r["srid"] or 3857, types[r["layer_id"]]
            old, new = r["old_data"], r["new_data"]
            t, a, g = _table(lyr), sql.Identifier(*T), lyr.pg.geometry_column
            if r["action"] in ("insert", "update"):
                if not await _matches(conn, lyr, pk, new, srid, ty):
                    raise conflict
                if not await in_scope(conn, ctx, lyr, pk, "edit"):
                    raise _scope_error(ctx, lyr)
            if r["action"] == "insert":
                await conn.execute(sql.SQL("DELETE FROM {t} AS {a} WHERE {pk}").format(t=t, a=a, pk=_pk_is(lyr, pk)))
            elif r["action"] == "update":
                sets = [sql.SQL("{} = {}").format(sql.Identifier(k), _typed(ty, k, v))
                        for k, v in _props(lyr, old, ty).items()]
                if g and old.get("geometry") is not None and new.get("geometry") is not None:
                    sets.append(sql.SQL("{} = {}").format(sql.Identifier(g), _geom_sql(lyr, old["geometry"], srid)))
                if sets:
                    await conn.execute(sql.SQL("UPDATE {t} AS {a} SET {s} WHERE {pk}").format(
                        t=t, a=a, s=sql.SQL(", ").join(sets), pk=_pk_is(lyr, pk)))
            else:                                         # delete → ponowne wstawienie
                exists = await (await conn.execute(sql.SQL("SELECT 1 FROM {t} AS {a} WHERE {pk}").format(
                    t=t, a=a, pk=_pk_is(lyr, pk)))).fetchone()
                if exists:
                    raise conflict
                vals = {lyr.pg.key: pk, **_props(lyr, old, ty)}
                cols = [sql.Identifier(k) for k in vals]
                exprs = [_typed(ty, k, v) for k, v in vals.items()]
                if g and old.get("geometry") is not None:
                    cols.append(sql.Identifier(g))
                    exprs.append(_geom_sql(lyr, old["geometry"], srid))
                await conn.execute(sql.SQL("INSERT INTO {t} ({c}) OVERRIDING SYSTEM VALUE VALUES ({v})").format(
                    t=t, c=sql.SQL(", ").join(cols), v=sql.SQL(", ").join(exprs)))
            if r["action"] != "insert" and not await in_scope(conn, ctx, lyr, pk, "edit"):
                raise _scope_error(ctx, lyr)
            done.append((r["layer_id"], pk, r["action"], new, old))
