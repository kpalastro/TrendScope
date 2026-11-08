from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.errors import ApiError
from app.models import Product, ScoringProfile, utcnow
from app.schemas import RecalculateRequest
from app.services import audit
from app.services.metrics import compute_all_metrics, compute_product_metrics
from app.services.scoring import COMPONENT_LABELS, DEFAULT_THRESHOLDS
from app.services.scoring_service import compute_all_scores, compute_product_score, get_active_profile

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
def create_profile(
    payload: dict, request: Request, user: AdminUser, db: DbSession
) -> dict:
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
    audit.record(
        db,
        action="scoring_profile.create",
        entity_type="scoring_profile",
        entity_id=profile.id,
        user=user,
        request=request,
        changes={"country": profile.country, "version": profile.version},
    )
    return _payload(profile)


@router.post("/scoring-profiles/{profile_id}/activate")
def activate_profile(
    profile_id: UUID, request: Request, user: AdminUser, db: DbSession
) -> dict:
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
    audit.record(
        db,
        action="scoring_profile.activate",
        entity_type="scoring_profile",
        entity_id=profile.id,
        user=user,
        request=request,
        changes={"country": profile.country, "version": profile.version},
    )
    return _payload(profile)


@router.post("/scores/recalculate", status_code=202)
def recalculate_scores(
    payload: RecalculateRequest,
    request: Request,
    user: AdminUser,
    db: DbSession,
) -> dict:
    """Recompute metrics and scores for one product or the whole catalogue.

    ``as_of_date`` defaults to today and may be in the past, which lets an
    operator rebuild snapshots after correcting historical observations.
    """

    if payload.all and payload.product_id is not None:
        raise ApiError(
            422, "VALIDATION_ERROR", "Supply either product_id or all=true, not both."
        )
    if not payload.all and payload.product_id is None:
        raise ApiError(
            422, "VALIDATION_ERROR", "Supply a product_id or set all=true."
        )
    as_of = payload.as_of_date or date.today()
    if as_of > date.today():
        raise ApiError(422, "VALIDATION_ERROR", "as_of_date cannot be in the future.")

    if payload.product_id is not None:
        product = db.get(Product, payload.product_id)
        if product is None:
            raise ApiError(404, "NOT_FOUND", "Product not found.")
        if product.status == "merged":
            raise ApiError(
                409,
                "CONFLICT",
                "This product was merged; recalculate the surviving product instead.",
            )
        profile = get_active_profile(db)
        if profile is None:
            raise ApiError(
                409, "BUSINESS_RULE_VIOLATION", "No active scoring profile is configured."
            )
        metric = compute_product_metrics(db, product, as_of)
        compute_product_score(db, product, metric, profile, as_of)
        db.commit()
        products = 1
    else:
        products = compute_all_metrics(db, as_of)
        compute_all_scores(db, as_of)

    now = utcnow()
    audit.record(
        db,
        action="scores.recalculate",
        entity_type="score",
        entity_id=payload.product_id,
        user=user,
        request=request,
        changes={"products": products, "as_of_date": as_of.isoformat(), "all": payload.all},
    )
    return {
        "job": {
            "id": f"recalc-{now.strftime('%Y%m%d%H%M%S')}",
            "type": "scores.recalculate",
            "status": "succeeded",
            "progress": {"processed": products, "total": products},
            "result_url": "/api/v1/products",
            "error": None,
            "created_at": now,
            "poll_url": "/api/v1/products",
        },
        "products": products,
        "as_of_date": as_of,
    }
