-- Migration: Add demographic_backfill to scheduled_jobs job_type CHECK constraint
-- Date: 2026-04-02
-- Purpose: Allow scheduling demographic backfill jobs that process historical data day-by-day

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
    'ad_intelligence_analysis',
    'iteration_auto_run',
    'size_variant',
    'smart_edit',
    'analytics_sync',
    'seo_status_sync',
    'creative_deep_analysis',
    'seo_content_eval',
    'seo_publish',
    'seo_auto_interlink',
    'demographic_backfill'
));
