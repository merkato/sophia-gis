"""Wtyczki Sophii: wykrywanie, ładowanie, migracje i uprawnienia.

Wtyczka to katalog `<PLUGINS_DIR>/<id>/` z manifestem `sophia-plugin.json` (docs/WTYCZKI.md):
- `api/<pakiet>/` — pakiet Pythona z `router` (FastAPI), montowany pod `/api/plugins/<id>`,
- `migrations/NNN_*.sql` — SQL we własnym schemacie wtyczki, wykonywany przy włączeniu i przy starcie,
- `web/…` — moduł ES ładowany przez WebUI (`export function register(host)`),
- `capabilities` — uprawnienia wtyczki; administrator przypisuje je grupom albo użytkownikom.

Instalacja = skopiowanie katalogu przez administratora serwera (scripts/server/plugin.sh) i restart API.
Włączanie/wyłączanie i przypisanie uprawnień — panel administratora („Wtyczki”), bez restartu.
Kod wtyczki działa w procesie API z pełnym dostępem do bazy — tylko zaufane źródła.
"""
from __future__ import annotations

import importlib
import inspect
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status

from . import __version__ as SOPHIA_VERSION
from .config import get_settings
from .db import portal_conn
from .security import CurrentUser, require_user

log = logging.getLogger("sophia.plugins")

MANIFEST = "sophia-plugin.json"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


@dataclass
class Plugin:
    id: str
    path: Path
    name: str = ""
    version: str = "0"
    description: str = ""
    sophia: str = ""                                   # np. ">=0.1"
    requires: dict[str, str] = field(default_factory=dict)
    capabilities: list[dict] = field(default_factory=list)   # [{"id": "egib.import", "title": "…"}]
    api_package: str | None = None
    web_entry: str | None = None                       # ścieżka względem katalogu wtyczki
    menu: str | None = None                            # krótka nazwa menu wtyczki w panelu (web.menu)
    pages: list[dict] = field(default_factory=list)    # [{"id", "title", "capability"}]
    windows: list[dict] = field(default_factory=list)  # okna z górnego paska: [{"id", "title", "capability"}]
    settings: list[dict] = field(default_factory=list)  # [{"id", "title", "type": "text"|"project", "description"}]
    error: str | None = None                           # wtyczka nie załadowana (manifest, zgodność, import)
    module: object | None = None                       # zaimportowany pakiet API (opcjonalnie `async def startup()`)

    @property
    def capability_ids(self) -> set[str]:
        return {c["id"] for c in self.capabilities}

    def migrations(self) -> list[Path]:
        d = self.path / "migrations"
        return sorted(d.glob("*.sql")) if d.is_dir() else []


REGISTRY: dict[str, Plugin] = {}


# ---------------------------------------------------------------------------- wersje


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def version_ok(spec: str, version: str) -> bool:
    """Prosty warunek wersji: „>=1.2”, „==1.0”, „<2” albo kilka po przecinku; pusty = dowolna."""
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        m = re.match(r"^(>=|<=|==|>|<)?\s*([\d.]+)$", part)
        if not m:
            return False
        op, want = m.group(1) or ">=", _ver(m.group(2))
        have = _ver(version)
        ok = {">=": have >= want, "<=": have <= want, "==": have == want, ">": have > want, "<": have < want}[op]
        if not ok:
            return False
    return True


# ---------------------------------------------------------------------------- wykrywanie


def read_manifest(path: Path) -> Plugin:
    pid = path.name
    plugin = Plugin(id=pid, path=path)
    try:
        m = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        plugin.error = f"Błędny manifest: {exc}"
        return plugin
    if m.get("id") != pid or not ID_RE.match(pid):
        plugin.error = f"Identyfikator w manifeście ({m.get('id')!r}) musi być taki jak nazwa katalogu i pasować do {ID_RE.pattern}"
        return plugin
    plugin.name = m.get("name") or pid
    plugin.version = str(m.get("version") or "0")
    plugin.description = m.get("description") or ""
    plugin.sophia = m.get("sophia") or ""
    plugin.requires = dict(m.get("requires") or {})
    plugin.capabilities = [c for c in m.get("capabilities") or [] if isinstance(c, dict) and c.get("id")]
    bad = [c["id"] for c in plugin.capabilities if not c["id"].startswith(pid + ".")]
    if bad:
        plugin.error = f"Uprawnienia muszą zaczynać się od „{pid}.”: {bad}"
        return plugin
    api = m.get("api") or {}
    plugin.api_package = api.get("package")
    web = m.get("web") or {}
    plugin.web_entry = web.get("entry")
    plugin.menu = (web.get("menu") or "").strip() or None
    plugin.pages = [p for p in web.get("pages") or [] if isinstance(p, dict) and p.get("id")]
    plugin.windows = [w for w in web.get("windows") or [] if isinstance(w, dict) and w.get("id")]
    plugin.settings = [s for s in m.get("settings") or [] if isinstance(s, dict) and s.get("id")
                       and s.get("type", "text") in ("text", "project")]
    if not version_ok(plugin.sophia, SOPHIA_VERSION):
        plugin.error = f"Wymaga Sophii {plugin.sophia}, zainstalowana {SOPHIA_VERSION}"
    return plugin


def discover(plugins_dir: Path) -> dict[str, Plugin]:
    found: dict[str, Plugin] = {}
    if not plugins_dir.is_dir():
        return found
    for d in sorted(plugins_dir.iterdir()):
        if d.is_dir() and (d / MANIFEST).is_file():
            found[d.name] = read_manifest(d)
    # zależności: brakująca albo w złej wersji, albo sama z błędem → błąd (powtarzane do stabilizacji)
    changed = True
    while changed:
        changed = False
        for p in found.values():
            if p.error:
                continue
            for dep, spec in p.requires.items():
                d = found.get(dep)
                reason = (f"brak wtyczki „{dep}”" if d is None else
                          f"„{dep}” {d.version} nie spełnia {spec}" if not version_ok(spec, d.version) else
                          f"„{dep}” nie działa" if d.error else None)
                if reason:
                    p.error = f"Zależność: {reason}"
                    changed = True
                    break
    return found


def load_into(app: FastAPI, plugins_dir: Path | None = None) -> None:
    """Przy starcie API: wykryj wtyczki, zaimportuj ich kod i zamontuj routery (także wyłączonych —
    dostęp blokuje `enabled_guard`, więc włączenie w panelu nie wymaga restartu)."""
    REGISTRY.clear()
    REGISTRY.update(discover(plugins_dir or get_settings().plugins_dir))
    for p in _in_dependency_order():
        if p.error or not p.api_package:
            continue
        try:
            api_dir = str(p.path / "api")
            if api_dir not in sys.path:
                sys.path.insert(0, api_dir)
            module = importlib.import_module(p.api_package)
            router: APIRouter = module.router
            p.module = module
        except Exception as exc:  # błąd wtyczki nie może zatrzymać Sophii
            p.error = f"Błąd ładowania kodu: {exc}"
            log.exception("wtyczka %s: błąd ładowania", p.id)
            continue
        app.include_router(router, prefix=f"/api/plugins/{p.id}", tags=[f"wtyczka: {p.id}"],
                           dependencies=[Depends(enabled_guard(p.id))])
        log.info("wtyczka %s %s: załadowana", p.id, p.version)


def _in_dependency_order() -> list[Plugin]:
    done: list[Plugin] = []
    seen: set[str] = set()

    def visit(p: Plugin, stack: tuple[str, ...] = ()):
        if p.id in seen or p.id in stack:
            return
        for dep in p.requires:
            if dep in REGISTRY:
                visit(REGISTRY[dep], stack + (p.id,))
        seen.add(p.id)
        done.append(p)

    for p in REGISTRY.values():
        visit(p)
    return done


# ---------------------------------------------------------------------------- stan w bazie


async def enabled_ids() -> set[str]:
    async with portal_conn() as conn:
        rows = await (await conn.execute("SELECT id FROM portal.plugins WHERE enabled")).fetchall()
    return {r["id"] for r in rows}


async def migrate(plugin: Plugin) -> list[str]:
    """Wykonuje nowe pliki migracji wtyczki (każdy we własnej transakcji); zwraca nazwy wykonanych."""
    applied: list[str] = []
    async with portal_conn() as conn:
        # autocommit: blokada i odczyt wykonanych migracji poza transakcją, każda migracja we własnej, od razu
        # zatwierdzonej transakcji — inaczej drugi proces API (kilka workerów) czekający na blokadę widzi
        # stary stan portal.plugin_migrations i wykonuje migrację drugi raz
        await conn.set_autocommit(True)
        await conn.execute("SELECT pg_advisory_lock(hashtext('sophia_plugin_' || %s))", (plugin.id,))
        try:
            done = {r["name"] for r in await (await conn.execute(
                "SELECT name FROM portal.plugin_migrations WHERE plugin_id = %s", (plugin.id,))).fetchall()}
            for f in plugin.migrations():
                if f.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(f.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO portal.plugin_migrations (plugin_id, name) VALUES (%s, %s)",
                                       (plugin.id, f.name))
                applied.append(f.name)
                log.info("wtyczka %s: migracja %s", plugin.id, f.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext('sophia_plugin_' || %s))", (plugin.id,))
            await conn.set_autocommit(False)
    return applied


async def startup() -> None:
    """Po migracjach rdzenia: zaległe migracje włączonych wtyczek (np. po aktualizacji wtyczki) i ich
    `startup()` (np. porządek po zadaniach przerwanych restartem API)."""
    for pid in await enabled_ids():
        p = REGISTRY.get(pid)
        if p and not p.error:
            try:
                await migrate(p)
                hook = getattr(p.module, "startup", None)
                if hook:
                    await hook()
            except Exception as exc:
                p.error = f"Błąd migracji: {exc}"
                log.exception("wtyczka %s: błąd migracji", pid)


# ---------------------------------------------------------------------------- uprawnienia


async def user_capabilities(user: CurrentUser) -> dict[str, set[str]]:
    """Uprawnienia użytkownika we włączonych, działających wtyczkach (administrator — wszystkie)."""
    active = {pid for pid in await enabled_ids() if pid in REGISTRY and not REGISTRY[pid].error}
    if user.is_admin:
        return {pid: REGISTRY[pid].capability_ids for pid in active}
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            """SELECT plugin_id, capability FROM portal.plugin_access
                WHERE user_id = %s OR group_id = ANY(%s)""", (user.id, user.group_ids))).fetchall()
    out: dict[str, set[str]] = {}
    for r in rows:
        if r["plugin_id"] in active and r["capability"] in REGISTRY[r["plugin_id"]].capability_ids:
            out.setdefault(r["plugin_id"], set()).add(r["capability"])
    return out


def enabled_guard(plugin_id: str):
    async def guard():
        p = REGISTRY.get(plugin_id)
        if p is None or p.error or plugin_id not in await enabled_ids():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Wtyczka jest wyłączona")
    return guard


def require_plugin(plugin_id: str, capability: str | None = None):
    """Zależność dla endpointów wtyczki: użytkownik ma uprawnienie `capability` (albo dowolne
    uprawnienie wtyczki, gdy None). Zwraca CurrentUser."""
    async def dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        caps = (await user_capabilities(user)).get(plugin_id, set())
        if not caps or (capability and capability not in caps):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnienia do tej funkcji wtyczki")
        return user
    return dep


def data_dir(plugin_id: str) -> Path:
    """Katalog na pliki wtyczki (np. przesłane GML): <uploads>/_plugins/<id> — poza katalogami projektów,
    więc sprzątanie plików osieroconych go nie dotyka."""
    d = get_settings().uploads_dir / "_plugins" / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    return d


ALL_CODES = "*"


async def plugin_scope(user: CurrentUser, project_slug: str) -> tuple[bool, list[str] | None]:
    """Zakres danych użytkownika w projekcie podany przez wtyczkę — zamiast kodów z grup (project_access).

    Pakiet API wtyczki może mieć `async def scope_codes(user, project_slug)`, zwracające None (wtyczka nie dotyczy
    projektu), `"*"` (cały obszar) albo listę kodów wymiaru zakresu (pusta = nic). Pierwsza odpowiedź wygrywa;
    liczą się tylko włączone, działające wtyczki. Wynik: (czy wtyczka rozstrzygnęła, kody | None = bez ograniczeń)."""
    providers = [p for p in REGISTRY.values() if p.module is not None and not p.error and hasattr(p.module, "scope_codes")]
    if not providers:
        return False, None
    active = await enabled_ids()
    for p in providers:
        if p.id not in active:
            continue
        codes = await p.module.scope_codes(user, project_slug)
        if codes is None:
            continue
        return True, (None if codes == ALL_CODES else sorted({str(c) for c in codes}))
    return False, None


async def get_settings_for(plugin_id: str) -> dict:
    async with portal_conn() as conn:
        row = await (await conn.execute("SELECT settings FROM portal.plugins WHERE id = %s", (plugin_id,))).fetchone()
    return (row or {}).get("settings") or {}


THEME_KEYS = ("css", "logo", "title", "favicon", "layers_panel")


async def theme(project: str | None = None) -> dict:
    """Wygląd interfejsu podany przez wtyczkę: pakiet API może mieć `async def theme()` albo (Sophia ≥ 0.8.1)
    `async def theme(project)` — wygląd dla projektu otwartego w mapie (slug albo None), zwracające słownik
    z polami (każde opcjonalne): "css" — adres arkusza stylów, "logo" — adres obrazka w pasku, "title" — nazwa
    aplikacji, "favicon" — ikona karty, "layers_panel" — "open" / "closed": panel warstw po otwarciu (projektu). Pierwsza włączona wtyczka z niepustą odpowiedzią wygrywa."""
    providers = [p for p in REGISTRY.values() if p.module is not None and not p.error and hasattr(p.module, "theme")]
    if not providers:
        return {}
    active = await enabled_ids()
    for p in providers:
        if p.id not in active:
            continue
        try:
            fn = p.module.theme
            t = await (fn(project) if inspect.signature(fn).parameters else fn())
        except Exception:  # błąd wtyczki nie może zablokować ekranu logowania
            log.exception("wtyczka %s: błąd theme()", p.id)
            continue
        if t:
            return {k: str(t[k]) for k in THEME_KEYS if t.get(k)}
    return {}
