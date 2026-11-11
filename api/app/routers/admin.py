"""Panel administracyjny: użytkownicy, grupy, projekty i ich uprawnienia (rola, zdjęcia/pliki, zakres).

Publikacja z Fii (POST /api/admin/publish) jest dostępna także dla autorów projektów (can_publish).
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..config import get_settings
from ..db import layer_conn, portal_conn
from ..qgsproject import get_project
from ..security import CurrentUser, hash_password, require_admin, require_publisher

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
# Publikacja: administrator albo autor projektów (osobny router — bez wymogu administratora)
publish_router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _all(query: str, params: tuple = ()) -> list[dict]:
    async with portal_conn() as conn:
        return await (await conn.execute(query, params)).fetchall()


async def _exec(query: str, params: tuple = ()) -> dict | None:
    async with portal_conn() as conn:
        cur = await conn.execute(query, params)
        return await cur.fetchone() if cur.description else None


# ------------------------------------------------------------------------------ użytkownicy

class UserIn(BaseModel):
    login: str
    full_name: str | None = None
    email: str | None = None
    password: str | None = None
    is_admin: bool = False
    is_active: bool = True
    can_publish: bool = False           # autor projektów (publikacja przez Fię)
    group_ids: list[int] = []


@router.get("/users")
async def list_users():
    return await _all("""
        SELECT u.id, u.login, u.full_name, u.email, u.is_admin, u.is_active, u.can_publish, u.last_login_at,
               coalesce(array_agg(ug.group_id) FILTER (WHERE ug.group_id IS NOT NULL), '{}') AS group_ids
        FROM portal.users u LEFT JOIN portal.user_groups ug ON ug.user_id = u.id
        GROUP BY u.id ORDER BY u.login""")


@router.post("/users", status_code=201)
async def create_user(body: UserIn):
    if not body.password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hasło jest wymagane")
    async with portal_conn() as conn, conn.transaction():
        row = await (await conn.execute(
            """INSERT INTO portal.users (login, full_name, email, password_hash, is_admin, is_active, can_publish)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (body.login, body.full_name, body.email, hash_password(body.password), body.is_admin,
             body.is_active, body.can_publish))).fetchone()
        for gid in body.group_ids:
            await conn.execute("INSERT INTO portal.user_groups VALUES (%s, %s)", (row["id"], gid))
    return row


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UserIn, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id and not body.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nie można odebrać sobie uprawnień administratora")
    async with portal_conn() as conn, conn.transaction():
        await conn.execute(
            """UPDATE portal.users SET login=%s, full_name=%s, email=%s, is_admin=%s, is_active=%s,
                   can_publish=%s WHERE id=%s""",
            (body.login, body.full_name, body.email, body.is_admin, body.is_active, body.can_publish, user_id))
        if body.password:
            await conn.execute("UPDATE portal.users SET password_hash=%s WHERE id=%s",
                               (hash_password(body.password), user_id))
        await conn.execute("DELETE FROM portal.user_groups WHERE user_id=%s", (user_id,))
        for gid in body.group_ids:
            await conn.execute("INSERT INTO portal.user_groups VALUES (%s, %s)", (user_id, gid))
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nie można usunąć własnego konta")
    await _exec("DELETE FROM portal.users WHERE id=%s", (user_id,))


# ------------------------------------------------------------------------------ grupy

class GroupIn(BaseModel):
    name: str
    description: str | None = None


@router.get("/groups")
async def list_groups():
    return await _all("SELECT id, name, description FROM portal.groups ORDER BY name")


@router.post("/groups", status_code=201)
async def create_group(body: GroupIn):
    return await _exec("INSERT INTO portal.groups (name, description) VALUES (%s, %s) RETURNING id",
                       (body.name, body.description))


@router.put("/groups/{group_id}")
async def update_group(group_id: int, body: GroupIn):
    await _exec("UPDATE portal.groups SET name=%s, description=%s WHERE id=%s",
                (body.name, body.description, group_id))
    return {"ok": True}


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: int):
    await _exec("DELETE FROM portal.groups WHERE id=%s", (group_id,))


# ------------------------------------------------------------------------------ projekty

class ProjectIn(BaseModel):
    slug: str
    title: str
    description: str | None = None
    file_name: str
    sort_order: int = 0
    is_public: bool = False


class ProjectAccessIn(BaseModel):
    group_id: int
    role: Literal["viewer", "editor", "manager"]
    can_photos: bool = True             # dodawanie zdjęć
    can_files: bool = True              # dodawanie dokumentów
    scope_all: bool = True              # cały obszar; inaczej tylko scope_codes
    scope_codes: list[str] = []


class LayerAccessIn(BaseModel):
    group_id: int
    layer_id: str
    can_view: bool = True
    can_insert: bool = False
    can_update: bool = False
    can_delete: bool = False


@router.get("/projects")
async def list_projects_admin():
    return await _all("SELECT * FROM portal.projects ORDER BY sort_order, title")


@router.get("/project-files")
async def scan_project_files():
    """Pliki .qgs/.qgz w katalogu projektów — do rejestracji w panelu."""
    root = get_settings().projects_dir
    registered = {r["file_name"] for r in await _all("SELECT file_name FROM portal.projects")}
    files = sorted(p for ext in ("*.qgz", "*.qgs") for p in root.rglob(ext))
    return [{"file_name": str(p.relative_to(root)).replace("\\", "/"),
             "registered": str(p.relative_to(root)).replace("\\", "/") in registered} for p in files]


@router.post("/projects", status_code=201)
async def create_project(body: ProjectIn):
    _validate_project_file(body.file_name)
    return await _exec(
        """INSERT INTO portal.projects (slug, title, description, file_name, sort_order, is_public)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (body.slug, body.title, body.description, body.file_name, body.sort_order, body.is_public))


@router.put("/projects/{project_id}")
async def update_project(project_id: int, body: ProjectIn):
    _validate_project_file(body.file_name)
    await _exec(
        """UPDATE portal.projects SET slug=%s, title=%s, description=%s, file_name=%s, sort_order=%s,
               is_public=%s WHERE id=%s""",
        (body.slug, body.title, body.description, body.file_name, body.sort_order, body.is_public, project_id))
    return {"ok": True}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: int):
    await _exec("DELETE FROM portal.projects WHERE id=%s", (project_id,))


@router.get("/projects/{project_id}/access")
async def get_project_access(project_id: int):
    return {
        "groups": await _all(
            """SELECT group_id, role, can_photos, can_files, scope_all, scope_codes
               FROM portal.project_access WHERE project_id=%s""", (project_id,)),
        "layers": await _all("SELECT * FROM portal.layer_access WHERE project_id=%s", (project_id,)),
    }


@router.put("/projects/{project_id}/access")
async def set_project_access(project_id: int, groups: list[ProjectAccessIn], layers: list[LayerAccessIn]):
    async with portal_conn() as conn, conn.transaction():
        await conn.execute("DELETE FROM portal.project_access WHERE project_id=%s", (project_id,))
        await conn.execute("DELETE FROM portal.layer_access WHERE project_id=%s", (project_id,))
        for g in groups:
            codes = sorted({c.strip() for c in g.scope_codes if c.strip()})
            await conn.execute(
                """INSERT INTO portal.project_access
                       (project_id, group_id, role, can_photos, can_files, scope_all, scope_codes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (project_id, g.group_id, g.role, g.can_photos, g.can_files, g.scope_all, codes))
        for la in layers:
            await conn.execute(
                """INSERT INTO portal.layer_access
                       (project_id, group_id, layer_id, can_view, can_insert, can_update, can_delete)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (project_id, la.group_id, la.layer_id, la.can_view, la.can_insert, la.can_update, la.can_delete))
    return {"ok": True}


@router.get("/projects/{project_id}/scope")
async def project_scope(project_id: int):
    """Wymiar zakresu projektu (z Fii) i kody obszarów z warstwy granic — do wyboru w panelu."""
    row = await _exec("SELECT file_name FROM portal.projects WHERE id=%s", (project_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nieznany projekt")
    path = (get_settings().projects_dir / row["file_name"]).resolve()
    if not path.exists():
        return {"scope": None}
    project = get_project(path)
    dim = project.scope
    if dim is None:
        return {"scope": None}
    b = project.layers[dim.layer_id]
    from psycopg import sql
    async with layer_conn(b.pg.conninfo) as conn:
        values = await (await conn.execute(sql.SQL(
            "SELECT DISTINCT {f}::text AS code FROM {t} WHERE {f} IS NOT NULL ORDER BY 1 LIMIT 2000").format(
            f=sql.Identifier(dim.field), t=sql.Identifier(b.pg.schema, b.pg.table)))).fetchall()
    rules = {lid: {"name": lyr.name, "mode": lyr.scope_mode, "field": lyr.scope_field}
             for lid, lyr in project.layers.items() if lyr.pg}
    return {"scope": {"label": dim.label, "layer": b.name, "field": dim.field,
                      "codes": [v["code"] for v in values], "layers": rules}}


def _validate_project_file(file_name: str):
    root = get_settings().projects_dir.resolve()
    path = (root / file_name).resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Plik projektu nie istnieje")
    try:
        get_project(path)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Nie można odczytać projektu: {exc}") from exc


@router.get("/projects/{project_id}/diagnostics")
async def project_diagnostics(project_id: int):
    """Raport problemów konfiguracyjnych — to, czego brakuje w Lizmapie najbardziej."""
    row = await _exec("SELECT file_name FROM portal.projects WHERE id=%s", (project_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    p = get_project((get_settings().projects_dir / row["file_name"]).resolve())
    issues = []
    for lyr in p.layers.values():
        if lyr.type == "vector" and lyr.provider == "postgres" and lyr.pg is None:
            issues.append({"layer": lyr.name, "level": "error",
                           "msg": "Połączenie PostgreSQL bez 'service=' — warstwa nie będzie edytowalna"})
        if lyr.pg and not lyr.pg.key:
            issues.append({"layer": lyr.name, "level": "warning", "msg": "Brak klucza głównego (key=)"})
        if lyr.pg and lyr.pg.geometry_column and not lyr.pg.srid:
            issues.append({"layer": lyr.name, "level": "warning", "msg": "Nieznany SRID geometrii"})
        if lyr.type == "raster" and lyr.provider == "gdal":
            issues.append({"layer": lyr.name, "level": "info",
                           "msg": "Raster GDAL — upewnij się, że ścieżka jest względna i plik leży w /rasters"})
    for rel in p.relations:
        for side in (rel.parent_layer, rel.child_layer):
            if side not in p.layers:
                issues.append({"layer": rel.name, "level": "error", "msg": f"Relacja wskazuje brakującą warstwę {side}"})
        child = p.layers.get(rel.child_layer)
        parent = p.layers.get(rel.parent_layer)
        if child and parent and child.pg and parent.pg and child.pg.conninfo != parent.pg.conninfo:
            issues.append({"layer": rel.name, "level": "warning", "msg": "Relacja między różnymi bazami"})
    return issues


# ------------------------------------------------------------------------------ publikacja z wtyczki

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@publish_router.post("/publish")
async def publish_project(
    slug: str = Form(...),
    title: str = Form(...),
    project_file: UploadFile = File(...),
    portal_json: str | None = Form(None),
    user: CurrentUser = Depends(require_publisher),
):
    """Wtyczka QGIS wysyła .qgz (+ konfigurację .portal.json). Plik trafia do <projects>/<slug>/.
    Autor projektów (nie administrator) publikuje nowe projekty i aktualizuje te, których jest właścicielem."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieprawidłowy identyfikator projektu")
    existing = await _exec("SELECT owner_id FROM portal.projects WHERE slug=%s", (slug,))
    if existing and not user.is_admin and existing["owner_id"] != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Projekt o tym identyfikatorze należy do kogoś innego — wybierz inny identyfikator")
    if not (project_file.filename or "").lower().endswith(".qgz"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Oczekiwano pliku .qgz")
    root = get_settings().projects_dir
    target_dir = root / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f"{slug}.qgz.upload"
    with tmp.open("wb") as out:
        shutil.copyfileobj(project_file.file, out)
    if not zipfile.is_zipfile(tmp):
        tmp.unlink()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Uszkodzony plik .qgz")
    if portal_json:
        json.loads(portal_json)  # walidacja składni
        (target_dir / f"{slug}.portal.json").write_text(portal_json, "utf-8")
    tmp.replace(target_dir / f"{slug}.qgz")

    file_name = f"{slug}/{slug}.qgz"
    _validate_project_file(file_name)
    await _exec(
        """INSERT INTO portal.projects (slug, title, file_name, owner_id) VALUES (%s, %s, %s, %s)
           ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, file_name = EXCLUDED.file_name""",
        (slug, title, file_name, None if user.is_admin else user.id))
    return {"ok": True, "file_name": file_name}
