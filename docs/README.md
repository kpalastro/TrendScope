# TrendScope AI — Planning Documents

**Status:** Phase 1 implemented. These documents remain the contract for Phases 2–4.
**Repository state at planning time:** empty directory, not a git repository.
**Specification:** TrendScope AI PRD v1.0 (Australian eCommerce product intelligence platform).
**Last updated:** 2026-11-08.

This `/docs` set is the contract for implementation. Phase 1 is implemented in `backend/` and
`frontend/`; the deviations and the current scope are recorded in the root [`README.md`](../README.md).
Phases 2–4 proceed per [`05-implementation-plan.md`](05-implementation-plan.md); anything marked
"decision" requires sign-off before the milestone that depends on it.

## Documents

| # | Document | What it settles |
|---|---|---|
| 01 | [Architecture](01-architecture.md) | System shape, module boundaries, connector framework, pipeline, scoring maths, security, deployment |
| 02 | [Database ERD](02-database-erd.md) | Tables, columns, keys, constraints, indexes, invariants, migration order |
| 03 | [API contract](03-api-contract.md) | REST surface, conventions, auth, error model, payload schemas |
| 04 | [Data-source assessment](04-data-source-assessment.md) | Which provider integrations are actually available in AU, which are blocked, what each costs |
| 05 | [Implementation plan](05-implementation-plan.md) | Milestones, exit criteria, test matrix, risks, open decisions |

## The five findings that shape this plan

1. **The repository is empty.** This is greenfield. No existing conventions to preserve; the stack in
   PRD §6 is adopted as-is.
2. **Google Trends has no public API.** The official API has been in application-only alpha since
   July 2025, and `pytrends` was archived in April 2025. Phase 1 therefore uses the free routes:
   manual CSV export and the public BigQuery `google_trends` dataset, behind a connector interface,
   with a deterministic mock. A paid intermediary (DataForSEO) is available as a disabled, optional
   plugin (`google_trends_dataforseo`) with explicit credentials and terms; it remains off by
   default until usage shows the free route is the limiting factor. See
   [`06-free-first-gap-analysis.md`](06-free-first-gap-analysis.md).
3. **Amazon Australia is not reachable through a legitimate first-party API.** PA-API 5.0 is being
   retired in favour of the Creators API, which has no bestseller endpoint and no `amazon.com.au`
   domain; Keepa has no AU catalogue either. Amazon data is mock-only until a licensed vendor and a
   legal review are approved. It is deliberately out of the MVP.
4. **TikTok Creative Center product trends are effectively unavailable.** There is no public API, the
   internal endpoint changed in October 2026, and the official Commercial Content API is EU/EEA/UK/CH
   only. Social scoring cannot be a live signal in Phase 1–2 in Australia.
5. **eBay sold-item data is restricted.** Finding API (`findCompletedItems`) was decommissioned in
   February 2025; Marketplace Insights is limited-release and not open to new users. eBay AU can
   supply *active listing* competition and prices via Browse API — never sales. The product must say
   "active listings", never "sales".

Consequence: the MVP scores from **Google Trends + CSV/manual import + eBay active listings (mock in
Phase 1)**, and the scoring engine is built for partial data from day one — which the PRD requires
anyway (§4.4).

## Naming conventions used throughout

- Provider keys: `google_trends`, `google_trends_dataforseo`, `google_bigquery_trends`, `ebay_au`,
  `amazon_au`, `amazon_public_research`, `meta_ad_library`, `tiktok`, `exploding_topics`,
  `cj_dropshipping`, `aliexpress`, `alibaba`, `csv_import`, `manual`, `mock`.
- Score components: `demand`, `marketplace`, `social`, `competition`, `profitability`, `seasonal`.
- Growth windows: `7d`, `30d`, `90d`, `180d`, `365d`.
- API and DB fields are `snake_case`; the TypeScript types in `frontend/src/lib/types.ts` mirror
  the API contract by hand, so no camelCase translation layer exists. Regenerating them from
  OpenAPI remains a follow-up (see `05-implementation-plan.md` M2).
