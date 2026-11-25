"""Rozstrzyganie uprawnień: projekt -> rola grupy -> nadpisania warstw -> zakres danych (scope.py)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status

from .config import get_settings
from .db import portal_conn
from .qgsproject import LayerDef, Project, get_project
from .security import CurrentUser

ROLE_RANK = {"viewer": 1, "editor": 2, "manager": 3}


def combine_layer_access(group_roles: dict[int, str], rows: list[dict]) -> dict[str, "LayerPerms"]:
    """Prawa do warstw z kilku grup użytkownika. Ustawienie warstwy w grupie (portal.layer_access) zastępuje rolę
    tej grupy dla tej warstwy; grupa bez ustawienia dla warstwy daje prawa z roli (edycja od roli „edycja”).
    Użytkownik dostaje sumę z grup. Wynik tylko dla warstw, które mają ustawienie w którejś grupie użytkownika
    (pozostałe — z roli, jak dotąd)."""
    by_layer: dict[str, dict[int, dict]] = {}
    for r in rows:
        if r["group_id"] in group_roles:
            by_layer.setdefault(r["layer_id"], {})[r["group_id"]] = r
    out: dict[str, LayerPerms] = {}
    for layer_id, per_group in by_layer.items():
        p = LayerPerms()
        for gid, role in group_roles.items():
            r = per_group.get(gid)
            if r is not None:
                g = LayerPerms(bool(r["can_view"]), bool(r["can_insert"]), bool(r["can_update"]), bool(r["can_delete"]))
            else:
                edit = ROLE_RANK.get(role, 0) >= ROLE_RANK["editor"]
                g = LayerPerms(True, edit, edit, edit)
            p = LayerPerms(p.view or g.view, p.insert or g.insert, p.update or g.update, p.delete or g.delete)
        out[layer_id] = p
    return out


@dataclass
class LayerPerms:
    view: bool = False
    insert: bool = False
    update: bool = False
    delete: bool = False

    @property
    def any_edit(self) -> bool:
        return self.insert or self.update or self.delete


@dataclass
class ProjectContext:
    id: int
    slug: str
    title: str
    path: Path
    project: Project
    role: str | None                    # None = dostęp publiczny (anonim)
    user: CurrentUser | None
    _layer_overrides: dict[str, LayerPerms]
    # Zakres danych: None = bez ograniczeń (administrator, autor projektu, grupa „cały obszar”,
    # projekt publiczny, projekt bez wymiaru zakresu); lista = suma kodów z grup użytkownika
    scope_codes: list[str] | None = None
    can_photos: bool = False            # dodawanie zdjęć (z grup w projekcie; domyślnie włączone)
    can_files: bool = False             # dodawanie dokumentów
    # bezpiecznik obiektów chronionych (app/protection.py): odblokowanie projektu do tej chwili
    unlock_until: datetime | None = None
    unlock_by: str | None = None
    unlock_reason: str | None = None

    @property
    def unlocked(self) -> bool:
        return self.unlock_until is not None and self.unlock_until > datetime.now(timezone.utc)

    @property
    def can_edit_protected(self) -> bool:
        """Zmiana obiektów chronionych: tylko w czasie odblokowania, administrator albo zarządzający projektem."""
        return self.unlocked and bool(self.user) and (self.user.is_admin or self.role == "manager")

    def layer(self, layer_id: str) -> LayerDef:
        lyr = self.project.layers.get(layer_id)
        if lyr is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznana warstwa")
        return lyr

    def perms(self, layer_id: str) -> LayerPerms:
        lyr = self.layer(layer_id)
        if lyr.hidden:
            # "Ukryta" (Fia) = tylko w QGIS Desktop, np. ortofoto do pracy, które w WebUI daje katalog
            # podkładów. Niewidoczna dla wszystkich, także administratora — jedno źródło kafli.
            return LayerPerms()
        if self.user and self.user.is_admin:
            return LayerPerms(True, lyr.editable, lyr.editable, lyr.editable)
        if layer_id in self._layer_overrides:
            p = self._layer_overrides[layer_id]
            # Nadpisanie nie może włączyć edycji warstwy niezaznaczonej jako edytowalna w projekcie.
            return LayerPerms(p.view, p.insert and lyr.editable, p.update and lyr.editable,
                              p.delete and lyr.editable)
        can_edit = lyr.editable and ROLE_RANK.get(self.role or "", 0) >= ROLE_RANK["editor"]
        return LayerPerms(True, can_edit, can_edit, can_edit)

    def require(self, layer_id: str, action: str) -> LayerDef:
        if not getattr(self.perms(layer_id), action):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Brak uprawnienia '{action}' do warstwy")
        return self.layer(layer_id)


async def load_project_context(slug: str, user: CurrentUser | None) -> ProjectContext:
    s = get_settings()
    async with portal_conn() as conn:
        proj = await (
            await conn.execute(
                "SELECT id, slug, title, file_name, is_public, owner_id FROM portal.projects WHERE slug = %s",
                (slug,)
            )
        ).fetchone()
        if proj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznany projekt")

        role: str | None = None
        overrides: dict[str, LayerPerms] = {}
        scope_codes: list[str] | None = None
        can_photos = can_files = False
        unrestricted = bool(user and (user.is_admin or proj["owner_id"] == user.id))
        if unrestricted:
            role = "manager"
            can_photos = can_files = True
        elif user and user.group_ids:
            rows = await (
                await conn.execute(
                    """SELECT group_id, role, can_photos, can_files, scope_all, scope_codes FROM portal.project_access
                       WHERE project_id = %s AND group_id = ANY(%s)""",
                    (proj["id"], user.group_ids),
                )
            ).fetchall()
            if rows:
                role = max((r["role"] for r in rows), key=ROLE_RANK.__getitem__)
                can_photos = any(r["can_photos"] for r in rows)
                can_files = any(r["can_files"] for r in rows)
                if not any(r["scope_all"] for r in rows):
                    scope_codes = sorted({c for r in rows for c in r["scope_codes"]})
                # prawa do warstw (Panel → Projekty → Grupy i zakres…): suma z grup, ustawienie warstwy
                # zastępuje rolę tej grupy dla tej warstwy
                layer_rows = await (await conn.execute(
                    """SELECT group_id, layer_id, can_view, can_insert, can_update, can_delete
                         FROM portal.layer_access WHERE project_id = %s AND group_id = ANY(%s)""",
                    (proj["id"], user.group_ids))).fetchall()
                overrides = combine_layer_access({r["group_id"]: r["role"] for r in rows}, layer_rows)

    if user and role and not unrestricted:
        # wtyczka może podać zakres użytkownika w projekcie (np. przypisane nadleśnictwo) zamiast kodów grup
        from .plugins import plugin_scope
        handled, codes = await plugin_scope(user, proj["slug"])
        if handled:
            scope_codes = codes

    async with portal_conn() as conn:
        unlock = await (await conn.execute(
            "SELECT until, by_login, reason FROM portal.protection_unlock WHERE project_id = %s AND until > now()",
            (proj["id"],))).fetchone()

    if role is None and not proj["is_public"]:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED if user is None else status.HTTP_403_FORBIDDEN,
            "Brak dostępu do projektu",
        )

    path = (s.projects_dir / proj["file_name"]).resolve()
    if not path.is_relative_to(s.projects_dir.resolve()) or not path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Brak pliku projektu na serwerze")

    return ProjectContext(
        id=proj["id"], slug=proj["slug"], title=proj["title"], path=path,
        project=get_project(path), role=role, user=user, _layer_overrides=overrides,
        scope_codes=scope_codes, can_photos=can_photos, can_files=can_files,
        unlock_until=unlock["until"] if unlock else None, unlock_by=unlock["by_login"] if unlock else None,
        unlock_reason=unlock["reason"] if unlock else None,
    )

