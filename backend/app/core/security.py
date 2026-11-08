"""Password hashing, JWT access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

ALGORITHM = "HS256"
REFRESH_TOKEN_BYTES = 48
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id, role: str, expires_minutes: int | None = None) -> tuple[str, int]:
    expires = expires_minutes or settings.access_token_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, expires * 60


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def create_refresh_token(days: int | None = None) -> tuple[str, str, datetime]:
    """Return ``(raw_token, sha256_hash, expires_at)``.

    The raw value is only ever placed in the HttpOnly cookie; the database
    stores the hash, so a stolen database dump cannot be replayed as a session.
    """

    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=days if days is not None else settings.refresh_token_days
    )
    return raw, hash_refresh_token(raw), expires_at


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
