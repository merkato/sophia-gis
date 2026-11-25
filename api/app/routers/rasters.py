"""Wysyłka rastrów z Fii (GeoTIFF, piramidy .ovr, mozaiki VRT) — bez skryptów i poleceń na serwerze.

Cel wysyłki:
  - rastry projektu: <projects_dir>/<slug>/… (obok .qgz, np. rastry/seria/arkusz.tif) — administrator albo właściciel;
  - biblioteka:      <rasters_dir>/<seria>/…  (wspólna dla wielu projektów, ../../rasters w QGIS) — administrator.

Przebieg: POST /plan (lista plików z sumami SHA-256) -> sesja i lista plików do wysłania; PUT części po kolei
(poniżej limitu proxy, z wznawianiem od odebranej długości); POST /commit -> kontrola sum i zawartości, podmiana
przez rename w kolejności arkusze -> piramidy -> VRT (QGIS Server nie czyta niedokończonego pliku), potem zmiana
czasu modyfikacji projektów, które używają tych rastrów: QGIS Server przeładowuje projekt i otwiera rastry od nowa
(bez restartu), a nowa wersja projektu daje nowe adresy kafli (cache kafli nie wymaga czyszczenia).

Sesja leży w katalogu docelowym (<cel>/.upload-<id>/), żeby rename był w obrębie jednego systemu plików.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import portal_conn
from ..security import CurrentUser, require_publisher

log = logging.getLogger("sophia.rasters")
router = APIRouter(prefix="/api/admin/rasters", tags=["rasters"])

RASTER_EXT = (".tif", ".tiff", ".ovr")
EXTENSIONS = RASTER_EXT + (".vrt", ".aux.xml", ".tfw")
CHUNK_MAX = 64 * 1024 * 1024              # jedna część (Fia wysyła po 32 MB; proxy przyjmuje do 100 MB)
XML_MAX = 32 * 1024 * 1024                # VRT / .aux.xml
SESSION_TTL_S = 24 * 3600
HASH_CACHE = ".sophia-hash.json"
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SID_RE = re.compile(r"^[0-9a-f]{32}$")
_locks: dict[str, asyncio.Lock] = {}


# ------------------------------------------------------------------------------ ścieżki i cele

def clean_path(raw: str) -> str:
    """Ścieżka względna pliku w katalogu docelowym: ukośniki /, NFC, bez .., bez ukrytych składników,
    tylko rozszerzenia rastrów. Zwraca znormalizowaną ścieżkę albo zgłasza 422."""
    p = unicodedata.normalize("NFC", (raw or "").strip())
    bad = HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Niedozwolona ścieżka pliku: {raw!r}")
    if not p or "\\" in p or "\x00" in p or p.startswith("/") or ":" in p.split("/")[0]:
        raise bad
    parts = PurePosixPath(p).parts
    if any(x in ("", ".", "..") or x.startswith(".") for x in parts):
        raise bad
    if not p.lower().endswith(EXTENSIONS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Niedozwolony typ pliku: {raw} (dozwolone: {', '.join(EXTENSIONS)})")
    return "/".join(parts)


def _kind_order(path: str) -> int:
    """Kolejność podmiany: arkusze i inne pliki -> piramidy -> VRT (VRT wskazuje gotowe arkusze)."""
    low = path.lower()
    if low.endswith(".vrt"):
        return 3
    if low.endswith(".ovr"):
        return 2
    return 1


class Target(BaseModel):
    project: str | None = None            # rastry projektu (slug)
    library: bool = False                 # biblioteka data/rasters


async def _project_row(slug: str) -> dict:
    async with portal_conn() as conn:
        row = await (await conn.execute(
            "SELECT id, slug, file_name, owner_id FROM portal.projects WHERE slug=%s", (slug,))).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projekt nie jest opublikowany — najpierw opublikuj go w Fii")
    return row


async def resolve_target(t: Target, user: CurrentUser) -> tuple[Path, str]:
    """Katalog docelowy i jego opis (do sesji); sprawdza uprawnienia."""
    s = get_settings()
    if t.library == bool(t.project):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj projekt albo bibliotekę")
    if t.library:
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bibliotekę rastrów zmienia tylko administrator")
        root = s.rasters_dir
        if not root.is_dir():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Biblioteka rastrów nie jest dostępna dla API")
        return root.resolve(), "library"
    if not _SLUG_RE.match(t.project or ""):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieprawidłowy identyfikator projektu")
    row = await _project_row(t.project)
    if not user.is_admin and row["owner_id"] != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rastry projektu wysyła administrator albo właściciel projektu")
    root = (s.projects_dir / row["file_name"]).resolve().parent
    if root.parent != s.projects_dir.resolve():
        raise HTTPException(status.HTTP_409_CONFLICT, "Projekt nie leży we własnym katalogu — opublikuj go ponownie w Fii")
    return root, f"project:{row['slug']}"


# ------------------------------------------------------------------------------ sumy kontrolne

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_cache(root: Path) -> dict:
    try:
        return json.loads((root / HASH_CACHE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(root: Path, cache: dict) -> None:
    tmp = root / f"{HASH_CACHE}.tmp"
    tmp.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
    tmp.replace(root / HASH_CACHE)


def server_hash(root: Path, rel: str, cache: dict) -> str | None:
    """SHA-256 pliku na serwerze (z pamięcią po rozmiarze i czasie modyfikacji) albo None, gdy go nie ma."""
    p = root / rel
    try:
        st = p.stat()
    except OSError:
        return None
    hit = cache.get(rel)
    if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns:
        return hit["sha256"]
    digest = sha256_file(p)
    cache[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha256": digest}
    return digest


def extra_files(root: Path, wanted: set[str]) -> list[str]:
    """Rastry na serwerze w katalogach wysyłanych plików, których nie ma na liście (np. usunięte arkusze)."""
    dirs = {str(PurePosixPath(p).parent) for p in wanted}
    out = []
    for d in sorted(dirs):
        base = root if d == "." else root / d
        if not base.is_dir():
            continue
        for f in sorted(base.iterdir()):
            rel = f.name if d == "." else f"{d}/{f.name}"
            if f.is_file() and not f.name.startswith(".") and f.name.lower().endswith(EXTENSIONS) and rel not in wanted:
                out.append(rel)
    return out


# ------------------------------------------------------------------------------ walidacja zawartości

def validate_vrt(data: bytes, rel: str, exists: Callable[[str], bool]) -> None:
    """VRT: źródła tylko względne i wewnątrz katalogu docelowego, bez /vsi… i bez funkcji Pythona.
    Spreparowany VRT mógłby przez WMS pokazać dowolny plik serwera albo pobierać dane z sieci."""
    try:
        root_el = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"{rel}: niepoprawny XML ({e})") from e
    if root_el.tag != "VRTDataset":
        raise ValueError(f"{rel}: to nie jest VRT GDAL (VRTDataset)")
    here = PurePosixPath(rel).parent
    for el in root_el.iter():
        if el.tag in ("PixelFunctionCode", "PixelFunctionLanguage"):
            raise ValueError(f"{rel}: funkcje pikseli w Pythonie są niedozwolone")
        if el.tag not in ("SourceFilename", "SourceDataset"):
            continue
        name = (el.text or "").strip().replace("\\", "/")
        if el.get("relativeToVRT") != "1" or name.startswith("/") or ":" in name or name.lower().startswith("/vsi"):
            raise ValueError(f"{rel}: źródło „{name}” musi być ścieżką względną do VRT "
                             "(Fia → „Wysyłka rastrów” → „Przygotuj zaznaczone…” poprawia VRT)")
        target = os.path.normpath(str(here / name)).replace("\\", "/")
        if target.startswith("../") or target == ".." or target.startswith("/"):
            raise ValueError(f"{rel}: źródło „{name}” wychodzi poza katalog docelowy")
        if not exists(target):
            raise ValueError(f"{rel}: brak pliku źródłowego „{name}” (ani w wysyłce, ani na serwerze — "
                             "sprawdź wielkość liter w nazwie)")


def validate_file(path: Path, rel: str, exists: Callable[[str], bool]) -> None:
    low = rel.lower()
    if low.endswith(RASTER_EXT):
        with path.open("rb") as f:
            if f.read(4) not in TIFF_MAGIC:
                raise ValueError(f"{rel}: to nie jest plik TIFF")
    elif low.endswith((".vrt", ".aux.xml")):
        if path.stat().st_size > XML_MAX:
            raise ValueError(f"{rel}: plik XML za duży")
        data = path.read_bytes()
        if low.endswith(".vrt"):
            validate_vrt(data, rel, exists)
        else:
            try:
                ET.fromstring(data)
            except ET.ParseError as e:
                raise ValueError(f"{rel}: niepoprawny XML ({e})") from e
    elif low.endswith(".tfw"):
        if path.stat().st_size > 4096:
            raise ValueError(f"{rel}: plik .tfw za duży")


# ------------------------------------------------------------------------------ sesje

def _session_dir(root: Path, sid: str) -> Path:
    if not _SID_RE.match(sid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej sesji wysyłki")
    return root / f".upload-{sid}"


def _part(sdir: Path, rel: str) -> Path:
    return sdir / (rel + ".part")


def cleanup_stale(root: Path, now: float | None = None) -> int:
    now = now or time.time()
    n = 0
    for d in root.glob(".upload-*"):
        try:
            if d.is_dir() and now - d.stat().st_mtime > SESSION_TTL_S:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n


async def _load_session(sid: str, user: CurrentUser) -> tuple[dict, Path, Path]:
    """Sesja po identyfikatorze: szukamy w katalogach projektów i w bibliotece (sesja zna swój cel)."""
    s = get_settings()
    if not _SID_RE.match(sid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej sesji wysyłki")
    candidates = [s.rasters_dir / f".upload-{sid}"] + list(s.projects_dir.glob(f"*/.upload-{sid}"))
    for sdir in candidates:
        meta = sdir / "session.json"
        if meta.is_file():
            sess = json.loads(meta.read_text("utf-8"))
            if sess["user_id"] != user.id and not user.is_admin:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "To nie jest Twoja sesja wysyłki")
            return sess, sdir, sdir.parent
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej sesji wysyłki (wygasła albo zakończona)")


class FileIn(BaseModel):
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class PlanIn(Target):
    files: list[FileIn]
    dry_run: bool = False                 # tylko porównanie („Sprawdź na serwerze”), bez sesji


@router.post("/plan")
async def plan(body: PlanIn, user: CurrentUser = Depends(require_publisher)):
    """Porównanie listy plików z serwerem; tworzy sesję, gdy jest co wysłać."""
    root, label = await resolve_target(body, user)
    files: dict[str, dict] = {}
    for f in body.files:
        rel = clean_path(f.path)
        if rel in files:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Plik podany dwa razy: {rel}")
        files[rel] = {"size": f.size, "sha256": f.sha256.lower()}
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak plików")
    if body.library and any("/" not in r for r in files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Biblioteka: pliki w katalogu serii (np. tk25/arkusz.tif), nie w katalogu głównym")

    def compare():
        cleanup_stale(root)
        cache = _load_cache(root)
        upload, same = [], []
        for rel, f in files.items():
            (same if server_hash(root, rel, cache) == f["sha256"] else upload).append(rel)
        _save_cache(root, cache)
        return upload, same, extra_files(root, set(files))

    upload, same, extra = await asyncio.to_thread(compare)
    need = sum(files[r]["size"] for r in upload)
    free = shutil.disk_usage(root).free
    res = {"upload": upload, "same": same, "extra": extra, "need_bytes": need, "free_bytes": free, "session": None}
    if need * 1.1 + 256 * 1024 * 1024 > free:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE,
                            f"Za mało miejsca na serwerze: potrzeba {need / 2**20:.0f} MB, wolne {free / 2**20:.0f} MB")
    if upload and not body.dry_run:
        sid = uuid.uuid4().hex
        sdir = _session_dir(root, sid)
        sdir.mkdir()
        sess = {"id": sid, "user_id": user.id, "login": user.login, "target": label, "created": time.time(),
                "files": files, "upload": upload}
        (sdir / "session.json").write_text(json.dumps(sess, ensure_ascii=False), "utf-8")
        res["session"] = sid
    return res


@router.get("/sessions/{sid}")
async def session_status(sid: str, user: CurrentUser = Depends(require_publisher)):
    """Ile bajtów każdego pliku już odebrano — wznawianie po przerwanym połączeniu."""
    sess, sdir, _ = await _load_session(sid, user)
    files = {}
    for rel in sess["upload"]:
        p = _part(sdir, rel)
        files[rel] = {**sess["files"][rel], "received": p.stat().st_size if p.exists() else 0}
    return {"id": sid, "target": sess["target"], "files": files}


@router.put("/sessions/{sid}/file")
async def upload_chunk(sid: str, path: str, offset: int, request: Request,
                       user: CurrentUser = Depends(require_publisher)):
    """Kolejna część pliku od `offset` (musi równać się dotąd odebranej długości)."""
    sess, sdir, _ = await _load_session(sid, user)
    rel = clean_path(path)
    if rel not in sess["upload"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Pliku nie ma w planie wysyłki: {rel}")
    size = sess["files"][rel]["size"]
    part = _part(sdir, rel)
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if offset != have:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"message": f"Oczekiwano części od bajtu {have}", "received": have})
    written = 0
    with part.open("ab") as out:
        async for block in request.stream():
            written += len(block)
            if written > CHUNK_MAX or have + written > size:
                out.truncate(have)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Za duża część albo plik dłuższy niż w planie")
            out.write(block)
    os.utime(sdir)                         # sesja żywa (sprzątanie po 24 h bezczynności)
    return {"received": have + written}


class CommitIn(BaseModel):
    delete_extra: bool = False


def projects_using(projects_dir: Path, prefixes: list[str]) -> list[Path]:
    """Pliki projektów (.qgz/.qgs), których źródła warstw wskazują bibliotekę rastrów (np. rasters/tk25/)."""
    out = []
    for p in sorted(projects_dir.glob("*/*.qg[sz]")):
        try:
            if p.suffix == ".qgz":
                with zipfile.ZipFile(p) as z:
                    name = next((n for n in z.namelist() if n.endswith(".qgs")), None)
                    text = z.read(name).decode("utf-8", "replace") if name else ""
            else:
                text = p.read_text("utf-8", "replace")
        except (OSError, zipfile.BadZipFile):
            continue
        if any(f"rasters/{x}" in text for x in prefixes):
            out.append(p)
    return out


def touch(paths: list[Path]) -> None:
    """Nowy czas modyfikacji projektu: QGIS Server przeładowuje go i otwiera rastry od nowa (sprawdzone 25.11)."""
    now = time.time()
    for p in paths:
        os.utime(p, (now, now))


def apply_session(sess: dict, sdir: Path, root: Path, delete_extra: bool, projects_dir: Path) -> dict:
    """Zatwierdzenie sesji: komplet i sumy, walidacja, rename (arkusze -> piramidy -> VRT), nadmiar, touch projektów.
    ValueError — sesja zostaje (można dosłać pliki i spróbować ponownie)."""
    files, upload = sess["files"], sess["upload"]
    for rel in upload:
        p = _part(sdir, rel)
        got = p.stat().st_size if p.exists() else -1
        if got != files[rel]["size"]:
            raise ValueError(f"{rel}: odebrano {max(got, 0)} z {files[rel]['size']} B — dokończ wysyłkę")
    for rel in upload:
        if sha256_file(_part(sdir, rel)) != files[rel]["sha256"]:
            _part(sdir, rel).unlink()
            raise ValueError(f"{rel}: suma kontrolna się nie zgadza — wyślij plik ponownie")
    # pliki dostępne po podmianie: z wysyłki albo już na serwerze (bez usuwanych jako nadmiar)
    extra = extra_files(root, set(files))
    gone = set(extra) if delete_extra else set()

    def exists(rel: str) -> bool:
        return rel in files or (rel not in gone and (root / rel).is_file())

    for rel in upload:
        validate_file(_part(sdir, rel), rel, exists)
    cache = _load_cache(root)
    added, replaced = [], []
    for rel in sorted(upload, key=lambda r: (_kind_order(r), r)):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        (replaced if dest.exists() else added).append(rel)
        os.chmod(_part(sdir, rel), 0o644)
        os.replace(_part(sdir, rel), dest)
        st = dest.stat()
        cache[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha256": files[rel]["sha256"]}
    deleted = []
    if delete_extra:
        for rel in extra:
            (root / rel).unlink(missing_ok=True)
            cache.pop(rel, None)
            deleted.append(rel)
    _save_cache(root, cache)
    shutil.rmtree(sdir, ignore_errors=True)
    if sess["target"] == "library":
        series = sorted({r.split("/")[0] for r in files if "/" in r})
        projects = projects_using(projects_dir, [f"{x}/" for x in series])
    else:
        projects = sorted(root.glob("*.qg[sz]"))
    touch(projects)
    return {"added": added, "replaced": replaced, "deleted": deleted,
            "extra": [] if delete_extra else extra, "projects": [p.parent.name for p in projects]}


@router.post("/sessions/{sid}/commit")
async def commit(sid: str, body: CommitIn, user: CurrentUser = Depends(require_publisher)):
    sess, sdir, root = await _load_session(sid, user)
    async with _locks.setdefault(str(root), asyncio.Lock()):
        try:
            res = await asyncio.to_thread(apply_session, sess, sdir, root, body.delete_extra,
                                          get_settings().projects_dir)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    if res["projects"]:
        # podkłady „warstwa Sophii” z tych projektów: nowa wersja -> nowe adresy kafli
        async with portal_conn() as conn:
            await conn.execute("UPDATE portal.basemaps SET updated_at = now() "
                               "WHERE kind = 'sophia' AND config->>'project' = ANY(%s)", (res["projects"],))
    log.info("rastry: %s (%s) — dodane %d, podmienione %d, usunięte %d; projekty odświeżone: %s",
             sess["target"], user.login, len(res["added"]), len(res["replaced"]), len(res["deleted"]),
             ", ".join(res["projects"]) or "—")
    return res


@router.delete("/sessions/{sid}")
async def abort(sid: str, user: CurrentUser = Depends(require_publisher)):
    _, sdir, _ = await _load_session(sid, user)
    await asyncio.to_thread(shutil.rmtree, sdir, True)
    return {"ok": True}
