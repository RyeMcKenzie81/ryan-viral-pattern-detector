-- Migration: Add blueprint_id to generated_ads
-- Date: 2026-03-05
-- Purpose: Link generated ads to the landing page blueprint used during generation.
--          Enables blueprint-aware ad creation in V2 pipeline.

ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS
    blueprint_id UUID REFERENCES landing_page_blueprints(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_generated_ads_blueprint ON generated_ads(blueprint_id);

COMMENT ON COLUMN generated_ads.blueprint_id IS
    'Landing page blueprint used for context during ad generation. NULL = no blueprint.';
