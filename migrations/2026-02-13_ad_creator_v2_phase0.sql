-- ============================================================================
-- Migration: Ad Creator V2 — Phase 0 Prerequisites
-- Date: 2026-02-13
-- Purpose: Schema changes required before V2 pipeline implementation.
--
-- Changes:
--   P0-1: Add ad_creation_v2 + future job types to scheduled_jobs CHECK
--   P0-2: Add canvas_size to generated_ads + composite unique index
--   P0-3: Add template_id FK to product_template_usage + backfill
--   P0-4: Add template_selection_config JSONB to brands
--   P1-4: Add campaign_objective to meta_ads_performance
--   9d:   Add metadata JSONB to scheduled_job_runs
-- ============================================================================


-- ============================================================================
-- P0-1: Job Type Constraint
-- ============================================================================
-- Add ad_creation_v2 plus Phase 6-7 future job types.
-- Also includes competitor_scrape, reddit_scrape, amazon_review_scrape which
-- the worker already routes but were missing from the CHECK constraint.

ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN (
    -- Existing
    'ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
    'template_approval', 'congruence_reanalysis', 'ad_classification',
    'asset_download', 'competitor_scrape', 'reddit_scrape',
    'amazon_review_scrape',
    -- V2 (Phase 0)
    'ad_creation_v2',
    -- Phase 6: Creative Genome
    'creative_genome_update', 'genome_validation',
    -- Phase 6: Quality calibration
    'quality_calibration',
    -- Phase 7: Experiments
    'experiment_analysis'
));

COMMENT ON COLUMN scheduled_jobs.job_type IS
    'Job type: ad_creation, ad_creation_v2, meta_sync, scorecard, template_scrape, '
    'template_approval, congruence_reanalysis, ad_classification, asset_download, '
    'competitor_scrape, reddit_scrape, amazon_review_scrape, '
    'creative_genome_update, genome_validation, quality_calibration, experiment_analysis';


-- ============================================================================
-- P0-2: Multi-Size Variant Identity
-- ============================================================================
-- Add canvas_size column, relax prompt_index cap, rebuild unique index
-- as composite key (ad_run_id, prompt_index, canvas_size).

-- 1. Add canvas_size column (currently extracted but not persisted)
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS canvas_size TEXT;

COMMENT ON COLUMN generated_ads.canvas_size IS
    'Canvas dimensions string (e.g. 1080x1080, 1080x1350). '
    'Enables multi-size variants sharing same (ad_run_id, prompt_index).';

-- 2. Drop the existing unique index that prevents multi-size variants
DROP INDEX IF EXISTS idx_generated_ads_run_index;

-- 3. Recreate as composite index allowing multiple sizes per prompt_index
--    COALESCE handles existing rows where canvas_size is NULL
CREATE UNIQUE INDEX idx_generated_ads_run_index
ON generated_ads(ad_run_id, prompt_index, COALESCE(canvas_size, 'default'));

-- 4. Relax prompt_index CHECK (original was 1-5, too low for multi-size x multi-color)
--    Note: fix_generated_ads_constraint.sql already dropped this, but be safe
ALTER TABLE generated_ads DROP CONSTRAINT IF EXISTS generated_ads_prompt_index_check;
ALTER TABLE generated_ads ADD CONSTRAINT generated_ads_prompt_index_check
CHECK (prompt_index >= 1 AND prompt_index <= 100);


-- ============================================================================
-- P0-3: Template ID on product_template_usage
-- ============================================================================
-- Add template_id UUID FK for reliable template identity (replacing
-- filename-based matching via template_storage_name).

ALTER TABLE product_template_usage
ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES scraped_templates(id);

CREATE INDEX IF NOT EXISTS idx_product_template_usage_template_id
ON product_template_usage(template_id)
WHERE template_id IS NOT NULL;

COMMENT ON COLUMN product_template_usage.template_id IS
    'FK to scraped_templates.id — preferred over template_storage_name for joins';

-- Backfill from storage_path match.
-- Tie-break: pick the most recently created active template when
-- multiple scraped_templates share the same storage_path.
UPDATE product_template_usage ptu
SET template_id = st.id
FROM (
    SELECT DISTINCT ON (storage_path) id, storage_path
    FROM scraped_templates
    WHERE is_active = TRUE
    ORDER BY storage_path, created_at DESC
) st
WHERE st.storage_path = ptu.template_storage_name
  AND ptu.template_id IS NULL;


-- ============================================================================
-- P0-4: Template Selection Config on brands
-- ============================================================================
-- Per-brand config for the template scoring pipeline (Section 8).
-- Default min_asset_score = 0.0 means no gate (all templates eligible).

ALTER TABLE brands
ADD COLUMN IF NOT EXISTS template_selection_config JSONB DEFAULT '{"min_asset_score": 0.0}';

COMMENT ON COLUMN brands.template_selection_config IS
    'Per-brand template scoring config: min_asset_score (gate threshold), weight overrides, etc.';


-- ============================================================================
-- P1-4: Campaign Objective on meta_ads_performance
-- ============================================================================
-- Stores the campaign objective (CONVERSIONS, TRAFFIC, BRAND_AWARENESS, etc.)
-- for reward signal weight selection in the Creative Genome.

ALTER TABLE meta_ads_performance
ADD COLUMN IF NOT EXISTS campaign_objective TEXT;

CREATE INDEX IF NOT EXISTS idx_meta_ads_performance_campaign_objective
ON meta_ads_performance(campaign_objective)
WHERE campaign_objective IS NOT NULL;

COMMENT ON COLUMN meta_ads_performance.campaign_objective IS
    'Campaign objective from meta_campaigns (CONVERSIONS, TRAFFIC, BRAND_AWARENESS, etc.). '
    'UNKNOWN if campaign sync failed.';


-- ============================================================================
-- 9d: Metadata JSONB on scheduled_job_runs
-- ============================================================================
-- Tracks progress and diagnostic info: ads_attempted, ads_approved,
-- campaign_sync_error, stub marker, etc.

ALTER TABLE scheduled_job_runs
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

COMMENT ON COLUMN scheduled_job_runs.metadata IS
    'Structured metadata: progress tracking, error details, stub markers, etc.';


-- ============================================================================
-- P0-5: scraped_template_ids on scheduled_jobs
-- ============================================================================
-- Stores selected scraped template IDs for ad_creation jobs using the
-- scraped template library. Matches the existing pattern of template_ids,
-- template_source, template_mode, template_count as top-level columns.

ALTER TABLE scheduled_jobs
ADD COLUMN IF NOT EXISTS scraped_template_ids UUID[] DEFAULT '{}';

COMMENT ON COLUMN scheduled_jobs.scraped_template_ids IS
    'Selected scraped_templates IDs for jobs with template_source=scraped';


-- ============================================================================
-- Backfill audit queries (run manually after migration)
-- ============================================================================
-- These are informational — they do NOT modify data.

-- Check for ambiguous mappings (multiple active templates with same storage_path)
-- Expected: 0 rows for Phase 0 gate to pass
-- SELECT storage_path, COUNT(*) as cnt
-- FROM scraped_templates
-- WHERE is_active = TRUE
-- GROUP BY storage_path
-- HAVING COUNT(*) > 1;

-- Check for unmapped usage rows (template_id still NULL after backfill)
-- Acceptable if they correspond to deactivated templates
-- SELECT COUNT(*) FROM product_template_usage WHERE template_id IS NULL;

-- Historical backfill for campaign_objective (run after meta_campaigns is populated by Part A code)
-- UPDATE meta_ads_performance map
-- SET campaign_objective = mc.objective
-- FROM meta_campaigns mc
-- WHERE mc.meta_campaign_id = map.meta_campaign_id
--   AND mc.meta_ad_account_id = map.meta_ad_account_id
--   AND map.campaign_objective IS NULL;
