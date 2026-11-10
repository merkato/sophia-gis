"""Podkłady mapowe — wspólny katalog dla wszystkich projektów.

Podkłady nie pochodzą z projektów QGIS: definiuje je administrator raz, a WebUI pokazuje je
w każdym projekcie. Dzięki temu jedna usługa (np. ortofotomapa) ma zawsze jedno źródło kafli:
  - wmts:   przeglądarka pobiera kafle wprost z serwisu (np. geoportal.gov.pl), bez naszego serwera,
  - xyz:    jw. (np. OpenStreetMap),
  - sophia: warstwa z projektu Sophii (np. biblioteka TK25) przez /ows i wspólny cache kafli.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from ..db import portal_conn
from ..permissions import load_project_context
from ..security import CurrentUser, optional_user, require_admin
from ..wmts import CapabilitiesError, parse_capabilities, strip_capabilities_query

router = APIRouter(tags=["basemaps"])
admin = APIRouter(prefix="/api/admin/basemaps", tags=["admin"], dependencies=[Depends(require_admin)])

MAX_CAPABILITIES_BYTES = 10 * 1024 * 1024
COLUMNS = "id, name, kind, is_overlay, opacity, visible_default, enabled, sort_order, attribution, config, updated_at"


class BasemapIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["wmts", "xyz", "sophia"]
    is_overlay: bool = False
    opacity: float = Field(1.0, ge=0, le=1)
    visible_default: bool = False
    enabled: bool = True
    sort_order: int = 0
    attribution: str | None = None
    config: dict[str, Any]

    @model_validator(mode="after")
    def _check_config(self) -> BasemapIn:
        c = self.config
        required = {
            "wmts": ("url", "layer", "matrix_set", "format", "tile_grid"),
            "xyz": ("url",),
            "sophia": ("project", "layers"),
        }[self.kind]
        missing = [k for k in required if not c.get(k)]
        if missing:
            raise ValueError(f"Brak w konfiguracji: {', '.join(missing)}")
        if self.kind in ("wmts", "xyz") and not str(c["url"]).startswith("https://"):
            raise ValueError("Adres kafli musi zaczynać się od https:// (strona Sophii działa po HTTPS)")
        if self.kind == "wmts":
            g = c["tile_grid"]
            for k in ("crs", "origin", "resolutions", "matrix_ids", "tile_size"):
                if k not in g:
                    raise ValueError(f"Niepełna siatka kafli: brak {k}")
            if len(g["resolutions"]) != len(g["matrix_ids"]):
                raise ValueError("Siatka kafli: liczba rozdzielczości różna od liczby poziomów")
        return self


def _out(row: dict) -> dict:
    d = dict(row)
    d["version"] = int(d.pop("updated_at").timestamp()) if isinstance(row["updated_at"], datetime) else 0
    return d


# ------------------------------------------------------------------------------ publiczne

@router.get("/api/basemaps")
async def list_basemaps(user: CurrentUser | None = Depends(optional_user)):
    """Włączone podkłady dla WebUI (w kolejności sort_order)."""
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            f"SELECT {COLUMNS} FROM portal.basemaps WHERE enabled ORDER BY sort_order, name")).fetchall()
    out = []
    for r in rows:
        if r["kind"] == "sophia":
            # podkład z projektu Sophii widzi tylko ten, kto ma dostęp do projektu
            try:
                await load_project_context(r["config"]["project"], user)
            except HTTPException:
                continue
        d = _out(r)
        d.pop("enabled")
        out.append(d)
    return out


# ------------------------------------------------------------------------------ administrator

@admin.get("")
async def admin_list():
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            f"SELECT {COLUMNS} FROM portal.basemaps ORDER BY sort_order, name")).fetchall()
    return [_out(r) for r in rows]


@admin.post("", status_code=201)
async def admin_create(body: BasemapIn):
    async with portal_conn() as conn:
        row = await (await conn.execute(
            f"""INSERT INTO portal.basemaps (name, kind, is_overlay, opacity, visible_default, enabled,
                                              sort_order, attribution, config)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}""",
            (body.name, body.kind, body.is_overlay, body.opacity, body.visible_default, body.enabled,
             body.sort_order, body.attribution, Jsonb(body.config)))).fetchone()
    return _out(row)


@admin.put("/{basemap_id}")
async def admin_update(basemap_id: int, body: BasemapIn):
    async with portal_conn() as conn:
        row = await (await conn.execute(
            f"""UPDATE portal.basemaps SET name=%s, kind=%s, is_overlay=%s, opacity=%s, visible_default=%s,
                       enabled=%s, sort_order=%s, attribution=%s, config=%s, updated_at=now()
                WHERE id=%s RETURNING {COLUMNS}""",
            (body.name, body.kind, body.is_overlay, body.opacity, body.visible_default, body.enabled,
             body.sort_order, body.attribution, Jsonb(body.config), basemap_id))).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego podkładu")
    return _out(row)


@admin.delete("/{basemap_id}", status_code=204)
async def admin_delete(basemap_id: int):
    async with portal_conn() as conn:
        await conn.execute("DELETE FROM portal.basemaps WHERE id=%s", (basemap_id,))


class CapabilitiesIn(BaseModel):
    url: str | None = None        # adres GetCapabilities (serwer pobierze dokument)
    xml: str | None = None        # albo wklejona treść dokumentu


def _prefer_https(kvp: str | None, source_url: str | None) -> str | None:
    """Serwisy (np. geoportal.gov.pl) podają w GetCapabilities adresy http://, choć działają po HTTPS.
    Na stronie HTTPS przeglądarka zablokowałaby takie kafle — zmieniamy schemat, gdy host się zgadza."""
    if not kvp:
        return None
    k = urlsplit(kvp)
    if k.scheme == "http":
        s = urlsplit(source_url) if source_url else None
        if s is None or (s.scheme == "https" and s.hostname == k.hostname):
            return "https://" + kvp[len("http://"):]       # urlunsplit zgubiłby końcowe "?"
    return kvp


@admin.post("/capabilities")
async def admin_capabilities(body: CapabilitiesIn):
    """Analiza WMTS GetCapabilities: warstwy, formaty, macierze kafli — dane do edytora podkładu."""
    if not body.url and not body.xml:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj adres GetCapabilities albo treść XML")
    xml: bytes
    if body.xml:
        xml = body.xml.encode()
    else:
        url = body.url.strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Adres musi zaczynać się od http(s)://")
        if "request=" not in url.lower():
            url += ("&" if "?" in url else "?") + "SERVICE=WMTS&REQUEST=GetCapabilities"
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client, \
                    client.stream("GET", url, headers={"User-Agent": "Sophia/0.1"}) as res:
                if res.status_code != 200:
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Serwis odpowiedział kodem {res.status_code}")
                chunks, size = [], 0
                async for chunk in res.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_CAPABILITIES_BYTES:
                        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Dokument GetCapabilities jest za duży")
                    chunks.append(chunk)
                xml = b"".join(chunks)
        except httpx.HTTPError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Nie udało się pobrać: {exc}") from exc
        body.url = url
    try:
        caps = parse_capabilities(xml)
    except CapabilitiesError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    out = caps.to_dict()
    kvp = caps.kvp_url or (strip_capabilities_query(body.url) if body.url else None)
    out["kvp_url"] = _prefer_https(kvp, body.url)
    out["capabilities_url"] = body.url
    for layer in out["layers"]:
        layer["resource_urls"] = {f: _prefer_https(t, body.url) for f, t in layer["resource_urls"].items()}
    return out
