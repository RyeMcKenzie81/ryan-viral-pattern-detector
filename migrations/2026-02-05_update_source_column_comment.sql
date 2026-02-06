-- Migration: Update source column comment to reflect current classification sources
-- Date: 2026-02-05
-- Purpose: Document the full set of classification source values

COMMENT ON COLUMN ad_creative_classifications.source IS 'Classification source: existing_brand_ad_analysis, gemini_video, gemini_light_stored, gemini_light_thumbnail, or skipped_* variants (skipped_missing_image, skipped_missing_video_file, skipped_video_budget_exhausted, skipped_video_classification_failed)';
