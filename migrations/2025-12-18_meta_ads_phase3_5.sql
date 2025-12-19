-- Migration: Meta Ads Phase 3.5 Enhancements
-- Date: 2025-12-18
-- Purpose: Add CPM, ad status, and adset support for Facebook-style hierarchy

-- Add CPM and status to performance table
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    cpm NUMERIC(10, 4);  -- Cost per 1000 impressions

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    ad_status TEXT;  -- ACTIVE, PAUSED, DELETED, ARCHIVED, etc.

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    meta_adset_id TEXT;  -- Ad set ID for hierarchy grouping

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    adset_name TEXT;  -- Ad set name for display

-- Add indexes for hierarchy queries
CREATE INDEX IF NOT EXISTS idx_meta_perf_adset ON meta_ads_performance(meta_adset_id);
CREATE INDEX IF NOT EXISTS idx_meta_perf_campaign ON meta_ads_performance(meta_campaign_id);
CREATE INDEX IF NOT EXISTS idx_meta_perf_status ON meta_ads_performance(ad_status);

-- Update campaigns table with counts
ALTER TABLE meta_campaigns ADD COLUMN IF NOT EXISTS
    adset_count INTEGER DEFAULT 0;

ALTER TABLE meta_campaigns ADD COLUMN IF NOT EXISTS
    ad_count INTEGER DEFAULT 0;

-- Create ad sets table for caching adset metadata
CREATE TABLE IF NOT EXISTS meta_adsets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_account_id TEXT NOT NULL,
    meta_adset_id TEXT NOT NULL,
    meta_campaign_id TEXT NOT NULL,
    name TEXT,
    status TEXT,  -- ACTIVE, PAUSED, DELETED, ARCHIVED
    optimization_goal TEXT,  -- CONVERSIONS, LINK_CLICKS, etc.
    billing_event TEXT,  -- IMPRESSIONS, LINK_CLICKS, etc.
    daily_budget NUMERIC(12, 2),
    lifetime_budget NUMERIC(12, 2),
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(meta_ad_account_id, meta_adset_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_adsets_campaign ON meta_adsets(meta_campaign_id);
CREATE INDEX IF NOT EXISTS idx_meta_adsets_brand ON meta_adsets(brand_id);
CREATE INDEX IF NOT EXISTS idx_meta_adsets_status ON meta_adsets(status);

COMMENT ON TABLE meta_adsets IS 'Cached ad set metadata from Meta Ads API';
COMMENT ON COLUMN meta_ads_performance.cpm IS 'Cost per 1000 impressions: (spend / impressions) * 1000';
COMMENT ON COLUMN meta_ads_performance.ad_status IS 'Ad delivery status from Meta: ACTIVE, PAUSED, DELETED, etc.';
