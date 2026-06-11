-- Migration: sync_health_check job type (sync staleness monitor)
-- Date: 2026-06-11
-- Purpose: Register a daily ops monitor that detects (a) data syncs that have
--   stopped succeeding (meta_sync / analytics_sync / destination_sync /
--   asset_download with no completed run in >threshold_hours) and (b) Meta OAuth
--   tokens expired or expiring within token_warn_days, then emits ONE summary
--   activity event (auto-Slacks on 'error'). Logic lives in
--   viraltracker/services/sync_health_service.py.
--
-- Job creation is NOT executed by default — use the templates at the bottom.
-- It is a GLOBAL job (brand_id = NULL), like Daily Meta Token Refresh.

-- 1. Allow the new job_type (CHECK is an explicit allowlist). Full current set
--    re-declared with 'sync_health_check' appended.
ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS valid_job_type;
ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;
ALTER TABLE scheduled_jobs ADD CONSTRAINT valid_job_type CHECK (job_type = ANY (ARRAY[
  'ad_creation','ad_creation_v2','meta_sync','scorecard','template_scrape',
  'template_approval','congruence_reanalysis','ad_classification','asset_download',
  'competitor_scrape','reddit_scrape','amazon_review_scrape','creative_genome_update',
  'creative_deep_analysis','genome_validation','winner_evolution','experiment_analysis',
  'quality_calibration','ad_intelligence_analysis','analytics_sync','seo_status_sync',
  'iteration_auto_run','size_variant','smart_edit','seo_content_eval','seo_publish',
  'seo_auto_interlink','demographic_backfill','seo_opportunity_scan','token_refresh',
  'competitor_intel_analysis','quick_intel_analysis','destination_sync',
  'weekly_product_digest','sync_health_check'
]::text[]));

-- 2. Runtime limit. Lightweight: a few PostgREST reads, no Meta/Gemini/LLM.
INSERT INTO job_runtime_limits (job_type, max_runtime_seconds, notes)
SELECT 'sync_health_check', 300, 'Read-only staleness + token checks (DB only)'
WHERE NOT EXISTS (SELECT 1 FROM job_runtime_limits WHERE job_type='sync_health_check');

-- 3. Concurrency cap. Single global job; modest.
INSERT INTO job_concurrency_limits (scope_type, scope_key, max_concurrent, enabled, notes)
SELECT 'job_type', 'sync_health_check', 2, true, 'Global read-only monitor; light'
WHERE NOT EXISTS (
  SELECT 1 FROM job_concurrency_limits WHERE scope_type='job_type' AND scope_key='sync_health_check'
);

-- ----------------------------------------------------------------------------
-- TEMPLATES (run after the above). Not executed by default.
-- ----------------------------------------------------------------------------
--
-- RUN NOW (one-time, fires ~1 min out — to eyeball the alert in the Activity Feed):
--   INSERT INTO scheduled_jobs (name, job_type, schedule_type, status, trigger_source, brand_id, parameters, next_run_at, max_runs)
--   VALUES ('Sync Health Check - Run Now', 'sync_health_check', 'one_time', 'active', 'manual',
--           NULL, '{"threshold_hours": 48, "token_warn_days": 7}'::jsonb,
--           now() + interval '1 minute', 1);
--
-- RECURRING (daily 09:00 Pacific = 16:00 UTC — after the morning data syncs have
-- run + retried, so staleness reflects today's syncs):
--   INSERT INTO scheduled_jobs (name, job_type, schedule_type, cron_expression, status, trigger_source, brand_id, parameters, next_run_at)
--   VALUES ('Sync Health Monitor - Daily', 'sync_health_check', 'recurring', '0 9 * * *', 'active', 'scheduled',
--           NULL, '{"threshold_hours": 48, "token_warn_days": 7}'::jsonb,
--           now() + interval '1 minute');
