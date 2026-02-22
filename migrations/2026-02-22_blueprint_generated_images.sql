-- Migration: Add generated images support to blueprints
-- Date: 2026-02-22
-- Purpose: Store AI-generated image metadata and HTML with replaced images

ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS generated_images_meta JSONB DEFAULT '{}';

ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS blueprint_mockup_html_with_images TEXT;

COMMENT ON COLUMN landing_page_blueprints.generated_images_meta IS
  'Per-slot image metadata keyed by index: {analysis, storage_path, image_type, prompt, time_ms, error}';

COMMENT ON COLUMN landing_page_blueprints.blueprint_mockup_html_with_images IS
  'Blueprint mockup HTML with competitor images replaced by AI-generated brand images';
