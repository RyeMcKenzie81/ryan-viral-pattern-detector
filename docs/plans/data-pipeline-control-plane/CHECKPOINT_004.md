# Data Pipeline Control Plane — Checkpoint 004

**Date:** 2026-02-06
**Phase:** Template Queue Migration (Priority 1 Page Migration)
**Status:** Complete

## Summary

Migrated the Template Queue "Ingest New" tab from blocking in-process template scraping to `queue_one_time_job('template_scrape')`. This follows the same pattern established in the Ad Performance Meta Sync migration (Checkpoint 001). A brand selector was added to the tab since the job system requires `brand_id` for job creation and freshness tracking.

## Changes

### 1. Template Queue — `render_ingestion_trigger()` rewrite

**File:** `viraltracker/ui/pages/28_📋_Template_Queue.py`

**What changed:**
- Added `render_brand_selector()` at the top of the function — brand context is required for `queue_one_time_job` and aligns with the `execute_template_scrape_job` handler which uses `brand_id` for freshness tracking and asset association
- Default mode now queues via `queue_one_time_job('template_scrape', ...)` with parameters: `search_url`, `max_ads`, `images_only`, `auto_queue`
- Added "Run scrape directly (legacy)" checkbox toggle — identical pattern to Ad Performance's `sync_legacy_mode`
- Legacy mode preserves the original `run_template_ingestion()` in-process behavior
- Added `"queued"` status handling in the result display section
- Added `render_recent_manual_scrapes()` — shows last 5 one-time template_scrape runs for the selected brand with status and log summaries, so users don't have to navigate to Pipeline Manager
- Consolidated `ingest_legacy_mode` session state init at top of file with other session state keys

**Before:**
```
User clicks "Start Ingestion"
→ run_template_ingestion() runs in-process (blocks UI 1-3 min)
→ Result displayed inline
```

**After (default):**
```
User selects brand, clicks "Start Ingestion"
→ queue_one_time_job('template_scrape') creates one-time job
→ Worker picks it up within 60s
→ "Template scrape queued!" message shown
→ User can check Pipeline Manager for progress
```

**After (legacy toggle):**
```
Same as before — run_template_ingestion() runs in-process
```

### 2. PLAN.md Updated

Updated remaining work section to mark Template Queue migration as complete.

## Pattern Consistency

This migration follows the exact same pattern as the Ad Performance Meta Sync migration:

| Aspect | Ad Performance | Template Queue |
|--------|---------------|----------------|
| Job type | `meta_sync` | `template_scrape` |
| Queue function | `queue_one_time_job(brand_id, "meta_sync", ...)` | `queue_one_time_job(brand_id, "template_scrape", ...)` |
| Legacy toggle | `st.checkbox("Run sync directly (legacy)", ...)` | `st.checkbox("Run scrape directly (legacy)", ...)` |
| Legacy fallback | `sync_ads_from_meta()` in-process | `run_template_ingestion()` in-process |
| Success message | "Meta sync queued! It will start within 60 seconds." | "Template scrape queued! It will start within 60 seconds." |
| Error fallback | "Please try the legacy mode." | "Please try legacy mode." |

## Parameters Mapping

The queued job passes these parameters to `execute_template_scrape_job`:

| UI Field | Parameter Key | Default |
|----------|--------------|---------|
| Facebook Ad Library URL | `search_url` | (required) |
| Max Ads | `max_ads` | 20 |
| Images Only | `images_only` | True |
| (automatic) | `auto_queue` | True |

## Side Effect: Brand Context on Template Queue

Adding `render_brand_selector()` to the Ingest New tab introduces brand context to this page for the first time. This was listed as a deferred item in Checkpoint 003:

> template_queue / template_evaluation banners — pages have no brand selector; add when brand context is introduced

The brand selector on the Ingest New tab means freshness banners could now be added to that tab in a future iteration, though the other tabs (Pending Review, Template Library, etc.) still lack brand context.

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/ui/pages/28_📋_Template_Queue.py` | Rewrote `render_ingestion_trigger()` with brand selector, queue_one_time_job, legacy toggle, and recent runs display |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work and future page migrations |

## Post-Plan Review

- Graph Invariants Checker: **PASS** (G1-G6 all pass, P1-P8 skipped — no graph files changed)
- Test/Evals Gatekeeper: **PASS** (T1-T4 all pass, A1-A5 skipped — no graph files changed)
- Consolidated Verdict: **PASS**

## Verification

- `python3 -m py_compile viraltracker/ui/pages/28_📋_Template_Queue.py` — PASS
