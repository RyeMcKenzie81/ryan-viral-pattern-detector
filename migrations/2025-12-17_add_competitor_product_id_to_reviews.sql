-- Migration: Add competitor_product_id to competitor_amazon_reviews
-- Date: 2025-12-17
-- Purpose: Allow linking reviews to specific competitor products

-- Add competitor_product_id column
ALTER TABLE competitor_amazon_reviews
ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_reviews_product
ON competitor_amazon_reviews(competitor_product_id);

COMMENT ON COLUMN competitor_amazon_reviews.competitor_product_id IS 'Optional link to specific competitor product';

-- Also add to competitor_amazon_review_analysis for product-level analysis
ALTER TABLE competitor_amazon_review_analysis
ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_analysis_product
ON competitor_amazon_review_analysis(competitor_product_id);

COMMENT ON COLUMN competitor_amazon_review_analysis.competitor_product_id IS 'Optional link to specific competitor product for product-level analysis';
