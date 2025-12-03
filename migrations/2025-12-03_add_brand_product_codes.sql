-- Migration: Add brand_code and product_code for ad filename generation
-- Date: 2025-12-03
-- Purpose: Enable structured ad filenames like WP-C3-a1b2c3-d4e5f6-SQ.jpg

-- Add brand_code to brands table (e.g., "WP" for WonderPaws)
ALTER TABLE brands ADD COLUMN IF NOT EXISTS brand_code VARCHAR(4);

-- Add product_code to products table (e.g., "C3" for Collagen 3x)
ALTER TABLE products ADD COLUMN IF NOT EXISTS product_code VARCHAR(4);

-- Add comments
COMMENT ON COLUMN brands.brand_code IS 'Short code for ad filenames (e.g., WP for WonderPaws). Max 4 chars, uppercase.';
COMMENT ON COLUMN products.product_code IS 'Short code for ad filenames (e.g., C3 for Collagen 3x). Max 4 chars, uppercase.';

-- Create unique index to prevent duplicate codes within a brand
CREATE UNIQUE INDEX IF NOT EXISTS idx_brands_brand_code ON brands(brand_code) WHERE brand_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_product_code_brand ON products(brand_id, product_code) WHERE product_code IS NOT NULL;
