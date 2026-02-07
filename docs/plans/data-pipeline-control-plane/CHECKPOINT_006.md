# Data Pipeline Control Plane — Checkpoint 006

**Date:** 2026-02-07
**Phase:** Competitor Research Ad Scrape Migration (Priority 3 Page Migration)
**Status:** Complete

## Summary

Migrated the Competitor Research "Scrape Ads from Ad Library" section from blocking in-process scraping to `queue_one_time_job('competitor_scrape')`. Unlike Priorities 1-2 which reused existing job handlers, this required creating a new `competitor_scrape` job type with a new handler in `scheduler_worker.py`.

## Changes

### 1. New job handler — `execute_competitor_scrape_job()`

**File:** `viraltracker/worker/scheduler_worker.py`

**What was added:**
- New `execute_competitor_scrape_job()` async handler
- Added `'competitor_scrape'` routing in `execute_job()` dispatcher
- Handler calls `FacebookAdsScraper.search_ad_library()` + `CompetitorService.save_competitor_ads_batch()` — the same code path used by the in-process `scrape_competitor_facebook_ads()` UI function
- Freshness tracking via `DatasetFreshnessService` on `competitor_ads` dataset
- Standard retry/failure handling via `_reschedule_after_failure()`

**Parameters consumed:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `competitor_id` | str | (required) | Competitor UUID to link scraped ads to |
| `ad_library_url` | str | (required) | Facebook Ad Library URL to scrape |
| `max_ads` | int | 500 | Maximum ads to scrape |

### 2. Pipeline Manager registration

**File:** `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py`

Added `competitor_scrape` to `JOB_TYPE_INFO`:
```python
"competitor_scrape": {"emoji": "🕵️", "label": "Competitor Scrape", "default_params": {"max_ads": 500}},
```

`competitor_ads` was already in `DATASET_LABELS` (no change needed).

### 3. Competitor Research — Ad Scraping section rewrite

**File:** `viraltracker/ui/pages/12_🔍_Competitor_Research.py`

**What changed:**
- Default mode now queues via `queue_one_time_job('competitor_scrape', ...)` with parameters: `competitor_id`, `ad_library_url`, `max_ads`
- Added "Run scrape directly (legacy)" checkbox toggle
- Legacy mode preserves the original `scrape_competitor_facebook_ads()` in-process behavior
- Added `render_recent_competitor_scrapes()` — shows last 5 one-time competitor_scrape runs for the selected brand/competitor with status and log summaries
- Added `scrape_legacy_mode` session state init at top of file

**Before:**
```
User clicks "Scrape Ads from Ad Library"
→ scrape_competitor_facebook_ads() runs in-process (blocks UI up to 15 min)
→ Result displayed inline
```

**After (default):**
```
User sets max_ads, clicks "Scrape Ads from Ad Library"
→ queue_one_time_job('competitor_scrape') creates one-time job
→ Worker picks it up within 60s
→ "Competitor scrape queued!" message shown
→ Recent runs section shows progress
```

**After (legacy toggle):**
```
Same as before — scrape_competitor_facebook_ads() runs in-process
```

### 4. PLAN.md Updated

Updated remaining work section and future page migrations table to mark Competitor Research (Priority 3) as complete.

## Pattern Consistency

| Aspect | Previous Migrations | Competitor Research |
|--------|--------------------|--------------------|
| Job type | `meta_sync`, `template_scrape`, `asset_download` | `competitor_scrape` (NEW) |
| Queue function | `queue_one_time_job(brand_id, job_type, ...)` | Same pattern |
| Legacy toggle | `st.checkbox("Run ... directly (legacy)", ...)` | Same pattern |
| Recent runs | `render_recent_*()` | `render_recent_competitor_scrapes()` |
| Pipeline Manager | Already registered | Added to `JOB_TYPE_INFO` |

## Key Difference: Competitor Context

Unlike brand-scoped jobs, competitor scrape jobs need a `competitor_id` parameter since the `scheduled_jobs` table only has `brand_id`. The `competitor_id` is passed via `parameters` JSONB. The `render_recent_competitor_scrapes()` function filters jobs client-side by `parameters.competitor_id` to show only runs for the selected competitor.

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | Added `execute_competitor_scrape_job()` handler + dispatcher routing |
| `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | Added `competitor_scrape` to `JOB_TYPE_INFO` |
| `viraltracker/ui/pages/12_🔍_Competitor_Research.py` | Rewrote ad scraping section with queue_one_time_job, legacy toggle, and recent runs; added session state init |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work and future page migrations |

## Post-Plan Review

- Graph Invariants Checker: **PASS** (G1-G6 all pass, P1-P8 skipped — no graph files changed)
- Test/Evals Gatekeeper: **PASS** (T1-T4 all pass, A1-A5 skipped — no graph files changed)
- Consolidated Verdict: **PASS**

## Verification

- `python3 -m py_compile viraltracker/worker/scheduler_worker.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/12_🔍_Competitor_Research.py` — PASS
