-- Migration: link static (image) classifications to their deep image analysis
-- Date: 2026-06-08
-- Purpose: Static image ads now get creative_awareness_level from ImageAnalysisService
--   (deep, on-image text). Mirror the video path's video_analysis_id with an
--   image_analysis_id, so the classify-once staleness gate can tell whether a cached
--   image classification points at a CURRENT-version ad_image_analysis row.

ALTER TABLE ad_creative_classifications
    ADD COLUMN IF NOT EXISTS image_analysis_id UUID;

COMMENT ON COLUMN ad_creative_classifications.image_analysis_id IS
    'Link to the ad_image_analysis row whose awareness_level drove creative_awareness_level '
    'for a static (image) ad. Parallel to video_analysis_id. Used by the image classify-once '
    'staleness gate (re-classify when the linked analysis is stale/missing).';
