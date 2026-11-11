"""Rozstrzyganie uprawnień: projekt -> rola grupy -> nadpisania warstw -> zakres danych (scope.py)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status

from .config import get_settings
from .db import portal_conn
from .qgsproject import LayerDef, Project, get_project
from .security import CurrentUser

ROLE_RANK = {"viewer": 1, "editor": 2, "manager": 3}


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
        if user and (user.is_admin or proj["owner_id"] == user.id):
            role = "manager"
            can_photos = can_files = True
        elif user and user.group_ids:
            rows = await (
                await conn.execute(
                    """SELECT role, can_photos, can_files, scope_all, scope_codes FROM portal.project_access
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
                # Suma (OR) uprawnień ze wszystkich grup użytkownika
                for r in await (
                    await conn.execute(
                        """SELECT layer_id, bool_or(can_view) v, bool_or(can_insert) i,
                                  bool_or(can_update) u, bool_or(can_delete) d
                           FROM portal.layer_access WHERE project_id = %s AND group_id = ANY(%s)
                           GROUP BY layer_id""",
                        (proj["id"], user.group_ids),
                    )
                ).fetchall():
                    overrides[r["layer_id"]] = LayerPerms(r["v"], r["i"], r["u"], r["d"])

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
    )

