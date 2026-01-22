-- ============================================================================
-- Migration: Template Scrape Longevity Tracking
-- ============================================================================
-- Date: 2025-01-22
-- Purpose: Add longevity tracking columns to facebook_ads table and
--          add template_scrape job type to scheduled_jobs.
--
-- Changes:
--   1. Add first_seen_at, last_seen_at, last_checked_at, times_seen to facebook_ads
--   2. Backfill existing records
--   3. Add indexes for longevity queries
--   4. Update scheduled_jobs job_type constraint to include template_scrape
-- ============================================================================

-- ============================================================================
-- 1. Add longevity tracking columns to facebook_ads
-- ============================================================================

-- first_seen_at: When we first scraped this ad
ALTER TABLE facebook_ads
ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;

-- last_seen_at: Last time we saw this ad as active during a scrape
ALTER TABLE facebook_ads
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

-- last_checked_at: Last time we checked this ad (regardless of active status)
ALTER TABLE facebook_ads
ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;

-- times_seen: Number of times we've seen this ad across scrapes
ALTER TABLE facebook_ads
ADD COLUMN IF NOT EXISTS times_seen INT DEFAULT 1;

COMMENT ON COLUMN facebook_ads.first_seen_at IS 'When we first scraped this ad';
COMMENT ON COLUMN facebook_ads.last_seen_at IS 'Last time we saw this ad as active during a scrape';
COMMENT ON COLUMN facebook_ads.last_checked_at IS 'Last time we checked this ad (regardless of status)';
COMMENT ON COLUMN facebook_ads.times_seen IS 'Number of times seen across scrapes (for dedup tracking)';

-- ============================================================================
-- 2. Backfill existing records
-- ============================================================================

-- Set first_seen_at to scraped_at for existing records
UPDATE facebook_ads
SET first_seen_at = scraped_at,
    last_seen_at = CASE
        WHEN is_active THEN scraped_at
        ELSE COALESCE(end_date, scraped_at)
    END,
    last_checked_at = scraped_at,
    times_seen = 1
WHERE first_seen_at IS NULL;

-- ============================================================================
-- 3. Add indexes for longevity queries
-- ============================================================================

-- Index for finding ads by first seen date (for "new ads" queries)
CREATE INDEX IF NOT EXISTS idx_facebook_ads_first_seen
ON facebook_ads(first_seen_at);

-- Index for finding ads by last seen date (for "days active" sorting)
CREATE INDEX IF NOT EXISTS idx_facebook_ads_last_seen
ON facebook_ads(last_seen_at);

-- Index for finding ads that need checking (stale check)
CREATE INDEX IF NOT EXISTS idx_facebook_ads_last_checked
ON facebook_ads(last_checked_at);

-- ============================================================================
-- 4. Update scheduled_jobs job_type constraint
-- ============================================================================

-- Drop existing constraint if it exists
ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

-- Add updated constraint with template_scrape
ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard', 'template_scrape'));

-- ============================================================================
-- Done! Template scrape jobs use brand_id only (product_id is already nullable)
-- ============================================================================
