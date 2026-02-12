-- Migration: Add Meta API source support to brand_ad_analysis
-- Date: 2026-02-11
-- Purpose: Enable Brand Research to analyze ads from both Ad Library scraping
-- and Meta API sources. Adds meta_ad_id, meta_asset_id FK, data_source column,
-- and source-aware dedup indexes.

-- New columns for Meta API sourced analysis
ALTER TABLE brand_ad_analysis ADD COLUMN IF NOT EXISTS meta_ad_id TEXT;
ALTER TABLE brand_ad_analysis ADD COLUMN IF NOT EXISTS meta_asset_id UUID REFERENCES meta_ad_assets(id);
ALTER TABLE brand_ad_analysis ADD COLUMN IF NOT EXISTS data_source TEXT DEFAULT 'ad_library'
    CHECK (data_source IN ('ad_library', 'meta_api'));

-- Preflight: deduplicate existing rows before creating UNIQUE indexes
-- (keeps newest row per group, deletes older duplicates)
DELETE FROM brand_ad_analysis a
USING brand_ad_analysis b
WHERE a.brand_id = b.brand_id
  AND a.analysis_type = b.analysis_type
  AND a.facebook_ad_id = b.facebook_ad_id
  AND a.facebook_ad_id IS NOT NULL
  AND a.created_at < b.created_at;

-- Source-aware dedupe UNIQUE partial indexes (prevent concurrent duplicate writes)
CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_analysis_meta_ad
    ON brand_ad_analysis(brand_id, analysis_type, meta_ad_id)
    WHERE meta_ad_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_analysis_fb_ad
    ON brand_ad_analysis(brand_id, analysis_type, facebook_ad_id)
    WHERE facebook_ad_id IS NOT NULL;

COMMENT ON COLUMN brand_ad_analysis.meta_ad_id IS 'Meta ad ID for Meta API sourced analysis';
COMMENT ON COLUMN brand_ad_analysis.meta_asset_id IS 'FK to meta_ad_assets for Meta API sourced assets';
COMMENT ON COLUMN brand_ad_analysis.data_source IS 'Which pipeline produced this: ad_library or meta_api';

-- Update analysis_type CHECK to include video_vision
ALTER TABLE brand_ad_analysis DROP CONSTRAINT IF EXISTS brand_ad_analysis_analysis_type_check;
ALTER TABLE brand_ad_analysis ADD CONSTRAINT brand_ad_analysis_analysis_type_check
    CHECK (analysis_type IN ('image_vision', 'video_vision', 'video_storyboard', 'copy_analysis', 'synthesis'));
