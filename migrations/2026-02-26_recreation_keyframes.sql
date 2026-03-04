-- Migration: Add keyframe support for Kling Omni Video integration
-- Date: 2026-02-26
-- Purpose: Store per-scene keyframe images on recreation candidates and
--          Kling element IDs on brand avatars for character consistency.

-- 1a. Store per-scene keyframe images on recreation candidates
-- Structure: [{scene_idx, first_frame_path, last_frame_path, first_frame_description, last_frame_description, status}]
ALTER TABLE video_recreation_candidates
ADD COLUMN IF NOT EXISTS scene_keyframes JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN video_recreation_candidates.scene_keyframes IS 'Per-scene keyframe images for Kling Omni Video integration.';

-- 1b. Store Kling element_id on brand avatars for reuse across videos
-- Elements persist in Kling API — created once per avatar via /v1/general/advanced-custom-elements
ALTER TABLE brand_avatars
ADD COLUMN IF NOT EXISTS kling_element_id TEXT;

COMMENT ON COLUMN brand_avatars.kling_element_id IS 'Kling API element ID for character consistency, created once per avatar.';
