-- Migration: Add product constraint and offer fields
-- Date: 2025-11-26
-- Purpose: Add fields for controlling ad generation claims, offers, and compliance

-- Add new columns to products table
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS current_offer TEXT,
  ADD COLUMN IF NOT EXISTS prohibited_claims TEXT[],
  ADD COLUMN IF NOT EXISTS required_disclaimers TEXT,
  ADD COLUMN IF NOT EXISTS brand_voice_notes TEXT,
  ADD COLUMN IF NOT EXISTS unique_selling_points TEXT[];

-- Add comments to document field usage
COMMENT ON COLUMN products.current_offer IS 'Active promotional offer text (e.g., "Up to 35% off subscription 3-packs"). Used directly in ad copy to prevent hallucinated discounts.';
COMMENT ON COLUMN products.prohibited_claims IS 'Array of claims that MUST NOT appear in ads (e.g., ["cure", "FDA approved", "treat disease", "medical grade"]). Legal compliance.';
COMMENT ON COLUMN products.required_disclaimers IS 'Legal disclaimers that must appear in ads (e.g., "*These statements have not been evaluated by the FDA")';
COMMENT ON COLUMN products.brand_voice_notes IS 'Tone and style guidelines for ad copy (e.g., "friendly and approachable, not clinical")';
COMMENT ON COLUMN products.unique_selling_points IS 'Array of key differentiators vs competitors (e.g., ["Triple-action formula", "Made in USA", "Vet-recommended"])';

-- Example data update for Wonder Paws Collagen product
-- Run this separately after migration:
-- UPDATE products
-- SET
--   current_offer = 'Up to 35% off with subscription 3-pack vs single purchase',
--   prohibited_claims = ARRAY['cure', 'FDA approved', 'treat', 'prevent disease', 'medical grade', 'veterinarian prescribed'],
--   required_disclaimers = '*These statements have not been evaluated by the FDA. This product is not intended to diagnose, treat, cure, or prevent any disease.',
--   brand_voice_notes = 'Warm, caring, and pet-owner friendly. Focus on quality of life improvements, not medical claims.',
--   unique_selling_points = ARRAY['Triple-action collagen formula', 'Supports joints, coat, and skin', 'Easy liquid drops', 'Made with natural ingredients']
-- WHERE id = '83166c93-632f-47ef-a929-922230e05f82';
