# Data Pipeline Control Plane — Checkpoint 002

**Date:** 2026-02-07
**Phase:** Live Testing + UX Fix
**Status:** Partially tested, one UX fix applied

## Test Results

### Test 1: Queue-Based Meta Sync ✅
- Queued via Ad Performance "Sync Ads" button (non-legacy mode)
- Worker picked up the job within 60 seconds
- Job executed successfully:
  - Fetched 2343 insight records (30 days)
  - Synced 2343 data rows to performance table
  - Updated 100 missing thumbnails
  - Downloaded 2 images to storage
- Hit Meta API rate limit during fetch — MetaAdsService retry logic handled it (retry 1/3 after 15s)

### Test 2: Stuck Run Recovery ✅
- On first startup, recovery sweep found 5 genuinely stuck runs from Dec 2025 - Jan 2026
- All marked failed with descriptive error message
- Parent jobs rescheduled with retry backoff (attempt 1, retry in 5m)
- Second poll cycle: no more stuck runs found (one-time cleanup)

### Test 3: Dataset Freshness Recording ✅
- `dataset_status` table populated via POST → 201 Created (record_start)
- After completion: POST → 200 OK (record_success upsert)
- `ad_assets` dataset also recorded separately

### Test 4: Auto-Archive ✅
- One-time manual job completed → status set to `archived`
- Job no longer appears in active job queries

### Test 5: Freshness Banner on Ad Performance — Fixed
- **Issue found:** Banner only showed warnings (stale/missing), no positive indicator for fresh data
- **User expectation:** See confirmation that data is fresh
- **Fix applied:** Banner now shows green `st.success` line when all datasets are fresh (e.g., "Data fresh: **Ad Performance Data** synced 5m ago")
- When mixed (some fresh, some stale): fresh shown as `st.info`, stale as `st.warning`

### Test 6: Pipeline Manager in Sidebar — User Action Needed
- **Issue found:** Pipeline Manager not appearing in sidebar
- **Root cause:** `pipeline_manager` is an opt-in feature key (hidden by default)
- **Fix:** User needs to go to Admin → System section → toggle "Pipeline Manager" ON
- **Not a bug** — this is the standard feature gating pattern for all opt-in pages

## Remaining Tests

### Not Yet Tested
- [ ] **Pipeline Manager Health tab** — verify brand freshness grid with color coding
- [ ] **Pipeline Manager Schedules tab** — create/update recurring schedule, test cadence presets
- [ ] **Pipeline Manager Active Jobs tab** — verify pause/resume controls
- [ ] **Pipeline Manager Run History tab** — verify filters and expandable logs
- [ ] **Pipeline Manager Freshness Matrix tab** — verify brand x dataset grid
- [ ] **Pipeline Manager "Run Now" buttons** — verify they create one-time jobs
- [ ] **Legacy sync toggle** — verify checkbox enables old blocking sync path
- [ ] **Retry exhaustion** — simulate 3 consecutive failures, verify backoff then cron fallback
- [ ] **Recurring schedule via Pipeline Manager** — create daily meta_sync, verify worker picks it up
- [ ] **Multiple brands** — verify freshness is tracked independently per brand
- [ ] **Freshness banner green indicator** — verify new success banner appears after sync

## Changes in This Checkpoint

### Modified Files
| File | Change |
|---|---|
| `viraltracker/ui/utils.py` | `render_freshness_banner()` now shows green success indicator when all datasets fresh, info when mixed |

## Known Issues

1. **"0 ads synced" in logs** — Pre-existing: `ads_synced` counts unique `ad_id` keys from raw insights, but the field name may differ in Meta API response. Data rows are synced correctly (2343 rows). Cosmetic only.

2. **Recovered stuck runs trigger retries** — Expected behavior: old stuck jobs get rescheduled for retry, will exhaust retries (3 max) and settle. One-time cleanup cost.
