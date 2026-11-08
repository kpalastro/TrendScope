# 05 — Implementation Plan

**Approach:** PRD §14/§16 — build Phase 1 to a working MVP, verify it, then proceed. Each milestone
below is independently reviewable and ends with passing tests, updated docs and a written summary of
implemented vs outstanding work.

**Estimated effort:** Phase 1 ≈ **24–32 engineer-days** for one senior full-stack engineer, assuming
the open decisions in §6 are answered before M4. Phases 2–4 are estimates, not commitments.

## 0. Status (2026-11-08)

Phase 1 is implemented on the `phase-1-completion` branch. This table records what the codebase
actually covers against the milestones below; unlisted work is still planned.

| Milestone | Status | Notes |
|---|---|---|
| M0 Foundation | Done | Compose stack, health endpoints, structured errors, request IDs |
| M1 Schema and seed | Done | Migrations `0001`–`0003`; seeders and constraint tests |
| M2 Catalogue API | Done | Catalogue, rotating refresh tokens, logout, RBAC, audit log |
| M3 Import and dedup | Done | CSV import, identifier-first matching, fuzzy review queue, non-destructive merge |
| M4 Free-first connectors | Done | See [`06-free-first-gap-analysis.md`](06-free-first-gap-analysis.md) |
| M5 Metrics | Done | Growth guards, coverage, competition, discovery read models |
| M6 Scoring | Done | Profiles, explainable scores, `POST /scores/recalculate` |
| M7 Frontend | Done | Shell, dashboard, explorer, product detail, watchlist |
| M8 Reports and export | Done | GST profit calculator with saved scenarios; CSV/JSON/XLSX reports |
| M9 Hardening | Partial | Backend suite green (126 tests) and production build clean; PDF export, Playwright smoke, accessibility audit and the 10k-product performance check remain |

---

## 1. Sequencing principle

Backend and schema first, then the pipeline, then the UI — because the PRD's correctness requirements
(growth guards, score explainability, provenance) live in the backend and are cheap to test there and
expensive to retrofit through a UI.

```
M0 Foundation → M1 Schema → M2 Catalogue API → M3 CSV import + dedup
   → M4 Connector framework + Google Trends → M5 Metrics → M6 Scoring
   → M7 Frontend shell + Explorer + Product → M8 Watchlist + Reports/Export
   → M9 Hardening + acceptance
```

M4 (live data) can run in parallel with M7 (UI) once M2 is stable, because the API contract is fixed
in [`03-api-contract.md`](03-api-contract.md).

---

## 2. Phase 0 / M0 — Foundation (2–3 days)

**Deliverables**
- Git repository initialised; `.gitignore`, `.editorconfig`, `Makefile`.
- `docker-compose.yml`: `postgres:16`, `redis:7`, `api`, `worker`, `beat`, `web`, one-shot `migrate`.
- Backend skeleton: FastAPI factory, settings via pydantic-settings, structlog JSON logging,
  request-id middleware, exception handlers for the error envelope, `/health` and `/health/ready`.
- Frontend skeleton: Next.js + TS + Tailwind + shadcn/ui, app shell, placeholder routes for all 12
  navigation items.
- Alembic configured (async URL for app, sync for migrations).
- pytest + `docker-compose.test.yml` (disposable Postgres/Redis), coverage config, ruff/black/mypy.
- CI workflow: lint → typecheck → unit → integration → frontend build.
- `.env.example` with every variable and a safe default; no secrets committed.
- `README.md` with `docker compose up` instructions.

**Exit criteria**
- `docker compose up` starts all services; `/health/ready` returns 200; the web shell renders.
- `make test` passes (with the trivial health test only).
- CI green on an empty feature branch.

---

## 3. Phase 1 milestones

### M1 — Database schema and seed data (3–4 days)

**Deliverables:** all migrations from [`02-database-erd.md`](02-database-erd.md) §8; ORM models;
repositories for products/categories/sources; seeders for the 16-category tree + subcategories, the
default AU scoring profile (PRD weights), profit assumptions, and provider registry rows.

**Tests:** migration up/down/up on empty DB; constraint tests (unique identifier, unique watchlist,
duplicate category name under one parent, observation natural key); seed idempotency.

**Exit criteria:** `alembic upgrade head` from empty; `make seed` twice yields identical row counts;
all constraint tests pass.

---

### M2 — Catalogue API and explorer read model (4–5 days)

**Deliverables**
- `GET/POST/PATCH/DELETE /products*`, `/categories*`, `/products/{id}` with `data_quality` block.
- Trigram search, all filters and sorts from the API contract; cursor pagination for time series.
- Auth (login/refresh/logout/me), RBAC dependency, audit logging on mutations.
- OpenAPI export + `openapi-typescript` generation in CI.

**Tests:** endpoint contract tests (status codes, envelopes, authz per role); filter/sort
combinations; pagination edges; error envelope shape; 401/403/404/409 matrix.

**Exit criteria:** PRD §15.2 and §15.4 satisfied; published OpenAPI matches this document; RBAC
covered by tests for every mutating route.

---

### M3 — CSV import and deduplication (3–4 days)

**Deliverables**
- `POST /products/import/csv` (multipart, 10 MB cap), streaming parse, per-row validation report.
- Template download, dry-run mode (`?dry_run=true`), row-level errors returned in the job result.
- Normaliser (title cleanup, variant stripping, unit/currency parsing).
- Matcher: identifier → exact name+brand → trigram candidates; `product_matches` queue; merge service
  with cycle protection and audit.
- Job abstraction + `GET /jobs/{id}`.

**Tests (PRD §13):** product discovery from a CSV; dedup exact and fuzzy; merge does not orphan
observations; malformed rows rejected without aborting the batch; duplicate import is idempotent;
10 MB limit enforced.

**Exit criteria:** PRD §15.3; importing the same file twice creates no duplicates; every merged pair is
reversible in the audit log.

---

### M4 — Connector framework and free-first providers (4–6 days) — **supersedes decision D1**

**Deliverables**
- `BaseConnector` lifecycle (`fetch_data`, `validate_data`, `normalize_data`, `get_source_status`,
  `get_last_sync`, `handle_errors`), registry, `data_sources` wiring, `ingestion_runs` bookkeeping.
  Implemented synchronously in Phase 1; per-source locks and retry/rate-limit hooks remain the
  documented extension points.
- Free-first plugins: `mock`, `csv_import`, `google_trends` (manual fallback), `google_bigquery_trends`
  (public dataset, optional credentials), `ebay_au` (Browse API, active listings), `meta_ad_library`
  (advertising only), `amazon_public_research` and `tiktok` (manual fallbacks), legacy `amazon_au`
  (unavailable), plus disabled optional plugins `exploding_topics` (paid) and `cj_dropshipping`.
- `GET/PATCH /data-sources`, `test-connection`, `POST /sync`, `/sync/status`, `/data-sources/{id}/runs`.
- Cost/usage/availability fields on every source; no provider is enabled merely by having a web
  subscription.
- Celery app + beat schedule with `Australia/Sydney`; `job_schedules` sync.

**Tests (PRD §13):** connector status derivation per availability state (no network); unconfigured
sync returns `503` with a reason; one provider failing does not stop others; observation idempotency
on re-ingest; provenance round-trip; secrets never serialised in `test-connection` responses.

**Exit criteria:** with only `mock`, CSV and manual entry, the pipeline populates observations
end-to-end and the app runs with zero data subscriptions; with valid credentials, a real provider can
be enabled without touching scoring or schema.

---

### M5 — Metric computation (3–4 days)

**Deliverables:** windows 7/30/90/180/365; growth with every guard from architecture §8.1 and stored
reason codes; coverage/confidence; trend direction; competition index and classification with the
evidence-coverage rule; seasonality once ≥12 months exist; daily `product_metrics` snapshot job;
`/trending`, `/emerging`, `/opportunities`, `/seasonal`, `/products/{id}/trends|metrics`, dashboard
read models.

**Tests (PRD §13):** growth percentage maths against hand-computed fixtures; zero baseline → null +
`zero_baseline`; sparse window → `insufficient_current_data`; stale data; extreme growth clamp; no
`0%` is ever emitted for a null; recomputation is deterministic (same inputs → same snapshot);
competition class `unknown` below two evidence inputs.

**Exit criteria:** PRD §15.5 and §15.6; a golden fixture dataset produces exact expected values for all
five windows; deleting and recomputing a date reproduces byte-identical metrics.

---

### M6 — Scoring engine and competition API (3–4 days)

**Deliverables:** six component calculators; percentile normalisation with cohort fallback; missing-data
weight renormalisation; confidence shrinkage; classification with the `insufficient_data` gate;
`scoring_profiles` CRUD/versioning/activation; `POST /scores/recalculate`;
`GET /products/{id}/score`, `/competition/summary`, `/products/{id}/competition`; profile immutability.

**Tests (PRD §13):** every component in isolation; all-missing → `insufficient_data`; one-component
evidence cannot yield an "excellent" classification; weights must sum to 1.0; score history preserved;
profile edit creates a new version and old scores still resolve.

**Exit criteria:** PRD §15.7 and §15.8; a property-based test asserts `coverage < 0.60 ⇒
classification == insufficient_data`; a test asserts missing data never raises the score relative to
the same data with the component explicitly scored at the cohort median (the PRD's anti-inflation rule).

---

### M7 — Frontend: shell, dashboard, explorer, product detail (4–5 days)

**Deliverables**
- Auth pages; sidebar navigation per PRD §11; light/dark mode; responsive layout.
- Dashboard: KPI tiles, 8 widgets, data-source health, sync time, demo-data banner.
- Explorer: search-first, URL-state filters, sortable table, CSV export button.
- Product detail: all 18 PRD §4.7 fields, trend chart with multi-window toggle, score breakdown with
  per-component explanation, competition panel, supplier panel, confidence/coverage block.
- Shared `DataQualityBadge` and `NotEnoughData` components used everywhere.

**Tests:** component tests for chart empty states and the quality badge; Playwright smoke — login →
dashboard → filter explorer → open product → chart renders → watchlist add; axe accessibility check on
primary pages; visual check at 375 px and 1440 px.

**Exit criteria:** PRD §15.9; no page shows `0%` growth, a raw score without coverage, or an
unlabelled synthetic data point.

---

### M8 — Watchlist, profit calculator, reports, CSV export (3–4 days)

**Deliverables**
- Watchlist CRUD, statuses from PRD §5.3, notes, compare (2–5 products), export.
- Profit calculator UI + `POST /profit/calculate`, assumptions endpoint, saved scenarios.
- Weekly report builder (PRD §10: top 20 trending, fastest-growing, new emerging, declining, category
  movements, catalogue recommendations) → `research_reports` + CSV; XLSX and PDF renderers.
- `GET /exports/products`, `/exports/watchlist`.
- Disclaimers/sources/limitations block on every report.

**Tests (PRD §13):** GST calculation table (registered/not registered, GST-inclusive vs exclusive,
input-tax-credit on/off, duty); margin/break-even maths; report generation with empty and sparse data;
CSV escaping; report idempotency (`UNIQUE (report_type, country, period_start)`).

**Exit criteria:** PRD §15.10, §15.11, §15.12; a weekly report generated from demo data contains
sources and limitations; calculator results match hand-worked examples to the cent.

---

### M9 — Hardening and acceptance (2–3 days)

- Full test matrix (§5) green; coverage ≥ 80% on `services/`, `pipeline/`, `connectors/base.py`.
- `make demo` brings up the stack with labelled synthetic data and a working weekly report.
- README: setup, configuration, provider credentials, troubleshooting, architecture links.
- Acceptance walkthrough against PRD §15 items 1–15, recorded line by line.
- Performance sanity: 10k products, explorer p95 < 500 ms, dashboard p95 < 800 ms.

**Exit criteria:** every PRD §15 criterion demonstrably passes or is explicitly reported as not met
with a reason. This is the Phase 1 gate; Phase 2 does not start before it.

---

## 4. Phases 2–4 (outline only)

### Phase 2 — Market intelligence (≈15–20 days, gated on D2)
eBay AU Browse API (listings/prices/competition; sold data only if Marketplace Insights is granted);
Amazon via mock until a licensed vendor + legal approval; Exploding Topics CSV; manual social import;
competition analysis UI; price monitoring; product comparison; weekly/monthly report automation.
**Blocked items are reported, not faked.**

### Phase 3 — Supplier intelligence (≈12–18 days)
CJ API v2 connector (with points budget and 30-day-activity risk handling); AliExpress Open Platform
behind an approved app; CSV supplier feeds; landed-cost comparison; profitability per supplier;
catalogue export.

### Phase 4 — AI intelligence (≈12–16 days)
LLM provider abstraction, tool layer over existing services, structured claims with citations,
assistant UI with SSE, AI market summaries, emerging/anomaly detection, seasonal forecasting.
Every phase-4 feature depends on the evidence layer built in phases 1–3; it is not a substitute for it.

---

## 5. Test matrix (PRD §13 traceability)

| PRD §13 requirement | Where | Milestone |
|---|---|---|
| Product discovery | `tests/integration/discovery` + CSV fixture | M3, M4 |
| Product deduplication | `tests/unit/matching`, DB constraint tests | M1, M3 |
| Data normalisation | `tests/unit/normalise` (titles, units, currencies) | M3 |
| Historical trend calculations | `tests/unit/metrics` golden fixtures | M5 |
| Growth percentage calculations | `tests/unit/growth` incl. guards | M5 |
| Opportunity score calculations | `tests/unit/scoring` + property tests | M6 |
| Missing data handling | `tests/unit/scoring_missing` | M6 |
| Profitability calculations | `tests/unit/profit` | M8 |
| GST calculations | `tests/unit/gst` table-driven | M8 |
| API failures | `tests/contract/connectors` fault injection | M4 |
| Retry behaviour | `tests/unit/retry` | M4 |
| Database operations | `tests/integration/repositories` | M1, M2 |
| Report generation | `tests/integration/reports` | M8 |

Additional required tests: auth/RBAC matrix, observation idempotency, merge safety, synthetic-data
labelling, OpenAPI contract diff, Playwright smoke, accessibility check.

**Test data policy:** all fixtures are either synthetic (clearly named) or recorded provider responses
with secrets stripped. No real customer data, no copied marketplace listings stored in the repo.

---

## 6. Open decisions (needed before the stated milestone)

| # | Decision | Options | Recommendation | Needed by |
|---|---|---|---|---|
| **D1** | Google Trends data route | **Free-first (adopted 2026-11-08):** manual CSV export + public BigQuery `google_trends` dataset · DataForSEO (~US$165/mo) · SerpApi · official alpha · `pytrends` (rejected: archived, brittle, ToS risk) | **Free routes for the MVP.** Revisit a paid intermediary only after 60–90 days of own collected history shows the free route's coverage is the limiting factor. See [`06-free-first-gap-analysis.md`](06-free-first-gap-analysis.md). | M4 (resolved) |
| **D2** | Amazon AU strategy | Mock-only (Phase 2) · licensed scraping vendor + legal review · defer entirely | **Mock-only until legal sign-off**; do not spend on a vendor before Phase 1 acceptance | Phase 2 |
| **D3** | Social signal | No live source · licensed TikTok data vendor · manual/CSV research | **Manual/CSV + mock now**; revisit when a vendor is contracted | Phase 2 |
| **D4** | Tenancy | Single-tenant, one workspace, multiple users with roles (proposed) · multi-tenant SaaS | **Single-tenant**; schema already carries `user_id`, so multi-tenant is additive later | M2 |
| **D5** | Report formats at MVP | CSV only · CSV + XLSX · CSV + XLSX + PDF | **CSV + XLSX** at MVP; PDF via WeasyPrint if delivery accepts the heavier dependency | M8 |
| **D6** | Demo dataset | No seed data · labelled synthetic dataset | **Labelled synthetic dataset** (`make seed-demo`) — required by PRD §15.13, must display a "Demo data" badge | M0/M9 |
| **D7** | Deploy target after local | AWS ECS · Azure Container Apps · single VPS | Not needed for MVP; compose only. Decide before M9 if a staging URL is wanted | post-MVP |

---

## 7. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Google Trends scaling makes cross-run growth comparisons invalid | High | High | Store request window in metadata; re-fetch consistent windows; dedicated test; document in methodology |
| Provider terms change / pricing rises (Trends, Exploding Topics) | Medium | Medium | Connector abstraction + CSV fallback + per-source disable; monthly cost review |
| Amazon/TikTok never become legally available | Medium | Medium | Product designed for partial data; scoring renormalises; UI states limitations |
| Data coverage so thin that scores are misleading | High at launch | High | Coverage gate (`<0.60` → `insufficient_data`), confidence shrinkage, visible coverage everywhere |
| Scope creep into Phase 2 during Phase 1 | High | High | PRD §14 and the M9 gate; Phase 2 items are explicitly out of scope |
| CJ API revoked for zero-transaction accounts (Phase 3) | Medium | Medium | CSV fallback; monitor `last_checked_at`; flag stale supplier data |
| CSV imports with hostile content (formula injection in exports) | Medium | Medium | Escape leading `=`, `+`, `-`, `@` in CSV/XLSX outputs; size/row limits |
| Score weights tuned to look good on demo data | Medium | High | Profile versioning, immutable history, tests that missing data cannot inflate scores |
| Legal exposure from scraping vendors | Low–Medium | High | No scraping in code; vendor use only after written approval (D2) |

---

## 8. Definition of done (each milestone)

1. Acceptance criteria above met and demonstrated.
2. New/changed tests pass; full suite green; coverage threshold met.
3. Migrations reversible; seed idempotent.
4. API changes reflected in `03-api-contract.md` and regenerated frontend types.
5. Structured logs and error codes for new failure paths.
6. Docs updated (README/config/methodology).
7. Written summary: implemented, deliberately deferred, blockers.
8. No secrets, credentials or real market data in the repository.

---

## 9. PRD §15 acceptance checklist (Phase 1 gate)

| # | Criterion | Verified by |
|---|---|---|
| 1 | Runs locally via Docker Compose | M0 + M9 walkthrough |
| 2 | Dashboard accessible | M7 |
| 3 | Products discovered or imported | M3/M4 |
| 4 | Products categorised and searchable | M2/M7 |
| 5 | Historical observations stored | M1/M4 |
| 6 | Weekly/monthly/quarterly comparisons work | M5 |
| 7 | Opportunity scores calculated correctly | M6 golden tests |
| 8 | Missing data does not produce misleading results | M5/M6 property tests |
| 9 | Product detail shows historical trends | M7 |
| 10 | Watchlist | M8 |
| 11 | Weekly reports | M8 |
| 12 | CSV export | M8 |
| 13 | Mock integrations for demos | M4/M9 labelled synthetic data |
| 14 | Automated tests pass | CI |
| 15 | Setup documented | README + docs |

---

## 10. Immediate next actions

1. **Approve or amend D1–D7** (§6). D1 and D4 are hard blockers for M4 and M2 respectively.
2. Confirm the stack as specified (no changes proposed beyond additions in architecture §4.3).
3. Initialise git and scaffold M0.
4. Begin M1 schema work — it has no external dependency and unblocks everything else.
