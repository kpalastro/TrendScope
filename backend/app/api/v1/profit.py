"""GST-aware profit calculator and saved scenarios."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.core.errors import ApiError
from app.models import Product, ProfitScenario
from app.schemas import (
    ProfitInputs,
    ProfitScenarioCreate,
    ProfitScenarioPatch,
)
from app.services import audit
from app.services.profit import (
    ASSUMPTIONS_VERSION,
    DEFAULTS,
    DISCLAIMER,
    ProfitInputError,
    calculate,
)

router = APIRouter(prefix="/profit", tags=["profit"])


def _calculate(inputs: ProfitInputs) -> dict:
    try:
        return calculate(inputs.model_dump())
    except ProfitInputError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc


def _scenario_payload(entry: ProfitScenario) -> dict:
    stored = entry.outputs or {}
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "name": entry.name,
        "currency": entry.currency,
        "assumptions_version": entry.assumptions_version,
        "inputs": entry.inputs or {},
        "outputs": stored.get("outputs", stored),
        "warnings": stored.get("warnings", []),
        "disclaimer": stored.get("disclaimer", DISCLAIMER),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _get_owned_scenario(db, scenario_id: UUID, user) -> ProfitScenario:
    entry = db.get(ProfitScenario, scenario_id)
    if entry is None:
        raise ApiError(404, "NOT_FOUND", "Profit scenario not found.")
    if entry.user_id != user.id and user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "This scenario belongs to another user.")
    return entry


@router.post("/calculate")
def calculate_profit(payload: ProfitInputs, user: CurrentUser) -> dict:
    """Stateless calculation. Nothing is written."""

    return _calculate(payload)


@router.get("/assumptions")
def get_assumptions(user: CurrentUser) -> dict:
    return {
        "assumptions_version": ASSUMPTIONS_VERSION,
        "defaults": DEFAULTS,
        "notes": [
            "Amounts are decimal strings in the chosen currency.",
            "GST is 10% for Australia; confirm the rate and whether the supplier is registered.",
            "Advertising is reported separately as the break-even ad cost and then deducted "
            "for profit per order.",
        ],
        "disclaimer": DISCLAIMER,
    }


@router.get("/scenarios")
def list_scenarios(
    user: CurrentUser,
    db: DbSession,
    product_id: UUID | None = None,
) -> dict:
    stmt = select(ProfitScenario).where(ProfitScenario.user_id == user.id)
    if product_id is not None:
        stmt = stmt.where(ProfitScenario.product_id == product_id)
    rows = db.execute(stmt.order_by(ProfitScenario.updated_at.desc())).scalars().all()
    return {"data": [_scenario_payload(row) for row in rows]}


@router.post("/scenarios", status_code=201)
def create_scenario(
    payload: ProfitScenarioCreate,
    request: Request,
    user: WriteUser,
    db: DbSession,
) -> dict:
    if payload.product_id is not None and db.get(Product, payload.product_id) is None:
        raise ApiError(404, "NOT_FOUND", "Product not found.")
    calc = _calculate(payload.inputs)
    entry = ProfitScenario(
        product_id=payload.product_id,
        user_id=user.id,
        name=payload.name,
        currency=payload.inputs.currency.upper(),
        inputs=calc["inputs"],
        outputs={
            "outputs": calc["outputs"],
            "warnings": calc["warnings"],
            "disclaimer": calc["disclaimer"],
        },
        assumptions_version=calc["assumptions_version"],
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    audit.record(
        db,
        action="profit_scenario.create",
        entity_type="profit_scenario",
        entity_id=entry.id,
        user=user,
        request=request,
        changes={"name": entry.name, "product_id": payload.product_id},
    )
    return _scenario_payload(entry)


@router.patch("/scenarios/{scenario_id}")
def update_scenario(
    scenario_id: UUID,
    payload: ProfitScenarioPatch,
    request: Request,
    user: WriteUser,
    db: DbSession,
) -> dict:
    entry = _get_owned_scenario(db, scenario_id, user)
    before = {"name": entry.name, "product_id": str(entry.product_id) if entry.product_id else None}
    if payload.product_id is not None:
        if db.get(Product, payload.product_id) is None:
            raise ApiError(404, "NOT_FOUND", "Product not found.")
        entry.product_id = payload.product_id
    if payload.name is not None:
        entry.name = payload.name
    if payload.inputs is not None:
        calc = _calculate(payload.inputs)
        entry.inputs = calc["inputs"]
        entry.outputs = {
            "outputs": calc["outputs"],
            "warnings": calc["warnings"],
            "disclaimer": calc["disclaimer"],
        }
        entry.assumptions_version = calc["assumptions_version"]
        entry.currency = payload.inputs.currency.upper()
    entry.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    audit.record(
        db,
        action="profit_scenario.update",
        entity_type="profit_scenario",
        entity_id=entry.id,
        user=user,
        request=request,
        changes={"before": before, "after": {"name": entry.name}},
    )
    return _scenario_payload(entry)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: UUID,
    request: Request,
    user: WriteUser,
    db: DbSession,
) -> Response:
    entry = _get_owned_scenario(db, scenario_id, user)
    name = entry.name
    db.delete(entry)
    db.commit()
    audit.record(
        db,
        action="profit_scenario.delete",
        entity_type="profit_scenario",
        entity_id=scenario_id,
        user=user,
        request=request,
        changes={"name": name},
    )
    return Response(status_code=204)
