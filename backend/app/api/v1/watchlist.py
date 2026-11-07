from __future__ import annotations

import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, WriteUser
from app.core.errors import ApiError
from app.models import WatchlistEntry, utcnow
from app.schemas import WatchlistCreate, WatchlistUpdate
from app.services.catalog import get_product_row, summary_payload

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _entry_payload(db, entry: WatchlistEntry) -> dict:
    row = get_product_row(db, entry.product_id)
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "status": entry.status,
        "notes": entry.notes,
        "priority": entry.priority,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "product": summary_payload(db, row) if row else None,
    }


@router.get("")
def list_watchlist(
    user: CurrentUser,
    db: DbSession,
    status: str | None = None,
    sort: Literal["-updated_at", "-priority", "status"] = "-updated_at",
) -> dict:
    stmt = select(WatchlistEntry).where(WatchlistEntry.user_id == user.id)
    if status:
        stmt = stmt.where(WatchlistEntry.status == status)
    if sort == "-priority":
        stmt = stmt.order_by(WatchlistEntry.priority.is_(None), WatchlistEntry.priority.desc())
    elif sort == "status":
        stmt = stmt.order_by(WatchlistEntry.status, WatchlistEntry.updated_at.desc())
    else:
        stmt = stmt.order_by(WatchlistEntry.updated_at.desc())
    entries = db.execute(stmt).scalars().all()
    return {"data": [_entry_payload(db, entry) for entry in entries], "meta": {"total": len(entries)}}


@router.get("/export")
def export_watchlist(user: CurrentUser, db: DbSession) -> Response:
    entries = db.execute(
        select(WatchlistEntry)
        .where(WatchlistEntry.user_id == user.id)
        .order_by(WatchlistEntry.updated_at.desc())
    ).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "product",
            "category",
            "status",
            "priority",
            "opportunity_score",
            "growth_7d_pct",
            "growth_30d_pct",
            "competition_class",
            "notes",
            "updated_at",
        ]
    )
    for entry in entries:
        row = get_product_row(db, entry.product_id)
        if row is None:
            continue
        payload = summary_payload(db, row)
        writer.writerow(
            [
                payload["name"],
                (payload["category"] or {}).get("name"),
                entry.status,
                entry.priority,
                payload["opportunity_score"],
                payload["growth"]["d7"]["pct"],
                payload["growth"]["d30"]["pct"],
                payload["competition_class"],
                (entry.notes or "").replace("\n", " "),
                entry.updated_at.isoformat(),
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="trendscope-watchlist.csv"'},
    )


@router.post("", status_code=201)
def add_to_watchlist(payload: WatchlistCreate, user: WriteUser, db: DbSession) -> dict:
    if get_product_row(db, payload.product_id) is None:
        raise ApiError(404, "NOT_FOUND", "Product not found.")
    existing = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.id,
            WatchlistEntry.product_id == payload.product_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "CONFLICT", "Product is already on your watchlist.")
    entry = WatchlistEntry(
        user_id=user.id,
        product_id=payload.product_id,
        status=payload.status,
        notes=payload.notes,
        priority=payload.priority,
    )
    db.add(entry)
    db.commit()
    return _entry_payload(db, entry)


@router.patch("/{entry_id}")
def update_watchlist(
    entry_id: UUID, payload: WatchlistUpdate, user: WriteUser, db: DbSession
) -> dict:
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Watchlist entry not found.")
    if payload.status is not None:
        entry.status = payload.status
    # An explicit null clears notes or priority; an omitted field leaves it alone.
    if "notes" in payload.model_fields_set:
        entry.notes = payload.notes
    if "priority" in payload.model_fields_set:
        entry.priority = payload.priority
    entry.updated_at = utcnow()
    db.commit()
    return _entry_payload(db, entry)


@router.delete("/{entry_id}", status_code=204)
def remove_from_watchlist(entry_id: UUID, user: WriteUser, db: DbSession) -> Response:
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Watchlist entry not found.")
    db.delete(entry)
    db.commit()
    return Response(status_code=204)


@router.post("/compare")
def compare(payload: dict, user: CurrentUser, db: DbSession) -> dict:
    ids = payload.get("product_ids") or []
    if not (2 <= len(ids) <= 5):
        raise ApiError(422, "VALIDATION_ERROR", "Provide between 2 and 5 product_ids.")
    items = []
    for identifier in ids:
        row = get_product_row(db, identifier)
        if row is None:
            raise ApiError(404, "NOT_FOUND", f"Product not found: {identifier}")
        items.append(summary_payload(db, row))
    return {
        "data": items,
        "disclaimer": "Comparison surfaces available evidence only; unavailable components are null, not zero.",
    }
