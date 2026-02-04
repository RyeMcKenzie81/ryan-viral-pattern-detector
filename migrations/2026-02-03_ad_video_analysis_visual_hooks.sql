-- Migration: Add visual hook fields to ad_video_analysis
-- Date: 2026-02-03
-- Purpose: Capture visual context for complete hook fingerprinting
--          (spoken + overlay + visual = complete hook)

-- Add visual hook description field
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS hook_visual_description TEXT;

COMMENT ON COLUMN ad_video_analysis.hook_visual_description IS
'Description of what is visually happening in first 3-5 seconds';

-- Add visual hook elements array
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS hook_visual_elements TEXT[];

COMMENT ON COLUMN ad_video_analysis.hook_visual_elements IS
'Key visual elements in hook (e.g., person, dog, product, text_overlay)';

-- Add visual hook type
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS hook_visual_type TEXT;

COMMENT ON COLUMN ad_video_analysis.hook_visual_type IS
'Visual hook type: unboxing, transformation, demonstration, testimonial, lifestyle, problem_agitation, authority, social_proof, product_hero, curiosity';
