from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ..config import get_settings
from ..db import portal_conn
from ..security import CurrentUser, create_token, require_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response):
    async with portal_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT id, password_hash FROM portal.users WHERE login = %s AND is_active", (body.login,)
            )
        ).fetchone()
        if row is None or not verify_password(row["password_hash"], body.password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy login lub hasło")
        await conn.execute("UPDATE portal.users SET last_login_at = now() WHERE id = %s", (row["id"],))
        await conn.execute(
            "INSERT INTO portal.audit_log (user_id, action) VALUES (%s, 'login')", (row["id"],)
        )
    s = get_settings()
    token = create_token(row["id"])
    response.set_cookie(
        s.cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="lax",
        max_age=s.jwt_ttl_minutes * 60, path="/",
    )
    # Token zwracany także w treści — dla wtyczki QGIS (nagłówek Authorization: Bearer).
    return {"token": token}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(get_settings().cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser = Depends(require_user)):
    return {
        "id": user.id, "login": user.login, "full_name": user.full_name,
        "is_admin": user.is_admin, "groups": user.group_names,
    }
