-- Migration: Add product detection and language detection to content bucket categorizations
-- Date: 2026-03-20
-- Purpose: Enable per-file product + language detection during Gemini categorization

ALTER TABLE content_bucket_categorizations
  ADD COLUMN IF NOT EXISTS detected_product_id UUID REFERENCES products(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS detected_product_name TEXT,
  ADD COLUMN IF NOT EXISTS detected_language TEXT NOT NULL DEFAULT 'en';

CREATE INDEX IF NOT EXISTS idx_content_bucket_cat_detected_product
  ON content_bucket_categorizations(detected_product_id)
  WHERE detected_product_id IS NOT NULL;

COMMENT ON COLUMN content_bucket_categorizations.detected_product_id IS 'FK to products — null if content is general brand content or product not in catalog';
COMMENT ON COLUMN content_bucket_categorizations.detected_product_name IS 'Denormalized product name from Gemini detection (may not match catalog)';
COMMENT ON COLUMN content_bucket_categorizations.detected_language IS 'ISO 639-1 language code detected from content (default en)';
