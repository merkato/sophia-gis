"""Listy wartości dla pól formularza: widżety QGIS RelationReference i ValueRelation.

RelationReference (pole klucza obcego, np. przebiegi_linii.pid -> projekty_kolejowe.fid):
  wartości = klucze rekordów warstwy nadrzędnej z relacji, etykiety = wyrażenie wyświetlane tej
  warstwy (gdy to nazwa pola), w przeciwnym razie pierwsze pole tekstowe.
ValueRelation (słownik): wartości/etykiety z pól Key/Value wskazanej warstwy.
Warstwa źródłowa musi być warstwą PostGIS projektu, a użytkownik musi mieć prawo jej podglądu.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import sql

from ..db import layer_conn
from ..permissions import ProjectContext, load_project_context
from ..qgsproject import LayerDef
from ..security import CurrentUser, optional_user
from .features import _base_filter, _table

router = APIRouter(prefix="/api/projects/{slug}/layers/{layer_id}/fields", tags=["features"])
MAX_OPTIONS = 5000


def label_field(lyr: LayerDef) -> str | None:
    """Pole etykiety rekordu: wyrażenie wyświetlane z QGIS (gdy to sama nazwa pola) albo pierwsze pole tekstowe."""
    names = {f.name for f in lyr.fields}
    expr = (lyr.display_expression or "").strip()
    if len(expr) > 1 and expr[0] == expr[-1] == '"':
        expr = expr[1:-1]
    if expr in names:
        return expr
    key = lyr.pg.key if lyr.pg else None
    return next((f.name for f in lyr.fields
                 if f.name != key and f.type and any(t in f.type.lower() for t in ("char", "text", "string"))), None)


def _resolve(ctx: ProjectContext, lyr: LayerDef, field_name: str) -> tuple[LayerDef, str, str | None]:
    """(warstwa źródłowa, pole wartości, pole etykiety) dla pola z widżetem relacyjnym."""
    fd = next((f for f in lyr.fields if f.name == field_name), None)
    if fd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak pola")
    cfg = fd.widget_config or {}
    layers = ctx.project.layers
    if fd.widget == "RelationReference":
        rels = [r for r in ctx.project.relations if r.child_layer == lyr.id
                and any(child == field_name for _, child in r.pairs)]
        rel = next((r for r in rels if r.id == cfg.get("Relation")), rels[0] if rels else None)
        if rel is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pole nie należy do żadnej relacji w projekcie")
        target = layers.get(rel.parent_layer)
        key = next(parent for parent, child in rel.pairs if child == field_name)
        return target, key, label_field(target) if target else None
    if fd.widget == "ValueRelation":
        target = layers.get(cfg.get("Layer") or "") or next(
            (lay for lay in layers.values() if lay.name == cfg.get("LayerName")), None)
        if target is None or not cfg.get("Key"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Słownik (ValueRelation) wskazuje nieznaną warstwę")
        return target, cfg["Key"], cfg.get("Value") or cfg["Key"]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Pole ma widżet {fd.widget}, nie relacyjny")


@router.get("/{field_name}/options")
async def field_options(slug: str, layer_id: str, field_name: str,
                        user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    target, key, label = _resolve(ctx, lyr, field_name)
    if target is None or target.pg is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Źródło listy musi być warstwą PostGIS projektu")
    ctx.require(target.id, "view")
    k = sql.Identifier(key)
    lbl = sql.Identifier(label) if label else k
    q = sql.SQL("SELECT {k}::text AS value, coalesce({l}::text, {k}::text) AS label FROM {t} WHERE {w} "
                "ORDER BY 2 LIMIT {lim}").format(
        k=k, l=lbl, t=_table(target), w=_base_filter(target), lim=sql.Literal(MAX_OPTIONS))
    async with layer_conn(target.pg.conninfo) as conn:
        rows = await (await conn.execute(q)).fetchall()
    return {"layer_id": target.id, "layer_name": target.name, "options": rows}
