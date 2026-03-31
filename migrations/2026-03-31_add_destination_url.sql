-- Migration: Add destination_url to meta_ads_performance
-- Date: 2026-03-31
-- Purpose: Store the landing page URL from Meta ad creatives so we can
--          map ads → offer variants → products for product-level filtering
--          in Creative Intelligence.

ALTER TABLE meta_ads_performance
ADD COLUMN IF NOT EXISTS destination_url TEXT;

COMMENT ON COLUMN meta_ads_performance.destination_url IS 'Landing page URL from ad creative object_story_spec.link_data.link';

-- Index for joining with product_offer_variants
CREATE INDEX IF NOT EXISTS idx_meta_ads_performance_destination_url
ON meta_ads_performance (destination_url)
WHERE destination_url IS NOT NULL;
