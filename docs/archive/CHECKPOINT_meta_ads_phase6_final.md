# Checkpoint: Meta Ads Performance - Phase 6 FINAL (Automation Tested)

**Date**: 2025-12-20
**Status**: COMPLETE AND TESTED

## Summary

Phase 6 Automation is now fully implemented and tested. The scheduler worker successfully syncs Meta Ads performance data on a daily schedule.

## Test Results

**Successful Run** (2025-12-20 21:02:59 UTC):
```
status: completed
Syncing Meta Ads for brand: Wonder Paws
Days back: 7
Fetching insights for last 7 days...
Fetched 710 insight records
Synced 0 ads, 710 data rows
```

## Issues Resolved During Testing

### 1. Branch Deployment Issue
- **Problem**: Render scheduler worker was deployed from wrong branch
- **Solution**: Switched Render to deploy from `main` branch

### 2. Foreign Key Relationship Error
- **Problem**: PostgREST couldn't find FK relationship between `scheduled_jobs` and `brands`
- **Error**: `Could not find a relationship between 'scheduled_jobs' and 'brands'`
- **Solution**: Fetch brands separately instead of using FK join syntax in `get_due_jobs()`

### 3. API Method Signature Error
- **Problem**: `sync_performance_to_db() got an unexpected keyword argument 'ad_account_id'`
- **Solution**: Use correct flow: `get_ad_insights()` → `sync_performance_to_db(insights)`

### 4. Null Value Handling
- **Problem**: `object of type 'NoneType' has no len()` on `template_ids`
- **Solution**: Use `job.get('template_ids') or []` pattern instead of `job.get('template_ids', [])`

### 5. Meta API Token Missing
- **Problem**: `(#200) Provide valid app ID` error
- **Solution**: Add `META_GRAPH_API_TOKEN` environment variable to Render scheduler worker

### 6. UI Fixes
- **Nested expander error**: Replaced expander with divider + markdown header
- **Duplicate element ID**: Added unique keys to text_area widgets

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/worker/scheduler_worker.py` | Fixed null handling, API flow, brand fetching |
| `viraltracker/ui/pages/30_📈_Ad_Performance.py` | Fixed nested expander issue |
| `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | Fixed job type display, duplicate widget IDs |

## Key Code Patterns

### Defensive Null Handling
```python
# Use `or` pattern for values that may be explicitly null
templates = job.get('template_ids') or []  # Handles null correctly
params = job.get('parameters') or {}
brand_info = job.get('brands') or {}
```

### Correct Meta Sync Flow
```python
# Step 1: Fetch insights from Meta API
insights = await service.get_ad_insights(
    brand_id=UUID(brand_id),
    days_back=days_back
)

# Step 2: Save to database
rows_inserted = await service.sync_performance_to_db(
    insights=insights,
    brand_id=UUID(brand_id)
)
```

### Fetching Brands Separately (for PostgREST)
```python
# Can't use FK join syntax for scheduled_jobs → brands
# Fetch brands in a separate query
brand_ids_needed = set()
for job in jobs:
    if not job.get('products') and job.get('brand_id'):
        brand_ids_needed.add(job['brand_id'])

if brand_ids_needed:
    brands_result = db.table("brands").select("id, name").in_("id", list(brand_ids_needed)).execute()
    brand_map = {b['id']: b for b in (brands_result.data or [])}
```

## Deployment Checklist

For Render scheduler worker service:
- [x] Deploy from `main` branch
- [x] Add `META_GRAPH_API_TOKEN` environment variable
- [x] Verify service restarts on push

## Active Schedule

| Job Name | Brand | Schedule | Status |
|----------|-------|----------|--------|
| Daily Meta Ads Sync | Wonder Paws | 10 AM PST daily | Active |

## SQL Commands Reference

### Trigger Job Manually
```sql
UPDATE scheduled_jobs
SET next_run_at = NOW()
WHERE job_type = 'meta_sync'
AND status = 'active';
```

### Check Latest Run
```sql
SELECT r.status, r.error_message, r.logs
FROM scheduled_job_runs r
JOIN scheduled_jobs j ON r.scheduled_job_id = j.id
WHERE j.job_type = 'meta_sync'
ORDER BY r.started_at DESC
LIMIT 1;
```

## What's Next: Phase 7 (Future)

**OAuth Per-Brand Authentication**
- For connecting ad accounts not in your Business Manager
- Per-brand token storage and refresh
- "Connect Facebook" button in brand settings

## Reference Files

- **Previous checkpoint**: `docs/archive/CHECKPOINT_meta_ads_phase6.md`
- **Scheduler worker**: `viraltracker/worker/scheduler_worker.py`
- **Ad Performance UI**: `viraltracker/ui/pages/30_📈_Ad_Performance.py`
- **Meta Ads Service**: `viraltracker/services/meta_ads_service.py`
