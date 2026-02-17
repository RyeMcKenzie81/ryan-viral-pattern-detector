-- Migration: Ad Intelligence Background Worker
-- Date: 2026-02-17
-- Purpose: Add ad_intelligence_analysis job type, rendered_markdown column,
--   and dedup index for background analysis.

-- 1a. Add 'ad_intelligence_analysis' to job_type CHECK (full current list)
ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN (
    'ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
    'template_approval', 'congruence_reanalysis', 'ad_classification',
    'asset_download', 'competitor_scrape', 'reddit_scrape',
    'amazon_review_scrape',
    'ad_creation_v2',
    'creative_genome_update', 'genome_validation',
    'quality_calibration',
    'winner_evolution', 'experiment_analysis',
    'ad_intelligence_analysis'
));

-- 1b. Store rendered markdown for instant retrieval
ALTER TABLE ad_intelligence_runs
ADD COLUMN IF NOT EXISTS rendered_markdown TEXT;

COMMENT ON COLUMN ad_intelligence_runs.rendered_markdown IS
    'Pre-rendered ChatRenderer markdown from full_analysis(). '
    'Stored so agent tool can serve cached results instantly.';

-- 1c. Dedup index: one active ad_intelligence_analysis job per brand
-- Scope: blocks ANY concurrent analysis for same brand (intentional).
-- Released when job completes (status='completed' via _update_job_next_run).
CREATE UNIQUE INDEX IF NOT EXISTS idx_sj_dedup_ad_intelligence
    ON scheduled_jobs (brand_id)
    WHERE job_type = 'ad_intelligence_analysis'
      AND schedule_type = 'one_time'
      AND status = 'active';
