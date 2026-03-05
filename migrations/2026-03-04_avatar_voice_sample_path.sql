-- Migration: Add voice_sample_path to brand_avatars
-- Date: 2026-03-04
-- Purpose: Store the storage path of uploaded voice sample videos separately
--          from voice creation, enabling the simplified 2-step video avatar
--          creation flow where voice source is chosen at element creation time.

ALTER TABLE brand_avatars ADD COLUMN IF NOT EXISTS voice_sample_path TEXT;

COMMENT ON COLUMN brand_avatars.voice_sample_path IS 'Storage path for uploaded voice sample video (used for voice creation during element creation)';
