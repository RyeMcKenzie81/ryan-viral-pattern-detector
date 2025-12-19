-- Migration: Add campaign_name to meta_ads_performance
-- Date: 2025-12-19
-- Purpose: Store campaign name for display in hierarchy views

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    campaign_name TEXT;

CREATE INDEX IF NOT EXISTS idx_meta_perf_campaign_name ON meta_ads_performance(campaign_name);

COMMENT ON COLUMN meta_ads_performance.campaign_name IS 'Campaign name from Meta for display';
