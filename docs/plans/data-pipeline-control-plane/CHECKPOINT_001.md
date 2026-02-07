# Data Pipeline Control Plane — Checkpoint 001

**Date:** 2026-02-06
**Phase:** Batch 1-3 Complete (Phases 1-4)
**Status:** Implementation complete, pending migration execution

## What Was Built

### Phase 1: Dataset Freshness Tracking + Readiness Banner

1. **`dataset_status` table** (`migrations/2026-02-06_dataset_status.sql`)
   - Tracks freshness per brand per dataset_key
   - Separates `last_success_at` from `last_attempt_at` (failed runs don't make data look fresh)
   - Includes `error_message`, `records_affected`, `metadata` JSONB
   - `updated_at` trigger for auto-timestamp
   - Multi-tenant via `organization_id`

2. **`DatasetFreshnessService`** (`viraltracker/services/dataset_freshness_service.py`)
   - `record_start()` — sets running, never touches last_success_at
   - `record_success()` — updates last_success_at, clears error
   - `record_failure()` — sets failed, stores error, never touches last_success_at
   - `get_freshness()`, `get_all_freshness()`, `check_is_fresh()`
   - All methods upsert on `(brand_id, dataset_key)` unique constraint

3. **Step-level freshness in meta_sync** (`viraltracker/worker/scheduler_worker.py`)
   - Steps 1-2 (performance data): fatal — failure marks whole job failed
   - Steps 3-5 (thumbnails, assets, classification): non-fatal — each dataset tracked independently
   - Each step records its own start/success/failure to its own dataset_key

4. **Manual sync freshness** (`viraltracker/ui/pages/30_📈_Ad_Performance.py`)
   - Records start/success/failure around the legacy manual sync path

5. **Dataset requirements registry** (`viraltracker/ui/dataset_requirements.py`)
   - Maps page keys to required datasets with max_age_hours and fix actions
   - Covers: ad_performance, hook_analysis, template_queue, template_evaluation, congruence_insights

6. **Freshness banner** (`viraltracker/ui/utils.py`)
   - `render_freshness_banner(brand_id, page_key)` shows stale/failed/never-synced warnings
   - Shows last success age, current running status, failure errors
   - Added to Ad Performance page after brand selector

### Phase 2: Migrate Manual Meta Sync to Queue

7. **Pipeline helpers** (`viraltracker/services/pipeline_helpers.py`)
   - `ensure_recurring_job()` — create or update recurring schedule for (brand_id, job_type)
   - `queue_one_time_job()` — queue immediate one-time execution

8. **Scheduler enhancements migration** (`migrations/2026-02-06_scheduler_enhancements.sql`)
   - Added `trigger_source` column: 'scheduled', 'manual', 'api'
   - Added 'archived' to status CHECK constraint

9. **Queue-based manual sync** (`viraltracker/ui/pages/30_📈_Ad_Performance.py`)
   - Default: queues to background worker via `queue_one_time_job()`
   - Legacy toggle: checkbox to run sync directly (old blocking path)

10. **Auto-archive** (`viraltracker/worker/scheduler_worker.py`)
    - Completed one-time manual jobs get `status='archived'`
    - Prevents table clutter from "Run Now" accumulation

11. **Ad Scheduler fix** (`viraltracker/ui/pages/24_📅_Ad_Scheduler.py`)
    - "All" filter now excludes archived jobs

### Phase 3: Pipeline Manager UI

12. **Pipeline Manager** (`viraltracker/ui/pages/62_🔧_Pipeline_Manager.py`, ~550 lines)
    - **Tab 1: Health Overview** — per-brand dataset freshness grid, color-coded, Run Now buttons
    - **Tab 2: Schedules** — brand-scoped recurring schedule management with cadence presets
    - **Tab 3: Active Jobs** — all active/paused jobs with pause/resume controls
    - **Tab 4: Run History** — recent runs with filters and expandable logs
    - **Tab 5: Freshness Matrix** — brand x dataset grid view

13. **Nav registration** (`viraltracker/ui/nav.py`)
    - Added Pipeline Manager to System section

14. **Feature gating** (`viraltracker/services/feature_service.py`, `viraltracker/ui/pages/69_🔧_Admin.py`)
    - Added `PIPELINE_MANAGER` feature key
    - Added to Admin toggles

### Phase 4: Retry Logic + Stuck Run Recovery

15. **Retry migration** (`migrations/2026-02-06_scheduler_retry_columns.sql`)
    - `max_retries` (default 3) and `last_error` on scheduled_jobs
    - `attempt_number` (default 1) on scheduled_job_runs

16. **Retry logic** (`viraltracker/worker/scheduler_worker.py`)
    - `_reschedule_after_failure()` now supports exponential backoff: 5m, 10m, 20m (capped 60m)
    - After retries exhausted: recurring jobs fall back to cron, one-time jobs stay dead
    - `create_job_run()` auto-calculates attempt_number from last run's status
    - `_update_job_next_run()` clears `last_error` on success

17. **Stuck run recovery** (`viraltracker/worker/scheduler_worker.py`)
    - `recover_stuck_runs()` — sweeps for runs stuck in 'running' > 30 minutes
    - Marks stuck runs as failed, reschedules parent job
    - Runs at the start of every poll cycle

## File Summary

### New Files (7)
| File | Lines |
|---|---|
| `migrations/2026-02-06_dataset_status.sql` | 52 |
| `migrations/2026-02-06_scheduler_enhancements.sql` | 17 |
| `migrations/2026-02-06_scheduler_retry_columns.sql` | 9 |
| `viraltracker/services/dataset_freshness_service.py` | 195 |
| `viraltracker/services/pipeline_helpers.py` | 155 |
| `viraltracker/ui/dataset_requirements.py` | 60 |
| `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | 550 |

### Modified Files (7)
| File | Change Summary |
|---|---|
| `viraltracker/worker/scheduler_worker.py` | +189 lines (freshness, retries, stuck recovery, auto-archive) |
| `viraltracker/ui/utils.py` | +60 lines (freshness banner) |
| `viraltracker/ui/pages/30_📈_Ad_Performance.py` | +52/-10 lines (banner, queue sync, legacy toggle) |
| `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | +4 lines (archived exclusion) |
| `viraltracker/services/feature_service.py` | +1 line (PIPELINE_MANAGER key) |
| `viraltracker/ui/nav.py` | +2 lines (Pipeline Manager registration) |
| `viraltracker/ui/pages/69_🔧_Admin.py` | +1 line (admin toggle) |

## What's NOT Built Yet

- Phase 5 FastAPI endpoint (deferred)
- Freshness wiring for other 7 job handlers (ad_creation, scorecard, template_scrape, etc.)
- Freshness banners on other pages (hook_analysis, template_queue, etc.)
- Future page migrations (Template Queue, Brand Research, etc.)

## Activation Steps

1. Run the 3 SQL migrations against Supabase (in order)
2. Deploy updated worker
3. Enable `pipeline_manager` feature in Admin
4. Verify: trigger a meta_sync → check dataset_status rows appear → check Pipeline Manager Health tab

## Known Limitations

- Only meta_sync and manual Ad Performance sync record freshness (other handlers need wiring)
- pytest not installed in dev environment — tests not run
- No unit tests written yet for new services (DatasetFreshnessService, pipeline_helpers)
