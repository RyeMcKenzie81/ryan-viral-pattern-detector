-- Migration: Add fallback landing page URL to product_urls
-- Date: 2025-12-10
-- Purpose: Allow manually specifying a landing page URL for persona research
--          when there aren't enough ads to scrape URLs from

-- Add is_fallback column to mark manually-entered fallback URLs
-- These are used for brand research scraping even when no ads point to them
ALTER TABLE product_urls ADD COLUMN IF NOT EXISTS is_fallback boolean DEFAULT false;

COMMENT ON COLUMN product_urls.is_fallback IS 'Whether this is a fallback URL for brand research (not discovered from ads)';

-- Create index for efficient querying of fallback URLs
CREATE INDEX IF NOT EXISTS idx_product_urls_is_fallback ON product_urls(is_fallback) WHERE is_fallback = true;
