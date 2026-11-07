"""Slug allocation that stays unique in the catalogue."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product
from app.services.normalise import slugify


def unique_external_id(db: Session, source_id, base: str) -> str:
    """Return a provider-scoped external id that is free in ``products``.

    ``products`` is unique on ``(source_id, external_id)`` across every status, so
    a slug-only id can collide with an archived product or another name that
    slugifies identically. Suffix the base until it is unused.
    """
    candidate = base
    suffix = 2
    while (
        db.execute(
            select(Product.id).where(
                Product.source_id == source_id,
                Product.external_id == candidate,
            )
        ).first()
        is not None
    ):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def unique_product_slug(db: Session, base: str, fallback: str | None = None) -> str:
    candidate = slugify(base)
    for suffix in range(0, 50):
        slug = candidate if suffix == 0 else f"{candidate}-{suffix + 1}"
        found = db.execute(select(Product.id).where(Product.slug == slug)).first()
        if found is None:
            return slug
    return slugify(f"{base}-{fallback or ''}", 200)
