-- Migration: Add video_vision analysis type
-- Date: 2025-12-05
-- Purpose: Add video_vision to allowed analysis types for brand_ad_analysis

-- Drop existing constraint and recreate with video_vision
ALTER TABLE brand_ad_analysis DROP CONSTRAINT IF EXISTS brand_ad_analysis_analysis_type_check;

ALTER TABLE brand_ad_analysis ADD CONSTRAINT brand_ad_analysis_analysis_type_check
    CHECK (analysis_type IN (
        'image_vision',
        'video_vision',      -- NEW: Gemini video analysis with full transcript
        'video_storyboard',  -- Original: Video frame-by-frame analysis
        'copy_analysis',
        'synthesis'
    ));

COMMENT ON COLUMN brand_ad_analysis.analysis_type IS
    'Type of analysis: image_vision (image AI), video_vision (video AI with transcript), video_storyboard (frame analysis), copy_analysis (text), synthesis (combined)';
