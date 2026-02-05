# Checkpoint: Standalone Asset Download Job + meta_sync Bug Fix

**Date:** 2026-02-05
**Branch:** `feat/veo-avatar-tool`
**Commit:** `f079bde` - feat: Add standalone asset_download job type + fix meta_sync kwarg bug

---

## Completed

### 1. Standalone `asset_download` Scheduled Job Type

**Problem:** Asset downloads were only available as Step 4 inside `meta_sync` jobs or via a manual UI button on the Ad Performance page. They couldn't be scheduled independently, which meant classification depended on running a full meta_sync first.

**Solution:** Added `asset_download` as an independently schedulable job type, completing the decoupled pipeline:

```
meta_sync → asset_download → classification
(each independently schedulable)
```

**Files changed:**

| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | Added `execute_asset_download_job()`, added routing in `execute_job()` |
| `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | Added `_render_asset_download_form()`, radio option, badge mappings (2 locations) |
| `migrations/2026-02-05_asset_download_job_type.sql` | Extended CHECK constraint to include `asset_download` |

**Worker function:** `execute_asset_download_job()` follows the same pattern as `execute_ad_classification_job()`:
- Extracts `brand_id`, `params` from job dict
- Clears `next_run_at` to prevent duplicate execution
- Creates job run record
- Instantiates `MetaAdsService()` and calls `download_new_ad_assets()`
- Logs video/image download counts
- Handles success (`_update_job_next_run`) and failure (`_reschedule_after_failure`)

**UI form:** `_render_asset_download_form()` with sections:
1. Brand selector (with cookie persistence)
2. Job name (auto-generated from brand)
3. Download settings: `max_videos` (0-100, default 20), `max_images` (0-200, default 40)
4. Schedule (recurring daily/weekly or one-time)
5. Buttons: Save Schedule / Run Now / Cancel

**Parameters format:**
```json
{
    "max_videos": 20,
    "max_images": 40
}
```

**Test results:**
- Created Infi asset download job with max_videos=10, max_images=10
- Run Now: downloaded 5 videos + 10 images (15 total)
- Worker logs confirmed correct execution and lifecycle

### 2. Fixed meta_sync `max_downloads` Bug

**Problem:** In `execute_meta_sync_job()` Step 4, the call was:
```python
await service.download_new_ad_assets(brand_id=UUID(brand_id), max_downloads=20)
```
But `download_new_ad_assets()` signature is `(brand_id, max_videos=20, max_images=40)`. The `max_downloads` kwarg was silently ignored by Python, so the method always used its defaults. Not harmful but incorrect.

**Fix:** Changed to:
```python
await service.download_new_ad_assets(
    brand_id=UUID(brand_id),
    max_videos=params.get('download_max_videos', 20),
    max_images=params.get('download_max_images', 40),
)
```
Now uses correct kwarg names and is configurable via meta_sync job parameters.

---

## Full Day Summary (2026-02-05)

All work done on branch `feat/veo-avatar-tool`:

| # | Feature | Commits |
|---|---------|---------|
| 1 | Background ad classification job type + Run Now buttons | `CHECKPOINT_2026-02-05_ad_intelligence.md` |
| 2 | BatchClassificationResult — accurate error vs skipped reporting | `ad04156`, `6002c43` |
| 3 | Remove copy-only classification fallback (skip instead of pollute) | `50c395b` |
| 4 | Remove garbage-dict error fallback + stale docs cleanup | `a1a1d6d` |
| 5 | Standalone asset_download job type | `f079bde` |
| 6 | meta_sync max_downloads kwarg bug fix | `f079bde` |
| 7 | Railway CLI skill (global) | N/A (not in repo) |

**Tech debt resolved:** Items 12 (asset download decoupling) and 13 (meta_sync kwarg bug).

**Pipeline now fully decoupled:**
- `meta_sync` — syncs ad data from Meta API
- `asset_download` — downloads creative files (videos + images) to Supabase storage
- `ad_classification` — pre-computes awareness classifications via Gemini
- Each can be scheduled independently with its own cadence and settings
