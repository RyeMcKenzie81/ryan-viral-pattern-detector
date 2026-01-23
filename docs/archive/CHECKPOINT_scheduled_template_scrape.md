# Checkpoint: Scheduled Template Scraping Feature

**Date:** 2025-01-22
**Branch:** feat/veo-avatar-tool
**Status:** Complete and tested

## Overview

Added the ability to schedule automated Facebook Ad Library scraping jobs that run on a recurring basis. This includes longevity tracking to monitor how long ads have been running.

## Features Implemented

### 1. New Job Type: `template_scrape`

A new scheduled job type that:
- Scrapes Facebook Ad Library at specified intervals
- Saves ads with deduplication (via `ad_archive_id`)
- Downloads image assets for new ads
- Queues assets for template review
- Tracks ad longevity (first seen, last seen, times seen)

### 2. Longevity Tracking

New columns on `facebook_ads` table to track ad lifespan:
- `first_seen_at` - When we first scraped this ad
- `last_seen_at` - Last time we saw the ad as active
- `last_checked_at` - Last time we checked this ad
- `times_seen` - Number of times seen across scrapes

### 3. Scheduled Tasks Dashboard

New UI page showing all upcoming scheduled jobs across all types (ad_creation, meta_sync, scorecard, template_scrape) grouped by timeframe in PST.

---

## Files Changed

### Database Migration

**`sql/2025-01-22_template_scrape_longevity.sql`**
```sql
-- Adds longevity tracking columns to facebook_ads
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS times_seen INT DEFAULT 1;

-- Adds template_scrape to job_type constraint
ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard', 'template_scrape'));
```

### Service Layer

**`viraltracker/services/ad_scraping_service.py`**

Modified `save_facebook_ad_with_tracking()` method:
- Checks if ad exists by `ad_archive_id`
- For new ads: Sets `first_seen_at`, `last_seen_at`, `times_seen=1`
- For existing ads: Preserves `first_seen_at`, updates `last_seen_at` if active, increments `times_seen`
- Returns dict with `ad_id`, `is_new`, `was_active` for tracking

Key code pattern:
```python
# Check if ad already exists
existing_result = self.supabase.table("facebook_ads").select(
    "id, first_seen_at, is_active, last_seen_at, times_seen"
).eq("ad_archive_id", ad_archive_id).execute()

existing = existing_result.data[0] if existing_result.data else None
is_new = existing is None
```

### Worker

**`viraltracker/worker/scheduler_worker.py`**

Added `execute_template_scrape_job()` handler (~150 lines):
- Fetches job parameters (search_url, max_ads, images_only, auto_queue)
- Calls `FacebookService.search_ads()` to scrape
- Builds ad dict manually (matching template_ingestion pattern)
- Saves each ad with `save_facebook_ad_with_tracking()`
- Downloads assets for new ads
- Queues assets for review if `auto_queue=True`
- Tracks new/updated/skipped counts

Key code pattern (must match template_ingestion.py exactly):
```python
ad_dict = {
    "id": ad.id,
    "ad_archive_id": ad.ad_archive_id,
    "page_id": ad.page_id,
    "page_name": ad.page_name,
    "is_active": ad.is_active,
    "start_date": ad.start_date.isoformat() if ad.start_date else None,
    "end_date": ad.end_date.isoformat() if ad.end_date else None,
    "currency": ad.currency,
    "spend": ad.spend,
    "impressions": ad.impressions,
    "reach_estimate": ad.reach_estimate,
    "snapshot": ad.snapshot,
    "categories": ad.categories,
    "publisher_platform": ad.publisher_platform,
    "political_countries": ad.political_countries,
    "entity_type": ad.entity_type,
}
```

Updated job router:
```python
if job_type == 'template_scrape':
    return await execute_template_scrape_job(job)
```

### UI Pages

**`viraltracker/ui/pages/24_📅_Ad_Scheduler.py`**

- Added job type selector (ad_creation vs template_scrape)
- Added `_render_template_scrape_form()` for scrape job configuration
- Form includes: brand selector, search URL input, max_ads, images_only, auto_queue options
- Added "📥" badge for template_scrape jobs in list view

**`viraltracker/ui/pages/28_📋_Template_Queue.py`**

- Added "Scheduled Scraping" tab (5th tab)
- Shows active template_scrape jobs with run history
- Displays recent scrape runs with stats

**`viraltracker/ui/pages/61_📅_Scheduled_Tasks.py`** (NEW)

- Dashboard showing all scheduled jobs grouped by timeframe
- Filters by job type and brand
- Shows jobs for Today, Tomorrow, This Week, Later
- Displays recent completed runs

### Scraper

**`viraltracker/scrapers/facebook_ads.py`**

- Added detailed logging of actor_input sent to Apify
- Logs full search URL for debugging

---

## Job Parameters Schema

Stored in `scheduled_jobs.parameters` (JSONB):

```json
{
    "search_url": "https://www.facebook.com/ads/library/?...",
    "max_ads": 250,
    "images_only": true,
    "auto_queue": true
}
```

---

## How It Works

### Creating a Scheduled Scrape

1. Go to **Ad Scheduler** page
2. Click **+ New Schedule**
3. Select **Template Scrape** job type
4. Select brand (for organization)
5. Enter Facebook Ad Library search URL
6. Configure: max ads, images only, auto queue
7. Set schedule (one-time or recurring with cron)
8. Save

### When Job Runs

1. Worker picks up due job from `scheduled_jobs` table
2. Clears `next_run_at` to prevent duplicate execution
3. Creates job run record
4. Calls Apify to scrape Facebook Ad Library
5. For each ad:
   - Skips video-only ads if `images_only=true`
   - Saves ad with longevity tracking (new or update)
   - Downloads assets for new ads only
   - Queues assets for review if `auto_queue=true`
6. Updates job run with results
7. Calculates next run time if recurring

### Deduplication

- Ads are deduplicated by `ad_archive_id` (unique constraint)
- Existing ads get updated (longevity fields)
- Assets only downloaded for truly new ads

---

## Bugs Fixed During Implementation

1. **FK error in Scheduled Tasks page** - Removed invalid `brands(name)` join, fetch brand names separately

2. **Non-existent columns error** - Removed `scraped_template_ids` and other columns that don't exist on `scheduled_jobs`

3. **Wrong URL appearing** - Was a red herring; user was looking at different job's logs

4. **All saves failing (243/243)** - Multiple issues:
   - Used `model_dump()` instead of manual dict building (datetime serialization)
   - Missing longevity columns (migration not run)
   - Used `.maybeSingle()` (JavaScript API) instead of `.execute()` (Python API)

5. **Supabase Python API** - `.maybeSingle()` doesn't exist in Python client. Use:
   ```python
   result = self.supabase.table(...).select(...).eq(...).execute()
   existing = result.data[0] if result.data else None
   ```

---

## Key Lessons Learned

### 1. Match Existing Patterns Exactly

The template_ingestion pipeline worked. The scheduled worker had to match it exactly:
- Build dict manually with specific fields (not `model_dump()`)
- Convert dates with `.isoformat()` explicitly
- Don't pass extra parameters

### 2. Supabase Python vs JavaScript API

Python client doesn't have:
- `.maybeSingle()` - use `.execute()` and check `result.data[0]`
- Some other convenience methods

### 3. Error Visibility

Worker logs go to stdout, not job run logs. Added error capture to return actual error messages in job results for visibility.

---

## Testing

### Successful Test Run

```
Scraping templates for brand: Wonder Paws
Search URL: https://www.facebook.com/ads/library/?...view_all_page_id=470900729771745
Max ads: 250, Images only: True, Auto queue: True
Scraped 243 ads from Facebook Ad Library
First ad: Wuffes (archive_id: 2191928707883881...)

=== Summary ===
New ads: 219
Updated ads: 24
Queued for review: 243
```

- 219 new ads saved
- 24 existing ads updated (longevity tracking working)
- 243 assets queued for review
- Runtime: ~15-20 minutes (includes asset downloads)

### Verify with SQL

```sql
SELECT
  id, page_name, ad_archive_id, scrape_source,
  first_seen_at, times_seen, created_at
FROM facebook_ads
WHERE scrape_source = 'scheduled_scrape'
ORDER BY created_at DESC
LIMIT 20;
```

---

## Future Enhancements

1. **Days Active Display** - Show `(last_seen_at - start_date).days` in Template Library UI
2. **Brand Linking** - Currently not passing brand_id to save (removed to match working pattern). Could re-add.
3. **Activity Status Tracking** - Mark ads as inactive when they disappear from scrapes
4. **Performance** - Could parallelize asset downloads

---

## Related Files

- Plan: `/Users/ryemckenzie/.claude/plans/polished-humming-lynx.md`
- Migration: `sql/2025-01-22_template_scrape_longevity.sql`
- Working reference: `viraltracker/pipelines/template_ingestion.py`
