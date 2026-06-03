-- Migration: destination_sync job type
-- Date: 2026-06-03
-- Purpose: Split ad destination-URL capture (+ classification populate) out of
--   meta_sync Step 4.5 into its own scheduled job. meta_sync was repeatedly
--   hitting the 1800s runtime ceiling (and a Meta rate-limit failure) for large
--   accounts; the destination work added to that. A dedicated job gets its own
--   runtime limit, concurrency cap (serialized to protect the Meta rate budget),
--   and cadence, and lets meta_sync run lighter.
--
-- NOTE: once the worker that drops Step 4.5 is deployed, destinations are ONLY
-- captured by this new job — so this migration ALSO creates a recurring
-- destination_sync job for every brand that currently has an active recurring
-- meta_sync, to avoid a silent regression.

-- 1. Allow the new job_type on scheduled_jobs (CHECK is an explicit allowlist).
ALTER TABLE scheduled_jobs DROP CONSTRAINT valid_job_type;
ALTER TABLE scheduled_jobs ADD CONSTRAINT valid_job_type CHECK (job_type = ANY (ARRAY[
  'ad_creation','ad_creation_v2','meta_sync','scorecard','template_scrape',
  'template_approval','congruence_reanalysis','ad_classification','asset_download',
  'competitor_scrape','reddit_scrape','amazon_review_scrape','creative_genome_update',
  'creative_deep_analysis','genome_validation','winner_evolution','experiment_analysis',
  'quality_calibration','ad_intelligence_analysis','analytics_sync','seo_status_sync',
  'iteration_auto_run','size_variant','smart_edit','seo_content_eval','seo_publish',
  'seo_auto_interlink','demographic_backfill','seo_opportunity_scan','token_refresh',
  'competitor_intel_analysis','quick_intel_analysis',
  'destination_sync'
]::text[]));

-- 2. Runtime limit (lighter than meta_sync's 1800s; ~250 sequential Meta reads + populate).
INSERT INTO job_runtime_limits (job_type, max_runtime_seconds, notes)
SELECT 'destination_sync', 1200, 'Destination URL capture + classification populate; 1 Meta call/ad'
WHERE NOT EXISTS (SELECT 1 FROM job_runtime_limits WHERE job_type='destination_sync');

-- 3. Concurrency cap = 1: serialize destination_sync across workers so it never
--    piles onto meta_sync's Meta API rate budget (the 06:47 rate-limit failure).
INSERT INTO job_concurrency_limits (scope_type, scope_key, max_concurrent, enabled, notes)
SELECT 'job_type', 'destination_sync', 1, true, 'Meta API-bound; serialize to protect rate budget'
WHERE NOT EXISTS (
  SELECT 1 FROM job_concurrency_limits WHERE scope_type='job_type' AND scope_key='destination_sync'
);

-- 4. Create a recurring destination_sync job for each brand with an active
--    recurring meta_sync (preserves capture for all brands). Daily at 08:00,
--    offset from the 05:00-06:30 morning batch. First run set ~2 min out so the
--    new path validates/drains immediately; cron re-arms to daily thereafter.
INSERT INTO scheduled_jobs
  (name, job_type, schedule_type, cron_expression, status, trigger_source, brand_id, parameters, next_run_at)
SELECT DISTINCT
  'Destination Sync - Recurring', 'destination_sync', 'recurring', '0 8 * * *',
  'active', 'scheduled', ms.brand_id, '{"destination_limit": 250}'::jsonb,
  now() + interval '2 minutes'
FROM scheduled_jobs ms
WHERE ms.job_type='meta_sync' AND ms.schedule_type='recurring' AND ms.status='active'
  AND NOT EXISTS (
    SELECT 1 FROM scheduled_jobs d
    WHERE d.job_type='destination_sync' AND d.brand_id=ms.brand_id AND d.schedule_type='recurring'
  );
