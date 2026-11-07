"""Shared FastAPI dependencies: database session, current user, role checks."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import ApiError
from app.core.security import decode_token
from app.models import User

ROLE_PERMISSIONS = {
    "admin": ["read", "write", "admin"],
    "analyst": ["read", "write"],
    "viewer": ["read"],
}

bearer = HTTPBearer(auto_error=False)


def _unauthorised(message: str = "Authentication required.") -> ApiError:
    return ApiError(
        401,
        "UNAUTHENTICATED",
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> User:
    if not settings.auth_required:
        user = db.execute(select(User).order_by(User.created_at)).scalars().first()
        if user is None:
            raise ApiError(503, "SOURCE_UNAVAILABLE", "Auth is disabled but no user exists.")
        return user

    if credentials is None or not credentials.credentials:
        raise _unauthorised()
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorised("Access token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorised("Access token is invalid.") from exc

    subject = payload.get("sub")
    if not subject:
        raise _unauthorised("Access token is missing a subject.")
    try:
        user_id = UUID(str(subject))
    except ValueError as exc:
        raise _unauthorised("Access token has an invalid subject.") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorised("User is not active.")
    return user


def require_write(user: User = Depends(get_current_user)) -> User:
    if "write" not in ROLE_PERMISSIONS.get(user.role, []):
        raise ApiError(403, "FORBIDDEN", "This action requires the analyst or admin role.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if "admin" not in ROLE_PERMISSIONS.get(user.role, []):
        raise ApiError(403, "FORBIDDEN", "This action requires the admin role.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
WriteUser = Annotated[User, Depends(require_write)]
AdminUser = Annotated[User, Depends(require_admin)]
DbSession = Annotated[Session, Depends(get_db)]
