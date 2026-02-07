# Data Pipeline Control Plane — Checkpoint 005

**Date:** 2026-02-07
**Phase:** Brand Research Asset Download Migration (Priority 2 Page Migration)
**Status:** Complete

## Summary

Migrated the Brand Research "Download Assets" section from blocking in-process asset downloading to `queue_one_time_job('asset_download')`. This follows the same pattern established in the Template Queue migration (Checkpoint 004) and the Ad Performance Meta Sync migration (Checkpoint 001). A legacy toggle preserves the original in-process behavior.

## Changes

### 1. Brand Research — `render_download_section()` rewrite

**File:** `viraltracker/ui/pages/05_🔬_Brand_Research.py`

**What changed:**
- Default mode now queues via `queue_one_time_job('asset_download', ...)` with parameters: `max_videos`, `max_images`
- Added "Run download directly (legacy)" checkbox toggle — identical pattern to Template Queue's `ingest_legacy_mode` and Ad Performance's `sync_legacy_mode`
- Legacy mode preserves the original `download_assets_sync()` in-process behavior with "Max ads to process" slider
- Queued mode shows separate "Max videos" and "Max images" sliders to match the `execute_asset_download_job` worker handler parameters
- Added `render_recent_asset_downloads()` — shows last 5 one-time asset_download runs for the selected brand with status and log summaries
- Added `download_legacy_mode` session state init at top of file with other session state keys

**Before:**
```
User clicks "Download Assets"
→ download_assets_sync() calls BrandResearchService.download_assets_for_brand() in-process
→ UI blocks for 1-5 minutes
→ Result displayed inline
```

**After (default):**
```
User sets max_videos/max_images, clicks "Download Assets"
→ queue_one_time_job('asset_download') creates one-time job
→ Worker picks it up within 60s, calls MetaAdsService.download_new_ad_assets()
→ "Asset download queued!" message shown
→ Recent runs section shows progress
```

**After (legacy toggle):**
```
Same as before — download_assets_sync() runs in-process
```

### 2. PLAN.md Updated

Updated remaining work section and future page migrations table to mark Brand Research (Priority 2) as complete.

## Pattern Consistency

This migration follows the exact same pattern as prior migrations:

| Aspect | Ad Performance | Template Queue | Brand Research |
|--------|---------------|----------------|----------------|
| Job type | `meta_sync` | `template_scrape` | `asset_download` |
| Queue function | `queue_one_time_job(brand_id, "meta_sync", ...)` | `queue_one_time_job(brand_id, "template_scrape", ...)` | `queue_one_time_job(brand_id, "asset_download", ...)` |
| Legacy toggle | `st.checkbox("Run sync directly (legacy)", ...)` | `st.checkbox("Run scrape directly (legacy)", ...)` | `st.checkbox("Run download directly (legacy)", ...)` |
| Legacy fallback | `sync_ads_from_meta()` in-process | `run_template_ingestion()` in-process | `download_assets_sync()` in-process |
| Success message | "Meta sync queued!" | "Template scrape queued!" | "Asset download queued!" |
| Recent runs | N/A | `render_recent_manual_scrapes()` | `render_recent_asset_downloads()` |

## Parameters Mapping

The queued job passes these parameters to `execute_asset_download_job`:

| UI Field | Parameter Key | Default |
|----------|--------------|---------|
| Max videos | `max_videos` | 20 |
| Max images | `max_images` | 40 |

## Note: Service Method Difference

The queued path and legacy path use different service methods:
- **Queued** (worker handler): `MetaAdsService.download_new_ad_assets(brand_id, max_videos, max_images)` — downloads by media type counts
- **Legacy** (in-process): `BrandResearchService.download_assets_for_brand(brand_id, limit, ad_ids)` — downloads by ad count with product filtering

The worker handler was already implemented and tested (see Checkpoint 003). Product-level filtering is only available in legacy mode; the queued job downloads for the entire brand, which is the more common use case.

## Modified Files

| File | Change |
|------|--------|
| `viraltracker/ui/pages/05_🔬_Brand_Research.py` | Rewrote `render_download_section()` with queue_one_time_job, legacy toggle, and recent runs display; added session state init |
| `docs/plans/data-pipeline-control-plane/PLAN.md` | Updated remaining work and future page migrations |

## Post-Plan Review

- Graph Invariants Checker: **PASS** (G1-G6 all pass, P1-P8 skipped — no graph files changed)
- Test/Evals Gatekeeper: **PASS** (T1-T4 all pass, A1-A5 skipped — no graph files changed)
- Consolidated Verdict: **PASS**

## Verification

- `python3 -m py_compile viraltracker/ui/pages/05_🔬_Brand_Research.py` — PASS
