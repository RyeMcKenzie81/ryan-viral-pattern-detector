-- Migration: Add product_id to brand_landing_pages
-- Date: 2025-12-07
-- Purpose: Link landing pages to products using URL pattern matching

-- Add product_id column
ALTER TABLE brand_landing_pages
ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id) ON DELETE SET NULL;

-- Add index for product queries
CREATE INDEX IF NOT EXISTS idx_brand_landing_pages_product_id
ON brand_landing_pages(product_id);

-- Comment
COMMENT ON COLUMN brand_landing_pages.product_id IS 'Product this landing page belongs to (matched via URL patterns)';
