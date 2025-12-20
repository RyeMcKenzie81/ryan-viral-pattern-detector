# Checkpoint: Meta Ads Performance - Phase 6 Complete (Automation)

**Date**: 2025-12-19
**Context Window**: Fresh session

## Summary

Implemented Phase 6: Automation - extended the scheduler worker to support Meta Ads sync and scorecard jobs alongside existing ad creation jobs.

## What Was Implemented

### 1. Database Migration

Added `job_type` column to `scheduled_jobs` table:
- Default: `'ad_creation'` (backward compatible)
- New types: `'meta_sync'`, `'scorecard'`
- Made `product_id` and `template_mode` nullable for non-ad jobs

**File**: `migrations/2025-12-19_add_scheduler_job_types.sql`

### 2. Scheduler Worker Extensions

Modified `scheduler_worker.py` to route jobs by type:

**Job Routing** (`execute_job()`):
```python
if job_type == 'meta_sync':
    return await execute_meta_sync_job(job)
elif job_type == 'scorecard':
    return await execute_scorecard_job(job)
else:
    return await execute_ad_creation_job(job)  # Default
```

### 3. Meta Sync Job Handler

**Function**: `execute_meta_sync_job(job)`

Syncs Meta Ads performance data for a brand:
- Gets brand's ad account from `brand_ad_accounts` table
- Calls `MetaAdsService.sync_performance_to_db()`
- Parameters from `job['parameters']`:
  - `days_back`: Number of days to sync (default: 7)

### 4. Scorecard Job Handler

**Function**: `execute_scorecard_job(job)`

Generates weekly performance analysis:
- Aggregates performance data by ad
- Calculates ROAS for each ad
- Categorizes into top performers (ROAS >= 2x) and needs attention (ROAS < 1x)
- Generates summary report
- Parameters from `job['parameters']`:
  - `days_back`: Analysis period (default: 7)
  - `min_spend`: Minimum spend filter (default: $10)
  - `export_email`: Email to send report (optional)

### 5. Scheduling UI

Added automated sync scheduling to Ad Performance page:
- Expander section: "⏰ Automated Sync Schedule"
- When no schedule exists:
  - Select sync time (hour in PST)
  - Select days to sync (3, 7, 14, or 30)
  - "Enable Daily Sync" button
- When schedule exists:
  - Shows active schedule info
  - Shows last run status
  - "Remove" button to disable

**Location**: `render_sync_scheduling()` in `30_📈_Ad_Performance.py`

## Files Modified

| File | Changes |
|------|---------|
| `migrations/2025-12-19_add_scheduler_job_types.sql` | New migration for job_type column |
| `viraltracker/worker/scheduler_worker.py` | Added job routing, meta_sync handler, scorecard handler |
| `viraltracker/ui/pages/30_📈_Ad_Performance.py` | Added `render_sync_scheduling()` UI |

## Job Types Summary

| Job Type | Purpose | Required Fields | Parameters |
|----------|---------|-----------------|------------|
| `ad_creation` | Generate ads from templates | `product_id`, `template_mode` | `num_variations`, `color_mode`, etc. |
| `meta_sync` | Sync Meta Ads data | `brand_id` | `days_back` |
| `scorecard` | Weekly performance report | `brand_id` | `days_back`, `min_spend`, `export_email` |

## How to Use

### Schedule Daily Meta Sync (UI)
1. Go to Ad Performance page
2. Select a brand with linked ad account
3. Expand "⏰ Automated Sync Schedule"
4. Choose time and days to sync
5. Click "Enable Daily Sync"

### Schedule via SQL (Direct)
```sql
INSERT INTO scheduled_jobs (
    brand_id, name, job_type, schedule_type,
    cron_expression, next_run_at, parameters
) VALUES (
    'your-brand-uuid',
    'Daily Meta Ads Sync',
    'meta_sync',
    'recurring',
    '0 6 * * *',  -- 6 AM daily
    NOW() + INTERVAL '1 day',
    '{"days_back": 7}'::jsonb
);
```

### Schedule Weekly Scorecard
```sql
INSERT INTO scheduled_jobs (
    brand_id, name, job_type, schedule_type,
    cron_expression, next_run_at, parameters
) VALUES (
    'your-brand-uuid',
    'Weekly Performance Scorecard',
    'scorecard',
    'recurring',
    '0 9 * * 1',  -- Mondays 9 AM
    NOW() + INTERVAL '7 days',
    '{"days_back": 7, "min_spend": 10.0, "export_email": "you@example.com"}'::jsonb
);
```

## What's Next: Phase 7 (Future)

**OAuth Per-Brand Authentication**
- For connecting ad accounts not in your Business Manager
- Per-brand token storage and refresh
- "Connect Facebook" button in brand settings

## Reference Files

- **Plan**: `/Users/ryemckenzie/.claude/plans/rippling-cuddling-summit.md`
- **Previous checkpoint**: `/docs/archive/CHECKPOINT_meta_ads_phase5_final.md`
- **Scheduler worker**: `viraltracker/worker/scheduler_worker.py`
- **Ad Performance UI**: `viraltracker/ui/pages/30_📈_Ad_Performance.py`
- **Meta Ads Service**: `viraltracker/services/meta_ads_service.py`

## Brand ID Reference

Wonder Paws: `bc8461a8-232d-4765-8775-c75eaafc5503`
