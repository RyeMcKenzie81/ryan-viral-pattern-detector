-- Migration: Add missing columns to competitor_ads table
-- Date: 2025-12-11
-- Purpose: Add columns expected by competitor_service.save_competitor_ad()

-- Add brand_id for direct brand association (also retrievable via competitor_id -> competitors.brand_id)
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id) ON DELETE CASCADE;

-- Add page_id for Facebook page identifier
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS page_id TEXT;

-- Add stopped_running for end date of ad
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS stopped_running DATE;

-- Rename ad_body to ad_creative_body for consistency with service (if ad_body exists)
-- Note: We'll add ad_creative_body as new column instead of renaming to be safe
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS ad_creative_body TEXT;

-- Add scrape metadata
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS scrape_source TEXT;
ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ;

-- Add index for brand_id
CREATE INDEX IF NOT EXISTS idx_competitor_ads_brand ON competitor_ads(brand_id);

-- Comments
COMMENT ON COLUMN competitor_ads.brand_id IS 'Brand tracking this competitor (denormalized from competitors.brand_id)';
COMMENT ON COLUMN competitor_ads.page_id IS 'Facebook page ID of the advertiser';
COMMENT ON COLUMN competitor_ads.stopped_running IS 'Date the ad stopped running (end_date from Ad Library)';
COMMENT ON COLUMN competitor_ads.ad_creative_body IS 'Main body text of the ad creative';
COMMENT ON COLUMN competitor_ads.scrape_source IS 'Source of the scrape (e.g., ad_library_search, page_ads)';
COMMENT ON COLUMN competitor_ads.scraped_at IS 'Timestamp when this ad was scraped';
