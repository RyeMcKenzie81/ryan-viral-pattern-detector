-- Migration: Add source_reference_image column to brand_avatars
-- Date: 2026-03-11
-- Purpose: Store user-uploaded reference photo that guides AI generation
--          of angle shots (frontal, 3/4, side, full body). Previously,
--          uploaded references were stored directly as slot images.

ALTER TABLE brand_avatars
    ADD COLUMN IF NOT EXISTS source_reference_image TEXT;

COMMENT ON COLUMN brand_avatars.source_reference_image IS
    'Storage path for user-uploaded source reference photo that guides AI angle generation.';
