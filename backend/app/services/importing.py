"""Manual CSV import.

Rows are validated before anything is written. A row with an unknown category or
an unparseable price is rejected with a row number and a reason; it never
silently disappears. Duplicate names are merged into the existing product rather
than creating a second catalogue entry.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Category,
    DataSource,
    Product,
    ProductKeyword,
    ProductMetric,
    TrendObservation,
    utcnow,
)
from app.services.metrics import compute_product_metrics
from app.services.normalise import normalise_name, slugify
from app.services.scoring_service import compute_product_score, get_active_profile
from app.services.slugs import unique_external_id, unique_product_slug

TEMPLATE_COLUMNS = [
    "name",
    "category",
    "brand",
    "price",
    "keywords",
    "description",
    "image_url",
]


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    rejected: int = 0
    errors: list[dict] = field(default_factory=list)
    product_ids: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.rejected


def template_csv() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow(
        [
            "Silicone Kitchen Organisation Tray",
            "home-kitchen",
            "Aurora Home",
            "34.50",
            "kitchen;organiser;tray",
            "Optional description",
            "",
        ]
    )
    return buffer.getvalue()


def _category_lookup(db: Session) -> dict[str, Category]:
    lookup: dict[str, Category] = {}
    for category in db.execute(select(Category)).scalars():
        lookup[category.slug.lower()] = category
        lookup[category.name.lower()] = category
    return lookup


def _split_keywords(raw: str) -> list[str]:
    import re

    parts = [part.strip() for part in re.split(r"[;|,]", raw or "") if part.strip()]
    return parts[:10]


def _parse_price(raw: str) -> float | None:
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def import_csv(db: Session, source: DataSource, content: str) -> ImportResult:
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(content))

    # Materialise the rows before writing anything: csv.Error surfaces while the
    # reader is draining, and a half-applied file would leave the catalogue in a
    # state the operator cannot reconcile from the response.
    try:
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        raw_rows = list(reader)
    except csv.Error as exc:
        result.errors.append({"row": 0, "issue": f"Could not read CSV: {exc}"})
        result.rejected += 1
        return result

    if "name" not in headers:
        result.errors.append({"row": 0, "issue": "Missing required column: name"})
        result.rejected += 1
        return result

    categories = _category_lookup(db)
    seen_names: set[str] = set()
    active_profile = get_active_profile(db)

    for line_number, raw_row in enumerate(raw_rows, start=2):
        row = {
            (key or "").strip().lower(): (value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        name = row.get("name", "")
        if len(name) < 2:
            result.rejected += 1
            result.errors.append({"row": line_number, "issue": "name is required"})
            continue
        normalised = normalise_name(name)
        if not normalised or normalised in seen_names:
            result.rejected += 1
            result.errors.append(
                {"row": line_number, "issue": "duplicate name within this file"}
            )
            continue
        seen_names.add(normalised)

        category = None
        raw_category = row.get("category", "")
        if raw_category:
            category = categories.get(raw_category.lower()) or categories.get(
                slugify(raw_category)
            )
            if category is None:
                result.rejected += 1
                result.errors.append(
                    {"row": line_number, "issue": f"unknown category: {raw_category}"}
                )
                continue

        try:
            price = _parse_price(row.get("price", ""))
        except ValueError:
            result.rejected += 1
            result.errors.append({"row": line_number, "issue": "price is not a number"})
            continue
        if price is not None and price <= 0:
            result.rejected += 1
            result.errors.append({"row": line_number, "issue": "price must be greater than zero"})
            continue

        candidates = (
            db.execute(select(Product).where(Product.normalised_name == normalised))
            .scalars()
            .all()
        )
        product = next((item for item in candidates if item.status == "active"), None)
        archived = next((item for item in candidates if item.status == "archived"), None)

        if product is None and archived is not None:
            # Re-importing a product that was archived re-activates the existing
            # row: it already owns the external id, slug and raw history.
            product = archived
            product.status = "active"
            product.is_manual = True
            result.updated += 1
        elif product is not None:
            result.updated += 1
        else:
            product = Product(
                external_id=unique_external_id(db, source.id, f"csv-{slugify(name)}"),
                source_id=source.id,
                name=name[:300],
                normalised_name=normalised,
                slug=unique_product_slug(db, name, normalised),
                description=row.get("description") or None,
                category_id=category.id if category else None,
                brand=(row.get("brand") or None),
                image_url=(row.get("image_url") or None),
                country="AU",
                currency="AUD",
                status="active",
                is_manual=True,
                is_synthetic=False,
            )
            db.add(product)
            db.flush()
            result.created += 1

        product.last_seen_at = utcnow()
        if category and not product.category_id:
            product.category_id = category.id
        if brand := row.get("brand"):
            product.brand = brand[:160]
        result.product_ids.append(product.id)

        seen_keywords: set[str] = set()
        for keyword in _split_keywords(row.get("keywords", "")):
            normalised_keyword = (normalise_name(keyword) or keyword.lower())[:200]
            if not normalised_keyword or normalised_keyword in seen_keywords:
                continue
            seen_keywords.add(normalised_keyword)
            exists = db.execute(
                select(ProductKeyword.id).where(
                    ProductKeyword.product_id == product.id,
                    ProductKeyword.normalised_keyword == normalised_keyword,
                    ProductKeyword.source_id == source.id,
                )
            ).first()
            if exists is None:
                db.add(
                    ProductKeyword(
                        product_id=product.id,
                        keyword=keyword[:200],
                        normalised_keyword=normalised_keyword,
                        source_id=source.id,
                    )
                )

        if price is not None:
            today = date.today()
            observation = db.execute(
                select(TrendObservation).where(
                    TrendObservation.product_id == product.id,
                    TrendObservation.source_id == source.id,
                    TrendObservation.observation_date == today,
                    TrendObservation.metric_name == "marketplace_avg_price",
                    TrendObservation.granularity == "daily",
                    TrendObservation.country == "AU",
                )
            ).scalar_one_or_none()
            if observation is None:
                db.add(
                    TrendObservation(
                        product_id=product.id,
                        source_id=source.id,
                        observation_date=today,
                        granularity="daily",
                        metric_name="marketplace_avg_price",
                        country="AU",
                        unit="aud",
                        currency="AUD",
                        metric_value=price,
                        is_synthetic=False,
                        meta={"origin": "csv_import"},
                    )
                )
            # An existing same-day observation is left untouched: raw history is
            # append-only, and the natural key does not permit a second row for
            # the same (product, source, date, metric).

    db.flush()

    today = date.today()
    for product_id in result.product_ids:
        product = db.get(Product, product_id)
        if product is None:
            continue
        metric = compute_product_metrics(db, product, today)
        if isinstance(metric, ProductMetric) and active_profile is not None:
            compute_product_score(db, product, metric, active_profile, today)

    db.commit()
    return result
