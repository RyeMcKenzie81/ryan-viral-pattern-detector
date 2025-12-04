-- ============================================================================
-- Migration: Add Facebook Ad Library URL to brands
-- Date: 2025-12-04
-- Purpose: Allow brands to store their Facebook Ad Library URL for scraping
-- ============================================================================

-- Add facebook_page_id column
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS facebook_page_id TEXT;

-- Add ad_library_url column
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS ad_library_url TEXT;

-- Comments
COMMENT ON COLUMN brands.facebook_page_id IS 'Facebook Page ID for this brand (used for Ad Library scraping)';
COMMENT ON COLUMN brands.ad_library_url IS 'Full Facebook Ad Library URL for this brand (e.g., https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=123456789)';
