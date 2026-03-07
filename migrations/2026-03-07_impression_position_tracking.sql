-- Migration: Add position & impression tracking columns to facebook_ads
-- Date: 2026-03-07
-- Purpose: Capture Apify position data and parsed impression bounds for
--          impression-based scoring and collation dedup (Fix 10 Phase 1)

-- Position tracking
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS best_scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS latest_scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS scrape_total INT;

-- Parsed impression data (for EU/political ads when available)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_lower INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_upper INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_text TEXT;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_facebook_ads_best_position
    ON facebook_ads(best_scrape_position) WHERE best_scrape_position IS NOT NULL;

-- Comments
COMMENT ON COLUMN facebook_ads.scrape_position IS
    'Raw Apify position field from most recent scrape (inflated by creative group expansion)';
COMMENT ON COLUMN facebook_ads.best_scrape_position IS
    'Best (lowest) deduped creative position ever seen — the primary scoring signal';
COMMENT ON COLUMN facebook_ads.latest_scrape_position IS
    'Most recent deduped creative position — used with start_date for velocity';
COMMENT ON COLUMN facebook_ads.scrape_total IS
    'Total ads in search results at time of scrape — for position normalization';
COMMENT ON COLUMN facebook_ads.impression_lower IS
    'Lower bound of impression range (parsed from impressions_with_index)';
COMMENT ON COLUMN facebook_ads.impression_upper IS
    'Upper bound of impression range (parsed from impressions_with_index)';
COMMENT ON COLUMN facebook_ads.impression_text IS
    'Display text for impression range (e.g. "1K-5K")';
