# 01 — Technical Architecture

**Project:** TrendScope AI
**Status:** Proposed — pending sign-off on decisions D1–D7 in
[`05-implementation-plan.md`](05-implementation-plan.md)
**Scope of this document:** system shape and module boundaries for all four PRD phases. Phase 1 is
buildable exactly as described; later phases extend it without reshaping it.

---

## 1. Starting point

The target directory `/home/palbot/Projects/ecom/TrendScope` is empty and is not a git repository.
There are no existing frameworks, conventions, migrations or CI to preserve (PRD §16.1–16.3
therefore resolve to "initialise the recommended architecture"). The PRD's prescribed stack —
Next.js/React/TypeScript/Tailwind/Recharts, Python 3.12/FastAPI/SQLAlchemy/Pydantic, PostgreSQL,
Celery/Redis, Docker Compose — is adopted unchanged. Deviations are listed in §4.3 and are all
additive.

---

## 2. System overview

```
                          ┌──────────────────────────────────────────────┐
                          │  Next.js 15 (App Router, TS, Tailwind)        │
                          │  Dashboard · Explorer · Product · Watchlist   │
                          │  Reports · Settings · Assistant (Phase 4)     │
                          └───────────────┬──────────────────────────────┘
                                          │ REST /api/v1 (JSON, OpenAPI 3.1)
                          ┌───────────────▼──────────────────────────────┐
                          │  FastAPI application                          │
                          │  api/ → services/ → repositories/ → models/   │
                          │  auth · RBAC · rate limit · audit            │
                          └───────┬───────────────────────┬──────────────┘
                                  │                       │
        ┌─────────────────────────▼─────────┐   ┌─────────▼──────────────────┐
        │  Domain services                   │   │  Orchestration              │
        │  scoring · metrics · competition   │   │  Celery worker + beat       │
        │  profitability (GST) · reporting   │   │  scheduled + manual jobs    │
        └─────────────────────────┬─────────┘   └─────────┬──────────────────┘
                                  │                       │
        ┌─────────────────────────▼───────────────────────▼──────────────────┐
        │  Ingestion layer                                                     │
        │  connectors/ (google_trends, ebay_au, amazon_au, tiktok,             │
        │               exploding_topics, cj_dropshipping, aliexpress, csv)     │
        │  normalisation → category mapping → product matching → persistence   │
        └───────────────────────────────┬──────────────────────────────────────┘
                                        │
        ┌───────────────────────────────▼──────────────────────────────────────┐
        │  PostgreSQL 16            Redis 7                  Object storage     │
        │  products, observations,  Celery broker,           (local FS in dev,   │
        │  snapshots, scores,       cache, rate-limit        S3-compatible in    │
        │  audit, reports           counters                 prod) for exports   │
        └──────────────────────────────────────────────────────────────────────┘
```

**Read path** (fast, no aggregation on request): product metrics are pre-computed daily into
`product_metrics` and `opportunity_scores`. Explorer and dashboard queries read snapshots, not raw
observations. Raw observation history stays append-only for recomputation and charts.

**Write path** (slow, isolated): connectors produce normalised observations; a per-source run is
committed atomically; derived snapshots are recomputed by an idempotent job. A failing provider can
never roll back another provider's data (PRD §4.3).

---

## 3. Repository layout

```
TrendScope/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI factory, lifespan, middleware
│   │   ├── core/                    # config, security, logging, errors, pagination, cache
│   │   ├── api/v1/                  # routers only — thin, no business logic
│   │   ├── schemas/                 # Pydantic request/response models
│   │   ├── models/                  # SQLAlchemy 2.0 ORM models
│   │   ├── repositories/            # query construction, no business rules
│   │   ├── services/                # business rules (scoring, metrics, competition, profit)
│   │   ├── connectors/
│   │   │   ├── base.py              # Connector protocol + result types
│   │   │   ├── registry.py          # provider key → class
│   │   │   ├── http.py              # shared retrying/limiting HTTP client
│   │   │   ├── google_trends/       # dataforseo.py, serpapi.py, mock.py
│   │   │   ├── ebay/                # browse.py, mock.py
│   │   │   ├── amazon/              # mock.py (vendor connector added Phase 2)
│   │   │   ├── tiktok/              # mock.py, manual_import.py
│   │   │   ├── exploding_topics/    # api.py, csv.py, mock.py
│   │   │   └── suppliers/           # cj.py, aliexpress.py, csv.py, mock.py
│   │   ├── pipeline/                # ingest, normalise, match, derive, score, report
│   │   ├── jobs/                    # Celery app, tasks, beat schedule, schedules sync
│   │   ├── ai/                      # provider abstraction, tools, assistant (Phase 4)
│   │   ├── reports/                 # builders + renderers (csv, xlsx, pdf)
│   │   └── seed/                    # categories tree, scoring profile, demo sources
│   ├── alembic/                     # migrations
│   ├── tests/
│   │   ├── unit/                    # pure logic: scoring, growth, GST, matching
│   │   ├── integration/             # API + DB + pipeline with real Postgres/Redis
│   │   ├── contract/                # connector fixtures + recorded responses
│   │   └── fixtures/                # golden datasets, CSV samples
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/app/                     # routes: (dashboard), products, watchlist, ...
│   ├── src/components/              # ui/ + domain components
│   ├── src/lib/                     # api client, generated types, formatters
│   ├── src/hooks/
│   └── Dockerfile
├── docker-compose.yml
├── docker-compose.test.yml
├── .env.example
├── Makefile                         # up, test, migrate, lint, seed, fmt
└── docs/                            # this set
```

**Layering rule (enforced in review):** routers may call services and repositories; services may call
repositories, connectors and other services; repositories may not import services; connectors may not
import repositories or models. Domain logic never lives in a router or a Celery task.

---

## 4. Stack decisions

### 4.1 Adopted from the PRD

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind, Recharts | App Router; server components for read-heavy pages |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 | Async SQLAlchemy (`asyncpg`); sync engine only for Alembic |
| DB | PostgreSQL 16 | `pg_trgm` for fuzzy product search; `pgvector` deferred |
| Queue | Celery 5 + Redis 7 | Beat scheduler, timezone `Australia/Sydney` |
| AI | OpenAI API (configurable model) | Behind an internal `LLMProvider` interface (§10) |
| Infra | Docker Compose, Alembic, structlog, pytest | CI-ready, local-first |

### 4.2 Supporting libraries

- `httpx` + `tenacity` for connectors; `limits`/Redis counters for rate limiting.
- `argon2-cffi` for password hashing; `pyjwt` for tokens.
- `openpyxl` (XLSX), `weasyprint` (PDF), stdlib `csv` for exports.
- `orjson` response class for throughput.
- Frontend: `shadcn/ui`, TanStack Query, TanStack Table, `openapi-typescript`, `zod`.
- No global state library — server state via TanStack Query, URL state via search params.

### 4.3 Deliberate deviations / additions to the PRD

| Addition | Why |
|---|---|
| `scoring_profiles` table | PRD §4.4 requires admin-editable weights and historical score explainability; hard-coded weights cannot satisfy both. |
| `product_metrics` daily snapshot table | Explorer sorting/filtering on 7/30/90-day growth across thousands of products cannot aggregate raw observations per request. |
| `product_identifiers`, `product_aliases`, `product_matches` | PRD §4.1 "avoid duplicate product records" needs deterministic identity (GTIN/ASIN) plus a reviewable merge queue, not name string equality. |
| `ingestion_runs`, `source_records` | PRD §4.3 requires per-provider status, error logging and sync times; PRD §8 requires raw history to be preserved. |
| `profit_scenarios` | Persisting calculator inputs is needed for the product detail page and for comparing scenarios. |
| `job_schedules` | PRD §9 makes frequencies configurable; code-only cron cannot be changed without deploy. |
| `assistant_conversations` / `assistant_messages` (Phase 4) | PRD §4.8 requires verifiable citations distinguishing verified/estimated/model-generated claims; that is an audit trail. |
| `users` + refresh tokens | PRD §12 requires authentication; a single-user MVP still needs a real identity row for watchlists and audit logs. |

---

## 5. Backend module contracts

- **`core/config.py`** — one `Settings` object (pydantic-settings) read from env. No module reads
  `os.environ` directly. Fails fast on missing required values outside test/demo mode.
- **`core/errors.py`** — `AppError(code, message, status, details)` hierarchy; a single exception
  handler converts to the API envelope in [`03-api-contract.md`](03-api-contract.md) §3. Domain code
  raises typed errors; routers never construct error responses by hand.
- **`api/v1/*`** — one router per resource. Validates input, calls one service method, returns a
  schema. Maximum ~15 lines per handler.
- **`services/*`** — pure where possible. Scoring, growth and profitability are pure functions over
  dataclasses with no DB access, which makes them exhaustively unit-testable (PRD §13). Orchestrating
  services fetch inputs via repositories, call the pure functions, persist outputs.
- **`repositories/*`** — typed query methods returning ORM entities or read models. Pagination and
  filtering live here. No HTTP, no scoring.
- **`models/*`** — SQLAlchemy 2.0 declarative with `Mapped[...]`; enums as PostgreSQL native enums
  with a `UNKNOWN`/`INSUFFICIENT` member where the domain needs "we do not know".

---

## 6. Connector framework

This is the most important abstraction in the system: PRD §4.3 requires modular, independently
replaceable providers that degrade gracefully.

### 6.1 Protocol

```python
class Connector(Protocol):
    provider_key: ClassVar[str]
    source_type: ClassVar[SourceType]

    async def health_check(self, ctx) -> HealthResult: ...
    async def discover(self, ctx, query: DiscoveryQuery) -> AsyncIterator[ProductCandidate]: ...
    async def fetch(self, ctx, targets: Sequence[Target], window: DateRange)
        -> AsyncIterator[ObservationBatch]: ...
```

- `ctx` carries credentials, timeouts, a `RateLimiter` and a `RequestRecorder`. Connectors never read
  settings or the DB.
- `ProductCandidate` = external id, title, category hint, identifiers (GTIN/ASIN/SKU), price, brand,
  image URL, payload.
- `ObservationBatch` = `(external_id, metric_name, value, unit, observation_date, granularity,
  confidence, source_timestamp, payload)` tuples plus batch-level metadata.
- Connectors return **observations, never scores**. Scoring is provider-agnostic.

### 6.2 Registry and lifecycle

`registry.py` maps `provider_key → class`. A `data_sources` row selects the key and holds non-secret
configuration. Changing vendor = new class + new key; the pipeline is untouched.

- **Enable/disable** — `data_sources.enabled`; disabled sources are skipped, never deleted.
- **Credentials** — stored only as environment variables/secrets. The DB stores a *reference name*
  (`secret_ref = "DATAFORSEO_LOGIN"`), never the value. `GET /data-sources` returns `configured:
  true/false` and provider status, never the secret.
- **Rate limiting** — token bucket per provider key in Redis, sized from
  `data_sources.rate_limit_per_min` with a conservative default (e.g. Google Trends 30/min, DataForSEO
  concurrent-task cap, eBay 5,000 calls/day app-level).
- **Retries** — `tenacity` exponential backoff with jitter on 429/5xx/timeouts only. 4xx auth errors
  do not retry; they set `sync_status = error` with an actionable message.
- **Circuit breaker** — after N consecutive failures a provider is skipped for a cooldown window and
  reported as `degraded` on the dashboard, so one dead vendor does not stall a nightly run.
- **Incremental sync** — `ingestion_runs.cursor` stores provider cursors/ETags where supported;
  otherwise the run re-fetches the window and upserts on the observation natural key.
- **Timeouts** — per-request (10–30 s) and per-run wall clock. The run is marked `partial` rather
  than lost.
- **Error logging** — structured log line per failed request with provider, endpoint, status,
  `request_id`, retry count; summarised into `ingestion_runs.error_summary`. Payloads are truncated
  before logging; secrets are redacted by a logging processor.

### 6.3 Synthetic data policy (important)

PRD §13 requires the full app to be demonstrable without credentials, while PRD §16.9 and §2 forbid
fabricating live data. Both hold only if synthetic data is **structurally labelled**:

- Mock connectors write to a `data_sources` row with `provider_key = 'mock'` and `is_synthetic = true`.
- Every observation carries a denormalised `is_synthetic` flag; every score computed from a
  synthetic-only evidence set is flagged.
- The API returns `data_quality.synthetic = true`; the UI renders a "Demo data" badge and a banner.
- A demo-mode banner is unavoidable on the dashboard. Synthetic rows can be purged with one command
  (`make purge-demo`).
- Real and synthetic observations are never blended into one score silently: if a score uses both,
  `data_quality.synthetic_share` is reported.

This is the difference between a demo and a false claim about Australian consumer demand.

---

## 7. Data pipeline

PRD §8's twelve steps map to explicit stages with transaction boundaries:

| # | Stage | Module | Persistence / failure behaviour |
|---|---|---|---|
| 1 | Fetch | `connectors/*` | No writes; in-memory batches |
| 2 | Validate | `pipeline/validate.py` | Reject malformed records individually; count in run |
| 3 | Normalise names/categories | `pipeline/normalise.py` | Title cleanup, unit/currency normalisation, taxonomy mapping with confidence; unmapped → `uncategorised` |
| 4 | Match/merge duplicates | `pipeline/match.py` | Identifier match → alias match → trigram similarity; ambiguous pairs go to `product_matches` for review, never auto-merged |
| 5 | Save raw observations | `pipeline/persist.py` | One transaction per 500 records; **insert-only** history; upsert only on the natural key for same-day revisions |
| 6 | Trend indicators | `pipeline/metrics.py` | Writes `product_metrics` snapshot for the day |
| 7 | Competition indicators | `pipeline/competition.py` | Same snapshot |
| 8 | Profitability estimate | `pipeline/profitability.py` | Only when supplier cost + a reference price exist; otherwise `null` with reason |
| 9 | Opportunity scores | `pipeline/scoring.py` | Writes `opportunity_scores` row per product/profile/day |
| 10 | AI summaries | `pipeline/summarise.py` | Phase 4; cached by (product, score_version) |
| 11 | Dashboard | `services/dashboard.py` | Reads snapshots; Redis cache TTL 60 s |
| 12 | Reports | `reports/*` | `research_reports` row + export artefacts |

**Idempotency and isolation**

- Each provider run takes a Postgres advisory lock on its `source_id`; overlapping runs are rejected.
- Observation writes are idempotent on `(product_id, source_id, observation_date, metric_name,
  granularity, country)`. Re-running a day cannot duplicate a series point.
- Derived recompute is keyed by `(product_id, as_of_date)` and is safe to re-run for any date.
- A provider failure marks only that run `failed`/`partial`; the rest of the pipeline proceeds.
- `source_timestamp` (provider's time) and `ingested_at` (ours) are separate columns — PRD §8.

**Deduplication strategy**

1. Exact identifier match (GTIN/UPC/EAN/ASIN) — automatic merge.
2. Exact normalised name + brand — automatic merge when brand is non-empty; otherwise queued.
3. Trigram similarity ≥ 0.90 on normalised name within the same category — queued as a candidate.
4. Token-set similarity with variant/size/colour stripping — Phase 2; embeddings (`pgvector`) — later.
5. Manual merge always wins and is never reversed automatically.

Merges are recorded (`merged_into_product_id`) rather than deleting rows, so observations stay
attached and the audit trail survives.

---

## 8. Metric definitions

### 8.1 Growth (PRD §4.2)

Windows are complete days only; "today" is excluded to avoid partial-day artefacts. Current window
ends at `as_of_date - 1`. Previous window is the equally sized window immediately before it.

```
growth_pct = (mean(current_window) / mean(previous_window) - 1) × 100
```

Guards, all configurable and stored as reason codes rather than zeros:

| Condition | Result |
|---|---|
| Coverage < 5 of 7 days (or 70% of a 30/90-day window) | `null`, reason `insufficient_current_data` |
| Baseline mean < `min_baseline_index` (default 5.0) | `null`, reason `insufficient_baseline` |
| Baseline mean == 0 | `null`, reason `zero_baseline` |
| Last observation older than `stale_after_days` (default 3) | `null`, reason `stale_data` |
| Computed growth > 900% | Value clamped for display, `extreme_growth = true` retained in raw value |

A `null` growth is rendered as "—" with the reason, never as 0% or "no growth". This is the single
most important correctness rule in the product: absence of evidence is not evidence of decline.

### 8.2 Data coverage and confidence

For each product and component:

- `coverage_pct` = share of score weight for which usable evidence exists (`0–100`).
- `confidence` = `coverage` × `freshness_factor` × `sample_factor` × `source_diversity_factor`, each
  in [0,1]. Freshness degrades linearly after `stale_after_days`; sample factor uses observation count
  relative to the window requirement; diversity counts distinct non-synthetic sources.
- Confidence is stored alongside every snapshot and score, and surfaces in the API and UI.

### 8.3 Competition (PRD §4.5)

Inputs when available: active listing count (log-scaled), Australian retailer count, price
distribution (IQR/CV), review concentration (HHI over top-10 listing review counts), brand dominance
share, advertising saturation. Each normalises to 0–100; the competition index is a weighted mean of
the available inputs.

Classification thresholds on the index: `<25` low · `25–49` moderate · `50–74` high · `≥75` saturated.
If fewer than two evidence inputs are available, the class is `unknown` with `coverage` reported —
the PRD's "do not equate a small number of indexed listings with low competition" rule.

### 8.4 Seasonality (PRD §4.2, §4.6)

Requires ≥ 12 months of observations. `seasonality_index(month) = month_mean / annual_mean`.
Upcoming opportunity = next 45 and 90 days weighted by index. Below 12 months the seasonal component
is simply unavailable and weight-renormalised away — never guessed.

---

## 9. Opportunity scoring engine (PRD §4.4)

### 9.1 Components and normalisation

Each component returns a 0–100 score plus the raw measurements that produced it. Normalisation is
**cohort-relative percentile ranking** within (category, country, as_of_date) for demand, marketplace
and social, because raw scales differ by provider and category. Profitability and seasonal use
explicit piecewise bands. Competition uses `100 - competition_index`.

| Component | Default weight | Inputs | Normalisation |
|---|---:|---|---|
| Demand | 25% | 30d growth, 7d momentum, index level | percentile of a composite z-score |
| Marketplace | 25% | listing count, review velocity, rank change | percentile composite |
| Social | 15% | engagement, hashtag views | percentile composite |
| Competition | 15% | competition index | `100 − index` |
| Profitability | 15% | contribution margin at reference price | piecewise: 10%→30, 25%→60, 40%→85, 55%→100 |
| Seasonal | 5% | seasonality index for next 90 days | piecewise on lift vs annual mean |

Percentile normalisation requires a cohort of at least `min_cohort_size` (default 20) products with
that input; below that an absolute banding fallback applies and the component is flagged
`low_cohort`.

### 9.2 Missing data

```
weight_available = Σ w_i  for components with usable evidence
score_raw        = Σ (w_i × s_i) / weight_available
coverage         = weight_available / Σ w_all           # 0..1
confidence       = coverage × quality_factors
score_final      = round(50 + (score_raw − 50) × confidence, 1)
```

- Missing components are excluded and remaining weights renormalised — **not** scored zero (PRD
  §4.4). `coverage` is stored and returned so the user sees what the number rests on.
- The shrinkage step in `score_final` is the guard the PRD's "low-confidence data must not increase
  the score" rule needs: renormalisation alone lets a single excellent component produce 100 from
  25% of the evidence. Shrinking toward 50 by confidence keeps rankings honest.
- Both `score_raw` and `score_final` are persisted, along with every component score and raw input
  in `opportunity_scores.components`. Nothing about a score is unexplainable.
- If `coverage < 0.60`, classification is `insufficient_data` regardless of score, and the UI shows
  "not enough data to rank" rather than a gold badge.

### 9.3 Classification and versioning

`80–100 excellent · 65–79 strong · 50–64 worth investigating · 35–49 weak · 0–34 low priority`
(PRD §4.4), configurable per scoring profile. Every recalculation inserts a new row keyed by
`(product_id, scoring_profile_id, calculated_on)`; history is never overwritten, so score movement is
queryable and the assistant can explain "why did this rise?".

Weights live in `scoring_profiles.weights` (JSONB, validated to sum to 1.0 ± 0.001) and profiles are
immutable once used: editing creates a new version. That keeps historical scores interpretable.

---

## 10. Profitability and GST (PRD §4.6)

Pure function `calculate_profit(inputs, assumptions) -> outputs`, unit-tested against a table of
worked examples.

**Model assumptions (all configurable in `profit_assumptions`):**

- AUD; GST rate 10%; platform is built for a GST-registered business (`gst_registered` toggle).
- Consumer-facing prices are **GST-inclusive** (Australian consumer law). `price_ex_gst =
  price_inc_gst / 1.1`.
- Landed cost is GST-inclusive too when the supplier charges Australian GST (e.g. low-value imported
  goods regime); the GST portion is an input tax credit for a registered business, so it is **excluded
  from cost** when `claim_input_tax_credit = true` (PRD §4.6's explicit rule). The calculator reports
  both the cash cost and the tax-adjusted economic cost.
- Import duty is computed as `customs_value × duty_rate` (default 0%, configurable; duty is a real
  cost, not recoverable).
- Payment fees are charged on the GST-inclusive amount (e.g. 1.75% + A$0.30).
- Outputs: landed cost, ex-GST price, gross profit, contribution margin (after payment + fulfilment +
  CAC), break-even CAC, profit per order, monthly profit at 100/500/1,000/5,000 orders, and the
  return/refund allowance effect.

Rounding is decimal (never float); money is `Numeric(12,2)` in the DB and decimal strings in JSON.

---

## 11. AI layer (Phase 4, interface designed now)

- `ai/llm.py` defines `LLMProvider.complete(messages, tools, response_schema)`. The OpenAI
  implementation is the PRD default; a deterministic `FakeProvider` is used in tests and demo mode.
  Model is configurable per deployment (`OPENAI_MODEL`), never hard-coded at call sites.
- **Retrieval only through tools** that wrap the same services the API uses: `search_products`,
  `get_product`, `get_trend_series`, `compare_products`, `get_competition`, `list_suppliers`,
  `calculate_profit`, `list_categories`, `get_report`. The assistant cannot query the DB directly, so
  every number it can say is reproducible through an API call.
- **Structured output** (PRD §4.8): `{answer, claims: [{text, evidence_type, source_refs,
  retrieved_at}]}` where `evidence_type ∈ {verified, estimated, model_generated, unavailable}`.
  Claims of type `verified` must carry at least one `source_ref` resolving to a stored observation or
  score id; the validator rejects otherwise. Missing data is answered with "not available", not a
  plausible number.
- **Guardrails:** no supplier availability claims unless `supplier_products.last_checked_at` is within
  the freshness window; token/tool-call budgets per request; every conversation persisted with the
  tool outputs used; prompt-injection-safe treatment of provider text (product titles are data, never
  instructions).
- Phase 1–3 ship the interface and the tool layer but not the UI; `POST /assistant/query` returns
  `501` until Phase 4 unless `ENABLE_ASSISTANT=true`.

---

## 12. Frontend architecture

- App Router with route groups: `(app)` for authenticated shell, `(auth)` for login.
- Server Components fetch from the API with the user's token held in an httpOnly cookie; interactive
  tables use TanStack Query against `/api/v1`.
- **Types are generated** from OpenAPI (`npm run gen:api`); a schema mismatch fails CI. No hand-copied
  interfaces.
- Charting: Recharts line/area for trend series, bar for category comparisons, sparkline in tables.
  Charts must render "insufficient data" states, not empty axes.
- Every product surface displays the data-quality block: coverage, confidence, last updated, source
  list, synthetic badge. This is a product requirement (PRD §2, §4.7), implemented as a shared
  component so it cannot be forgotten on a new page.
- Explorer state lives in the URL (shareable filters). Sorting/filtering is server-side.
- Dark/light via CSS custom properties with `prefers-color-scheme`, matching PRD §11.
- Accessibility: keyboard-navigable tables, chart data available as a table toggle, WCAG AA contrast.

Navigation maps 1:1 to PRD §11's twelve items; "Settings" holds data sources, scoring profiles,
profit assumptions, and users.

---

## 13. Cross-cutting concerns

| Concern | Decision |
|---|---|
| Config | pydantic-settings, `.env` in dev, no secrets in DB, no secrets in logs |
| Logging | structlog JSON, `request_id`/`job_id`/`source_id` bound to every line |
| Errors | typed domain errors → RFC 7807-style envelope; no stack traces to clients |
| Auth | Argon2id, short-lived access JWT (15 min) + rotating refresh token in httpOnly cookie (7 days) |
| RBAC | `admin` (weights, sources, merges), `analyst` (all research + watchlist), `viewer` (read) |
| Rate limits | per-IP on auth; per-user on assistant and exports; per-provider token buckets |
| Caching | Redis: dashboard 60 s, product detail 30 s with ETag; invalidated by recalc jobs |
| Audit | all mutations write `audit_logs` with actor, entity, diff, request id |
| Uploads | CSV max 10 MB, MIME + extension check, streaming parse, row-level error report |
| SSRF | connector URLs come from config allow-list, never user input |
| Migrations | Alembic, reviewed, one head, applied at deploy start |
| Time | store UTC `timestamptz`; schedule and present in `Australia/Sydney` |

---

## 14. Deployment topology

**Local / demo (acceptance criterion 1):**

```
docker compose up
  postgres:16 · redis:7 · api (uvicorn) · worker (celery) · beat · web (next start) · migrate (one-shot)
```

Seeded with the category tree, default scoring profile, profit assumptions, `csv_import` + `mock`
sources enabled, and optionally a labelled demo dataset (`make seed-demo`).

**Production (later):** stateless API/worker on ECS/Fargate or Azure Container Apps; managed
PostgreSQL (with `pg_trgm`, later `pgvector`); managed Redis; S3 for report artefacts; secrets in
AWS Secrets Manager / Key Vault injected as env; scheduled tasks via Celery beat on a single replica
(or a scheduler service). No architectural change is required — only config.

---

## 15. Non-goals for the MVP

- No scraping, CAPTCHA solving or anti-bot circumvention, ever (PRD §12).
- No claimed sales volumes without a provider that actually reports sold units.
- No Amazon or TikTok live data in Phase 1 (see [`04-data-source-assessment.md`](04-data-source-assessment.md)).
- No multi-country UI beyond a `country` filter that is wired but seeded with AU only.
- No pgvector semantic matching, anomaly detection or forecasting in Phase 1.
- No payments, catalogue publishing, or Shopify/WooCommerce write-back.
