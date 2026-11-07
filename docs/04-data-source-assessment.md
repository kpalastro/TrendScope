# 04 — Data-Source Assessment (Australia, late 2026)

**Purpose:** PRD §16.15 requires the build to "clearly identify unavailable APIs, subscription
requirements and integration limitations", and §4.3 requires the app to work with partial data.
This document is the evidence base for which connectors can be real in each phase.

**Method:** Desk research against vendor documentation and 2026 industry write-ups (sources at §7),
performed 2026-11-07. **API terms and pricing change frequently — re-verify at the point of purchase
and before each phase gate.** Nothing here is a legal opinion.

---

## 1. Summary matrix

| Provider | PRD use | Real access in AU (2026) | Verdict | Phase |
|---|---|---|---|---|
| Google Trends | search interest, momentum | No public API. Official API = application-only alpha since Jul 2025. `pytrends` archived Apr 2025. Paid intermediaries available (DataForSEO, SerpApi, SearchApi, Glimpse). | **Available via paid intermediary** | 1 |
| eBay Australia | listings, prices, competition | Browse API available (OAuth client credentials). Sold/completed data: Finding API decommissioned Feb 2025; Marketplace Insights is limited-release, AU supported but **closed to new users**. | **Partial** — active listings yes, sales no | 2 |
| Amazon Australia | BSR, prices, reviews | PA-API 5.0 being retired (Creators API). No bestseller endpoint in v5; **no `amazon.com.au` domain** in PA-API or Keepa. Creators API needs an Associates account with 10 qualifying sales/30 days. AU BSR requires a licensed scraping vendor + legal review. | **Unavailable first-party** | 2 (gated) |
| TikTok Creative Center | trending products, hashtags, engagement | No public API. Internal `creative_radar_api` is signed and changed/broke in Oct 2026; product-trend leaderboard unavailable. Official Commercial Content API is EU/EEA/UK/CH only. | **Unavailable for AU** | blocked |
| Exploding Topics | emerging topics | API exists (v1.7.2, 60 req/min) but requires Pro Business (US$249/mo) **plus** API add-on from US$1,000/mo per 1,000 requests. CSV export available from the US$99 plan. | **Available but expensive** | 2–3 (CSV first) |
| CJdropshipping | supplier cost, MOQ, stock | API v2 self-serve: install app, create key. Points-based limits from Jun/Jul 2026 (50k points/day base). Access revoked after 30 days with zero transaction volume. | **Available** | 3 |
| AliExpress | supplier cost | Open Platform requires developer approval and per-category Value-Added API approval. Sep 2026 ToS update prohibits systematic data retrieval without written permission. | **Available with approval** | 3 (gated) |
| Alibaba | supplier cost, MOQ | Partner/developer program; not a general self-serve feed. | **Verify at Phase 3** | 3 |
| Manual CSV / manual entry | user-supplied research | Fully under our control. | **Available** | 1 |
| Mock connectors | demo without credentials | Built by us; must be labelled synthetic. | **Available** | 1 |

---

## 2. Google Trends — Phase 1's only live signal

### What is true in 2026

- There is still **no generally available public Google Trends API**. Google announced an official API
  on 24 July 2025; it remains an **application-only alpha** with no self-serve signup and no public
  endpoint reference. What it adds over the UI: a rolling ~1,800-day window, daily/weekly/monthly
  aggregation, ISO 3166-2 sub-region breakdowns, and consistently scaled data that can be merged
  across requests.
- Even the official API returns **relative search interest**, never absolute search volume. The PRD is
  correct that public volume counts are not exposed, and the product must never claim them.
- `pytrends` **was archived on 17 April 2025** (last release 4.9.2, April 2023). It still works
  intermittently but breaks when Google changes internal endpoints and is subject to undocumented
  429s. **It must not be the production connector.**

### Decision

Use a **paid, documented intermediary** — recommended **DataForSEO** (≈US$0.011 per live task,
pay-as-you-go, US$50 minimum deposit; five keywords per task; interest-over-time, region, related
queries in one task). SerpApi is the fallback (250 free searches/month, then ≈US$25/mo for 1,000).
Glimpse is the only option offering *absolute estimated volume* — consider it if the business needs
volume estimates, but it is a different claim and must be labelled "estimated".

Cost at MVP scale: 500 tracked products × 1 keyword each × daily ≈ 15,000 requests/month ≈ **US$165/mo**
at DataForSEO live-task pricing; weekly instead of daily ≈ US$38/mo. Start weekly, per-keyword, and
make frequency configurable.

### Connector shape

```
connectors/google_trends/
  base.py        # shared payload → ObservationBatch mapping
  dataforseo.py  # provider_key google_trends (production)
  serpapi.py     # provider_key google_trends_serpapi (alternative)
  mock.py        # provider_key mock (synthetic)
```

- One `data_sources` row per configured provider; `config = {"geo": "AU", "frequency": "weekly",
  "max_keywords_per_run": 200}`.
- Observations per keyword: `search_interest` daily points; `search_interest_region` for AU states;
  `related_query_interest` stored with `metadata.related_query`.
- **Scale caveat to encode:** Trends values are normalised per request window. Comparing absolute
  index values across different fetch dates is invalid unless the provider returns consistently
  scaled data. The connector must store `metadata.request_window` and the metric layer must only
  compute growth within a single consistently-scaled series (or re-fetch the full window each run).
  This is a real correctness trap; it gets a dedicated test.
- Optional: apply for the official alpha. If accepted, it becomes a fourth connector with no changes
  elsewhere.

---

## 3. Amazon Australia — do not build on it yet

- **PA-API 5.0 is being retired** in favour of the **Creators API**; existing signed calls return
  `AccessDeniedException`. The Creators API requires an accepted Amazon Associates account with **10
  qualifying sales in the trailing 30 days**, and credentials (1 TPS / 8,640 TPD initially).
- **There is no bestsellers endpoint** in PA-API 5.0 (the v4 `TopSellers` group was removed) and no
  `SortBy=BestSellers`. The documented workaround is to request `WebsiteSalesRank` per item and sort
  locally — but that requires knowing the ASINs already.
- **Australia is the recurring gap:** the official domain table omits `amazon.com.au`, and Keepa's
  documented domain IDs also skip Australia. So the usual "Keepa gives BSR history" route does not
  work for the AU marketplace.
- Amazon **SP-API** has no bestseller lists and is scoped to your own catalogue / authorising sellers.
- Practical AU options are licensed scraping vendors that take a `location=Australia` parameter
  (Rainforest API, Bright Data, Canopy, Apify actors). Using them carries ToS, reliability and legal
  questions that must be cleared by the business before code is written.

**Recommendation:** Phase 2 adds an `amazon_au` connector interface with a **mock** implementation
only. A live vendor connector is a separate, explicitly-approved work item once (a) a vendor is
chosen, (b) the business accepts the terms, and (c) legal review says proceed. Do not imply Amazon
sales data exists before then.

---

## 4. eBay Australia — listings yes, sales no

- **Browse API** (OAuth 2.0 client credentials, application token) is generally available and supports
  `EBAY_AU`. It returns **active** listings: titles, prices, sellers, categories, item counts. That
  supplies the competition and price-distribution inputs in PRD §4.5.
- **Finding API `findCompletedItems` was decommissioned on 4 February 2025.** Browse API was the named
  replacement but does not return sold/completed items.
- **Marketplace Insights API** (90-day sold history) lists EBAY_AU as a supported marketplace, but
  eBay labels it **limited release / not open to new users**; community reports confirm access
  requests are being declined. Existing business relationships may offer an approval path via an
  account manager.
- Third-party "sold listings" APIs exist but are either scrapers or resellers; they reintroduce the
  legal/ToS question.

**Recommendation:** implement `ebay_au` against Browse API in Phase 2 for **listings, prices and
competition only**. The UI and API must say "active listings", and `sold_count`/`units_sold` remain
unsupported metrics. If Marketplace Insights is later granted, add it behind the same provider key as
an extra metric source without schema change.

---

## 5. TikTok Creative Center — blocked in Australia

- No documented public API. The site calls an internal `creative_radar_api` requiring per-session
  signed headers (`anonymous-user-id`, `timestamp`, `user-sign`) and rejecting datacenter IPs.
- In **October 2026** the Creative Center moved to a new app and the legacy
  `/creative_radar_api/v1/popular_trend/` endpoints began returning
  `{"code":0,"data":null,"msg":"deprecated"}` — a silent failure that looks like success. The product
  trends leaderboard source is reportedly unavailable.
- The only official APIs are the Research API, Marketing API, and the **Commercial Content API**, and
  the latter covers **EU/EEA/UK/Switzerland only** (32 country codes, max 10 records per call).
- Trend feeds are also heavily advertising-distributed (industry sampling found most "trending"
  videos were ads), so engagement counts are a weak demand proxy even when obtainable.

**Recommendation:** no live TikTok connector. Phase 2 ships `tiktok` as **manual import + mock**.
If a licensed social-trend vendor is later procured (Kalodata/FastMoss-style or an Apify actor under
contract), it plugs in as a new provider key. The social score component stays `unavailable` and is
weight-renormalised away (per PRD §4.4) until then — which is exactly the behaviour the scoring engine
is designed for.

---

## 6. Exploding Topics, suppliers, CSV

**Exploding Topics** — API v1.7.2 exists (`/topics`, `/topic`, `/products`, `/meta-trends`,
`/database-search`, 60 req/min, `api_key` query param). Cost is the blocker: API access is an add-on to
Pro Business (US$249/mo) starting at **US$1,000/mo for 1,000 requests**. CSV export is available from
the **Investor plan (US$99/mo)**. Note the API does **not** support custom keyword/geo analysis.

*Recommendation:* implement `exploding_topics` as a **CSV import** connector in Phase 2; add the API
connector only if the subscription is approved. Do not budget it silently into Phase 1.

**CJdropshipping** — API v2 is self-serve: install the API app, create a key, exchange for a 180-day
access token. Since June/July 2026 rate limiting is **points-based** (50,000 points/day base, 10–1,000
points per call, 429 on exhaustion), and **API access is revoked after 30 consecutive days with zero
transaction volume**. That last rule is a real operational risk for a research-only platform: a CJ
account that never sells may lose API access. Design the connector to degrade to CSV import.

**AliExpress** — Open Platform requires developer registration, a described business scenario, and
approval; Value-Added APIs need per-category approval. A **26 September 2026** Terms of Use update
prohibits systematic data retrieval without written permission (with a conditional DSA research
exception). Therefore: official Open Platform only, with an approved app; no scraping.

**Alibaba** — access is via the Alibaba.com developer/partner programme rather than a public
self-serve feed. Confirm terms and cost at the Phase 3 gate.

**CSV / manual** — the universal fallback. Every provider gets a CSV import path, and the CSV importer
is generic enough to serve supplier feeds, Exploding Topics exports and manual research. This is why
Phase 1 ships it first.

---

## 7. What Phase 1 can honestly claim

With Google Trends (paid) + CSV/manual import + mock:

| PRD capability | Phase 1 status |
|---|---|
| Search interest and growth 7/30/90d | **Real** (relative index; documented) |
| Seasonal patterns | Real after 12 months of history; otherwise unavailable |
| Marketplace popularity / listing counts | Mock or CSV-imported; live eBay from Phase 2 |
| Social momentum | Unavailable until a licensed feed exists |
| Competition (full) | Estimated from imported/mock listings; live from Phase 2 |
| Profitability | Real arithmetic on user-supplied or imported supplier costs |
| Opportunity score | Real, with coverage/confidence honestly reduced |
| Amazon / TikTok signals | Not claimed |

This is a defensible MVP: it answers "what is Australia searching for, is demand growing, and does
the unit economics work?" It does not pretend to know Amazon sales.

---

## 8. Sources

- Google Trends official API (alpha): https://developers.google.com/search/apis/trends
- DataForSEO Google Trends endpoints: https://docs.dataforseo.com/v3/keywords_data-google_trends-overview/
- Google Trends API landscape 2026: https://www.cite42.dev/blog/google-trends-api · https://www.risingtrends.co/blog/google-trends-api
- eBay Marketplace Insights: https://developer.ebay.com/api-docs/buy/api-insights.html
- eBay Buy API marketplace support (EBAY_AU): https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html
- eBay sold-listing access discussion: https://community.ebay.com/forum/talk-to-your-fellow-developers-57970/topic/access-to-soldcompleted-listing-data-what-options-do-non-partner-developers-actually-have-172713/
- Amazon PA-API bestsellers gap: https://blogs.rajubk.com/blog/amazon-paapi-5-has-no-bestsellers-endpoint
- Amazon sales ranks documentation: https://webservices.amazon.com/paapi5/documentation/use-cases/organization-of-items-on-amazon/browse-nodes/browse-nodes-and-sales-ranks.html
- Keepa Best Sellers API (no AU locale): https://keepa.com/api-docs/best-sellers.html
- Amazon data API comparison 2026: https://www.monocrawl.com/compare/amazon-product-data-apis
- TikTok Creative Center API reality: https://adextract.co/blog/tiktok-creative-center-api · https://tokconnect.com/guides/tiktok-trends-api/
- Exploding Topics API: https://explodingtopics.com/feature/et-api · https://api.explodingtopics.com/docs.md
- CJ Dropshipping API key + points: https://developers.cjdropshipping.com/en/api/start/apikey.html · https://developers.cjdropshipping.com/en/api/api2/standard/points.html
- AliExpress API access options: https://www.octoparse.com/blog/aliexpress-api

*Pricing and access terms were checked on 2026-11-07 and must be reconfirmed before subscribing.*
