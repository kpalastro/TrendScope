from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.errors import ApiError
from app.models import Category, Product
from app.services.catalog import category_counts
from app.services.presenters import category_payload
from app.services.normalise import slugify

router = APIRouter(prefix="/categories", tags=["categories"])


def _flat(db, only_active: bool = True) -> list[Category]:
    stmt = select(Category).order_by(Category.path)
    if only_active:
        stmt = stmt.where(Category.is_active.is_(True))
    return list(db.execute(stmt).scalars())


@router.get("")
def list_categories(user: CurrentUser, db: DbSession, tree: bool = False) -> dict:
    categories = _flat(db)
    counts = category_counts(db)
    if not tree:
        return {
            "data": [
                category_payload(category, counts.get(category.id, 0))
                for category in categories
            ]
        }

    nodes = {
        category.id: {
            **category_payload(category, counts.get(category.id, 0)),
            "children": [],
        }
        for category in categories
    }
    roots = []
    for category in categories:
        node = nodes[category.id]
        parent = nodes.get(category.parent_id)
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)
    return {"data": roots}


@router.post("", status_code=201)
def create_category(payload: dict, user: AdminUser, db: DbSession) -> dict:
    name = str(payload.get("name", "")).strip()
    if len(name) < 2:
        raise ApiError(422, "VALIDATION_ERROR", "name is required")
    slug = slugify(payload.get("slug") or name)
    if db.execute(select(Category.id).where(Category.slug == slug)).first():
        raise ApiError(409, "CONFLICT", "A category with this slug already exists.")
    parent = None
    if payload.get("parent_id"):
        try:
            parent_id = UUID(str(payload["parent_id"]))
        except (ValueError, AttributeError, TypeError):
            raise ApiError(422, "VALIDATION_ERROR", "parent_id must be a UUID.") from None
        # Raw dict payloads arrive as strings; the Uuid column needs a real UUID
        # on SQLite, which otherwise fails with an AttributeError and a 500.
        parent = db.get(Category, parent_id)
        if parent is None:
            raise ApiError(422, "VALIDATION_ERROR", "Unknown parent_id.")
    category = Category(
        name=name[:160],
        slug=slug[:160],
        parent_id=parent.id if parent else None,
        path=f"{parent.path}/{slug}" if parent else slug,
        level=(parent.level + 1) if parent else 0,
    )
    db.add(category)
    db.commit()
    return category_payload(category, 0)


@router.patch("/{category_id}")
def patch_category(category_id: UUID, payload: dict, user: AdminUser, db: DbSession) -> dict:
    category = db.get(Category, category_id)
    if category is None:
        raise ApiError(404, "NOT_FOUND", "Category not found.")
    if "name" in payload and payload["name"]:
        category.name = str(payload["name"])[:160]
    if payload.get("is_active") is not None:
        category.is_active = bool(payload["is_active"])
    db.commit()
    return category_payload(category)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: UUID, user: AdminUser, db: DbSession):
    from fastapi import Response

    category = db.get(Category, category_id)
    if category is None:
        raise ApiError(404, "NOT_FOUND", "Category not found.")
    count = db.execute(
        select(Product.id).where(Product.category_id == category.id).limit(1)
    ).first()
    children = db.execute(
        select(Category.id).where(Category.parent_id == category.id).limit(1)
    ).first()
    if count or children:
        raise ApiError(
            422, "BUSINESS_RULE_VIOLATION", "Only an empty category can be deleted."
        )
    db.delete(category)
    db.commit()
    return Response(status_code=204)
