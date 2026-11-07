# TrendScope AI — Phase 1

Australian eCommerce product-intelligence platform. TrendScope combines relative
search interest, marketplace listings and supplier offers into an evidence-aware
opportunity score, then lets you research candidates through a watchlist and
weekly reports.

**Phase 1 is a runnable prototype.** It ships a deterministic synthetic provider
and a CSV importer. Every synthetic record is labelled. No live marketplace,
price, sales or supplier data is fabricated into the product, and no provider is
scraped or accessed around its controls.

---

## Quick start (Docker)

Requirements: Docker Engine with Compose v2, and ports 3000 and 8000 free.

```bash
cp .env.example .env          # optional; the compose file has working defaults
docker compose up --build
```

On first boot the backend applies Alembic migrations, seeds 16 categories, the
data-source registry, an admin account and the scoring profile, then runs one
mock sync (48 products, up to 400 days each; newly discovered products carry
25 days). That takes roughly a minute; later boots reuse the existing data.

| Service | URL |
| --- | --- |
| Web app | http://localhost:3000 |
| API | http://localhost:8000/api/v1 |
| OpenAPI docs | http://localhost:8000/api/docs |
| Health | http://localhost:8000/health |

Sign in with the seeded local account:

```text
admin@trendscope.app / admin123
```

Change `ADMIN_PASSWORD` and `SECRET_KEY` before any shared deployment.

```bash
make logs       # follow logs
make down       # stop, keep the database volume
make clean      # stop and delete the database volume
```

## Quick start (local, no Docker)

The backend falls back to SQLite when `DATABASE_URL` is not set, which is enough
for the demo and the test suite. Celery is optional; the API works without it.

```bash
# terminal 1 — API
make backend-install
make seed                     # schema + reference data + demo sync
make dev-backend              # http://localhost:8000

# terminal 2 — web
make frontend-install
make dev-frontend             # http://localhost:3000
```

The frontend proxies `/api/backend/*` to `http://localhost:8000/api/v1` through a
Next.js rewrite, so the browser never needs cross-origin access. Set
`API_INTERNAL_URL` to change the target.

### Optional background jobs

```bash
docker compose up -d redis
cd backend
.venv/bin/celery -A app.jobs.celery_app.celery_app worker --loglevel=info
.venv/bin/celery -A app.jobs.celery_app.celery_app beat --loglevel=info
```

Schedules run in **Australia/Sydney**:

| Job | Schedule | Purpose |
| --- | --- | --- |
| `mock-sync-daily` | 02:00 daily | Extend mock observations one day |
| `recompute-scores-daily` | 03:00 daily | Recompute metrics and scores |
| `weekly-report-monday` | Monday 06:00 | Generate the weekly trend report |

---

## What Phase 1 includes

- **Catalogue** — 16 categories, search, composition filters (category, score,
  growth, competition, price, margin, supplier availability), 10 sort orders,
  pagination, CSV export.
- **Ingestion** — deterministic mock provider (48 products, up to 400 days,
  keyed on `(slug, date)`, idempotent), CSV import with per-row validation and
  line-number errors, manual product entry.
- **Trend analysis** — 7/30/90-day comparisons, trend direction, staleness,
  monthly means and a 12-month seasonality index.
- **Opportunity scoring** — six weighted components, coverage gating, confidence
  shrinkage, an explicit reason for every unavailable component.
- **Competition evidence** — listing count, price dispersion and review
  concentration; classified `unknown` below two independent signals.
- **Profitability** — GST-aware contribution margin from the cheapest supplier
  offer, shown as an estimate.
- **Dashboard** — eight ranked widgets plus summary KPIs and source health.
- **Product detail** — trend chart, score breakdown, competition evidence,
  listings, supplier offers, provenance and data-quality panel.
- **Watchlist** — statuses, priority, notes, CSV export, 2–5 product comparison.
- **Reports** — weekly snapshots with top growth, opportunities, emerging,
  category mix, unavailable-data counts, limitations and CSV/JSON download.
- **Auth** — Argon2id passwords, JWT bearer tokens, roles `admin`, `analyst`,
  `viewer`.
- **Tests** — 68 backend unit and integration tests.

## Architecture at a glance

```text
Next.js 15 (App Router)  ──/api/backend rewrite──▶  FastAPI /api/v1
                                                     │
                                        SQLAlchemy 2.0 ORM
                                                     │
                              PostgreSQL 16  ◀── Alembic migrations
                                                     ▲
        Celery worker + beat ── Redis ───────────────┘
```

Key design points:

1. **Raw history is append-only.** `trend_observations` is never updated in
   place; a natural key on `(product, source, date, metric)` makes re-ingestion
   idempotent.
2. **Reads never aggregate raw history.** Ingestion writes `product_metrics` and
   `opportunity_scores` snapshots. Every read path joins the latest snapshot.
3. **Missing data stays missing.** A growth value that cannot be computed is
   `null` with a reason code (`no_source`, `insufficient_current_data`,
   `insufficient_baseline`, `zero_baseline`, `stale_data`). It is never coerced
   to zero.
4. **Coverage gates scoring.** Below 60% data coverage a product classifies as
   `insufficient_data`; above it, the raw score is shrunk toward 50 by coverage
   confidence and the unavailable component weights are renormalised.
5. **Synthetic provenance travels.** `is_synthetic` is carried from observations
   through metrics, scores, suppliers and API payloads into the UI.

### Phase 1 deviations from the design documents

Recorded here so the documents and code do not silently disagree:

- **SQLAlchemy is synchronous.** The architecture document sketched an async
  ORM. Phase 1 uses SQLAlchemy 2.0's sync API with psycopg2. The ingestion and
  query paths are CPU/I/O-light; sync sessions keep the code readable and the
  SQLite test harness simple. Moving to async would not change the API contract.
- **Sync, import and report generation are synchronous.** They return `202` with
  a completed job record rather than polling a Celery task. The Celery worker and
  beat are wired for scheduled runs; the interactive endpoints stay synchronous
  in Phase 1 to keep local setup frictionless.
- **Only the mock provider and CSV importer are enabled.** Other providers are
  registered with explicit availability status and refuse sync with `501`.
- **Watchlist compare accepts product IDs.** The contract sketch used watchlist
  entry IDs; the UI sends `product_ids` because an entry can be removed while
  the comparison stays useful.

## Data sources

| Provider | Phase 1 status | Notes |
| --- | --- | --- |
| Mock (`mock`) | **Enabled, synthetic** | Deterministic generator; no external calls |
| CSV import (`csv_import`) | **Enabled** | UTF-8, 2 MB limit, per-row validation |
| Google Trends (`google_trends`) | Registered, disabled | Requires authorised access |
| eBay AU (`ebay_au`) | Registered, disabled | Marketplace listings only, no sales |
| Exploding Topics (`exploding_topics`) | Registered, disabled | Paid API |
| Amazon AU (`amazon_au`) | **Unavailable** | No first-party product API for AU |
| TikTok (`tiktok`) | **Unavailable** | Creative Center not accessible from AU |
| CJ Dropshipping (`cj_dropshipping`) | Registered, disabled | Supplier catalogue, authorised API |

No provider is contacted in Phase 1. Providers activate only with credentials
supplied through environment variables and terms-compliant access.

## Scoring model

Weights live in an active, versioned scoring profile:

| Component | Default weight | Evidence |
| --- | --- | --- |
| Demand | 0.25 | 7-day and 30-day search growth |
| Marketplace | 0.25 | Active listings, review velocity |
| Social | 0.15 | Unavailable in Phase 1 |
| Competition | 0.15 | Listing count, price dispersion, review HHI |
| Profitability | 0.15 | GST-aware contribution margin |
| Seasonal | 0.05 | Seasonality index (needs 12 months) |

The stored score is the **adjusted** score; the raw weighted score is kept
alongside it. Every product detail shows both, the component inputs, the weights
and the reason a component was unavailable.

Contribution margin, for the profitability score only:

```text
revenue      = market price
marketplace  = 1.75% of revenue + $0.30
fulfilment   = $8.50
packaging    = $1.20
returns      = 2% of revenue
GST          = revenue / 1.10   (remitted, not revenue)
contribution = revenue/GST basis − marketplace − fulfilment − packaging − returns
```

## API

The OpenAPI document is served at `/api/v1/openapi.json` and browsable at
`/api/docs`. Main resources:

```text
POST /api/v1/auth/login              GET /api/v1/auth/me
GET  /api/v1/dashboard                GET /api/v1/dashboard/summary
GET  /api/v1/products                 POST /api/v1/products
GET  /api/v1/products/{slug|id}       PATCH/DELETE /api/v1/products/{id}
GET  /api/v1/products/{id}/trends     GET /api/v1/products/{id}/score
POST /api/v1/products/import/csv      GET /api/v1/products/import/csv/template
GET  /api/v1/trending                 GET /api/v1/emerging
GET  /api/v1/opportunities            GET /api/v1/seasonal
GET  /api/v1/categories               POST /api/v1/categories
GET  /api/v1/watchlist                POST /api/v1/watchlist
POST /api/v1/watchlist/compare        GET /api/v1/watchlist/export
GET  /api/v1/reports                  POST /api/v1/reports
GET  /api/v1/reports/{id}/download    GET /api/v1/exports/products
GET  /api/v1/data-sources             POST /api/v1/data-sources/{id}/sync
GET  /api/v1/sync/status              GET /api/v1/scoring-profiles
```

Money is serialised as decimal strings, timestamps as ISO 8601 UTC, and errors
use a consistent envelope:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "details": [], "request_id": "..." } }
```

## Tests

```bash
make test
# 68 passed
```

The suite runs against a temporary SQLite database per test. It covers growth
window arithmetic, missing-data reasons, scoring renormalisation and shrinkage,
competition classification, normalisation/slugging, auth, product reads, watchlist
behaviour, CSV import validation, dashboard/report generation and sync
idempotency.

Alembic schema drift check:

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic check
```

## Project layout

```text
backend/
  app/
    api/v1/          route modules
    connectors/      base types, mock provider, catalogue
    core/            config, database, security, errors
    jobs/            Celery app and tasks
    services/        growth, scoring, metrics, ingestion, catalog, reports…
    main.py          FastAPI application
  alembic/           migrations
  tests/             unit and integration tests
frontend/
  src/app/           routes: dashboard, products, trending, categories,
                     watchlist, reports, sources, login
  src/components/    shell, auth provider, tables, UI primitives
  src/lib/           API client, types, formatting, fetch hook
docs/                architecture, ERD, API contract, source assessment, plan
sample_data/         CSV import example
docker-compose.yml   db, redis, backend, worker, beat, frontend
```

## Phase 1 acceptance (PRD §15)

| # | Criterion | Where |
| --- | --- | --- |
| 1 | Runs locally with Docker Compose | `docker compose up --build` |
| 2 | Dashboard with summary and widgets | `/` |
| 3 | Product discovery and CSV import | `/trending`, `/products` → Import CSV |
| 4 | Categories and search | `/categories`, product filters |
| 5 | Observation history stored | `trend_observations`, product detail chart |
| 6 | 7/30/90-day comparisons | Product rows, detail, `/trending` |
| 7 | Opportunity scores with breakdown | `/products/{slug}` |
| 8 | Missing data never shown as zero | reason codes + data-quality panel |
| 9 | Product detail charts | `/products/{slug}` trend chart |
| 10 | Watchlist | `/watchlist` |
| 11 | Weekly reports | `/reports` |
| 12 | CSV export | Products, watchlist, report downloads |
| 13 | Mock demo data clearly labelled | `is_synthetic` throughout the UI |
| 14 | Automated tests | `backend/tests`, `make test` |
| 15 | Documentation | `docs/`, this README |

## Limitations and next phases

- Social signal, Amazon AU and TikTok data are unavailable; the score renormalises
  around their absence and says so.
- Marketplace listings are not sales. Review counts and listing counts are
  proxies only.
- Supplier costs and margins are estimates from a synthetic catalogue.
- Phase 1 endpoints run ingestion synchronously; Phase 2 moves the interactive
  jobs onto Celery with pollable job resources.
- Real providers require authorised API access, credentials and terms review
  before they are enabled.
