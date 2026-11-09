"""Uwierzytelnianie: hasła (argon2), tokeny JWT w ciasteczku HttpOnly lub nagłówku Bearer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status

from .config import get_settings
from .db import portal_conn

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_token(user_id: int) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


@dataclass
class CurrentUser:
    id: int
    login: str
    full_name: str | None
    is_admin: bool
    group_ids: list[int]
    group_names: list[str]


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(get_settings().cookie_name)


async def optional_user(request: Request) -> CurrentUser | None:
    token = _token_from_request(request)
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    async with portal_conn() as conn:
        row = await (
            await conn.execute(
                """
                SELECT u.id, u.login, u.full_name, u.is_admin,
                       coalesce(array_agg(g.id) FILTER (WHERE g.id IS NOT NULL), '{}') AS group_ids,
                       coalesce(array_agg(g.name) FILTER (WHERE g.id IS NOT NULL), '{}') AS group_names
                FROM portal.users u
                LEFT JOIN portal.user_groups ug ON ug.user_id = u.id
                LEFT JOIN portal.groups g ON g.id = ug.group_id
                WHERE u.id = %s AND u.is_active
                GROUP BY u.id
                """,
                (int(payload["sub"]),),
            )
        ).fetchone()
    return CurrentUser(**row) if row else None


async def require_user(user: CurrentUser | None = Depends(optional_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wymagane logowanie")
    return user


async def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wymagane uprawnienia administratora")
    return user
