# 03 — API Contract

**Base URL:** `/api/v1`
**Format:** JSON (`application/json; charset=utf-8`); timestamps ISO 8601 UTC (`2026-11-07T04:12:00Z`)
**Contract of record:** this document, implemented as Pydantic schemas and published at
`/api/v1/openapi.json`. The frontend's TypeScript types are generated from the OpenAPI document in CI.
**Status:** Proposed v1. Breaking changes require a new version prefix, not an edit.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Field names | `snake_case` everywhere (DB, JSON, generated TS types) |
| IDs | UUID strings |
| Money | decimal **strings** (`"89.95"`), never JSON floats, plus a `currency` field |
| Percentages | numbers in percent units (`42.1` = +42.1%), `null` when not computable |
| Missing values | `null` + a reason field; never `0`, `"N/A"` or an omitted key |
| Enums | lowercase snake_case strings; unknown future values must be tolerated by clients |
| Empty collections | `[]`, never `null` |
| Date filters | `YYYY-MM-DD`; `from` inclusive, `to` inclusive |
| Sorting | `?sort=-score` (`-` = descending); whitelisted per endpoint |
| Filtering | flat query params; repeated params for multi-value (`?competition=low&competition=moderate`) |
| Partial responses | `?fields=id,name,score` where documented |
| Casing of query params | same as fields (`min_score`, `category_id`) |

### 1.1 Standard headers

| Header | Direction | Purpose |
|---|---|---|
| `Authorization: Bearer <jwt>` | request | access token |
| `X-Request-Id` | both | client may supply; server always returns one |
| `Idempotency-Key` | request | required on `POST` endpoints that trigger jobs or imports |
| `If-None-Match` | request | `ETag` support on product detail and dashboard |
| `X-RateLimit-Remaining` / `-Reset` | response | rate-limit state |
| `Retry-After` | response | on `429`/`503` |

---

## 2. Authentication and authorisation

- `POST /auth/login` returns an access token (default 480 min, `ACCESS_TOKEN_MINUTES`) and sets an
  opaque rotating refresh token in an `HttpOnly; SameSite=Lax` cookie (`Secure` outside
  development). The cookie is scoped to `/` so it also covers the Next.js rewrite at
  `/api/backend/auth/*`; only the server sees its value.
- Refresh tokens are single-use. `POST /auth/refresh` rotates the cookie and returns a new access
  token; replaying an already-rotated token is treated as theft and revokes every active session for
  that user.
- Access tokens are JWTs (`sub`, `role`, `exp`, `jti`), HS256 in dev and RS256-ready in config.
- Roles: `admin` (sources, scoring profiles, merges, users), `analyst` (all research, watchlist,
  reports), `viewer` (read-only).
- All endpoints except `/auth/login`, `/auth/refresh`, `/health` require a token.
- `POST /auth/logout` revokes the presented refresh token, clears the cookie and is idempotent.
- Every mutating request is written to `audit_logs` with actor, entity, diff and `request_id`.
- Failed logins are rate-limited per IP and per email (5/min, exponential lockout).

---

## 3. Error model

RFC 7807-inspired, one envelope for every non-2xx response:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "weights.demand", "issue": "must be between 0 and 1"}
    ],
    "request_id": "req_01J9Z6F3Q2"
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | malformed body/params |
| 401 | `UNAUTHENTICATED` | missing/expired/invalid token |
| 403 | `FORBIDDEN` | role not permitted |
| 404 | `NOT_FOUND` | unknown id or resource not visible |
| 409 | `CONFLICT` | duplicate watchlist entry, duplicate identifier, profile already immutable |
| 422 | `BUSINESS_RULE_VIOLATION` | e.g. deleting a seeded category, merging a product into itself |
| 429 | `RATE_LIMITED` | with `Retry-After` |
| 502 | `PROVIDER_ERROR` | upstream data provider failed during a synchronous call (connection test, report render) |
| 503 | `SOURCE_UNAVAILABLE` | provider disabled/unconfigured |
| 501 | `NOT_IMPLEMENTED` | feature gated to a later phase (e.g. assistant when disabled) |
| 500 | `INTERNAL_ERROR` | unexpected; `request_id` is the only diagnostic returned |

Errors never include stack traces, SQL, provider payloads or secret values.

---

## 4. Pagination and envelopes

Offset pagination for catalogue surfaces:

```json
{
  "data": [ ... ],
  "meta": {
    "page": 1,
    "per_page": 25,
    "total": 1432,
    "total_pages": 58,
    "generated_at": "2026-11-07T04:12:00Z",
    "filters_applied": {"country": "AU", "competition": ["low"]}
  }
}
```

- `page` default 1; `per_page` default 25, max 100. Out-of-range page returns an empty `data` array,
  not an error.
- Time-series endpoints use cursor pagination: `?cursor=<opaque>&limit=365`, response meta contains
  `next_cursor` (null at the end).
- Single-resource responses are the object itself (no envelope).

---

## 5. Shared schemas

### 5.1 `DataQuality`

Present on every product and score payload. This object is the contract for PRD §2's "never present
estimates as verified data".

```json
{
  "coverage_pct": 78.5,
  "confidence": 0.71,
  "synthetic": false,
  "synthetic_share": 0.0,
  "sources": ["google_trends", "ebay_au"],
  "missing_components": ["social"],
  "last_updated": "2026-11-07T02:00:00Z",
  "warnings": ["social unavailable: no social source configured"]
}
```

### 5.2 `ScoreBreakdown`

```json
{
  "score": 72.4,
  "score_raw": 81.2,
  "classification": "strong",
  "coverage_pct": 78.5,
  "confidence": 0.71,
  "components": {
    "demand":        {"score": 88.0, "weight": 0.25, "status": "available", "raw": {"growth_30d_pct": 42.1}},
    "marketplace":   {"score": 74.0, "weight": 0.25, "status": "available", "raw": {"listing_count": 312}},
    "social":        {"score": null, "weight": 0.15, "status": "unavailable", "reason": "no source"},
    "competition":   {"score": 68.0, "weight": 0.15, "status": "available", "raw": {"index": 32.0}},
    "profitability": {"score": 61.0, "weight": 0.15, "status": "estimated", "raw": {"margin_pct": 27.5}},
    "seasonal":      {"score": null, "weight": 0.05, "status": "insufficient_history", "reason": "< 12 months"}
  },
  "profile": {"id": "…", "name": "Default AU", "version": 3},
  "calculated_on": "2026-11-07"
}
```

`status` ∈ `available | estimated | unavailable | insufficient_history | stale`.

### 5.3 `Growth`

```json
{"pct": 42.1, "reason": "ok", "window_days": 30, "baseline_mean": 18.4, "current_mean": 26.1}
```

or

```json
{"pct": null, "reason": "insufficient_baseline", "window_days": 7}
```

### 5.4 `ProductSummary`

```json
{
  "id": "6f1c…",
  "name": "Silicone Kitchen Organisation Tray",
  "slug": "silicone-kitchen-organisation-tray",
  "category": {"id": "…", "name": "Kitchen Storage", "path": "home-kitchen/kitchen-storage"},
  "brand": "Generic",
  "image_url": "https://…",
  "country": "AU",
  "currency": "AUD",
  "price_range": {"min": "24.95", "max": "49.95", "market_avg": "34.50"},
  "opportunity_score": 72.4,
  "classification": "strong",
  "growth": {"d7": {...}, "d30": {...}, "d90": {...}},
  "competition_class": "moderate",
  "trend_direction": "rising",
  "estimated_margin_pct": 27.5,
  "supplier_available": true,
  "data_quality": { ... },
  "first_seen_at": "2026-10-21T00:00:00Z",
  "updated_at": "2026-11-07T02:00:00Z"
}
```

### 5.5 `ProductDetail`

`ProductSummary` plus `description`, `keywords[]`, `model`, `attributes{}`, `identifiers[]`,
`score_breakdown`, `competition`, `listings[]`, `suppliers[]`, `price_history`, `trend_series`
(optional `?include=series`), `recent_scores[]`, `sources[]` with collection dates and
`disclaimer`.

### 5.6 `Job`

Returned by any `202 Accepted`:

```json
{
  "job": {
    "id": "b91f…",
    "type": "import.csv",
    "status": "queued",
    "progress": {"processed": 0, "total": null},
    "result_url": null,
    "error": null,
    "created_at": "2026-11-07T04:12:00Z",
    "poll_url": "/api/v1/jobs/b91f…"
  }
}
```

`status` ∈ `queued | running | succeeded | failed | cancelled`.

---

## 6. Endpoint catalogue

Legend: **A** admin · **N** analyst+ · **V** viewer+ · **P** public (no auth) · **F** phase-gated.

### 6.1 Auth

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/auth/login` | P | `{email, password}` → `{access_token, expires_in, user}` + refresh cookie |
| POST | `/auth/refresh` | P (cookie) | rotate refresh token, return new access token |
| POST | `/auth/logout` | V | revoke refresh token, clear cookie |
| GET | `/auth/me` | V | current user + permissions |

### 6.2 Dashboard

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/dashboard/summary` | V | KPI tiles + source health + last sync |
| GET | `/dashboard/widgets/{widget}` | V | one widget's data |
| GET | `/dashboard` | V | all widgets in one call (cached 60 s) |

`widget` ∈ `weekly_trending | monthly_trending | fastest_growing | emerging | low_competition |
seasonal | best_margins | recently_discovered`. Common params: `country=AU` (default), `limit`
(default 10, max 50), `synthetic=include|exclude` (default `include`, always labelled).

`/dashboard/summary` response:

```json
{
  "country": "AU",
  "products_monitored": 1284,
  "new_this_week": 96,
  "increasing_demand": 412,
  "declining_demand": 173,
  "high_opportunity": 88,
  "average_opportunity_score": 48.2,
  "data_sources": [
    {"provider_key": "google_trends", "status": "ok", "last_sync_at": "2026-11-07T02:00:00Z", "coverage_pct": 91.2},
    {"provider_key": "mock", "status": "ok", "synthetic": true}
  ],
  "last_sync_at": "2026-11-07T02:00:00Z",
  "generated_at": "2026-11-07T04:12:00Z"
}
```

### 6.3 Products and discovery

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/products` | V | explorer: search, filter, sort, paginate |
| POST | `/products` | N | manual product creation |
| GET | `/products/{id}` | V | detail (`?include=series,listings,suppliers`) |
| PATCH | `/products/{id}` | N | edit catalogue fields |
| DELETE | `/products/{id}` | A | archive (soft) |
| GET | `/products/{id}/trends` | V | observation series (separate series per `metric_name` + `metric_type`) |
| GET | `/products/{id}/observations` | V | provenance rows; filter by `metric_type` |
| POST | `/products/{id}/observations` | N | manual observation with full provenance; `409` on duplicate natural key |
| PATCH | `/products/{id}/observations/{observation_id}` | N | correct a manual/CSV row; appends a correction log |
| POST | `/products/{id}/suppliers` | N | record a supplier quote; creates the supplier/offer if new |
| PATCH | `/products/{id}/suppliers/{offer_id}` | N | update a quote; recomputes margin and recommendation |
| GET | `/products/{id}/metrics` | V | daily snapshots |
| GET | `/products/{id}/score` | V | latest + `?history=true` |
| GET | `/products/{id}/listings` | V | marketplace listings |
| GET | `/products/{id}/competition` | V | competition analysis |
| GET | `/products/{id}/suppliers` | V | supplier offers + landed-cost preview |
| GET | `/products/{id}/similar` | V | F (pgvector) |
| POST | `/products/{id}/merge` | A | `{into_product_id}` → merge + audit |
| GET | `/products/matches` | A | dedup review queue |
| POST | `/products/matches/{id}/resolve` | A | `{action: "merge" | "reject"}` |
| POST | `/products/import/csv` | N | multipart upload → 202 `Job` |
| GET | `/products/import/csv/template` | V | download template with required columns |
| POST | `/products/import/observations/csv` | N | bulk manual observations → 202; row-level errors |
| GET | `/products/import/observations/template` | V | observation CSV template |
| POST | `/products/discover` | N | run discovery connectors → 202 `Job` |

An observation row includes `provider_name`, `source_url`, `verification_status`, `data_quality`,
`collected_at`, `revision` and `updated_at`, plus a nested `attribution` block with the same
evidence. The natural key is `(product, source, observation_date, metric_name, granularity,
country)`: a repeated sync inserts nothing, while a changed value updates the existing row,
increments `revision` and keeps up to five earlier values in `metadata.previous_values`. The
immutable provider snapshot preserves the complete earlier payload.

`POST /products` accepts an optional `identifiers` map (`gtin`, `upc`, `ean`, `isbn`, `asin`,`ebay_item`, `supplier_sku`, `mpn`, `shopify_sku`) and `aliases`. Values are normalised and a value
already owned by another product returns `409`. New products are queued for fuzzy review rather
than merged automatically.

Merges are non-destructive: the source is tombstoned (`status: "merged"`, `merged_into_product_id`),
its observations, metrics, scores, keywords, identifiers, aliases and watchlist entries move to the
survivor, and rows that share a natural key with the survivor are dropped and counted. The older
product (`first_seen_at`) survives. `POST /products/matches/{id}/resolve` accepts `merge` or
`reject`; resolving the same match twice returns `409`. `GET /products/matches` accepts
`?status=pending|merged|rejected|all` (default `pending`).

`GET /products` query parameters:

| Param | Type | Notes |
|---|---|---|
| `q` | string | trigram search over name, keywords, brand |
| `country` | char(2) | default `AU` |
| `category_id` | uuid | exact |
| `category_path` | string | subtree prefix, e.g. `home-kitchen` |
| `status` | enum | default `active` |
| `min_score` / `max_score` | number | 0–100 |
| `min_growth_7d` / `min_growth_30d` | number | percent; excludes null growth |
| `trend_direction` | enum | `rising | stable | declining | unknown` |
| `competition` | enum[] | `low | moderate | high | saturated | unknown` |
| `min_price` / `max_price` | decimal | reference selling price |
| `min_margin` | number | percent |
| `supplier_available` | bool | |
| `synthetic` | enum | `include | exclude | only` (default `include`) |
| `sort` | enum | `-opportunity_score` (default), `-growth_7d`, `-growth_30d`, `-marketplace_popularity`, `competition_index`, `-estimated_margin`, `-first_seen_at`, `name` |

### 6.4 Discovery views

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/trending` | V | `?window=7|30|90&direction=rising|declining&limit=20` |
| GET | `/emerging` | V | newly discovered + accelerating demand |
| GET | `/opportunities` | V | score ≥ threshold, coverage-gated |
| GET | `/opportunities/recommendations` | V | `recommended`/`investigate`/`not_recommended` gate with checks, economics and missing evidence |
| GET | `/seasonal` | V | `?horizon_days=45|90` upcoming seasonal opportunities |

These are read models over `product_metrics`, not separate data. `emerging` requires a `discovered_at`
within `?since_days=30` AND positive 7d growth — both must hold, otherwise a product is "new",
not "emerging".

`GET /opportunities/recommendations` is deliberately separate from the opportunity score. It returns
`verdict` (`recommended`, `investigate`, `not_recommended`), per-evidence `checks`
(`pass`/`fail`/`missing`), `missing_evidence`, `next_actions`, `economics` and a disclaimer. A product
without a recorded supplier price, delivery cost and positive contribution margin cannot be
`recommended`. Query parameters: `verdict`, `min_coverage`, `limit`, `synthetic`.

### 6.5 Categories

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/categories` | V | `?tree=true` nested, else flat with `path` |
| POST | `/categories` | A | create |
| PATCH | `/categories/{id}` | A | rename/move (path rewritten for subtree) |
| DELETE | `/categories/{id}` | A | only if empty |

### 6.6 Competition

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/competition/summary` | V | `?category_id=&country=` aggregate index, price bands, saturation counts |
| GET | `/competition/products/{id}` | V | alias of `/products/{id}/competition`, kept for navigation symmetry |

Competition payload:

```json
{
  "product_id": "6f1c…",
  "index": 32.0,
  "classification": "moderate",
  "coverage": 0.66,
  "evidence": {
    "active_listing_count": {"value": 312, "source": "ebay_au", "observed_at": "2026-11-06"},
    "australian_retailers": {"value": 7, "status": "estimated"},
    "price_dispersion_cv": 0.31,
    "review_concentration_hhi": 0.18,
    "brand_dominance_share": 0.22
  },
  "unavailable": ["advertising_saturation"],
  "caveats": ["Based on active marketplace listings, not sales."],
  "classified_at": "2026-11-07"
}
```

### 6.7 Suppliers

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/suppliers` | V | list, `?product_id=&availability=` |
| GET | `/suppliers/{id}` | V | supplier detail + offers |
| GET | `/supplier-products` | V | offers, filter by product/supplier/availability |
| POST | `/supplier-products/refresh` | N | trigger supplier sync → 202 |
| PATCH | `/supplier-products/{id}` | N | manual correction (cost, MOQ, availability) |

### 6.8 Watchlist

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/watchlist` | V | `?status=&sort=-updated_at` |
| POST | `/watchlist` | N | `{product_id, status?, notes?}`; 409 if present |
| PATCH | `/watchlist/{id}` | N | status/notes/priority |
| DELETE | `/watchlist/{id}` | N | remove |
| GET | `/watchlist/export` | N | `?format=csv` → file |
| POST | `/watchlist/compare` | N | `{product_ids: [...]}` (2–5) → comparison payload |

Status values: `discovered | researching | shortlisted | supplier_validation |
ready_for_catalogue | published | rejected`.

### 6.9 Profit calculator

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/profit/calculate` | V | stateless calculation |
| GET | `/profit/assumptions` | V | current GST/fee defaults + version |
| GET | `/profit/scenarios` | V | `?product_id=` |
| POST | `/profit/scenarios` | N | save scenario |
| PATCH | `/profit/scenarios/{id}` | N | update inputs, recompute |
| DELETE | `/profit/scenarios/{id}` | N | delete |

Request:

```json
{
  "currency": "AUD",
  "supplier_price": "12.40",
  "international_shipping": "3.10",
  "import_duty_rate_pct": 0,
  "supplier_charges_gst": false,
  "gst_registered": true,
  "gst_rate_pct": 10,
  "claim_input_tax_credit": true,
  "domestic_fulfilment": "8.50",
  "packaging": "1.20",
  "payment_fee_pct": 1.75,
  "payment_fee_fixed": "0.30",
  "advertising_cost_per_order": "12.00",
  "selling_price_inc_gst": "69.95",
  "return_rate_pct": 3.0,
  "monthly_order_volumes": [100, 500, 1000, 5000]
}
```

Response:

```json
{
  "inputs": { "...echoed after normalisation..." },
  "assumptions_version": "2026-11",
  "outputs": {
    "landed_cost_ex_gst": "15.50",
    "landed_cost_cash": "17.05",
    "gst_on_landed_cost": "1.55",
    "selling_price_ex_gst": "63.59",
    "gst_remitted_per_sale": "6.36",
    "gross_profit": "48.09",
    "gross_margin_pct": 75.63,
    "payment_fees": "1.52",
    "returns_allowance": "2.10",
    "contribution_margin": "34.77",
    "contribution_margin_pct": 54.67,
    "break_even_ad_cost": "34.77",
    "advertising_cost_per_order": "12.00",
    "profit_per_order": "22.77",
    "profit_margin_pct": 35.8,
    "monthly": [
      {"orders": 100, "revenue_ex_gst": "6359.09", "gross_profit": "4809.09", "advertising_spend": "1200.00", "profit": "2276.83"},
      {"orders": 500, "revenue_ex_gst": "31795.45", "gross_profit": "24045.45", "advertising_spend": "6000.00", "profit": "11384.14"}
    ]
  },
  "warnings": [
    "Import duty is set to 0%. Confirm the tariff classification before relying on this margin.",
    "Returns are provisioned at 3.00% of the GST-inclusive selling price."
  ],
  "disclaimer": "Estimate only. Excludes income tax, FX movement, storage and wastage beyond the return allowance. Confirm supplier GST registration, tariff classification and marketplace fees before committing stock."
}
```

These are the outputs for the default request above. Decimal strings keep the arithmetic
audit-proof; percentages are rounded half-up to two decimal places. `break_even_ad_cost` is the
advertising spend at which profit is zero, and `profit_per_order` deducts the advertising input.
A scenario stores the normalised inputs and the computed outputs together, so the saved view stays
reproducible after assumptions change. Reloading a scenario into the calculator recalculates it
against the current API.

### 6.10 Data sources and synchronisation

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/data-sources` | V | registry + status + `configured` (no secrets) |
| PATCH | `/data-sources/{id}` | A | `{enabled, config, rate_limit_per_min}` |
| POST | `/data-sources/{id}/test-connection` | A | local configuration check (no provider call) |
| POST | `/data-sources/{id}/health-check?live=` | A | record a health check; `live=true` makes the cheapest authenticated provider call |
| GET | `/data-sources/health` | V | latest health + 24-hour statistics for every source |
| GET | `/data-sources/{id}/health` | V | source health summary and recent checks |
| GET | `/data-sources/{id}/snapshots` | V | immutable archived payloads (metadata only) |
| GET | `/data-sources/{id}/snapshots/{snapshot_id}` | V | one snapshot including its normalised payload |
| POST | `/data-sources/{id}/sync` | N | 202 `Job`; requires `Idempotency-Key` |
| GET | `/data-sources/{id}/runs` | V | paginated `ingestion_runs` |
| GET | `/sync/status` | V | all sources: last run, next scheduled, errors |
| GET | `/jobs/{id}` | V | job status/progress/result |
| POST | `/jobs/{id}/cancel` | N | best-effort cancel |

Health checks are append-only. A configuration check is local and free; it returns `healthy`,
`manual`, `unavailable` or `unconfigured`, never a live latency. A live check uses the connector's
cheapest authenticated endpoint and may consume a small amount of provider quota. `live` in the
response distinguishes the two, and credential names are returned, never values.

`GET /data-sources` item:

```json
{
  "id": "…",
  "provider_key": "google_trends",
  "provider_name": "Google Trends",
  "source_type": "search_trend",
  "enabled": true,
  "configured": false,
  "is_synthetic": false,
  "cost_model": "free",
  "monthly_cost": "0.00",
  "cost_currency": "USD",
  "request_limit_month": null,
  "requests_used_month": 0,
  "estimated_monthly_spend": "0.00",
  "usage_period": "2026-11",
  "availability": "manual_fallback",
  "availability_reason": "No public keyword API; use the export or the BigQuery dataset.",
  "usage_rights": "Provider terms apply",
  "docs_url": "https://trends.google.com/trends/explore",
  "terms_url": "https://policies.google.com/terms",
  "health": "manual",
  "health_status": "manual",
  "last_health_check_at": "2026-11-08T03:15:00Z",
  "last_health_latency_ms": null,
  "connector": {
    "installed": true,
    "available": false,
    "state": "manual_fallback",
    "reason": "No public keyword API; use the export or the BigQuery dataset."
  },
  "config": {"geo": "AU"},
  "secret_ref": [],
  "sync_status": "never_run",
  "last_sync_at": null,
  "last_success_at": null,
  "last_error": null
}
```

`secret_ref` exposes **names only** — it tells an admin which variables to set, not their values.
`estimated_monthly_spend` is the declared subscription cost plus any metered usage; it is never
presented as a quote.

An ingestion run carries `records_fetched`, `records_written`, `records_updated`,
`records_rejected`, `error_summary` and `cursor`. `records_updated` counts observations whose value
changed for an existing natural key (not a new insert). `cursor` records retry metadata
(`retry_code`, `retry_attempts`, `succeeded_after_attempt`) and the `snapshot_id` written by the
run.

A snapshot item carries `record_count`, `observation_count`, `listing_count`, `checksum` (SHA-256
of the normalised payload), `truncated`, the covered `period_start`/`period_end` and an
`attribution` block (provider, usage rights, docs/terms, request count). The list endpoint omits
the payload; the detail endpoint includes the normalised observations, listings, products,
suppliers and offers. Payloads are bounded by `SNAPSHOT_MAX_RECORDS` and pruned after
`SNAPSHOT_RETENTION_DAYS`; a truncated snapshot still reports the full `record_count`.

### 6.11 Scoring profiles and recalculation

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/scoring-profiles` | V | list versions |
| GET | `/scoring-profiles/{id}` | V | weights + thresholds |
| POST | `/scoring-profiles` | A | new version (validated sum = 1.0) |
| POST | `/scoring-profiles/{id}/activate` | A | set default for its country |
| POST | `/scores/recalculate` | A | `{product_id?|all: true, as_of_date?}` → 202 |

`POST /scores/recalculate` requires exactly one of `product_id` or `all: true`, rejects a future
`as_of_date` (`422`) and returns `202` with a synchronous `job` record plus the number of products
scored. Unknown or merged products are rejected rather than silently skipped.

Weights validation error example is in §3.

### 6.12 Reports and exports

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/reports` | V | `?type=&country=&from=&to=` |
| POST | `/reports` | N | `{type, country, period_start, period_end}` → 201 |
| GET | `/reports/{id}` | V | status + structured data + available formats |
| GET | `/reports/{id}/download` | V | `?format=csv|json|xlsx` → file (XLSX: Summary, Products, Sources, Limitations) |
| DELETE | `/reports/{id}` | A | delete report + artefacts |
| GET | `/exports/products` | V | current explorer filters → CSV stream |
| GET | `/exports/watchlist` | V | CSV |

Every report payload includes:

```json
{
  "disclaimer": "Growth is derived from relative search interest, not sales. Coverage varies by source.",
  "sources": [
    {"provider_key": "google_trends", "collection_date": "2026-11-07", "coverage_pct": 91.2},
    {"provider_key": "csv_import", "collection_date": "2026-10-30", "coverage_pct": 100}
  ],
  "limitations": ["amazon_au unavailable", "tiktok unavailable"]
}
```

### 6.13 AI research assistant (Phase 4)

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/assistant/query` | N | question → answer with claims and citations |
| GET | `/assistant/conversations` | N | history |
| GET | `/assistant/conversations/{id}` | N | messages + tool calls + citations |
| DELETE | `/assistant/conversations/{id}` | N | delete own conversation |

`POST /assistant/query` streams Server-Sent Events when `Accept: text/event-stream`, else returns the
final object:

```json
{
  "conversation_id": "…",
  "answer": "Three products match: …",
  "claims": [
    {
      "text": "Search interest for X rose 42% in the last 30 days.",
      "evidence_type": "verified",
      "source_refs": [
        {"type": "trend_observation", "id": 918273, "provider": "google_trends", "observed_at": "2026-11-06"}
      ]
    },
    {
      "text": "This looks promising for Christmas gifting.",
      "evidence_type": "model_generated",
      "source_refs": []
    },
    {
      "text": "Amazon AU sales volume is unavailable.",
      "evidence_type": "unavailable",
      "source_refs": []
    }
  ],
  "coverage_note": "2 of 6 data sources available for this query.",
  "model": "configured-model-name",
  "created_at": "2026-11-07T04:12:00Z"
}
```

`evidence_type` ∈ `verified | estimated | model_generated | unavailable`. The server rejects an answer
whose `verified` claims lack resolvable `source_refs` (validation error, retry once, then degrade to
"unable to answer from available data").

### 6.14 Admin and operations

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/health` | P | liveness (`{"status":"ok"}`) |
| GET | `/health/ready` | P | DB + Redis + worker reachability |
| GET | `/audit-logs` | A | `?entity_type=&entity_id=&user_id=` |
| GET | `/settings` | A | feature flags, environment summary (no secrets) |
| PATCH | `/settings` | A | assistant enablement, demo mode, retention windows |
| GET | `/job-schedules` | A | cron registry |
| PATCH | `/job-schedules/{job_name}` | A | update cron/enabled |

---

## 7. Async behaviour and status codes

- `POST /products/import/csv`, `/products/discover`, `/data-sources/{id}/sync`, `/scores/recalculate`,
  `/supplier-products/refresh`, `/reports` return **202** with a `Job`.
- Clients poll `GET /jobs/{id}` (recommended 1 s backoff doubling to 10 s) or use the returned
  `poll_url`.
- `409` is returned when a run for that source is already in progress.
- A provider outage surfaces as a *successful* 202 whose job ends `failed` with a typed error code —
  triggering a sync is not the provider call.
- `health-check?live=false` is local and free; `health-check?live=true` is the one synchronous
  provider call (short timeout, one retry policy) so an admin gets an immediate answer and can see
  whether the failure was configuration or the provider.
- `DELETE` on products is soft (`status = archived`); archived products remain queryable via
  `?status=archived` for audit.

---

## 8. Rate limits

| Surface | Limit |
|---|---|
| `/auth/login` | 5/min per IP+email |
| General authenticated API | 300/min per user |
| `/exports/*`, `/reports/*/download` | 20/min per user |
| `/assistant/query` | 10/min per user, plus a token budget per day |
| Provider calls | governed server-side by per-source token buckets, not exposed to clients |

Exceeding a limit returns `429` with `Retry-After` and `X-RateLimit-Reset`.

---

## 9. Versioning and compatibility

- URL-versioned (`/api/v1`). Additive fields are non-breaking; removals/renames require `/api/v2`.
- New enum members are additive but clients must render unknown values as "Unknown" rather than crash.
- Deprecations announced via the `Deprecation` and `Sunset` response headers for at least one minor
  release.
- The OpenAPI document at `/api/v1/openapi.json` is generated from code and diffed in CI; a contract
  change without a regenerated client fails the build.

---

## 10. Endpoint → PRD traceability

| PRD requirement | Endpoint(s) |
|---|---|
| §4.1 discovery, categories, manual add, dedup | `/products*`, `/categories*`, `/products/matches*` |
| §4.2 multi-period trends, growth guards | `/products/{id}/trends`, `/products/{id}/metrics`, `GET /trending` |
| §4.3 provider status, last sync, errors | `/data-sources*`, `/sync/status`, `/jobs/{id}` |
| §4.4 scoring, weights, classification | `/products/{id}/score`, `/scoring-profiles*`, `/scores/recalculate` |
| §4.5 competition | `/products/{id}/competition`, `/competition/summary` |
| §4.6 profitability + GST | `/profit/calculate`, `/profit/scenarios*` |
| §4.7 product detail | `/products/{id}` |
| §4.8 assistant | `/assistant/*` |
| §5.1 dashboard | `/dashboard*` |
| §5.2 explorer | `GET /products` |
| §5.3 watchlist | `/watchlist*` |
| §9 scheduling, manual refresh | `/job-schedules*`, `/data-sources/{id}/sync` |
| §10 reports and export | `/reports*`, `/exports/*` |
| §12 security | `/auth/*`, `/audit-logs`, error model |
