-- Migration: Add competitor_product_id to competitor_amazon_reviews
-- Date: 2026-01-06
-- Purpose: Link scraped reviews to specific competitor products for filtering

-- Add the missing column
ALTER TABLE competitor_amazon_reviews
ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id);

-- Create index for filtering by product
CREATE INDEX IF NOT EXISTS idx_competitor_amazon_reviews_product
ON competitor_amazon_reviews(competitor_product_id);

-- Backfill existing reviews from their source URL record
UPDATE competitor_amazon_reviews car
SET competitor_product_id = cau.competitor_product_id
FROM competitor_amazon_urls cau
WHERE car.competitor_amazon_url_id = cau.id::text
  AND car.competitor_product_id IS NULL
  AND cau.competitor_product_id IS NOT NULL;

COMMENT ON COLUMN competitor_amazon_reviews.competitor_product_id IS 'Links review to specific competitor product for filtering';
