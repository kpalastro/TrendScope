from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update

from app.api.deps import ROLE_PERMISSIONS, CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_password,
)
from app.models import AuthRefreshToken, User, utcnow
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "trendscope_refresh"
# The browser scopes a cookie to the URL path it requested. The Next.js rewrite
# proxies /api/backend/auth/* to this API, so a path scoped to /api/v1/auth
# would never be sent back through the proxy. "/" also covers deployments that
# call the API directly. The value is an opaque, HttpOnly token either way.
REFRESH_COOKIE_PATH = "/"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        permissions=ROLE_PERMISSIONS.get(user.role, []),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _issue_refresh_cookie(
    response: Response, db, user: User, request: Request
) -> AuthRefreshToken:
    raw, token_hash, expires_at = create_refresh_token()
    entry = AuthRefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        ip=request.client.host if request.client else None,
    )
    db.add(entry)
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw,
        max_age=settings.refresh_token_days * 86_400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )
    return entry


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> LoginResponse:
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "UNAUTHENTICATED", "Email or password is incorrect.")
    token, expires_in = create_access_token(user.id, user.role)
    user.last_login_at = utcnow()
    _issue_refresh_cookie(response, db, user, request)
    db.commit()
    audit.record(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        user=user,
        request=request,
    )
    return LoginResponse(access_token=token, expires_in=expires_in, user=_user_out(user))


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
) -> LoginResponse:
    """Rotate the refresh token and mint a fresh access token.

    A refresh token is single-use. Presenting one that was already rotated is
    treated as theft: every active session for the user is revoked.
    """

    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "UNAUTHENTICATED", "No refresh token was supplied.")

    entry = db.execute(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == hash_refresh_token(raw))
    ).scalar_one_or_none()
    if entry is None:
        _clear_refresh_cookie(response)
        raise ApiError(401, "UNAUTHENTICATED", "Refresh token is not recognised.")

    now = datetime.now(timezone.utc)
    if entry.revoked_at is not None:
        db.execute(
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.user_id == entry.user_id,
                AuthRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        db.commit()
        _clear_refresh_cookie(response)
        audit.record(
            db,
            action="auth.refresh_reuse",
            entity_type="user",
            entity_id=entry.user_id,
            request=request,
            changes={"sessions_revoked": True},
        )
        raise ApiError(401, "UNAUTHENTICATED", "Refresh token has already been used.")

    if _as_utc(entry.expires_at) <= now:
        entry.revoked_at = now
        db.commit()
        _clear_refresh_cookie(response)
        raise ApiError(401, "UNAUTHENTICATED", "Refresh token has expired.")

    user = db.get(User, entry.user_id)
    if user is None or not user.is_active:
        entry.revoked_at = now
        db.commit()
        _clear_refresh_cookie(response)
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")

    successor = _issue_refresh_cookie(response, db, user, request)
    db.flush()
    entry.revoked_at = now
    entry.replaced_by_id = successor.id
    token, expires_in = create_access_token(user.id, user.role)
    db.commit()
    return LoginResponse(access_token=token, expires_in=expires_in, user=_user_out(user))


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbSession) -> Response:
    """Revoke the presented refresh token and clear the cookie. Idempotent."""

    out = Response(status_code=204)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        entry = db.execute(
            select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == hash_refresh_token(raw)
            )
        ).scalar_one_or_none()
        if entry is not None and entry.revoked_at is None:
            entry.revoked_at = datetime.now(timezone.utc)
            db.commit()
            audit.record(
                db,
                action="auth.logout",
                entity_type="user",
                entity_id=entry.user_id,
                request=request,
            )
    out.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )
    return out


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
