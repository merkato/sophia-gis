"""Panel administracyjny: użytkownicy, grupy, zasięgi, projekty i ich uprawnienia.

Z tych samych endpointów korzysta wtyczka QGIS (token Bearer administratora).
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..config import get_settings
from ..db import portal_conn
from ..qgsproject import get_project
from ..security import CurrentUser, hash_password, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


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
    group_ids: list[int] = []


@router.get("/users")
async def list_users():
    return await _all("""
        SELECT u.id, u.login, u.full_name, u.email, u.is_admin, u.is_active, u.last_login_at,
               coalesce(array_agg(ug.group_id) FILTER (WHERE ug.group_id IS NOT NULL), '{}') AS group_ids
        FROM portal.users u LEFT JOIN portal.user_groups ug ON ug.user_id = u.id
        GROUP BY u.id ORDER BY u.login""")


@router.post("/users", status_code=201)
async def create_user(body: UserIn):
    if not body.password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hasło jest wymagane")
    async with portal_conn() as conn, conn.transaction():
        row = await (await conn.execute(
            """INSERT INTO portal.users (login, full_name, email, password_hash, is_admin, is_active)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (body.login, body.full_name, body.email, hash_password(body.password), body.is_admin,
             body.is_active))).fetchone()
        for gid in body.group_ids:
            await conn.execute("INSERT INTO portal.user_groups VALUES (%s, %s)", (row["id"], gid))
    return row


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UserIn, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id and not body.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nie można odebrać sobie uprawnień administratora")
    async with portal_conn() as conn, conn.transaction():
        await conn.execute(
            """UPDATE portal.users SET login=%s, full_name=%s, email=%s, is_admin=%s, is_active=%s
               WHERE id=%s""",
            (body.login, body.full_name, body.email, body.is_admin, body.is_active, user_id))
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


# ------------------------------------------------------------------------------ zasięgi

class ExtentIn(BaseModel):
    name: str
    geometry: dict[str, Any]        # GeoJSON Polygon/MultiPolygon
    crs: str = "EPSG:2180"


class ExtentAssignmentIn(BaseModel):
    extent_id: int
    user_id: int | None = None
    group_id: int | None = None
    mode: Literal["view", "edit"] = "edit"


@router.get("/extents")
async def list_extents():
    return await _all("""SELECT e.id, e.name, ST_AsGeoJSON(ST_Transform(e.geom, 4326), 7)::json AS geometry,
                                ST_Area(e.geom) / 10000 AS area_ha
                         FROM portal.extents e ORDER BY e.name""")


@router.post("/extents", status_code=201)
async def create_extent(body: ExtentIn):
    srid = int(body.crs.split(":")[1])
    return await _exec(
        """INSERT INTO portal.extents (name, geom)
           VALUES (%s, ST_Multi(ST_MakeValid(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), %s), %s))))
           RETURNING id""",
        (body.name, json.dumps(body.geometry), srid, get_settings().extents_srid))


@router.delete("/extents/{extent_id}", status_code=204)
async def delete_extent(extent_id: int):
    await _exec("DELETE FROM portal.extents WHERE id=%s", (extent_id,))


@router.get("/extent-assignments")
async def list_extent_assignments():
    return await _all("SELECT * FROM portal.extent_assignments ORDER BY extent_id")


@router.post("/extent-assignments", status_code=201)
async def assign_extent(body: ExtentAssignmentIn):
    if (body.user_id is None) == (body.group_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj user_id albo group_id")
    return await _exec(
        "INSERT INTO portal.extent_assignments (extent_id, user_id, group_id, mode) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (body.extent_id, body.user_id, body.group_id, body.mode))


@router.delete("/extent-assignments/{assignment_id}", status_code=204)
async def unassign_extent(assignment_id: int):
    await _exec("DELETE FROM portal.extent_assignments WHERE id=%s", (assignment_id,))


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
        "groups": await _all("SELECT group_id, role FROM portal.project_access WHERE project_id=%s",
                             (project_id,)),
        "layers": await _all("SELECT * FROM portal.layer_access WHERE project_id=%s", (project_id,)),
    }


@router.put("/projects/{project_id}/access")
async def set_project_access(project_id: int, groups: list[ProjectAccessIn], layers: list[LayerAccessIn]):
    async with portal_conn() as conn, conn.transaction():
        await conn.execute("DELETE FROM portal.project_access WHERE project_id=%s", (project_id,))
        await conn.execute("DELETE FROM portal.layer_access WHERE project_id=%s", (project_id,))
        for g in groups:
            await conn.execute("INSERT INTO portal.project_access VALUES (%s, %s, %s)",
                               (project_id, g.group_id, g.role))
        for la in layers:
            await conn.execute(
                "INSERT INTO portal.layer_access VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (project_id, la.group_id, la.layer_id, la.can_view, la.can_insert, la.can_update, la.can_delete))
    return {"ok": True}


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


@router.post("/publish")
async def publish_project(
    slug: str = Form(...),
    title: str = Form(...),
    project_file: UploadFile = File(...),
    portal_json: str | None = Form(None),
):
    """Wtyczka QGIS wysyła .qgz (+ konfigurację .portal.json). Plik trafia do <projects>/<slug>/."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieprawidłowy identyfikator projektu")
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
        """INSERT INTO portal.projects (slug, title, file_name) VALUES (%s, %s, %s)
           ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, file_name = EXCLUDED.file_name""",
        (slug, title, file_name))
    return {"ok": True, "file_name": file_name}
