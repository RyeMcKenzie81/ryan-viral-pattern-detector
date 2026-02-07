# Data Pipeline Control Plane — Checkpoint 003

**Date:** 2026-02-06
**Phase:** Freshness Wiring + UI Banners
**Status:** Complete

## Summary

Wired dataset freshness tracking (`record_start`/`record_success`/`record_failure`) into 6 of the 7 remaining job handlers in `scheduler_worker.py`, and added freshness banners to 2 additional UI pages. All 8 job types now have freshness tracking (except `template_approval` which is cross-brand).

## Changes

### 1. Freshness Tracking in Job Handlers

Each handler follows the same pattern established in `execute_meta_sync_job`:
1. Import `DatasetFreshnessService` and instantiate
2. `record_start(brand_id, dataset_key, run_id)` at the beginning of the try block
3. `record_success(brand_id, dataset_key, records_affected, run_id)` before job run completion
4. `record_failure(brand_id, dataset_key, error_msg, run_id)` in the except block

| Handler | Dataset Key | Records Affected | Notes |
|---------|-------------|------------------|-------|
| `execute_ad_creation_job` | `ad_creations` | `ads_generated` | Guarded by `if brand_id` (brand comes from product join) |
| `execute_scorecard_job` | `scorecard` | `len(ads_analyzed)` | Always has brand_id |
| `execute_template_scrape_job` | `templates_scraped` | `new_count` | Always has brand_id |
| `execute_template_approval_job` | — | — | **Skipped**: cross-brand job, no brand_id available |
| `execute_congruence_reanalysis_job` | `congruence_analysis` | `analyzed_count` | Only tracked when `target_brand_id` param is set |
| `execute_ad_classification_job` | `ad_classifications` | `result['classified']` | Always has brand_id |
| `execute_asset_download_job` | `ad_assets` | `total` (videos + images) | Always has brand_id |

### 2. Freshness Banners on UI Pages

| Page | Page Key | Datasets Checked | Status |
|------|----------|------------------|--------|
| Hook Analysis (`35_🎣_Hook_Analysis.py`) | `hook_analysis` | `ad_classifications` (48h) | Added |
| Congruence Insights (`34_🔗_Congruence_Insights.py`) | `congruence_insights` | `ad_classifications` (48h), `landing_pages` (168h) | Added |
| Template Queue (`28_📋_Template_Queue.py`) | `template_queue` | — | **Deferred**: no brand selector |
| Template Evaluation (`29_🔍_Template_Evaluation.py`) | `template_evaluation` | — | **Deferred**: no brand selector |

### 3. PLAN.md Updated

Updated remaining work section to reflect completed items and deferred work.

## Dataset Key Registry (Complete)

All dataset keys now tracked across the system:

| Dataset Key | Produced By | Consumed By (Banner) | Max Age |
|-------------|------------|---------------------|---------|
| `meta_ads_performance` | meta_sync (steps 1-2) | Ad Performance page | 24h |
| `ad_thumbnails` | meta_sync (step 3) | — | — |
| `ad_assets` | meta_sync (step 4) / asset_download | — | — |
| `ad_classifications` | meta_sync (step 5) / ad_classification | Hook Analysis, Congruence Insights | 48h |
| `ad_creations` | ad_creation | — | — |
| `scorecard` | scorecard | — | — |
| `templates_scraped` | template_scrape | Template Queue (deferred) | 168h |
| `congruence_analysis` | congruence_reanalysis | — | — |

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | Added freshness tracking to 6 job handlers |
| `viraltracker/ui/pages/35_🎣_Hook_Analysis.py` | Added `render_freshness_banner(brand_id, "hook_analysis")` |
| `viraltracker/ui/pages/34_🔗_Congruence_Insights.py` | Added `render_freshness_banner(brand_id, "congruence_insights")` |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work section |

## Deferred Items

1. **template_approval freshness** — This job processes templates across all brands. Options:
   - Add per-brand tracking by deriving brand_id from each processed queue item
   - Create admin-level freshness tracking (requires schema change — `dataset_status.brand_id` has FK constraint)

2. **Template Queue / Template Evaluation banners** — These pages don't have brand selectors. The freshness banner requires brand_id. Options:
   - Add brand selector to these pages
   - Create a cross-brand freshness check (e.g., "any brand stale?")

## Verification

- `python3 -m py_compile viraltracker/worker/scheduler_worker.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/35_🎣_Hook_Analysis.py` — PASS
- `python3 -m py_compile viraltracker/ui/pages/34_🔗_Congruence_Insights.py` — PASS
