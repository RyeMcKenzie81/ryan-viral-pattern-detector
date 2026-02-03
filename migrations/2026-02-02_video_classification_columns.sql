-- Migration: Add video classification columns
-- Date: 2026-02-02
-- Purpose: Store video_id from Meta AdCreative for video-aware classification,
--          and track video duration from Gemini analysis.

-- meta_ads_performance: store video_id from Meta AdCreative
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS meta_video_id TEXT;
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS is_video BOOLEAN DEFAULT FALSE;

-- ad_creative_classifications: store video duration from Gemini analysis
ALTER TABLE ad_creative_classifications ADD COLUMN IF NOT EXISTS video_duration_sec INTEGER;
