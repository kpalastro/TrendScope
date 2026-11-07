from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ApiError
from app.services import dashboard as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user: CurrentUser, db: DbSession, country: str = "AU", limit: int = 10) -> dict:
    return {
        "summary": dashboard_service.summary(db, country=country),
        "widgets": dashboard_service.all_widgets(db, limit=limit, country=country),
    }


@router.get("/summary")
def summary(user: CurrentUser, db: DbSession, country: str = "AU") -> dict:
    return dashboard_service.summary(db, country=country)


@router.get("/widgets/{widget}")
def widget(
    widget: str, user: CurrentUser, db: DbSession, limit: int = 10, country: str = "AU"
) -> dict:
    if widget not in dashboard_service.WIDGETS:
        raise ApiError(
            404,
            "NOT_FOUND",
            f"Unknown widget. Available: {', '.join(sorted(dashboard_service.WIDGETS))}.",
        )
    return dashboard_service.widget(db, widget, limit=limit, country=country)
