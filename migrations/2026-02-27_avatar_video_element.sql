-- Migration: Add video element support to brand avatars
-- Date: 2026-02-27
-- Purpose: Enable video-based Kling elements with voice binding for consistent
--          voice across multi-scene Omni Video generation.

ALTER TABLE brand_avatars ADD COLUMN IF NOT EXISTS kling_voice_id TEXT;
ALTER TABLE brand_avatars ADD COLUMN IF NOT EXISTS calibration_video_path TEXT;
ALTER TABLE brand_avatars ADD COLUMN IF NOT EXISTS avatar_setup_mode TEXT DEFAULT 'multi_image';

COMMENT ON COLUMN brand_avatars.kling_voice_id IS 'Voice ID from element_voice_info after video element creation';
COMMENT ON COLUMN brand_avatars.calibration_video_path IS 'Storage path for calibration video used to create video element';
COMMENT ON COLUMN brand_avatars.avatar_setup_mode IS 'Element creation mode: multi_image (4 ref images) or video_element (video-based with voice)';
