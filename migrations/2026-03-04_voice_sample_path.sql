-- Migration: Add voice_sample_path to brand_avatars
-- Date: 2026-03-04
-- Purpose: Store the Supabase storage path of the uploaded voice sample video
--          so it persists across sessions and can be reused without re-uploading.

ALTER TABLE brand_avatars ADD COLUMN IF NOT EXISTS voice_sample_path TEXT;

COMMENT ON COLUMN brand_avatars.voice_sample_path IS 'Storage path for uploaded voice sample video (used to embed voice into calibration video)';
