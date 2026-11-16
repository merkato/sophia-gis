"""Wtyczki: lista dla zalogowanego (WebUI), pliki modułów web, administracja (włączanie, uprawnienia)."""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import plugins
from ..db import portal_conn
from ..security import CurrentUser, optional_user, require_admin, require_user

router = APIRouter(prefix="/api/plugins", tags=["wtyczki"])
admin = APIRouter(prefix="/api/admin/plugins", tags=["wtyczki"], dependencies=[Depends(require_admin)])

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


@router.get("")
async def my_plugins(user: CurrentUser | None = Depends(optional_user)):
    """Włączone wtyczki z uprawnieniami użytkownika: moduł web i strony, które może otworzyć."""
    if user is None:
        return []
    out = []
    for pid, caps in sorted((await plugins.user_capabilities(user)).items()):
        p = plugins.REGISTRY[pid]
        out.append({
            "id": p.id, "name": p.name, "version": p.version, "capabilities": sorted(caps),
            "web": f"/api/plugins/{p.id}/web/{p.web_entry}?v={p.version}" if p.web_entry else None,
            "pages": [pg for pg in p.pages if not pg.get("capability") or pg["capability"] in caps],
        })
    return out


@router.get("/{plugin_id}/web/{path:path}")
async def plugin_web(plugin_id: str, path: str, user: CurrentUser = Depends(require_user)):
    """Pliki modułu web wtyczki (tylko z katalogu `web/` i tylko dla użytkowników z uprawnieniem)."""
    p = plugins.REGISTRY.get(plugin_id)
    if p is None or plugin_id not in await plugins.user_capabilities(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak wtyczki")
    base = (p.path / "web").resolve()
    f = (p.path / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak pliku")
    return FileResponse(f, headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------------------- administracja


async def _state() -> dict[str, dict]:
    async with portal_conn() as conn:
        rows = await (await conn.execute("SELECT id, enabled, settings FROM portal.plugins")).fetchall()
        migs = await (await conn.execute("SELECT plugin_id, name FROM portal.plugin_migrations")).fetchall()
        acc = await (await conn.execute(
            """SELECT a.plugin_id, a.capability, a.group_id, a.user_id, g.name AS group_name, u.login
                 FROM portal.plugin_access a LEFT JOIN portal.groups g ON g.id = a.group_id
                 LEFT JOIN portal.users u ON u.id = a.user_id ORDER BY a.id""")).fetchall()
    state: dict[str, dict] = {r["id"]: {"enabled": r["enabled"], "settings": r["settings"], "migrations": [],
                                        "access": []} for r in rows}
    for m in migs:
        state.setdefault(m["plugin_id"], {"enabled": False, "settings": {}, "migrations": [], "access": []})
        state[m["plugin_id"]]["migrations"].append(m["name"])
    for a in acc:
        state.setdefault(a["plugin_id"], {"enabled": False, "settings": {}, "migrations": [], "access": []})
        state[a["plugin_id"]]["access"].append({k: a[k] for k in ("capability", "group_id", "user_id", "group_name", "login")})
    return state


@admin.get("")
async def list_plugins():
    """Zainstalowane wtyczki (także z błędem) ze stanem, migracjami i uprawnieniami."""
    state = await _state()
    out = []
    for p in sorted(plugins.REGISTRY.values(), key=lambda x: x.id):
        s = state.get(p.id, {"enabled": False, "settings": {}, "migrations": [], "access": []})
        out.append({
            "id": p.id, "name": p.name, "version": p.version, "description": p.description,
            "sophia": p.sophia, "requires": p.requires, "capabilities": p.capabilities, "pages": p.pages,
            "error": p.error, "enabled": s["enabled"], "settings": s["settings"],
            "migrations": {"applied": sorted(s["migrations"]),
                           "pending": [f.name for f in p.migrations() if f.name not in s["migrations"]]},
            "access": s["access"],
        })
    # wpisy po wtyczkach usuniętych z serwera — do posprzątania uprawnień
    for pid in sorted(set(state) - set(plugins.REGISTRY)):
        out.append({"id": pid, "name": pid, "version": "", "description": "", "sophia": "", "requires": {},
                    "capabilities": [], "pages": [], "error": "Wtyczki nie ma na serwerze",
                    "enabled": state[pid]["enabled"], "settings": state[pid]["settings"],
                    "migrations": {"applied": state[pid]["migrations"], "pending": []}, "access": state[pid]["access"]})
    return out


class PluginIn(BaseModel):
    enabled: bool
    settings: dict | None = None


@admin.put("/{plugin_id}")
async def update_plugin(plugin_id: str, body: PluginIn):
    p = plugins.REGISTRY.get(plugin_id)
    if body.enabled:
        if p is None or p.error:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Nie można włączyć: {p.error if p else 'brak wtyczki'}")
        missing = [d for d in p.requires if d not in await plugins.enabled_ids()]
        if missing:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Najpierw włącz wtyczki: {', '.join(missing)}")
        try:
            await plugins.migrate(p)
        except Exception as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Błąd migracji wtyczki: {exc}") from exc
    else:
        dependants = [o.id for o in plugins.REGISTRY.values() if plugin_id in o.requires]
        on = await plugins.enabled_ids()
        if blocked := [d for d in dependants if d in on]:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Najpierw wyłącz wtyczki zależne: {', '.join(blocked)}")
    async with portal_conn() as conn:
        await conn.execute(
            """INSERT INTO portal.plugins (id, enabled, settings) VALUES (%s, %s, coalesce(%s::jsonb, '{}'))
               ON CONFLICT (id) DO UPDATE SET enabled = EXCLUDED.enabled,
                 settings = coalesce(%s::jsonb, portal.plugins.settings), updated_at = now()""",
            (plugin_id, body.enabled, _json(body.settings), _json(body.settings)))
    return {"ok": True}


class AccessEntry(BaseModel):
    capability: str
    group_id: int | None = None
    user_id: int | None = None


@admin.put("/{plugin_id}/access")
async def set_access(plugin_id: str, entries: list[AccessEntry]):
    """Zastępuje listę uprawnień wtyczki: każde uprawnienie → grupy i/lub pojedynczy użytkownicy."""
    p = plugins.REGISTRY.get(plugin_id)
    caps = p.capability_ids if p else set()
    for e in entries:
        if e.capability not in caps:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Nieznane uprawnienie: {e.capability}")
        if (e.group_id is None) == (e.user_id is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Każdy wpis: grupa albo użytkownik")
    async with portal_conn() as conn, conn.transaction():
        await conn.execute("DELETE FROM portal.plugin_access WHERE plugin_id = %s", (plugin_id,))
        for e in {(x.capability, x.group_id, x.user_id) for x in entries}:
            await conn.execute("INSERT INTO portal.plugin_access (plugin_id, capability, group_id, user_id) "
                               "VALUES (%s, %s, %s, %s)", (plugin_id, *e))
    return {"ok": True}


def _json(v):
    import json
    return None if v is None else json.dumps(v)
