"""Przechowywanie plików w projekcie: zbiory plików (pola „Załącznik” warstw, zbiory wtyczek) i limity wielkości.

Zbiór warstwy = pole z widżetem „Załącznik” (ExternalResource): id `<id_warstwy>:<pole>`, rodzaj „photo” (podgląd
obrazu) albo „file”. Domyślny limit = globalny z konfiguracji API (MAX_PHOTO_MB / MAX_ATTACHMENT_MB); w projekcie
można go tylko obniżyć: Fia (`upload_limits` w .portal.json, przenoszone na serwer przy publikacji) albo panel
administratora → Projekty → „Przechowywanie plików”. Ustawienie z Fii nadpisuje przy publikacji wpis z panelu
dla tego samego zbioru; zbiorów, których Fia nie ustawia, publikacja nie rusza.

Wtyczka może zgłosić własne zbiory: `async def upload_sets(project_slug) -> [{"id", "title", "kind"}]` w pakiecie
API (id zbioru w projekcie: `plugin:<id_wtyczki>:<id>`), a limit odczytać przez `limit_mb(slug, set_id, kind)`.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from .config import get_settings
from .db import portal_conn
from .photos import is_photo_field, is_resource_field
from .qgsproject import Project

log = logging.getLogger("sophia.storage")
KINDS = ("photo", "file")


def global_mb(kind: str) -> int:
    s = get_settings()
    return s.max_photo_mb if kind == "photo" else s.max_attachment_mb


def layer_sets(project: Project) -> list[dict]:
    """Pola „Załącznik” warstw PostGIS projektu (bez warstw „Tylko w QGIS”)."""
    out = []
    for lid, lyr in project.layers.items():
        if not lyr.pg or lyr.hidden:
            continue
        for f in lyr.fields:
            if is_resource_field(f):
                kind = "photo" if is_photo_field(f) else "file"
                out.append({"id": f"{lid}:{f.name}", "source": "layer", "layer_id": lid, "layer": lyr.name,
                            "field": f.name, "title": f"{lyr.name} — {f.alias or f.name}", "kind": kind})
    return sorted(out, key=lambda s: s["title"].lower())


async def plugin_sets(slug: str) -> list[dict]:
    """Zbiory plików zgłoszone przez włączone wtyczki (`upload_sets(project_slug)`)."""
    from . import plugins

    out = []
    providers = [p for p in plugins.REGISTRY.values() if p.module is not None and not p.error and hasattr(p.module, "upload_sets")]
    if not providers:
        return out
    active = await plugins.enabled_ids()
    for p in providers:
        if p.id not in active:
            continue
        try:
            sets = await p.module.upload_sets(slug) or []
        except Exception:  # błąd wtyczki nie psuje panelu
            log.exception("wtyczka %s: błąd upload_sets()", p.id)
            continue
        for s in sets:
            if s.get("id") and s.get("kind") in KINDS:
                out.append({"id": f"plugin:{p.id}:{s['id']}", "source": "plugin", "plugin": p.name,
                            "title": f"{p.name} — {s.get('title') or s['id']}", "kind": s["kind"]})
    return out


async def project_limits(slug: str) -> dict[str, dict]:
    """{id zbioru: {"max_mb", "source", "updated_at", "updated_by"}} — tylko ustawione limity."""
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            """SELECT l.set_id, l.max_mb, l.source, l.updated_at, l.updated_by FROM portal.upload_limits l
                 JOIN portal.projects p ON p.id = l.project_id WHERE p.slug = %s""", (slug,))).fetchall()
    return {r["set_id"]: {"max_mb": float(r["max_mb"]), "source": r["source"], "updated_at": r["updated_at"],
                          "updated_by": r["updated_by"]} for r in rows}


async def limit_mb(slug: str, set_id: str, kind: str) -> float:
    """Limit wielkości pliku zbioru w MB: ustawiony w projekcie, nie większy niż globalny."""
    g = global_mb(kind)
    async with portal_conn() as conn:
        row = await (await conn.execute(
            """SELECT l.max_mb FROM portal.upload_limits l JOIN portal.projects p ON p.id = l.project_id
                WHERE p.slug = %s AND l.set_id = %s""", (slug, set_id))).fetchone()
    return min(float(row["max_mb"]), g) if row else float(g)


def clean_limits(given: dict, allowed: dict[str, str]) -> dict[str, Decimal]:
    """Limity z panelu albo z Fii: znane zbiory, liczba > 0 i ≤ limit globalny rodzaju; None/puste — domyślny.
    `allowed` = {id zbioru: rodzaj}. ValueError z komunikatem dla użytkownika."""
    out: dict[str, Decimal] = {}
    for sid, v in (given or {}).items():
        if v is None or v == "":
            continue
        if sid not in allowed:
            raise ValueError(f"Nieznany zbiór plików: {sid}")
        try:
            mb = Decimal(str(v)).quantize(Decimal("0.1"))
        except ArithmeticError as exc:
            raise ValueError(f"Niepoprawny limit dla {sid}: {v}") from exc
        g = global_mb(allowed[sid])
        if mb <= 0 or mb > g:
            raise ValueError(f"Limit dla {sid} musi być większy od 0 i nie większy niż globalny ({g} MB)")
        if mb < g:          # równy globalnemu = domyślny, nie zapisujemy
            out[sid] = mb
    return out


async def save_limits(project_id: int, limits: dict[str, Decimal], source: str, user_login: str | None,
                      replace_source: str | None = None) -> None:
    """Zapis limitów. Panel (source="webui"): komplet zbiorów — wpisy spoza `limits` usuwane.
    Publikacja (source="fia", replace_source="fia"): usuwa poprzednie wpisy z Fii i zapisuje nowe (nadpisując
    wpisy z panelu dla tych samych zbiorów)."""
    async with portal_conn() as conn:
        if replace_source:
            await conn.execute("DELETE FROM portal.upload_limits WHERE project_id = %s AND source = %s",
                               (project_id, replace_source))
        else:
            await conn.execute("DELETE FROM portal.upload_limits WHERE project_id = %s AND NOT (set_id = ANY(%s))",
                               (project_id, list(limits)))
        for sid, mb in limits.items():
            await conn.execute(
                """INSERT INTO portal.upload_limits (project_id, set_id, max_mb, source, updated_by)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, set_id) DO UPDATE SET max_mb = EXCLUDED.max_mb, source = EXCLUDED.source,
                          updated_at = now(), updated_by = EXCLUDED.updated_by""",
                (project_id, sid, mb, source, user_login))
