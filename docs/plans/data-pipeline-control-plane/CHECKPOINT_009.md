# Data Pipeline Control Plane — Checkpoint 009

**Date:** 2026-02-07
**Phase:** Platform Schedules Sub-Tab
**Status:** Complete — awaiting manual QA
**Commits:** `8e39209`, `1aaf4db`

## Summary

Split the Pipeline Manager's Schedules tab into **Brand Schedules** and **Platform Schedules** sub-tabs. Platform-level jobs (`template_approval`, `template_scrape`) now have their own scheduling UI with `brand_id=NULL`, separate from brand-scoped jobs.

### Why

`template_approval` and `template_scrape` operate on shared template pools across all brands. They don't fit the brand-scoped model of the existing Schedules tab:
- `template_approval` already inserted with `brand_id: None` — it couldn't be scheduled from the UI
- `template_scrape` was brand-triggered but output goes to a shared template pool

## Changes

### 1. `viraltracker/services/pipeline_helpers.py`

- **`ensure_recurring_job(brand_id)`**: Type `str` → `Optional[str]`. When `brand_id is None`, uses `.is_("brand_id", "null")` instead of `.eq()` for the upsert lookup
- **`queue_one_time_job(brand_id)`**: Type `str` → `Optional[str]`. Insert already handles None → SQL NULL
- **Log messages**: All 5 log lines now say `"for platform"` instead of `"for brand None"` when brand_id is None

### 2. `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py`

**New constants:**
- `PLATFORM_JOB_TYPES = ["template_approval", "template_scrape"]`
- `BRAND_SCHEDULABLE_TYPES = ["meta_sync", "ad_classification", "asset_download", "scorecard", "congruence_reanalysis"]`

**New functions:**
- `_get_last_run_info(job_id)` — queries `scheduled_job_runs` for most recent run status/time
- `render_platform_schedules()` — mirrors `render_schedules()` but:
  - No brand selector
  - Queries `brand_id IS NULL` recurring jobs
  - Shows last-run status in each expander
  - Editable `search_url` + `max_ads` params for `template_scrape`
  - Widget keys use `platform_` prefix to avoid collisions

**Updated functions:**
- `render_schedules()` — now uses `BRAND_SCHEDULABLE_TYPES` (removed template_scrape, template_approval)
- `get_scheduled_jobs_all()` — brand_name assignment loop moved outside `if brand_ids_needed:` block (bug fix: platform jobs now correctly labeled "Platform")
- `render_active_jobs()` — added "Created" date and last run status/date to each job row
- Health Overview — removed `template_scrape` from brand-scoped Run Now buttons

**Sub-tab wiring:**
```python
with tab2:
    sub_brand, sub_platform = st.tabs(["🏢 Brand Schedules", "🌐 Platform Schedules"])
```

### 3. `viraltracker/worker/scheduler_worker.py`

Guarded 3 freshness tracking calls in `execute_template_scrape_job()` with `if brand_id:`:
- Line 1542: `freshness.record_start()`
- Line 1724: `freshness.record_success()`
- Line 1749: `freshness.record_failure()`

The `dataset_status` table has `brand_id NOT NULL`, so these would fail for platform-level template_scrape jobs without the guard.

### 4. Data migration — `migrations/2026-02-07_platform_template_jobs.sql`

```sql
UPDATE scheduled_jobs SET brand_id = NULL
WHERE job_type IN ('template_scrape', 'template_approval')
  AND brand_id IS NOT NULL;
```

### 5. Bug fix — `get_scheduled_jobs_all()` brand_name assignment

The `_brand_name = "Platform"` fallback (line 143) was inside `if brand_ids_needed:`, making it unreachable when no brand-scoped jobs needed lookup. Moved the assignment loop to always run.

## What Did NOT Change

- Health Overview tab — stays brand-scoped
- Freshness Matrix tab — stays brand-scoped
- Active Jobs / Run History tabs — already work for all jobs
- `template_approval` handler — already had no freshness tracking
- `scheduled_jobs.brand_id` column — already nullable

## Testing Plan

See `docs/plans/data-pipeline-control-plane/TESTING_009_PLATFORM_SCHEDULES.md`

## Post-Plan Review

**Verdict: PASS** — both Graph Invariants Checker and Test/Evals Gatekeeper passed. No blocking issues. All plan items implemented. See conversation transcript for full report.
