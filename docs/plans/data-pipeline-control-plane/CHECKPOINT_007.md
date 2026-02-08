# Data Pipeline Control Plane — Checkpoint 007

**Date:** 2026-02-07
**Phase:** Reddit Research Pipeline Migration (Priority 4 Page Migration)
**Status:** Complete

## Summary

Migrated the Reddit Research "Run Reddit Sentiment Analysis" from blocking in-process pipeline execution to `queue_one_time_job('reddit_scrape')`. Like Checkpoint 006 (Competitor Research), this required creating a new `reddit_scrape` job type with a new handler in `scheduler_worker.py`.

## Changes

### 1. New job handler — `execute_reddit_scrape_job()`

**File:** `viraltracker/worker/scheduler_worker.py`

**What was added:**
- New `execute_reddit_scrape_job()` async handler
- Added `'reddit_scrape'` routing in `execute_job()` dispatcher
- Handler calls `run_reddit_sentiment()` from `viraltracker.pipelines.reddit_sentiment` — the same async pipeline used by the in-process UI function
- Freshness tracking via `DatasetFreshnessService` on `reddit_data` dataset
- Standard retry/failure handling via `_reschedule_after_failure()`
- Pipeline result status is checked — if `run_reddit_sentiment()` returns a non-success status, the job is treated as failed

**Parameters consumed:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search_queries` | list[str] | (required) | Search terms for Reddit |
| `subreddits` | list[str] | None | Subreddits to restrict search to |
| `timeframe` | str | "month" | Time range (hour/day/week/month/year/all) |
| `max_posts` | int | 500 | Maximum posts to scrape |
| `min_upvotes` | int | 20 | Minimum upvotes filter |
| `min_comments` | int | 5 | Minimum comments filter |
| `relevance_threshold` | float | 0.6 | Relevance score cutoff (0-1) |
| `signal_threshold` | float | 0.5 | Signal score cutoff (0-1) |
| `top_percentile` | float | 0.20 | Top percentage to keep for extraction |
| `persona_id` | str | None | Persona UUID to sync quotes to |
| `auto_sync_to_persona` | bool | False | Whether to sync quotes to persona fields |
| `persona_context` | str | None | Persona description for LLM relevance |
| `topic_context` | str | None | Topic/domain focus for LLM relevance |

### 2. Pipeline Manager registration

**File:** `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py`

Added `reddit_scrape` to `JOB_TYPE_INFO`:
```python
"reddit_scrape": {"emoji": "🔍", "label": "Reddit Scrape", "default_params": {"max_posts": 500}},
```

`reddit_data` was already in `DATASET_LABELS` (no change needed).

### 3. Reddit Research — Run button section rewrite

**File:** `viraltracker/ui/pages/15_🔍_Reddit_Research.py`

**What changed:**
- Default mode now queues via `queue_one_time_job('reddit_scrape', ...)` with all config parameters serialized into the `parameters` JSONB field
- Added "Run analysis directly (legacy)" checkbox toggle
- Legacy mode preserves the original `run_reddit_sentiment()` in-process behavior
- Queued mode requires a brand association (shows warning if no brand selected, directs user to legacy mode for standalone research)
- Added `render_recent_reddit_scrapes(brand_id)` — shows last 5 one-time reddit_scrape runs for the selected brand with status, queries preview, and log summaries
- Added `reddit_scrape_legacy_mode` session state init

**Before:**
```
User configures queries/filters, clicks "Run Reddit Sentiment Analysis"
→ run_reddit_sentiment() runs in-process (blocks UI 3-15 min)
→ Result displayed inline with quotes by category
```

**After (default):**
```
User configures queries/filters, clicks "Run Reddit Sentiment Analysis"
→ queue_one_time_job('reddit_scrape') creates one-time job
→ Worker picks it up within 60s
→ "Reddit scrape queued!" message shown
→ Recent runs section shows progress
```

**After (legacy toggle):**
```
Same as before — run_reddit_sentiment() runs in-process
Also supports standalone research (no brand required)
```

### 4. PLAN.md Updated

Updated remaining work section and future page migrations table to mark Reddit Research (Priority 4) as complete.

## Pattern Consistency

| Aspect | Previous Migrations | Reddit Research |
|--------|--------------------|--------------------|
| Job type | `meta_sync`, `template_scrape`, `asset_download`, `competitor_scrape` | `reddit_scrape` (NEW) |
| Queue function | `queue_one_time_job(brand_id, job_type, ...)` | Same pattern |
| Legacy toggle | `st.checkbox("Run ... directly (legacy)", ...)` | Same pattern |
| Recent runs | `render_recent_*()` | `render_recent_reddit_scrapes()` |
| Pipeline Manager | Already registered | Added to `JOB_TYPE_INFO` |
| Dataset freshness | Various dataset keys | `reddit_data` (already in DATASET_LABELS) |

## Key Difference: Brand Requirement

Unlike the original Reddit Research page which allowed standalone (no-brand) research, the queued mode requires a brand association because:
- `queue_one_time_job()` requires `brand_id`
- Dataset freshness tracking is brand-scoped
- Pipeline Manager views are brand-scoped

Users can still run standalone research via the legacy toggle, which preserves the original behavior completely.

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | Added `execute_reddit_scrape_job()` handler + dispatcher routing |
| `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | Added `reddit_scrape` to `JOB_TYPE_INFO` |
| `viraltracker/ui/pages/15_🔍_Reddit_Research.py` | Rewrote run button section with queue_one_time_job, legacy toggle, and recent runs; added session state init |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work and future page migrations |

## Verification

- `python3 -m py_compile viraltracker/worker/scheduler_worker.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/15_🔍_Reddit_Research.py` — PASS
