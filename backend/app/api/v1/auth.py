from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import ROLE_PERMISSIONS, CurrentUser, DbSession
from app.core.errors import ApiError
from app.core.security import create_access_token, verify_password
from app.models import User, utcnow
from app.schemas import LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        permissions=ROLE_PERMISSIONS.get(user.role, []),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "UNAUTHENTICATED", "Email or password is incorrect.")
    token, expires_in = create_access_token(user.id, user.role)
    user.last_login_at = utcnow()
    db.commit()
    return LoginResponse(access_token=token, expires_in=expires_in, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
