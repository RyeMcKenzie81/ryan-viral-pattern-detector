-- Migration: Meta Ads Demographic Performance Breakdowns
-- Date: 2026-04-02
-- Purpose: Store age/gender and placement breakdown data from Meta API
--          for demographic performance analysis in Creative Intelligence dashboard.

CREATE TABLE IF NOT EXISTS meta_ads_demographic_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_account_id TEXT NOT NULL,
    meta_ad_id TEXT NOT NULL,
    date DATE NOT NULL,

    -- Breakdown dimensions (empty string = not applicable for this breakdown_type)
    breakdown_type TEXT NOT NULL CHECK (breakdown_type IN ('age_gender', 'placement')),
    age_range TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    publisher_platform TEXT NOT NULL DEFAULT '',
    platform_position TEXT NOT NULL DEFAULT '',

    -- Core metrics
    spend NUMERIC(12, 2),
    impressions INTEGER,
    reach INTEGER,
    link_clicks INTEGER,
    link_ctr NUMERIC(10, 4),
    purchases INTEGER,
    purchase_value NUMERIC(12, 2),
    roas NUMERIC(8, 4),
    add_to_carts INTEGER,
    video_views INTEGER,

    fetched_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(meta_ad_id, date, breakdown_type, age_range, gender, publisher_platform, platform_position)
);

COMMENT ON TABLE meta_ads_demographic_performance IS 'Per-ad daily performance broken down by demographics (age/gender) and placement (platform/position). Populated by meta_sync scheduler job.';
COMMENT ON COLUMN meta_ads_demographic_performance.breakdown_type IS 'age_gender or placement — determines which dimension columns are populated';
COMMENT ON COLUMN meta_ads_demographic_performance.age_range IS 'Meta age bucket: 18-24, 25-34, 35-44, 45-54, 55-64, 65+. Empty string for placement rows.';
COMMENT ON COLUMN meta_ads_demographic_performance.gender IS 'male, female, or unknown. Empty string for placement rows.';
COMMENT ON COLUMN meta_ads_demographic_performance.publisher_platform IS 'facebook, instagram, audience_network, messenger. Empty string for age_gender rows.';
COMMENT ON COLUMN meta_ads_demographic_performance.platform_position IS 'feed, story, reels, right_hand_column, search, marketplace, etc. Empty string for age_gender rows.';

CREATE INDEX IF NOT EXISTS idx_demo_perf_brand_date ON meta_ads_demographic_performance(brand_id, date);
CREATE INDEX IF NOT EXISTS idx_demo_perf_brand_type ON meta_ads_demographic_performance(brand_id, breakdown_type);
CREATE INDEX IF NOT EXISTS idx_demo_perf_ad ON meta_ads_demographic_performance(meta_ad_id);
