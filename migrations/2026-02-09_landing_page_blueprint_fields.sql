-- Migration: Add fields needed for Landing Page Reconstruction Blueprint
-- Date: 2026-02-09
-- Purpose: Add guarantee, ingredients, results_timeline, faq_items to products
--          and brand_voice_tone, brand_colors to brands.
--          These support rich blueprint output and are useful standalone.

-- Products table: product-specific fields
ALTER TABLE products ADD COLUMN IF NOT EXISTS guarantee TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ingredients JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS results_timeline JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS faq_items JSONB DEFAULT '[]';

COMMENT ON COLUMN products.guarantee IS 'Money-back guarantee (e.g., "365-day money-back guarantee")';
COMMENT ON COLUMN products.ingredients IS 'Structured ingredient list [{name, benefit, proof_point}]';
COMMENT ON COLUMN products.results_timeline IS 'Expected results by timeframe [{timeframe, expected_result}]';
COMMENT ON COLUMN products.faq_items IS 'Common FAQ items [{question, answer}]';

-- Brands table: brand-wide fields
ALTER TABLE brands ADD COLUMN IF NOT EXISTS brand_voice_tone TEXT;
ALTER TABLE brands ADD COLUMN IF NOT EXISTS brand_colors JSONB DEFAULT '{}';

COMMENT ON COLUMN brands.brand_voice_tone IS 'Structured tone description (e.g., "Aggressive, masculine, bold, direct")';
COMMENT ON COLUMN brands.brand_colors IS 'Brand color palette {primary: "#hex", secondary: ["#hex"], accent: "#hex"}';
