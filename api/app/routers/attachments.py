"""Załączniki PDF powiązane z obiektami (projekt, warstwa, klucz główny)."""
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ..config import get_settings
from ..db import portal_conn
from ..permissions import load_project_context
from ..security import CurrentUser, optional_user, require_user

router = APIRouter(prefix="/api/projects/{slug}/layers/{layer_id}/features/{pk}/attachments",
                   tags=["attachments"])


def _storage_path(att_id: uuid.UUID) -> Path:
    h = att_id.hex
    return get_settings().attachments_dir / h[:2] / h[2:4] / f"{h}.pdf"


@router.get("")
async def list_attachments(slug: str, layer_id: str, pk: str, user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    ctx.require(layer_id, "view")
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            """SELECT a.id, a.file_name, a.size_bytes, a.description, a.uploaded_at, u.login AS uploaded_by
               FROM portal.attachments a LEFT JOIN portal.users u ON u.id = a.uploaded_by
               WHERE a.project_id = %s AND a.layer_id = %s AND a.feature_pk = %s
               ORDER BY a.uploaded_at DESC""", (ctx.id, layer_id, pk))).fetchall()
    return rows


@router.post("", status_code=201)
async def upload_attachment(slug: str, layer_id: str, pk: str, file: UploadFile = File(...),
                            description: str | None = Form(None), user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    lyr = ctx.require(layer_id, "update")
    if not lyr.attachments:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Warstwa nie obsługuje załączników")

    s = get_settings()
    att_id = uuid.uuid4()
    dest = _storage_path(att_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha, size, limit = hashlib.sha256(), 0, s.max_attachment_mb * 1024 * 1024
    first = await file.read(5)
    if first != b"%PDF-":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Dozwolone są tylko pliki PDF")
    try:
        with dest.open("wb") as out:
            chunk = first
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                        f"Plik większy niż {s.max_attachment_mb} MB")
                sha.update(chunk)
                out.write(chunk)
                chunk = await file.read(1024 * 1024)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    async with portal_conn() as conn:
        await conn.execute(
            """INSERT INTO portal.attachments (id, project_id, layer_id, feature_pk, file_name, content_type,
                   size_bytes, sha256, description, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, 'application/pdf', %s, %s, %s, %s)""",
            (att_id, ctx.id, layer_id, pk, Path(file.filename or "dokument.pdf").name, size,
             sha.hexdigest(), description, user.id))
        await conn.execute(
            """INSERT INTO portal.audit_log (user_id, project_id, layer_id, feature_pk, action, new_data)
               VALUES (%s, %s, %s, %s, 'attach', jsonb_build_object('attachment', %s::text))""",
            (user.id, ctx.id, layer_id, pk, str(att_id)))
    return {"id": att_id, "file_name": file.filename, "size_bytes": size}


async def _get_row(ctx, layer_id: str, pk: str, att_id: uuid.UUID) -> dict:
    async with portal_conn() as conn:
        row = await (await conn.execute(
            "SELECT * FROM portal.attachments WHERE id = %s AND project_id = %s AND layer_id = %s AND feature_pk = %s",
            (att_id, ctx.id, layer_id, pk))).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak załącznika")
    return row


@router.get("/{att_id}")
async def download_attachment(slug: str, layer_id: str, pk: str, att_id: uuid.UUID,
                              user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    ctx.require(layer_id, "view")
    row = await _get_row(ctx, layer_id, pk, att_id)
    # inline => przeglądarka otwiera PDF w nowej karcie zamiast pobierać
    return FileResponse(_storage_path(att_id), media_type="application/pdf", filename=row["file_name"],
                        content_disposition_type="inline")


@router.delete("/{att_id}", status_code=204)
async def delete_attachment(slug: str, layer_id: str, pk: str, att_id: uuid.UUID,
                            user: CurrentUser = Depends(require_user)):
    ctx = await load_project_context(slug, user)
    ctx.require(layer_id, "update")
    await _get_row(ctx, layer_id, pk, att_id)
    async with portal_conn() as conn:
        await conn.execute("DELETE FROM portal.attachments WHERE id = %s", (att_id,))
        await conn.execute(
            """INSERT INTO portal.audit_log (user_id, project_id, layer_id, feature_pk, action, old_data)
               VALUES (%s, %s, %s, %s, 'detach', jsonb_build_object('attachment', %s::text))""",
            (user.id, ctx.id, layer_id, pk, str(att_id)))
    _storage_path(att_id).unlink(missing_ok=True)
