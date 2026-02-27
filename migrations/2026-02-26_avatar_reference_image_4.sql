-- Migration: Add 4th reference image slot to brand_avatars
-- Date: 2026-02-26
-- Purpose: Support 4-angle avatar workflow (frontal, 3/4 view, side profile, full body)
--          for Kling element creation and consistent character generation.
--          Note: kling_element_id already exists on the table from the Omni migration.

ALTER TABLE brand_avatars
ADD COLUMN IF NOT EXISTS reference_image_4 TEXT;

COMMENT ON COLUMN brand_avatars.reference_image_4 IS 'Fourth reference image (full body) storage path for Kling element creation';
