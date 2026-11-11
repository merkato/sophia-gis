"""Zdjęcia: wysyłanie (także z aparatu telefonu) i podgląd plików z pól „Załącznik” (ExternalResource).

Dwa warianty konfiguracji w QGIS (docs/user/zdjecia.md):
  A. pole „Załącznik” w tabeli obiektów — jedno zdjęcie na obiekt; WebUI wysyła plik, dostaje
     ścieżkę i zapisuje ją w polu razem z resztą formularza,
  B. osobna tabela zdjęć powiązana relacją z obiektem — wiele zdjęć; jedno żądanie zapisuje plik
     i tworzy rekord z kluczem obcym rodzica (i punktem z GPS, jeśli tabela ma geometrię).

Pliki są udostępniane tylko przez obiekt (warstwa + klucz + pole): zdjęcie widzi każdy, kto widzi
obiekt — dostęp do projektu i warstwy oraz zakres danych użytkownika (app/scope.py; tabela zdjęć
bez geometrii — zakres obiektu nadrzędnego). Dodawanie: prawo edycji warstwy i prawo do zdjęć /
dokumentów nadane grupie w projekcie.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from psycopg import sql

from .. import photos
from ..config import get_settings
from ..db import layer_conn
from ..permissions import ProjectContext, load_project_context
from ..qgsproject import FieldDef, LayerDef
from ..scope import T, col, row_filter
from ..security import CurrentUser, optional_user, require_user
from .features import _audit, _fetch_one, _geom_sql, _row_to_feature, _scope_error, _table, in_scope

log = logging.getLogger("sophia.photos")

router = APIRouter(prefix="/api/projects/{slug}/layers/{layer_id}", tags=["photos"])


def _uploads(ctx: ProjectContext):
    return get_settings().uploads_dir / ctx.slug


def _resource_field(lyr: LayerDef, name: str, photo: bool) -> FieldDef:
    f = next((f for f in lyr.fields if f.name == name), None)
    if f is None or not photos.is_resource_field(f):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Pole '{name}' nie ma widżetu „Załącznik”")
    if photo and not photos.is_photo_field(f):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Pole '{name}' nie ma podglądu obrazu — użyj wysyłania pliku")
    if not lyr.pg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Załączniki tylko w warstwach PostGIS")
    return f


def _require_right(ctx: ProjectContext, photo: bool) -> None:
    if photo and not ctx.can_photos:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak prawa dodawania zdjęć w tym projekcie")
    if not photo and not ctx.can_files:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak prawa dodawania dokumentów w tym projekcie")


def _require_field_edit(ctx: ProjectContext, layer_id: str) -> None:
    perms = ctx.perms(layer_id)
    if not (perms.insert or perms.update):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnienia do edycji warstwy")


async def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().max_photo_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Zdjęcie większe niż {get_settings().max_photo_mb} MB")
    return data


async def _store_photo(ctx: ProjectContext, lyr: LayerDef, file: UploadFile) -> tuple[str, photos.Photo]:
    data = await _read_limited(file)
    try:
        photo = await asyncio.to_thread(photos.process_photo, data)
    except photos.PhotoError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    rel = photos.new_photo_path(lyr.pg.table if lyr.pg else lyr.id)
    dest = _uploads(ctx) / rel
    await asyncio.to_thread(photos.write_atomic, dest, photo.jpeg)
    try:
        await asyncio.to_thread(photos.ensure_thumb, dest, photos.thumb_path(_uploads(ctx), dest))
    except OSError:
        log.exception("Miniatura %s", dest)
    return rel, photo


async def _store_file(ctx: ProjectContext, lyr: LayerDef, f: FieldDef, file: UploadFile) -> dict:
    """Dokument zapisany bajt w bajt (bez konwersji), strumieniowo, z limitem i sumą SHA-256."""
    name = photos.safe_file_name(file.filename)
    try:
        photos.check_extension(f, name)
    except photos.PhotoError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    s = get_settings()
    rel = photos.new_file_path(lyr.pg.table if lyr.pg else lyr.id, name)
    dest = _uploads(ctx) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha, size, limit = hashlib.sha256(), 0, s.max_attachment_mb * 1024 * 1024
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                        f"Plik większy niż {s.max_attachment_mb} MB")
                sha.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pusty plik")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return {"path": rel, "name": name, "size": size, "sha256": sha.hexdigest()}


def _photo_meta(rel: str, photo: photos.Photo) -> dict:
    return {"path": rel, "width": photo.width, "height": photo.height, "taken_at": photo.taken_at,
            "lon": photo.lon, "lat": photo.lat}


async def _insert_child(ctx: ProjectContext, user: CurrentUser, lyr: LayerDef, field: str, rel: str,
                        parent_layer: str, parent_pk: str | None, crs: str,
                        gps: tuple[float, float] | None = None) -> dict:
    """Wariant B: rekord w tabeli zdjęć/dokumentów powiązanej relacją z obiektem nadrzędnym.
    Klucz obcy z wiersza rodzica (rodzic musi być widoczny dla użytkownika); tabela z geometrią
    punktową dostaje punkt z GPS zdjęcia albo punkt leżący na obiekcie nadrzędnym."""
    if parent_pk is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak parent_pk")
    ctx.require(lyr.id, "insert")
    parent = ctx.require(parent_layer, "view")
    relation = next((r for r in ctx.project.relations
                     if r.parent_layer == parent_layer and r.child_layer == lyr.id), None)
    if relation is None or not parent.pg or parent.pg.conninfo != lyr.pg.conninfo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Brak relacji między warstwami w projekcie QGIS")
    srid = int(crs.split(":")[1]) if crs.upper().startswith("EPSG:") else 2180

    async with layer_conn(lyr.pg.conninfo) as conn, conn.transaction():
        pg = col(T, parent.pg.geometry_column) if parent.pg.geometry_column else None
        prow = await (await conn.execute(sql.SQL(
            "SELECT {cols}{g} FROM {t} AS {a} WHERE {k}::text = {pk} AND {f}").format(
            cols=sql.SQL(", ").join(col(T, p) for p, _ in relation.pairs),
            g=sql.SQL(", ST_AsGeoJSON(ST_PointOnSurface({}))::json AS __pos, ST_SRID({}) AS __srid").format(pg, pg)
            if pg else sql.SQL(""),
            t=_table(parent), a=sql.Identifier(*T), k=col(T, parent.pg.key), pk=sql.Literal(parent_pk),
            f=row_filter(ctx, parent),
        ))).fetchone()
        if prow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu nadrzędnego")

        values = {c: prow[p] for p, c in relation.pairs}
        values[field] = rel
        cols = [sql.Identifier(k) for k in values]
        vals: list[sql.Composable] = [sql.Literal(v) for v in values.values()]
        if lyr.pg.geometry_column and lyr.geometry_type == "Point":
            geom = None
            if gps is not None:
                geom = _geom_sql(lyr, {"type": "Point", "coordinates": list(gps)}, 4326)
            elif pg and prow.get("__pos"):
                geom = _geom_sql(lyr, prow["__pos"], prow["__srid"] or srid)
            if geom is not None:
                cols.append(sql.Identifier(lyr.pg.geometry_column))
                vals.append(geom)
        try:
            pk = (await (await conn.execute(sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) RETURNING {k}::text AS pk").format(
                t=_table(lyr), c=sql.SQL(", ").join(cols), v=sql.SQL(", ").join(vals),
                k=sql.Identifier(lyr.pg.key)))).fetchone())["pk"]
        except psycopg.errors.IntegrityError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Nie można dodać rekordu: {e.diag.message_primary}") from e
        if not await in_scope(conn, ctx, lyr, pk, "edit"):
            raise _scope_error(ctx, lyr)
        row = await _fetch_one(conn, None, lyr, pk, srid, None)
    feature = _row_to_feature(row)
    await _audit(ctx, lyr.id, pk, "insert", None, feature)
    return feature


@router.post("/photos", status_code=201)
async def upload_photo(slug: str, layer_id: str, file: UploadFile = File(...), field: str = Form(...),
                       parent_layer: str | None = Form(None), parent_pk: str | None = Form(None),
                       crs: str = Form("EPSG:2180"), user: CurrentUser = Depends(require_user)):
    """Zdjęcie. Bez rodzica (wariant A): zapisuje plik i zwraca ścieżkę do wpisania w pole formularza.
    Z rodzicem (wariant B): dodatkowo tworzy rekord w tabeli zdjęć i zwraca go jako GeoJSON."""
    ctx = await load_project_context(slug, user)
    lyr = ctx.layer(layer_id)
    _resource_field(lyr, field, photo=True)
    _require_right(ctx, photo=True)
    if parent_layer is None:
        _require_field_edit(ctx, layer_id)
        rel, photo = await _store_photo(ctx, lyr, file)
        return _photo_meta(rel, photo)
    ctx.require(layer_id, "insert")
    rel, photo = await _store_photo(ctx, lyr, file)
    try:
        feature = await _insert_child(ctx, user, lyr, field, rel, parent_layer, parent_pk, crs,
                                      (photo.lon, photo.lat) if photo.lon is not None else None)
    except BaseException:
        (_uploads(ctx) / rel).unlink(missing_ok=True)
        raise
    return {**feature, "photo": _photo_meta(rel, photo)}


@router.post("/files", status_code=201)
async def upload_file(slug: str, layer_id: str, file: UploadFile = File(...), field: str = Form(...),
                      parent_layer: str | None = Form(None), parent_pk: str | None = Form(None),
                      crs: str = Form("EPSG:2180"), user: CurrentUser = Depends(require_user)):
    """Dokument (PDF, GML z podpisem, DOCX…) zapisany bez zmian. Warianty A i B jak przy zdjęciach;
    dozwolone typy z filtra plików widżetu „Załącznik” w QGIS."""
    ctx = await load_project_context(slug, user)
    lyr = ctx.layer(layer_id)
    f = _resource_field(lyr, field, photo=False)
    _require_right(ctx, photo=False)
    if parent_layer is None:
        _require_field_edit(ctx, layer_id)
        return await _store_file(ctx, lyr, f, file)
    ctx.require(layer_id, "insert")
    meta = await _store_file(ctx, lyr, f, file)
    try:
        feature = await _insert_child(ctx, user, lyr, field, meta["path"], parent_layer, parent_pk, crs)
    except BaseException:
        (_uploads(ctx) / meta["path"]).unlink(missing_ok=True)
        raise
    return {**feature, "file": meta}


def visible_condition(ctx: ProjectContext, lyr: LayerDef, _extent=None) -> sql.Composable:
    """Zgodność wsteczna: warunek widoczności rekordu (FROM tabela AS __t) — app/scope.py."""
    return row_filter(ctx, lyr, T, "view")


@router.get("/features/{pk}/files/{field}")
async def feature_file(slug: str, layer_id: str, pk: str, field: str, thumb: bool = False,
                       user: CurrentUser | None = Depends(optional_user)):
    """Plik z pola „Załącznik” obiektu (thumb=1: miniatura JPEG)."""
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "view")
    f = next((x for x in lyr.fields if x.name == field), None)
    if f is None or not photos.is_resource_field(f) or not lyr.pg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pole nie jest załącznikiem")
    async with layer_conn(lyr.pg.conninfo) as conn:
        row = await (await conn.execute(sql.SQL(
            "SELECT {c}::text AS v FROM {t} AS {a} WHERE {k}::text = {pk} AND {vis}").format(
            c=col(T, field), t=_table(lyr), a=sql.Identifier(*T), k=col(T, lyr.pg.key),
            pk=sql.Literal(pk), vis=visible_condition(ctx, lyr)))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak obiektu")
    try:
        rel = photos.normalize_value(row["v"])
    except photos.PhotoError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    src = photos.resolve_file(rel, _uploads(ctx), ctx.path.parent)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Brak pliku na serwerze: {rel}")
    headers = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"}
    if thumb and photos.is_photo_field(f):
        try:
            t = await asyncio.to_thread(photos.ensure_thumb, src, photos.thumb_path(_uploads(ctx), src))
        except OSError as e:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Nie da się odczytać obrazu") from e
        return FileResponse(t, media_type="image/jpeg", headers=headers)
    media = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    if src.suffix.lower().lstrip(".") in photos.BLOCKED_EXT:
        media = "application/octet-stream"
    inline = media in photos.INLINE_TYPES
    return FileResponse(src, media_type=media, filename=src.name, headers=headers,
                        content_disposition_type="inline" if inline else "attachment")


projects_router = APIRouter(prefix="/api/projects/{slug}", tags=["photos"])


@projects_router.get("/photos")
async def photo_manifest(slug: str, user: CurrentUser | None = Depends(optional_user)):
    """Lista plików z pól „Załącznik” widocznych dla użytkownika — do pobrania przez Fię do folderu
    projektu (QGIS Desktop pokazuje zdjęcia po ścieżce względnej). Pobieranie: features/{pk}/files/{field}."""
    ctx = await load_project_context(slug, user)
    files: dict[str, dict] = {}
    for lyr in ctx.project.layers.values():
        fields = [f for f in lyr.fields if photos.is_resource_field(f)]
        if not fields or not lyr.pg or not ctx.perms(lyr.id).view:
            continue
        vis = visible_condition(ctx, lyr)
        async with layer_conn(lyr.pg.conninfo) as conn:
            for f in fields:
                rows = await (await conn.execute(sql.SQL(
                    "SELECT {k}::text AS pk, {c}::text AS v FROM {t} AS {a} WHERE {c} IS NOT NULL AND {vis}").format(
                    k=col(T, lyr.pg.key), c=col(T, f.name), t=_table(lyr),
                    a=sql.Identifier(*T), vis=vis))).fetchall()
                for r in rows:
                    try:
                        rel = photos.normalize_value(r["v"])
                    except photos.PhotoError:
                        continue
                    if rel in files:
                        continue
                    src = photos.resolve_file(rel, _uploads(ctx), ctx.path.parent)
                    if src is None:
                        continue
                    st = src.stat()
                    files[rel] = {"path": rel, "layer_id": lyr.id, "pk": r["pk"], "field": f.name,
                                  "size": st.st_size, "mtime": int(st.st_mtime)}
    return {"project": slug, "files": sorted(files.values(), key=lambda x: x["path"])}
