# 06 — Free-First Gap Analysis and Implementation Record

**Purpose:** compare the original TrendScope Phase 1 specification
(`docs/01`–`docs/05`) with the free-first data-source specification supplied on
2026-11-08, record every material gap, and document how the codebase now closes it.

**Status:** implemented in the backend and frontend. Migrations `0001`–`0004` apply cleanly,
the full backend suite (155 tests) passes, and the frontend production build succeeds.

---

## 1. Specification comparison

### 1.1 What the original specification required

The original Phase 1 design already contained several constraints that the new
specification assumes:

- the app must work with partial data and must never coerce missing values to zero;
- actual sales, estimated sales and search interest are distinct quantities;
- connector status and limitations must be visible rather than guessed;
- the mock provider and CSV import are valid first-class data sources;
- Phase 1 must run locally without external accounts.

It also made one decision the free-first specification reverses:

- **D1 in `docs/05` recommended a paid Google Trends intermediary (DataForSEO,
  weekly cadence).** That is incompatible with "no paid provider is required for
  the MVP". It is superseded for Phase 1 by the free routes below. It remains a
  valid Phase 2 option once usage data shows the paid source earns its cost.

### 1.2 What the free-first specification added

| Requirement | Original Phase 1 | Gap found | Implementation |
| --- | --- | --- | --- |
| Operate with no marketplace subscription | Mock + CSV only | No usable free automation beyond mock/CSV | Google BigQuery public trends, eBay Browse, Meta Ad Library connectors; manual fallbacks for Trends, TikTok and Amazon |
| Independent connectors | A single mock builder | No connector plugin boundary | `connectors/framework.py` + registry; one module per provider |
| Connector lifecycle | None | No `fetch_data`/`validate_data`/`normalize_data`/`get_source_status`/`get_last_sync`/`handle_errors` | Implemented on `BaseConnector`; every connector inherits it |
| Complete observation provenance | `metric_name`, source, date, synthetic flag | Missing metric type, provider, period, source URL, verification, quality, collection time | New `trend_observations` columns + migration backfill; manual entry and CSV import write them |
| Separate component scores | Already separate | Read path could merge same-named metrics from different sources/types | Trend series now group by `(metric_name, metric_type)` |
| Cost and integration visibility | Source enabled/status only | No cost model, spend, usage, availability reason, rights or docs | New `data_sources` columns; `GET /data-sources` returns cost, usage, health, connector state |
| Paid providers optional | Not designed | No structural plugin slot | Paid providers are disabled plugins; enabling one adds no schema or scoring changes |
| Recommendation investigation | Score only | A high score could be read as "add this product" | `services/recommendations.py`, `GET /opportunities/recommendations`, product-detail panel |
| Supplier/delivery/margin evidence | Synthetic offers only | No API for the operator to record a real quote | `POST/PATCH /products/{id}/suppliers`; recomputes score and recommendation |
| Manual research workflow | Product CSV only | No observation entry | `POST/PATCH /products/{id}/observations`; observation CSV import |
| No scraping / no control bypass | Stated | Connector layer did not exist | Manual fallbacks and explicit refusals; no HTML scraping anywhere |
| Missing data never zero | Stated | New fields could default to `0` or `"available"` | Missing evidence yields `null` + `investigate`; connector availability is explicit |

---

## 2. Connector framework

`backend/app/connectors/framework.py` defines the lifecycle the specification
asked for:

```text
fetch_data(ctx) -> RawPayload
validate_data(payload) -> ValidationResult
normalize_data(payload) -> ConnectorDataset
run(ctx) -> fetch → validate → normalize
get_source_status(source) -> ConnectorStatus   (never calls the network)
get_last_sync(source) -> datetime | None
handle_errors(exc) -> ConnectorErrorInfo        (secret-free)
```

Connectors declare `provider_key`, `provider_name`, `cost_model`,
`default_availability`, `credential_names`, `docs_url`, `terms_url` and
`usage_rights`. The registry (`connectors/registry.py`) maps provider keys to
plugins. Ingestion (`services/ingestion.py`) runs any installed plugin through
`run_connector_sync`, records request usage, and writes every observation with
provenance.

### 2.1 Provider decisions

| Provider | Decision | Why |
| --- | --- | --- |
| Mock | Synthetic, enabled | Deterministic demo; always labelled |
| CSV import | Manual, enabled | Universal free fallback; also carries research observations |
| Google Trends | Free, manual fallback | No general public API; do not use archived `pytrends` |
| Google Trends via DataForSEO | Paid, optional, disabled | Documented Trends API with explicit terms; operator credentials and a terms/pricing review required. The free routes remain the default |
| Google BigQuery trends | Free, optional credentials | Public `bigquery-public-data.google_trends` dataset; `google-cloud-bigquery` is an optional extra |
| eBay AU | Free, credentials required | Browse API gives active listings/prices only; sold data is not available to new users |
| Meta Ad Library | Free, credentials required | Advertising activity only; never labelled as social engagement or sales |
| TikTok | Free, manual fallback | Creative Center is not available for AU; no scraping or signed-endpoint bypass |
| Amazon public research | Manual fallback | No first-party Amazon AU product API |
| Amazon AU legacy | Unavailable | Kept so old provenance stays resolvable; sync refuses |
| Exploding Topics | Paid, optional, disabled | Demonstrates the paid-plugin slot; requires explicit enablement and terms review |
| CJ Dropshipping | Free, optional, disabled | Conditional API access; not required by the MVP |

**Explicit non-goals:** scraping protected pages, bypassing authentication,
solving CAPTCHAs, circumventing anti-bot controls, or treating a web-app
subscription as an API/redistribution licence.

---

## 3. Observation provenance

Every `trend_observations` row now carries:

| Field | Meaning |
| --- | --- |
| `provider_name` | Named provider or manual method |
| `collected_at` | When the observation entered the system |
| `period_start` / `period_end` | What period the measurement covers |
| `country` | Geographic market |
| `original_metric` | The provider's own metric name |
| `metric_type` | `search_interest`, `marketplace_price`, `social_engagement`, `advertising`, `actual_sales`, `estimated_sales`, … |
| `verification_status` | `verified`, `estimated`, `unverified`, `synthetic` |
| `data_quality` | `high`, `medium`, `low`, `unknown`, `synthetic` |
| `source_url` | Where the operator or connector obtained it |

Migration `0002_free_first_sources` backfills existing rows from
`ingested_at`, `observation_date` and `is_synthetic`, so no history loses its
origin.

The read path (`services/presenters.py`) returns these fields in
`product_sources` and keeps series separate by metric type. Search interest,
listing counts, prices, engagement and advertising are therefore never summed as
if they measured the same thing.

---

## 4. Cost and integration visibility

`data_sources` now stores `cost_model`, `monthly_cost`, `cost_currency`,
`request_limit_month`, `requests_used_month`, `usage_period`, `availability`,
`availability_reason`, `usage_rights`, `docs_url`, `terms_url` and
`last_success_at`.

`GET /data-sources` and `/sync/status` return:

- free/paid/manual/synthetic cost model and estimated monthly spend;
- usage this month against a declared limit;
- availability state (`available`, `requires_credentials`, `manual_fallback`,
  `unavailable`) and the reason;
- connector installation, configuration and health;
- documentation and terms links.

`POST /data-sources/{id}/test-connection` reports credential/configuration state
without making a provider call.

---

## 5. Recommendation workflow

A high opportunity score is not a recommendation. The opportunity score measures
demand and marketplace evidence; it does not know whether a supplier quote leaves
a viable margin.

`services/recommendations.py` evaluates six checks:

| Check | Passes when |
| --- | --- |
| Demand | 7-day or 30-day search growth is positive and present |
| Supplier price | A supplier offer with a positive unit cost exists |
| Delivery cost | The same offer records a delivery cost (zero is allowed if real) |
| Contribution margin | Estimated margin ≥ 25% after fees, fulfilment and returns |
| Competition | Classified `low` or `moderate` |
| Evidence coverage | Opportunity score coverage ≥ 60% |

Verdict rules:

- any **fail** → `not_recommended`;
- otherwise any **missing** → `investigate`;
- only all-pass → `recommended`.

A stored margin without a supplier offer behind it is treated as missing, not as
evidence. Every response includes the checks, missing evidence, economics
(market price, supplier cost, delivery, landed cost, profit per unit), next
actions and a disclaimer that supplier quotes must be confirmed. It never claims
a sales forecast.

Surfaces:

- `GET /api/v1/opportunities/recommendations` — ranked list with verdict filter;
- `GET /api/v1/products/{slug}` — `recommendation` object;
- `/opportunities` page and a product-detail panel.

---

## 6. Manual research workflow

The free-first specification requires a manual path wherever an official API is
unavailable. Two endpoints close that gap:

- `POST /products/{identifier}/observations` records one observation with full
  provenance. Duplicate natural keys return `409` instead of silently replacing
  history. Operator-entered rows can be corrected through
  `PATCH /products/{identifier}/observations/{observation_id}`, which appends a
  correction log; connector history remains append-only.
- `POST /products/{identifier}/suppliers` records a supplier quote and
  recomputes metrics and the recommendation. `PATCH …/suppliers/{offer_id}`
  updates a quote after renegotiation.
- `GET /products/import/observations/template` and
  `POST /products/import/observations/csv` support bulk research entry. Unknown
  products and invalid rows are rejected with row numbers.

After any manual entry, `compute_product_metrics` and `compute_product_score`
run for the affected product, so the recommendation reflects the new evidence.

---

## 7. Connector operations, health and history

The connector framework records what happened, not only the latest value.

| Concern | Implementation |
| --- | --- |
| Transient provider failures | `connectors/http.py` retries network errors, `429`, `500`, `502`, `503` and `504` with bounded exponential backoff, jitter and `Retry-After`; client errors and auth failures are never retried |
| Connector-level retries | `run_connector_sync` retries only errors that `handle_errors` marks retryable, bounded by configured attempts and backoff; the successful attempt number is recorded in `ingestion_runs.cursor` |
| Health checks | `provider_health.evaluate` records an append-only `provider_health_checks` row and mirrors `health_status`, `last_health_check_at` and latency onto the source |
| Configuration vs live | `live=false` is a free local check; `live=true` calls each connector's cheapest authenticated probe (eBay OAuth token, BigQuery dry run, Meta one-row query, DataForSEO account endpoint). A missing probe falls back to the configuration result rather than inventing a failure |
| Immutable evidence | Every sync stores a `provider_snapshots` row with the normalised records, counts, period, SHA-256 checksum, attribution and truncation flag; retention is bounded and pruned weekly |
| Revised observations | A changed value for an existing natural key updates the row in place, increments `revision`, records `updated_at` and keeps up to five prior values in `metadata.previous_values`; `records_updated` distinguishes revisions from inserts |
| Scheduled operations | Celery beat runs a daily configuration health check, a daily sync of enabled non-synthetic connectors and a weekly snapshot prune |

The optional DataForSEO plugin (`google_trends_dataforseo`) is now a registered,
disabled paid connector with credentials, documented API terms and explicit
relative-index labelling. It does not replace the free manual/CSV route and is
not enabled by default.

---

## 8. Residual limitations

- Google Trends remains manual/CSV unless the BigQuery extra is installed and
  credentials are supplied. The public dataset is a trends sample, not a
  replacement for keyword-level series.
- eBay Browse returns active listings only. Sold counts and sold prices stay
  unavailable and are labelled as such.
- Meta Ad Library measures advertising activity, not demand. It is never mapped
  to `social_engagement`.
- Amazon AU and TikTok have no permitted automated route for this market.
- Supplier verification is manual. A `recommended` verdict means the evidence was
  recorded, not that the supplier was independently audited.
- Paid providers are structurally optional. Exploding Topics remains a disabled
  entry; DataForSEO is an optional, credential-gated Google Trends plugin and is
  disabled by default. Neither is required by the MVP.

## 9. Verification

- `backend`: `155 passed` under pytest, including the free-first tests for
  connector status gating, provenance, manual observations/suppliers, CSV
  observation import and every recommendation verdict path, the Phase-1
  completion tests for refresh-token rotation/reuse, merges, score recalculation,
  the GST profit model and XLSX export, and the connector-operations tests for
  retry/backoff, configuration and live health checks, snapshot truncation and
  pruning, observation revisions and DataForSEO normalisation.
- `alembic upgrade head` and `alembic check`: migrations `0001`–`0004` apply
  cleanly with no drift.
- `frontend`: `tsc --noEmit` and `next build` succeed; `/opportunities`,
  `/profit`, source health history and the snapshot archive are new surfaces.
