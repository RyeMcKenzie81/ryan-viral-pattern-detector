-- Migration: has_product_placement — layout attribute, orthogonal to awareness
-- Date: 2026-06-11
-- Purpose: "give me problem-aware templates WITH a product slot" needs a second,
--   independent filter: awareness is about what the message PRESUMES (a corner
--   pack-shot never raises the stage), while placement is about the LAYOUT (that
--   same corner pack-shot counts). Populated by the template analysis prompt for
--   new templates and by a one-off flash backfill for the existing library.
--   NULL = unknown/legacy.

ALTER TABLE scraped_templates
    ADD COLUMN IF NOT EXISTS has_product_placement BOOLEAN;

COMMENT ON COLUMN scraped_templates.has_product_placement IS
    'An identifiable product pack/bottle is visible anywhere in the frame (hero, '
    'co-hero, or corner signature). Layout attribute, independent of awareness_level. '
    'NULL = unknown/legacy.';

CREATE INDEX IF NOT EXISTS idx_scraped_templates_product_placement
    ON scraped_templates (has_product_placement);
