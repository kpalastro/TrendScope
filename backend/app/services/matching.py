"""Product identity, duplicate detection and non-destructive merges.

Three levels of evidence are used, strongest first:

1. A shared identifier (GTIN/UPC/EAN/ASIN/supplier SKU). This is deterministic,
   so it merges or refuses automatically rather than asking a human.
2. A shared normalised alias or exact normalised name.
3. A fuzzy name similarity, which only ever produces a *pending* match for an
   admin to approve or reject. Nothing is merged on a guess.

Merges are non-destructive: the source product keeps its row, is marked
``merged`` and points at the survivor through ``merged_into_product_id``. Raw
observations move to the survivor except where the survivor already holds the
same natural key, in which case the duplicate row is removed — the survivor's
history is never overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    IDENTIFIER_SCHEMES,
    MATCH_STATUSES,
    MarketplaceListing,
    OpportunityScore,
    Product,
    ProductAlias,
    ProductIdentifier,
    ProductKeyword,
    ProductMatch,
    ProductMetric,
    ProfitScenario,
    SupplierProduct,
    TrendObservation,
    WatchlistEntry,
    utcnow,
)
from app.services.normalise import normalise_name

FUZZY_THRESHOLD = 0.72
FUZZY_LIMIT = 5
MIN_FUZZY_LENGTH = 4


class IdentityError(ValueError):
    """An identifier/alias payload cannot be stored as supplied."""


class IdentifierConflict(IdentityError):
    """The identifier already belongs to a different product."""

    def __init__(self, scheme: str, value: str, product_id: UUID) -> None:
        super().__init__(
            f"{scheme}:{value} already belongs to product {product_id}."
        )
        self.scheme = scheme
        self.value = value
        self.product_id = product_id


@dataclass
class MergeSummary:
    source_id: UUID
    target_id: UUID
    moved: dict[str, int]
    dropped: dict[str, int]

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "moved": self.moved,
            "dropped": self.dropped,
        }


def normalise_identifier_value(value: object) -> str:
    """Strip separators and case so `ABC-123`, `abc123` and `ABC 123` agree."""

    text = str(value or "").strip()
    cleaned = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    return cleaned[:200]


def validate_identifier(scheme: str, value: object) -> tuple[str, str]:
    key = str(scheme or "").strip().lower()
    if key not in IDENTIFIER_SCHEMES:
        raise IdentityError(
            f"Unknown identifier scheme '{scheme}'. "
            f"Use one of: {', '.join(IDENTIFIER_SCHEMES)}."
        )
    cleaned = normalise_identifier_value(value)
    if not cleaned:
        raise IdentityError(f"Identifier value for '{key}' is empty.")
    if key in {"gtin", "upc", "ean", "isbn"} and not cleaned.isdigit():
        raise IdentityError(f"Identifier '{key}' must contain digits only.")
    return key, cleaned


def find_by_identifier(
    db: Session, identifiers: dict[str, object]
) -> Product | None:
    """Return the product that owns any of the supplied identifiers."""

    for scheme, value in (identifiers or {}).items():
        try:
            key, cleaned = validate_identifier(scheme, value)
        except IdentityError:
            continue
        row = db.execute(
            select(ProductIdentifier).where(
                ProductIdentifier.scheme == key,
                ProductIdentifier.value == cleaned,
            )
        ).scalar_one_or_none()
        if row is not None:
            return db.get(Product, row.product_id)
    return None


def add_identifiers(
    db: Session,
    product: Product,
    identifiers: dict[str, object],
    *,
    source_id: UUID | None = None,
) -> None:
    for scheme, value in (identifiers or {}).items():
        key, cleaned = validate_identifier(scheme, value)
        existing = db.execute(
            select(ProductIdentifier).where(
                ProductIdentifier.scheme == key,
                ProductIdentifier.value == cleaned,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.product_id != product.id:
                raise IdentifierConflict(key, cleaned, existing.product_id)
            continue
        db.add(
            ProductIdentifier(
                product_id=product.id,
                scheme=key,
                value=cleaned,
                source_id=source_id,
            )
        )
    db.flush()


def add_aliases(
    db: Session,
    product: Product,
    aliases: list[str],
    *,
    source_id: UUID | None = None,
) -> None:
    seen: set[str] = set()
    for alias in aliases or []:
        cleaned = str(alias or "").strip()
        if len(cleaned) < 2:
            continue
        normalised = normalise_name(cleaned)
        if not normalised or normalised in seen or normalised == product.normalised_name:
            continue
        seen.add(normalised)
        exists = db.execute(
            select(ProductAlias.id).where(
                ProductAlias.product_id == product.id,
                ProductAlias.normalised_alias == normalised,
            )
        ).first()
        if exists is None:
            db.add(
                ProductAlias(
                    product_id=product.id,
                    alias=cleaned[:300],
                    normalised_alias=normalised[:300],
                    source_id=source_id,
                )
            )
    db.flush()


def _similarity(normalised_a: str, normalised_b: str) -> float:
    direct = SequenceMatcher(None, normalised_a, normalised_b).ratio()
    # A second pass over alphabetically sorted tokens catches reordered names
    # such as "Tray Kitchen Silicone" versus "Silicone Kitchen Tray".
    sorted_a = " ".join(sorted(normalised_a.split()))
    sorted_b = " ".join(sorted(normalised_b.split()))
    reordered = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    return max(direct, reordered)


def _canonical_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if str(a) <= str(b) else (b, a)


def record_match(
    db: Session,
    product_a_id: UUID,
    product_b_id: UUID,
    method: str,
    similarity: float | None,
) -> ProductMatch | None:
    if product_a_id == product_b_id:
        return None
    if method not in {"identifier", "alias", "name_exact", "fuzzy"}:
        raise ValueError(f"Unknown match method '{method}'.")
    first, second = _canonical_pair(product_a_id, product_b_id)
    existing = db.execute(
        select(ProductMatch).where(
            ProductMatch.product_a_id == first,
            ProductMatch.product_b_id == second,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    match = ProductMatch(
        product_a_id=first,
        product_b_id=second,
        method=method,
        similarity=round(float(similarity), 3) if similarity is not None else None,
        status="pending",
    )
    db.add(match)
    db.flush()
    return match


def find_exact_duplicate(db: Session, product: Product) -> Product | None:
    """Exact normalised-name or alias match, excluding the product itself."""

    candidates = db.execute(
        select(Product).where(
            Product.normalised_name == product.normalised_name,
            Product.id != product.id,
            Product.status.in_(("active", "discovered")),
        )
    ).scalars().all()
    if candidates:
        return candidates[0]
    alias = db.execute(
        select(ProductAlias).where(
            ProductAlias.normalised_alias == product.normalised_name,
            ProductAlias.product_id != product.id,
        )
    ).scalar_one_or_none()
    return db.get(Product, alias.product_id) if alias is not None else None


def queue_fuzzy_candidates(db: Session, product: Product) -> list[ProductMatch]:
    """Queue up to ``FUZZY_LIMIT`` plausible duplicates for review."""

    reference = product.normalised_name
    if len(reference) < MIN_FUZZY_LENGTH:
        return []

    prefix = reference[:3]
    stmt = (
        select(Product)
        .where(
            Product.id != product.id,
            Product.status.in_(("active", "discovered")),
            Product.normalised_name.like(f"{prefix}%"),
        )
        .limit(500)
    )
    candidates = db.execute(stmt).scalars().all()
    if product.brand:
        same_brand = db.execute(
            select(Product)
            .where(
                Product.id != product.id,
                Product.status.in_(("active", "discovered")),
                Product.brand == product.brand,
            )
            .limit(100)
        ).scalars().all()
        seen = {item.id for item in candidates}
        candidates.extend(item for item in same_brand if item.id not in seen)

    scored = []
    for candidate in candidates:
        ratio = _similarity(reference, candidate.normalised_name)
        if ratio >= FUZZY_THRESHOLD:
            scored.append((ratio, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    matches: list[ProductMatch] = []
    for ratio, candidate in scored[:FUZZY_LIMIT]:
        match = record_match(db, product.id, candidate.id, "fuzzy", ratio)
        if match is not None:
            matches.append(match)
    return matches


def _reassign_observations(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_keys = {
        (row.source_id, row.observation_date, row.metric_name, row.granularity, row.country)
        for row in db.execute(
            select(TrendObservation).where(TrendObservation.product_id == target_id)
        ).scalars()
    }
    for row in db.execute(
        select(TrendObservation).where(TrendObservation.product_id == source_id)
    ).scalars():
        key = (row.source_id, row.observation_date, row.metric_name, row.granularity, row.country)
        if key in target_keys:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_keys.add(key)
            moved += 1
    return moved, dropped


def _reassign_metrics(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_dates = set(
        db.execute(
            select(ProductMetric.as_of_date).where(ProductMetric.product_id == target_id)
        ).scalars()
    )
    for row in db.execute(
        select(ProductMetric).where(ProductMetric.product_id == source_id)
    ).scalars():
        if row.as_of_date in target_dates:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_dates.add(row.as_of_date)
            moved += 1
    return moved, dropped


def _reassign_scores(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_keys = {
        (row.scoring_profile_id, row.calculated_on)
        for row in db.execute(
            select(OpportunityScore).where(OpportunityScore.product_id == target_id)
        ).scalars()
    }
    for row in db.execute(
        select(OpportunityScore).where(OpportunityScore.product_id == source_id)
    ).scalars():
        key = (row.scoring_profile_id, row.calculated_on)
        if key in target_keys:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_keys.add(key)
            moved += 1
    return moved, dropped


def _reassign_keywords(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_keys = {
        (row.normalised_keyword, row.source_id)
        for row in db.execute(
            select(ProductKeyword).where(ProductKeyword.product_id == target_id)
        ).scalars()
    }
    for row in db.execute(
        select(ProductKeyword).where(ProductKeyword.product_id == source_id)
    ).scalars():
        key = (row.normalised_keyword, row.source_id)
        if key in target_keys:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_keys.add(key)
            moved += 1
    return moved, dropped


def _reassign_identifiers(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_keys = {
        (row.scheme, row.value)
        for row in db.execute(
            select(ProductIdentifier).where(ProductIdentifier.product_id == target_id)
        ).scalars()
    }
    for row in db.execute(
        select(ProductIdentifier).where(ProductIdentifier.product_id == source_id)
    ).scalars():
        key = (row.scheme, row.value)
        if key in target_keys:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_keys.add(key)
            moved += 1
    return moved, dropped


def _reassign_aliases(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_keys = set(
        db.execute(
            select(ProductAlias.normalised_alias).where(ProductAlias.product_id == target_id)
        ).scalars()
    )
    for row in db.execute(
        select(ProductAlias).where(ProductAlias.product_id == source_id)
    ).scalars():
        if row.normalised_alias in target_keys:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_keys.add(row.normalised_alias)
            moved += 1
    return moved, dropped


def _reassign_watchlist(db: Session, source_id: UUID, target_id: UUID) -> tuple[int, int]:
    moved = dropped = 0
    target_users = set(
        db.execute(
            select(WatchlistEntry.user_id).where(WatchlistEntry.product_id == target_id)
        ).scalars()
    )
    for row in db.execute(
        select(WatchlistEntry).where(WatchlistEntry.product_id == source_id)
    ).scalars():
        if row.user_id in target_users:
            db.delete(row)
            dropped += 1
        else:
            row.product_id = target_id
            target_users.add(row.user_id)
            moved += 1
    return moved, dropped


def _reassign_simple(db: Session, model, source_id: UUID, target_id: UUID) -> int:
    result = db.execute(
        update(model).where(model.product_id == source_id).values(product_id=target_id)
    )
    return int(result.rowcount or 0)


def resolve_root(db: Session, product: Product) -> Product:
    """Follow ``merged_into_product_id`` so a merge never points at a tombstone."""

    seen: set[UUID] = set()
    current = product
    while current.merged_into_product_id is not None:
        if current.id in seen:
            raise IdentityError("Merge chain contains a cycle.")
        seen.add(current.id)
        successor = db.get(Product, current.merged_into_product_id)
        if successor is None:
            break
        current = successor
    return current


def _merge_fields(target: Product, source: Product) -> None:
    for field in ("brand", "category_id", "description", "image_url", "model", "external_id"):
        if getattr(target, field) in (None, "") and getattr(source, field) not in (None, ""):
            setattr(target, field, getattr(source, field))
    merged_attributes = dict(source.attributes or {})
    merged_attributes.update(target.attributes or {})
    target.attributes = merged_attributes
    if target.is_synthetic and not source.is_synthetic:
        target.is_synthetic = False
    target.last_seen_at = utcnow()
    target.updated_at = utcnow()


def merge_products(
    db: Session,
    source: Product,
    target: Product,
    *,
    method: str = "manual",
    reviewed_by: UUID | None = None,
) -> MergeSummary:
    """Move every child row from ``source`` to ``target`` and tombstone source."""

    if source.id == target.id:
        raise IdentityError("A product cannot be merged into itself.")
    target = resolve_root(db, target)
    if target.id == source.id:
        raise IdentityError("A product cannot be merged into itself.")

    # Prevent a cycle: the survivor must not already have been merged into source.
    if resolve_root(db, target).id == source.id:
        raise IdentityError("This merge would create a cycle.")

    moved: dict[str, int] = {}
    dropped: dict[str, int] = {}

    moved["observations"], dropped["observations"] = _reassign_observations(
        db, source.id, target.id
    )
    moved["metrics"], dropped["metrics"] = _reassign_metrics(db, source.id, target.id)
    moved["scores"], dropped["scores"] = _reassign_scores(db, source.id, target.id)
    moved["keywords"], dropped["keywords"] = _reassign_keywords(db, source.id, target.id)
    moved["identifiers"], dropped["identifiers"] = _reassign_identifiers(
        db, source.id, target.id
    )
    moved["aliases"], dropped["aliases"] = _reassign_aliases(db, source.id, target.id)
    moved["watchlist"], dropped["watchlist"] = _reassign_watchlist(db, source.id, target.id)
    moved["listings"] = _reassign_simple(db, MarketplaceListing, source.id, target.id)
    moved["supplier_offers"] = _reassign_simple(db, SupplierProduct, source.id, target.id)
    moved["profit_scenarios"] = _reassign_simple(db, ProfitScenario, source.id, target.id)

    _merge_fields(target, source)
    source.status = "merged"
    source.merged_into_product_id = target.id
    source.updated_at = utcnow()

    # Close pending review rows for this pair so the queue does not keep asking.
    pair_matches = db.execute(
        select(ProductMatch).where(
            ProductMatch.status == "pending",
            ProductMatch.product_a_id.in_((source.id, target.id)),
            ProductMatch.product_b_id.in_((source.id, target.id)),
        )
    ).scalars().all()
    for match in pair_matches:
        match.status = "merged"
        match.reviewed_by = reviewed_by
        match.reviewed_at = utcnow()

    db.flush()
    return MergeSummary(
        source_id=source.id,
        target_id=target.id,
        moved=moved,
        dropped=dropped,
    )


def recompute_after_merge(db: Session, target: Product, as_of: date | None = None) -> None:
    """Recompute metrics and score from the survivor's combined history."""

    from app.services.metrics import compute_product_metrics
    from app.services.scoring_service import compute_product_score, get_active_profile

    day = as_of or date.today()
    metric = compute_product_metrics(db, target, day)
    profile = get_active_profile(db)
    if profile is not None:
        compute_product_score(db, target, metric, profile, day)
    db.flush()


def match_status_allowed(value: str) -> str:
    if value not in MATCH_STATUSES:
        raise IdentityError(f"status must be one of {', '.join(MATCH_STATUSES)}")
    return value
