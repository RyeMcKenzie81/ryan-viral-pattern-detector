-- Migration: Add source_scraped_template_id to ad_runs
-- Date: 2026-03-06
-- Purpose: Enable V2 "View Results" page to join ad_runs with scraped_templates.
--          The PostgREST inner join on this column was returning zero rows because the column didn't exist.
--          Backfill from generation_config JSONB for existing V2 runs.

ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS source_scraped_template_id UUID
  REFERENCES scraped_templates(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ad_runs_source_scraped_template_id
  ON ad_runs(source_scraped_template_id) WHERE source_scraped_template_id IS NOT NULL;

-- Backfill from generation_config JSONB for existing V2 runs
UPDATE ad_runs
SET source_scraped_template_id = (generation_config->>'template_id')::UUID
WHERE source_scraped_template_id IS NULL
  AND generation_config->>'template_id' IS NOT NULL
  AND (generation_config->>'template_id') != '';

COMMENT ON COLUMN ad_runs.source_scraped_template_id IS
  'FK to scraped_templates.id. Populated by V2 pipeline, backfilled from generation_config.template_id.';
