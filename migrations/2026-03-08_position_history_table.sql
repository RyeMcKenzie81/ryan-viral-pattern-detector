-- Migration: Position history tracking for facebook ads
-- Date: 2026-03-08
-- Purpose: Track how ad positions change over time for trend detection

CREATE TABLE IF NOT EXISTS facebook_ad_position_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID NOT NULL REFERENCES facebook_ads(id) ON DELETE CASCADE,
    scrape_run_id UUID REFERENCES scheduled_job_runs(id),
    raw_position INT NOT NULL,
    deduped_position INT,
    scrape_total INT,
    is_active BOOLEAN DEFAULT TRUE,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(facebook_ad_id, scrape_run_id)
);

CREATE INDEX IF NOT EXISTS idx_fb_ad_position_history_ad_date
    ON facebook_ad_position_history(facebook_ad_id, scraped_at DESC);

COMMENT ON TABLE facebook_ad_position_history IS
    'Tracks position changes for facebook ads across scrape runs for trend detection';
COMMENT ON COLUMN facebook_ad_position_history.raw_position IS
    'Raw Apify position (inflated by creative group expansion)';
COMMENT ON COLUMN facebook_ad_position_history.deduped_position IS
    'Deduped creative position (counting only lead ads)';
COMMENT ON COLUMN facebook_ad_position_history.scrape_total IS
    'Total ads in search results at time of this scrape';
COMMENT ON COLUMN facebook_ad_position_history.is_active IS
    'Whether the ad was active at time of scrape';

-- Compaction function: keeps one entry per week for history > 30 days old,
-- caps at 100 entries per ad. Safe to run repeatedly.
CREATE OR REPLACE FUNCTION compact_position_history() RETURNS void AS $$
BEGIN
    -- Step 1: For entries older than 30 days, keep only the best (lowest)
    -- deduped_position per ad per ISO week
    DELETE FROM facebook_ad_position_history h
    WHERE h.scraped_at < NOW() - INTERVAL '30 days'
      AND h.id NOT IN (
          SELECT DISTINCT ON (facebook_ad_id, date_trunc('week', scraped_at))
                 id
          FROM facebook_ad_position_history
          WHERE scraped_at < NOW() - INTERVAL '30 days'
          ORDER BY facebook_ad_id, date_trunc('week', scraped_at),
                   COALESCE(deduped_position, raw_position) ASC
      );

    -- Step 2: Cap at 100 entries per ad (keep most recent)
    DELETE FROM facebook_ad_position_history
    WHERE id IN (
        SELECT id FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY facebook_ad_id
                       ORDER BY scraped_at DESC
                   ) as rn
            FROM facebook_ad_position_history
        ) ranked
        WHERE rn > 100
    );
END;
$$ LANGUAGE plpgsql;
