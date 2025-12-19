-- Migration: Meta Ads Performance Feedback Loop
-- Date: 2025-12-18
-- Purpose: Add tables to store Meta Ads performance data for feedback loop
--
-- Tables created:
--   - brand_ad_accounts: Links brands to Meta ad accounts (1:many ready)
--   - meta_ads_performance: Time-series performance snapshots
--   - meta_ad_mapping: Links generated_ads to Meta ads
--   - meta_campaigns: Campaign metadata cache

-- Ad accounts linked to brands (future: multiple accounts per brand)
CREATE TABLE IF NOT EXISTS brand_ad_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_account_id TEXT NOT NULL,  -- e.g., "act_123456789"
    account_name TEXT,                  -- Display name
    is_primary BOOLEAN DEFAULT true,    -- For future multi-account
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, meta_ad_account_id)
);

CREATE INDEX IF NOT EXISTS idx_brand_ad_accounts_brand ON brand_ad_accounts(brand_id);

COMMENT ON TABLE brand_ad_accounts IS 'Links brands to their Meta (Facebook) ad accounts';
COMMENT ON COLUMN brand_ad_accounts.meta_ad_account_id IS 'Meta ad account ID, e.g., act_123456789';
COMMENT ON COLUMN brand_ad_accounts.is_primary IS 'Primary account for this brand (for future multi-account support)';

-- Time-series performance data
CREATE TABLE IF NOT EXISTS meta_ads_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_account_id TEXT NOT NULL,   -- Source ad account
    meta_ad_id TEXT NOT NULL,
    meta_campaign_id TEXT NOT NULL,
    ad_name TEXT,                       -- Ad name (for matching)
    date DATE NOT NULL,

    -- Core metrics
    spend NUMERIC(12, 2),
    impressions INTEGER,
    reach INTEGER,
    frequency NUMERIC(10, 3),

    -- Link metrics
    link_clicks INTEGER,
    link_ctr NUMERIC(10, 4),        -- outbound_clicks_ctr
    link_cpc NUMERIC(10, 4),        -- cost_per_outbound_click

    -- Conversion metrics
    add_to_carts INTEGER,
    cost_per_add_to_cart NUMERIC(10, 4),
    purchases INTEGER,
    purchase_value NUMERIC(12, 2),
    roas NUMERIC(8, 4),             -- purchase_roas
    conversion_rate NUMERIC(10, 4), -- calculated: purchases / link_clicks * 100

    -- Video metrics (nullable, for video ads)
    video_views INTEGER,
    video_avg_watch_time NUMERIC(8, 2),
    video_p25_watched INTEGER,
    video_p50_watched INTEGER,
    video_p75_watched INTEGER,
    video_p100_watched INTEGER,

    -- Extensibility - store raw arrays for future metrics
    raw_actions JSONB,              -- Full actions array from Meta
    raw_costs JSONB,                -- Full cost_per_action_type array

    -- Tracking
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(meta_ad_id, date)
);

CREATE INDEX IF NOT EXISTS idx_meta_perf_brand ON meta_ads_performance(brand_id);
CREATE INDEX IF NOT EXISTS idx_meta_perf_account ON meta_ads_performance(meta_ad_account_id);
CREATE INDEX IF NOT EXISTS idx_meta_perf_date ON meta_ads_performance(date);
CREATE INDEX IF NOT EXISTS idx_meta_perf_ad_name ON meta_ads_performance(ad_name);

COMMENT ON TABLE meta_ads_performance IS 'Daily performance snapshots from Meta Ads API';
COMMENT ON COLUMN meta_ads_performance.ad_name IS 'Ad name from Meta, used for auto-matching to generated ads';
COMMENT ON COLUMN meta_ads_performance.link_ctr IS 'Outbound clicks CTR (outbound_clicks_ctr from Meta)';
COMMENT ON COLUMN meta_ads_performance.link_cpc IS 'Cost per outbound click (cost_per_outbound_click from Meta)';
COMMENT ON COLUMN meta_ads_performance.raw_actions IS 'Full actions array from Meta API for extensibility';

-- Link generated ads to Meta ads
CREATE TABLE IF NOT EXISTS meta_ad_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID REFERENCES generated_ads(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,
    meta_ad_account_id TEXT NOT NULL,   -- Source ad account
    meta_campaign_id TEXT NOT NULL,
    creative_hash TEXT,             -- image_hash from Meta (for future use)
    linked_at TIMESTAMPTZ DEFAULT NOW(),
    linked_by TEXT DEFAULT 'manual', -- 'auto' or 'manual'

    UNIQUE(generated_ad_id, meta_ad_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_mapping_generated ON meta_ad_mapping(generated_ad_id);
CREATE INDEX IF NOT EXISTS idx_meta_mapping_meta_ad ON meta_ad_mapping(meta_ad_id);

COMMENT ON TABLE meta_ad_mapping IS 'Links ViralTracker generated_ads to Meta ads for performance tracking';
COMMENT ON COLUMN meta_ad_mapping.linked_by IS 'How the link was created: auto (ID match) or manual (user linked)';

-- Campaign metadata cache
CREATE TABLE IF NOT EXISTS meta_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_account_id TEXT NOT NULL,   -- Source ad account
    meta_campaign_id TEXT NOT NULL,
    name TEXT,
    status TEXT,                        -- ACTIVE, PAUSED, DELETED, ARCHIVED
    objective TEXT,                     -- CONVERSIONS, TRAFFIC, etc.
    daily_budget NUMERIC(12, 2),
    lifetime_budget NUMERIC(12, 2),
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(meta_ad_account_id, meta_campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_campaigns_brand ON meta_campaigns(brand_id);
CREATE INDEX IF NOT EXISTS idx_meta_campaigns_status ON meta_campaigns(status);

COMMENT ON TABLE meta_campaigns IS 'Cached campaign metadata from Meta Ads API';
