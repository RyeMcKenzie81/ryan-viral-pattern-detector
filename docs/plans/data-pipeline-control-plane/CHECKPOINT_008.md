# Data Pipeline Control Plane — Checkpoint 008

**Date:** 2026-02-07
**Phase:** Amazon Review Scrape Migration (Priority 5 Page Migration)
**Status:** Complete

## Summary

Migrated the Competitor Research "Scrape" button for Amazon reviews from blocking in-process execution to `queue_one_time_job('amazon_review_scrape')`. Like Checkpoints 006 (Competitor Research) and 007 (Reddit Research), this required creating a new `amazon_review_scrape` job type with a new handler in `scheduler_worker.py`.

## Changes

### 1. New job handler — `execute_amazon_review_scrape_job()`

**File:** `viraltracker/worker/scheduler_worker.py`

**What was added:**
- New `execute_amazon_review_scrape_job()` async handler
- Added `'amazon_review_scrape'` routing in `execute_job()` dispatcher
- Handler calls `CompetitorService.scrape_amazon_reviews_for_competitor()` — the same synchronous method used by the in-process UI scrape button
- Freshness tracking via `DatasetFreshnessService` on `amazon_reviews` dataset
- Standard retry/failure handling via `_reschedule_after_failure()`

**Parameters consumed:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `competitor_amazon_url_id` | str | (required) | UUID of the competitor_amazon_urls record |
| `asin` | str | "Unknown" | ASIN for logging (informational only) |
| `include_keywords` | bool | True | Include keyword filter configs for broader coverage |
| `include_helpful` | bool | True | Include helpful-sort configs |

### 2. Pipeline Manager registration

**File:** `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py`

Added `amazon_review_scrape` to `JOB_TYPE_INFO`:
```python
"amazon_review_scrape": {"emoji": "📦", "label": "Amazon Review Scrape", "default_params": {}},
```

Added `amazon_reviews` to `DATASET_LABELS`:
```python
"amazon_reviews": "Amazon Reviews",
```

### 3. Competitor Research — Amazon tab scrape button rewrite

**File:** `viraltracker/ui/pages/12_🔍_Competitor_Research.py`

**What changed:**
- Default mode now queues via `queue_one_time_job('amazon_review_scrape', ...)` with `competitor_amazon_url_id` and `asin` serialized into the `parameters` JSONB field
- Added "Scrape reviews directly (legacy)" checkbox toggle at the top of the Amazon tab
- Legacy mode preserves the original in-process `scrape_amazon_reviews_for_competitor()` behavior
- Added `render_recent_amazon_review_scrapes(brand_id, competitor_amazon_url_id)` — shows last 5 one-time amazon_review_scrape runs for the selected Amazon URL with status and log summaries
- Added `amazon_scrape_legacy_mode` session state init

**Before:**
```
User clicks "📥 Scrape" on an Amazon URL row
→ scrape_amazon_reviews_for_competitor() runs in-process (blocks UI 5-15 min)
→ Result displayed inline with review counts
```

**After (default):**
```
User clicks "📥 Scrape" on an Amazon URL row
→ queue_one_time_job('amazon_review_scrape') creates one-time job
→ Worker picks it up within 60s
→ "Review scrape queued!" message shown
→ Recent runs section shows progress below each URL row
```

**After (legacy toggle):**
```
Same as before — scrape_amazon_reviews_for_competitor() runs in-process
```

### 4. PLAN.md Updated

Updated remaining work section and future page migrations table to mark Amazon Reviews (Priority 5) as complete.

## Pattern Consistency

| Aspect | Previous Migrations | Amazon Review Scrape |
|--------|--------------------|--------------------|
| Job type | `meta_sync`, `template_scrape`, `asset_download`, `competitor_scrape`, `reddit_scrape` | `amazon_review_scrape` (NEW) |
| Queue function | `queue_one_time_job(brand_id, job_type, ...)` | Same pattern |
| Legacy toggle | `st.checkbox("Run ... directly (legacy)", ...)` | Same pattern |
| Recent runs | `render_recent_*()` | `render_recent_amazon_review_scrapes()` |
| Pipeline Manager | Already registered | Added to `JOB_TYPE_INFO` + `DATASET_LABELS` |
| Dataset freshness | Various dataset keys | `amazon_reviews` (NEW) |

## Key Detail: Per-URL Scraping

Unlike other migrations where the entire operation is a single job, Amazon review scraping is per-URL (each competitor can have multiple Amazon URLs). The queued mode creates one job per scrape button click, and the `render_recent_amazon_review_scrapes` function filters runs by `competitor_amazon_url_id` to show relevant history for each URL row.

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | Added `execute_amazon_review_scrape_job()` handler + dispatcher routing |
| `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | Added `amazon_review_scrape` to `JOB_TYPE_INFO`, `amazon_reviews` to `DATASET_LABELS` |
| `viraltracker/ui/pages/12_🔍_Competitor_Research.py` | Rewrote Amazon tab scrape button with queue_one_time_job, legacy toggle, recent runs; added session state init |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work and future page migrations |

## Verification

- `python3 -m py_compile viraltracker/worker/scheduler_worker.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/12_🔍_Competitor_Research.py` — PASS

## All Page Migrations Complete

With this checkpoint, all 5 planned page migrations are now complete:

| Priority | Page | Job Type | Checkpoint |
|----------|------|----------|------------|
| 1 | Template Queue | `template_scrape` | 004 |
| 2 | Brand Research | `asset_download` | 005 |
| 3 | Competitor Research | `competitor_scrape` | 006 |
| 4 | Reddit Research | `reddit_scrape` | 007 |
| 5 | Amazon Reviews | `amazon_review_scrape` | 008 |
