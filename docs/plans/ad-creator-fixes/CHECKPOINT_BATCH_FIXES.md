# Checkpoint: Ad Creator Batch Fixes (Fixes 1-6, 8)

**Date:** 2026-03-06
**Branch:** `fix/ad-creator-batch-fixes` (merged into `feat/ad-creator-v2-phase0`)
**Migration:** `2026-03-06_ad_runs_source_template_id.sql` -- DEPLOYED

## Summary

7 fixes implemented across 15 files + 1 migration. All syntax-verified, committed individually, merged via fast-forward.

## Fixes Completed

### Fix 1: Scheduler Time Display Mismatch
- **Root Cause:** `next_run_at` parsed as UTC but displayed without `.astimezone(PST)` conversion
- **Files:** `viraltracker/ui/pages/24_Ad_Scheduler.py`
- **Changes:** Added `.astimezone(PST)` + `%Z` format to 4 time display locations (job list, detail view, run history started_at, run history completed_at)
- **Commit:** `20db0d1`

### Fix 2: Smart Edit Ratio Defaults to 1:1
- **Root Cause:** `create_edited_ad()` hardcoded `"1080x1080"` fallback instead of preserving source dimensions
- **Files:** `viraltracker/services/ad_creation_service.py`, `viraltracker/ui/pages/22_Ad_History.py`
- **Changes:**
  - Multi-step dimension detection chain: `canvas.dimensions` -> `canvas.aspect_ratio` (mapped via `RATIO_TO_DIMS`) -> canvas string parsing -> `variant_size` -> fallback with warning
  - Explicit dimension instruction in edit prompt: "Output MUST be {dimensions} pixels exactly"
  - Added `st.info()` showing current size in Smart Edit modal
- **Commit:** `59acfdb`

### Fix 4: Money-Back Guarantee Hallucination
- **Root Cause:** 3 compounding issues: (1) `Product` model lacked `guarantee` field (DB column existed), (2) USP keyword filter naively matched "guarantee", (3) no prompt instruction about guarantees
- **Files:** `viraltracker/services/models.py`, `viraltracker/pipelines/ad_creation_v2/models/prompt.py`, `viraltracker/pipelines/ad_creation_v2/services/generation_service.py`, `viraltracker/pipelines/ad_creation_v2/services/content_service.py`, `viraltracker/ui/pages/02_Brand_Manager.py`
- **Changes:**
  - Added `guarantee: Optional[str] = None` to `Product` model
  - Added `guarantee` to `ProductContext` prompt model
  - Wired `guarantee` through `generation_service.py` -> `ProductContext`
  - Removed `'guarantee'` and `'money-back'` from USP technical-specs keyword filter
  - Added explicit guarantee instruction to headline generation prompt: verified guarantee = MAY reference; null = MUST NOT mention
  - Added `help=` text to Brand Manager guarantee input field
- **Commit:** `119f7b1`

### Fix 6: Template Sorting -- Brand Dropdown + Date Sort
- **Root Cause:** `get_templates()` had no `source_brand` filter or sort options
- **Files:** `viraltracker/services/template_queue_service.py`, `viraltracker/ui/pages/21b_Ad_Creator_V2.py`
- **Changes:**
  - Added optional `source_brand` and `sort_by` params to `get_templates()` (backward-compatible)
  - Added `get_source_brands()` service method returning distinct non-null advertiser names
  - Added second filter row in V2 Ad Creator: Source Brand dropdown + Sort By selectbox
  - Sort options: Most Used (default), Least Used, Newest, Oldest
  - Pagination resets on any filter change
- **Commit:** `8994812`

### Fix 3: Listicle Landing Page Number Matching
- **Root Cause:** Landing page analysis detects listicle structure and stores `listicle_item_count` in `content_patterns` JSONB, but count was never passed to ad creation prompts
- **Files:** `viraltracker/pipelines/ad_creation_v2/models/prompt.py`, `viraltracker/pipelines/ad_creation_v2/nodes/select_content.py`, `viraltracker/pipelines/ad_creation_v2/services/content_service.py`
- **Changes:**
  - Added `listicle_count: Optional[int] = None` to `BlueprintContext`
  - In `SelectContentNode`, queries `landing_page_analyses` for matching URL when blueprint has `source_url`, extracts `listicle_item_count`
  - Added `listicle_count` optional param to `generate_benefit_variations()`
  - Added `CRITICAL LISTICLE RULE` prompt section when count is not None
- **Commit:** `87862af`

### Fix 5: V2 "View Results" Shows Nothing
- **Root Cause:** PostgREST `!inner` join on `source_scraped_template_id` column that didn't exist on `ad_runs` table. Query returned zero rows.
- **Files:** `viraltracker/services/ad_review_override_service.py`, `viraltracker/services/ad_creation_service.py`, `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py`
- **Migration:** `migrations/2026-03-06_ad_runs_source_template_id.sql`
- **Changes:**
  - Changed `!inner` to left join in `get_ads_filtered()` and `get_summary_stats()` (2 locations)
  - Added `source_scraped_template_id UUID REFERENCES scraped_templates(id) ON DELETE SET NULL` column
  - Backfilled from `generation_config->>'template_id'` for existing V2 runs
  - Added `source_scraped_template_id` optional param to `create_ad_run()`
  - `InitializeNode` now passes `template_id` as `source_scraped_template_id`
- **Commit:** `688aad0`

### Fix 8: Manual Template Addition with Auto-Ingestion
- **Root Cause:** No UI or service method to manually upload template images
- **Files:** `viraltracker/services/template_queue_service.py`, `viraltracker/ui/pages/28_Template_Queue.py`
- **Changes:**
  - New `add_manual_template()` async service method: uploads to S3 (`scraped-assets/manual/`), creates `scraped_ad_assets` record with `scrape_source="manual_upload"` and NULL `facebook_ad_id`, creates `template_queue` record, optionally runs AI analysis and auto-approves
  - New "Manual Upload" tab (6th tab) in Template Queue UI: multi-file uploader (PNG/JPG/JPEG/WEBP), thumbnail preview grid, AI analysis checkbox, auto-approve checkbox with warning, progress bar, summary
  - `analyze_template_for_approval()` already handles NULL `facebook_ad_id` gracefully (falls back to "Unknown Brand" / "")
- **Commit:** `198cd1c`

## Fix 7: Recurring Template Pulling -- ALREADY DONE
Investigation confirmed fully implemented. No changes needed.

## Files Changed (15 + 1 migration)

| File | Fixes |
|------|-------|
| `viraltracker/ui/pages/24_Ad_Scheduler.py` | 1 |
| `viraltracker/services/ad_creation_service.py` | 2, 5 |
| `viraltracker/ui/pages/22_Ad_History.py` | 2 |
| `viraltracker/services/models.py` | 4 |
| `viraltracker/pipelines/ad_creation_v2/models/prompt.py` | 3, 4 |
| `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` | 4 |
| `viraltracker/pipelines/ad_creation_v2/services/content_service.py` | 3, 4 |
| `viraltracker/ui/pages/02_Brand_Manager.py` | 4 |
| `viraltracker/services/template_queue_service.py` | 6, 8 |
| `viraltracker/ui/pages/21b_Ad_Creator_V2.py` | 6 |
| `viraltracker/pipelines/ad_creation_v2/nodes/select_content.py` | 3 |
| `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py` | 5 |
| `viraltracker/services/ad_review_override_service.py` | 5 |
| `viraltracker/ui/pages/28_Template_Queue.py` | 8 |
| `migrations/2026-03-06_ad_runs_source_template_id.sql` | 5 |

## Remaining Items (Not Yet Planned)

See `PLAN.md` items 9-13:
- Fix 9: Brand Manager -- LP Analysis & Gap Filling + Feature Parity with Onboarding
- Fix 10: Template ingestion/scoring -- impression-based prioritization
- Fix 11: Fix SEO tool -- GSC integration
- Fix 12: V1 Export Tool -- Zip download
- Fix 13: V2 Export Tool -- Google Drive

## Manual Testing Required

See `TESTING_CHECKLIST.md` for the full testing matrix.
