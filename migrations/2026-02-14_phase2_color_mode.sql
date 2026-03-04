-- Migration: Add color_mode column to generated_ads for Phase 2 multi-color tracking
-- Date: 2026-02-14
-- Purpose: Track which color mode was used for each generated ad (original, complementary, brand)

ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS color_mode TEXT;
COMMENT ON COLUMN generated_ads.color_mode IS 'Color mode used: original, complementary, brand';
