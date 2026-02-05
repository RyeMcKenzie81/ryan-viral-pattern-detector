# Checkpoint: Ad Intelligence — Background Classification & Run Now
**Date:** 2026-02-05
**Branch:** `feat/veo-avatar-tool`
**Previous Commit:** `273d09a` - feat: Add CPA metrics and creative strategy insights to account analysis

---

## Just Completed

### 1. Background Ad Classification (Decoupled from Chat)

**Problem:** `full_analysis()` calls `classify_batch()` synchronously — ~25 min for 242 ads. User waits the entire time.

**Solution:** New `ad_classification` job type pre-computes classifications in the background. The existing dedup logic (`_find_existing_classification` by `input_hash` + `prompt_version`) means `full_analysis()` automatically reuses fresh cached results, making it near-instant.

**Worker changes** (`viraltracker/worker/scheduler_worker.py`):
- `_run_classification_for_brand()` — shared helper that initializes services, fetches active ads, creates an `ad_intelligence_runs` audit record, and calls `classify_batch()`
- `execute_ad_classification_job()` — standalone job handler (params: `max_new`, `max_video`, `days_back`)
- `ad_classification` routing in `execute_job()`
- `auto_classify` chain in `execute_meta_sync_job()` — after asset download, if `params.auto_classify=True`, runs classification as a **non-fatal** step

**Service changes** (`viraltracker/services/ad_intelligence/ad_intelligence_service.py`):
- `create_classification_run()` — lightweight run record with `goal="background_classification"`

**No changes needed to:** `classify_batch()`, `full_analysis()`, `classifier_service.py`, database schema

### 2. "Run Now" Buttons for All Scheduler Job Types

Added "Run Now" button (creates one-time job set to execute in ~1 minute) to:
- **Ad Classification** — new form with brand selector, classification settings
- **Template Scrape** — was Save + Cancel, now Save + Run Now + Cancel
- **Ad Creation** — refactored submit section into helper functions, added Run Now
- **Template Approval** — already had Run Now (no changes)

**UI changes** (`viraltracker/ui/pages/24_📅_Ad_Scheduler.py`):
- New `_render_ad_classification_form()` with brand selector, max_new/max_video/days_back settings, schedule config
- Added `ad_classification` to job type radio selector
- Added type badge (🔬) in list view and detail view
- Refactored ad creation submit into shared helpers (`_validate_ad_creation_form`, `_build_ad_creation_parameters`, etc.)

### 3. Previous: CPA Metrics Enhancement
(From earlier in the day)
- Aggregate CPA added to awareness-level aggregates
- Format aggregates by (awareness, format)
- Creative insights auto-generated
- Pagination fix for baseline service

---

## Remaining Items

| Priority | Item | Notes |
|----------|------|-------|
| DONE | ~~Decouple classification from chat~~ | Background `ad_classification` job + `auto_classify` on meta_sync |
| HIGH | Scheduler resilience | Jobs that fail never get rescheduled - needs `_reschedule_after_failure()` |
| MEDIUM | CPC baseline bug | Per-row daily CPC inflates p75 ($79 instead of $2). Use aggregate CPC = total_spend/total_clicks |
| MEDIUM | Deep video analysis UI | Rich data in `ad_video_analysis` and `congruence_components` but no UI visibility |
| MEDIUM | Pipeline infrastructure | Current cron scheduler lacks retry/observability |

### Data Pipeline (Deferred)
User wants to streamline brand data ingestion — data is scattered and hard to track. Will scope this after fixing core ad intelligence issues.

---

## Reference Docs

- Tech debt: `/docs/TECH_DEBT.md`
- Ad intelligence checkpoints: `/docs/ad_intelligence/`
- Testing plan: `/docs/ad_intelligence/TESTING_PLAN.md`

---

## Current State

- All code committed and pushed to `feat/veo-avatar-tool` (commit `75535e3`)
- DB migration applied: `sql/2026-02-05_ad_classification_job_type.sql` (added `ad_classification` + `congruence_reanalysis` to CHECK constraint)
- UI tested: Run Now button works, job gets created and picked up by worker

### Known Issue: Classification errors on first run
Ran ad_classification for Infi brand: 109 active ads, 40 classified, 69 errors. The 40 classified = the `max_new` cap (set to 40), so the classifier hit its cap and stopped — the "69 errors" may be misleading (could be ads skipped after cap, not actual errors). Need to check worker/cron logs for actual error details.

**Next step:** Debug the 69 "errors" — share cron logs in new context window to see what `classify_batch` logged for each failed ad. Likely candidates:
- Missing thumbnails/ad copy for some ads
- Gemini API rate limiting
- The cap logic in `classify_batch` — when `max_new` is reached, it `break`s out of the loop, so remaining ads aren't errors, they're just unprocessed. The `errors = total_active - classified` math is wrong in this case.

### Likely Fix Needed
In `_run_classification_for_brand()`, the "errors" count is `len(active_ids) - total_classified`. But `classify_batch` stops early when `max_new` is reached (it `break`s). So 109 - 40 = 69 "errors" is actually 69 **skipped** ads, not errors. The logging should distinguish between skipped-due-to-cap and actual errors.
