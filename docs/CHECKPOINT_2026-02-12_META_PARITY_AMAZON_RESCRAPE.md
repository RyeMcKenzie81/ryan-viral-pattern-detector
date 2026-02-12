# Checkpoint: Meta API Data Source Parity + Amazon Re-scrape

**Date:** 2026-02-12
**Branch:** main
**Commits:** `7fd12e3` through `253d665`

---

## What Was Done

### Meta API Data Source Parity (4-Phase Plan — Completed)

Full implementation of treating Meta API ads as a first-class data source alongside Ad Library scrapes.

**Phase 1: Tool Readiness Improvements**
- Added `any_of_groups` requirement type — pass if ANY sub-requirement is met (e.g., has Ad Library URL OR has Meta ad account)
- Added `unlocks_tools` field showing which blocked tools get enabled when a requirement is fixed
- Updated all 14 tool configs with `any_of_groups` and `unlocks` metadata
- UI sorts blocked tools by unlock count, shows "Enables: X, Y, Z" badges
- Superuser bypass fix: Tool Readiness now passes session org context (`"all"`) instead of brand's real org UUID

**Phase 2: Meta API Creative Text + Destination Sync**
- `ad_copy` column added to `meta_ads_performance` — extracted from `object_story_spec` during thumbnail fetch
- Destination URL sync wired into `execute_meta_sync_job()` (Step 4.5) — calls `sync_ad_destinations_to_db()`
- `scrape_missing_lp=True` plumbed through: `execute_meta_sync_job()` → `_run_classification_for_brand()` → `classify_batch()` → `classify_ad()` → `_ensure_landing_page_exists()`
- Classifier updated to use `ad_copy` column instead of falling back to `ad_name`

**Phase 3: Brand Research Canonical Analysis**
- Source detection helper (`_detect_ad_source()`) — returns `"meta_api"`, `"ad_library"`, `"both"`, or `"none"`
- Parallel `_meta` analysis methods: `analyze_copy_batch_meta()`, `analyze_videos_for_brand_meta()`, `analyze_images_for_brand_meta()`
- `brand_ad_analysis` schema expanded: `meta_ad_id`, `meta_asset_id`, `data_source` columns + partial unique indexes
- `_save_copy_analysis()` updated for explicit Meta ID handling
- Brand Research UI: `AdIdSet` typed container, source-aware stats, dual-path action buttons

**Phase 4: URL Mapping Service Integration**
- `discover_meta_urls()` — discovers URLs from `meta_ad_destinations`
- `_bulk_match_meta()` — matches Meta ads to products via `meta_ad_product_matches` table
- `_add_to_review_queue()` — extended with `sample_meta_ad_ids TEXT[]` support
- URL Mapping UI calls both scrape and Meta discovery/matching paths
- `url_review_queue` schema extended with `sample_meta_ad_ids` column
- `meta_ad_product_matches` table created for persistent Meta product matches

### Amazon Review Re-scrape Capability

Added "Re-scrape Reviews" and "Re-analyze Reviews" buttons to three pages:

1. **Brand Research** (`05_🔬_Brand_Research.py`) — Per-product scrape button in Amazon Review Analysis section
2. **Pipeline Manager** (`62_🔧_Pipeline_Manager.py`) — New "Amazon Reviews" tab with brand selector, per-product scrape and analyze buttons
3. **Brand Manager** (`02_🏢_Brand_Manager.py`) — Amazon Insights tab shows ASIN info + scrape/analyze buttons

Uses `AmazonReviewService.scrape_reviews_for_product()` with upsert dedup (`UNIQUE(review_id, asin)`) — only new reviews are added on re-scrape.

### Bug Fixes

- **Copy analysis double-save**: `analyze_copy_batch_meta()` was saving twice (once inside `analyze_copy()`, once with Meta FKs). Fixed with `skip_save=True` parameter.
- **Opus 4.5 → 4.6**: Updated all UI text and stale comments referencing "Opus 4.5" to "Opus 4.6".
- **Amazon Insights field names**: Brand Manager showed raw dict keys ("themes", "product_issues") instead of actual content. The analysis saves nested dicts but the UI iterated over keys. Fixed extraction to match Brand Research's correct nested parsing.
- **Discover Variants Meta awareness**: Tab now checks `meta_ads_performance` when no scraped ads exist, shows contextual message instead of misleading "Scrape Ads" prompt.
- **URL Mapping wrong table check**: Tool Readiness checked `meta_ads_performance` (ads exist) instead of `meta_ad_destinations` (destination URLs available). Fixed.

### Tests Added

- `tests/test_scrape_missing_lp_plumbing.py` — 3 tests verifying `scrape_missing_lp=True` flows through the full classify chain
- `tests/test_review_queue_meta_merge.py` — 5 tests verifying `sample_meta_ad_ids` merge behavior in review queue

### SQL Migrations Run

1. `migrations/2026-02-11_meta_ads_ad_copy.sql` — `ad_copy` column on `meta_ads_performance`
2. `migrations/2026-02-11_brand_ad_analysis_meta.sql` — `meta_ad_id`, `meta_asset_id`, `data_source` columns + indexes
3. `migrations/2026-02-11_url_mapping_meta_support.sql` — `sample_meta_ad_ids`, `meta_ad_product_matches` table

---

## Files Changed

| File | Changes |
|------|---------|
| `viraltracker/services/tool_readiness_service.py` | `_check_any_of_group()`, `session_org_id`, `unlocks_tools` |
| `viraltracker/services/models.py` | `unlocks_tools` field on `ToolReadiness` |
| `viraltracker/ui/tool_readiness_requirements.py` | `any_of_groups` + `unlocks` for all tools |
| `viraltracker/ui/pages/07_📥_Tool_Readiness.py` | Hierarchy badges, sorting, session org |
| `viraltracker/services/meta_ads_service.py` | `ad_copy` extraction, backfill filter |
| `viraltracker/services/ad_intelligence/classifier_service.py` | Use `ad_copy`, `scrape_missing_lp` plumbing |
| `viraltracker/worker/scheduler_worker.py` | Destination sync, `scrape_missing_lp` plumbing, `organization_id` select |
| `viraltracker/services/brand_research_service.py` | Source adapter, Meta parallel methods, `skip_save` |
| `viraltracker/ui/pages/05_🔬_Brand_Research.py` | Dual-source stats, Amazon re-scrape, Opus 4.6 |
| `viraltracker/services/product_url_service.py` | Meta URL discovery, bulk matching, stats |
| `viraltracker/ui/pages/04_🔗_URL_Mapping.py` | Dual-source discover/match |
| `viraltracker/ui/pages/02_🏢_Brand_Manager.py` | Amazon re-scrape buttons, analysis extraction fix, Discover Variants Meta awareness |
| `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | New Amazon Reviews tab |
| `viraltracker/core/config.py` | Stale Opus 4.5 comments |
| `docs/TECH_DEBT.md` | Updated #20, added #21, #23, testing protocol |
| `tests/test_scrape_missing_lp_plumbing.py` | NEW |
| `tests/test_review_queue_meta_merge.py` | NEW |

---

## Known Issues / Remaining Work

See `docs/TECH_DEBT.md` item #20 for full list. Key items:

1. **Destination sync bootstrap UX** — Add "Fetch Destinations" button to URL Mapping so users don't have to run full meta_sync
2. **`get_matching_stats()` performance** — COUNT(DISTINCT) in Python for large Meta ad volumes
3. **Hook Analysis / Congruence end-to-end** — Verify classifications feed correctly for Meta-only brands
4. **Offer variant discovery from Meta ads** — Brand Manager's "Discover Variants" tab only works with scraped ads; Meta-only brands see an info message but can't discover variants. Needs a Meta-aware variant discovery path.
5. **Landing page → offer variant link** — No UI on Brand Research or URL Mapping to promote a landing page to an offer variant

---

## Testing Protocol

Test with 3 brand configurations after any changes to this subsystem:
1. **Meta-only** (ad account, no Ad Library URL)
2. **Scrape-only** (Ad Library URL, no ad account)
3. **Both sources**

See `docs/TECH_DEBT.md` item #20 for detailed per-configuration checks.
