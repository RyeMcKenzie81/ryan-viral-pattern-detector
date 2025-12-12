-- Migration: Add video/image/copy analysis types to competitor_ad_analysis
-- Date: 2025-12-12
-- Purpose: Support same analysis types as brand_ad_analysis for consistency

-- Drop existing constraint and add new one with additional types
ALTER TABLE competitor_ad_analysis
DROP CONSTRAINT IF EXISTS competitor_ad_analysis_analysis_type_check;

ALTER TABLE competitor_ad_analysis
ADD CONSTRAINT competitor_ad_analysis_analysis_type_check
CHECK (analysis_type IN (
    'ad_creative', 'ad_copy', 'landing_page', 'combined',
    'video_vision', 'image_vision', 'copy_analysis'
));

COMMENT ON COLUMN competitor_ad_analysis.analysis_type IS 'Type of analysis: video_vision, image_vision, copy_analysis, ad_creative, ad_copy, landing_page, combined';
