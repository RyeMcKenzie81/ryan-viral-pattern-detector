-- Migration: Comic Video Phase 5.5 - Manual Panel Adjustments
-- Date: 2025-12-08
-- Purpose: Add user_overrides column for per-panel camera/effects customization
--          and aspect_ratio column for output format selection

-- ============================================================================
-- Add user_overrides to comic_panel_instructions
-- Stores user's manual overrides for camera settings and effects
-- ============================================================================
ALTER TABLE comic_panel_instructions
ADD COLUMN IF NOT EXISTS user_overrides JSONB DEFAULT NULL;

COMMENT ON COLUMN comic_panel_instructions.user_overrides IS
'User overrides for auto-generated settings. JSON structure matches PanelOverrides model.
Example: {"vignette_enabled": false, "camera_end_zoom": 1.3, "mood_override": "positive"}';


-- ============================================================================
-- Add aspect_ratio to comic_video_projects
-- Stores the selected output aspect ratio
-- ============================================================================
ALTER TABLE comic_video_projects
ADD COLUMN IF NOT EXISTS aspect_ratio TEXT DEFAULT '9:16';

COMMENT ON COLUMN comic_video_projects.aspect_ratio IS
'Output aspect ratio. Values: 9:16 (vertical), 16:9 (horizontal), 1:1 (square), 4:5 (portrait)';


-- ============================================================================
-- Add index for projects by aspect ratio (optional, for analytics)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_comic_video_projects_aspect_ratio
ON comic_video_projects(aspect_ratio);
