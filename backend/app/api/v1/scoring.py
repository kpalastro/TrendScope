from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select, update

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.errors import ApiError
from app.models import ScoringProfile
from app.services.scoring import COMPONENT_LABELS, DEFAULT_THRESHOLDS

router = APIRouter(tags=["scoring"])


def _payload(profile: ScoringProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "country": profile.country,
        "version": profile.version,
        "weights": profile.weights,
        "thresholds": profile.thresholds,
        "is_active": profile.is_active,
        "is_default": profile.is_default,
        "created_at": profile.created_at,
    }


@router.get("/scoring-profiles")
def list_profiles(user: CurrentUser, db: DbSession) -> dict:
    rows = db.execute(
        select(ScoringProfile).order_by(ScoringProfile.country, ScoringProfile.version.desc())
    ).scalars().all()
    return {"data": [_payload(row) for row in rows]}


@router.get("/scoring-profiles/{profile_id}")
def get_profile(profile_id: UUID, user: CurrentUser, db: DbSession) -> dict:
    profile = db.get(ScoringProfile, profile_id)
    if profile is None:
        raise ApiError(404, "NOT_FOUND", "Scoring profile not found.")
    return _payload(profile)


@router.post("/scoring-profiles", status_code=201)
def create_profile(payload: dict, user: AdminUser, db: DbSession) -> dict:
    weights = payload.get("weights") or {}
    if set(weights) != set(COMPONENT_LABELS):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"weights must contain exactly: {', '.join(sorted(COMPONENT_LABELS))}",
        )
    try:
        values = {key: float(value) for key, value in weights.items()}
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "weights must be numbers") from exc
    if any(value < 0 or value > 1 for value in values.values()):
        raise ApiError(422, "VALIDATION_ERROR", "each weight must be between 0 and 1")
    if abs(sum(values.values()) - 1.0) > 1e-6:
        raise ApiError(422, "VALIDATION_ERROR", "weights must sum to 1.0")

    country = str(payload.get("country", "AU")).upper()[:2]
    latest = db.execute(
        select(ScoringProfile)
        .where(ScoringProfile.country == country)
        .order_by(ScoringProfile.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    profile = ScoringProfile(
        name=str(payload.get("name") or f"Default {country}")[:160],
        country=country,
        version=(latest.version + 1) if latest else 1,
        weights=values,
        thresholds=payload.get("thresholds") or DEFAULT_THRESHOLDS,
        is_active=False,
        is_default=False,
    )
    db.add(profile)
    db.commit()
    return _payload(profile)


@router.post("/scoring-profiles/{profile_id}/activate")
def activate_profile(profile_id: UUID, user: AdminUser, db: DbSession) -> dict:
    profile = db.get(ScoringProfile, profile_id)
    if profile is None:
        raise ApiError(404, "NOT_FOUND", "Scoring profile not found.")
    db.execute(
        update(ScoringProfile)
        .where(ScoringProfile.country == profile.country)
        .values(is_active=False, is_default=False)
    )
    profile.is_active = True
    profile.is_default = True
    db.commit()
    return _payload(profile)
