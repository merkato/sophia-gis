import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import close_pools, portal_conn
from .migrations import run_migrations
from .routers import admin, auth, basemaps, features, fields, ows, photos, projects, reports
from .security import hash_password

log = logging.getLogger("sophia")


async def _bootstrap_admin() -> None:
    s = get_settings()
    if not s.admin_password:
        return
    async with portal_conn() as conn:
        # ON CONFLICT: przy kilku procesach uvicorn (--workers) startujących równocześnie
        cur = await conn.execute(
            """INSERT INTO portal.users (login, full_name, password_hash, is_admin)
               VALUES (%s, %s, %s, true) ON CONFLICT (login) DO NOTHING""",
            (s.admin_login, "Administrator", hash_password(s.admin_password)))
        if cur.rowcount:
            log.warning("Utworzono konto administratora '%s'", s.admin_login)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_migrations()
    await _bootstrap_admin()
    yield
    await close_pools()


app = FastAPI(title="Sophia API", version="0.1.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

for r in (auth, projects, features, fields, photos, reports, ows, admin, basemaps):
    app.include_router(r.router)
app.include_router(basemaps.admin)
app.include_router(photos.projects_router)


@app.get("/api/health")
async def health():
    async with portal_conn() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}
