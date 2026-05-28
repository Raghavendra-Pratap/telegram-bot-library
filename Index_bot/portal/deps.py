"""Portal auth dependencies and roles."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from config import Config
from database import Database

_db = Database()


def user_role(user_id: int) -> str:
    return "admin" if Config.is_admin(user_id) else "user"


def get_user_id(authorization: str | None = Header(None)) -> int:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login required — use /portal in Telegram")
    token = authorization[7:].strip()
    uid = _db.get_portal_user_id(token)
    if not uid:
        raise HTTPException(401, "Invalid or expired session")
    return uid


def get_user_id_optional(
    authorization: str | None = Header(None),
    token: str | None = None,
) -> int:
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    elif token:
        raw = token.strip()
    if not raw:
        raise HTTPException(401, "Login required")
    uid = _db.get_portal_user_id(raw)
    if not uid:
        raise HTTPException(401, "Invalid or expired session")
    return uid


def require_admin(user_id: int = Depends(get_user_id)) -> int:
    if not Config.is_admin(user_id):
        raise HTTPException(403, "Admin access only")
    return user_id
