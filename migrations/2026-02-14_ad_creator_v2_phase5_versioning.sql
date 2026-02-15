-- Migration: Add prompt versioning and generation config
-- Date: 2026-02-14
-- Purpose: Enable reproducibility by tracking prompt version per ad
--          and full generation config per ad_run.
-- VERIFIED: No naming collisions with existing tables/columns.

-- 1. Add prompt_version to generated_ads
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS prompt_version TEXT;

COMMENT ON COLUMN generated_ads.prompt_version
IS 'Pydantic prompt schema version used to generate this ad (e.g. v2.1.0)';

-- 2. Add generation_config JSONB to ad_runs
ALTER TABLE ad_runs
ADD COLUMN IF NOT EXISTS generation_config JSONB;

COMMENT ON COLUMN ad_runs.generation_config
IS 'Full reproducibility snapshot: prompt_version, scorer_weights, quality_config, image_resolution, content_source, pipeline_version';
