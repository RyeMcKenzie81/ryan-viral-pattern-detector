-- Migration: weekly_product_digest job type
-- Date: 2026-06-03
-- Purpose: Register the weekly per-product Slack digest as a schedulable job
--   (awareness/CPA per product + US/CA market split + coverage), with its own
--   runtime + concurrency limits.
--
-- Job creation is intentionally NOT here — create the recurring (and a Run-Now
-- one-time) job via the templates at the bottom, once you have the Slack
-- Incoming Webhook URL (paste it into parameters.webhook_url).

-- 1. Allow the new job_type (CHECK is an explicit allowlist).
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
  'weekly_product_digest'
]::text[]));

-- 2. Runtime limit (per brand: full_analysis is DB-only here — classification off;
--    a handful of products + Slack post fit comfortably).
INSERT INTO job_runtime_limits (job_type, max_runtime_seconds, notes)
SELECT 'weekly_product_digest', 1800, 'Per-product DB aggregation (no Gemini/Meta) + Slack post'
WHERE NOT EXISTS (SELECT 1 FROM job_runtime_limits WHERE job_type='weekly_product_digest');

-- 3. Concurrency cap (not Meta/Gemini bound; modest).
INSERT INTO job_concurrency_limits (scope_type, scope_key, max_concurrent, enabled, notes)
SELECT 'job_type', 'weekly_product_digest', 2, true, 'DB + Slack; light'
WHERE NOT EXISTS (
  SELECT 1 FROM job_concurrency_limits WHERE scope_type='job_type' AND scope_key='weekly_product_digest'
);

-- ----------------------------------------------------------------------------
-- TEMPLATES (run after the above, with your webhook). Not executed by default.
-- ----------------------------------------------------------------------------
--
-- RUN NOW (one-time, fires ~1 min out — to eyeball the digest in a test channel):
--   INSERT INTO scheduled_jobs (name, job_type, schedule_type, status, trigger_source, brand_id, parameters, next_run_at, max_runs)
--   VALUES ('Weekly Digest - Run Now', 'weekly_product_digest', 'one_time', 'active', 'manual',
--           'd0cfa5c5-1132-447b-ade3-4db87995315b',
--           '{"days_back": 30, "webhook_url": "https://hooks.slack.com/services/XXX/YYY/ZZZ"}'::jsonb,
--           now() + interval '1 minute', 1);
--
-- RECURRING (Saturday 08:00 Pacific = the weekly cadence):
--   INSERT INTO scheduled_jobs (name, job_type, schedule_type, cron_expression, status, trigger_source, brand_id, parameters, next_run_at)
--   VALUES ('Weekly Product Digest - Martin', 'weekly_product_digest', 'recurring', '0 8 * * 6', 'active', 'scheduled',
--           'd0cfa5c5-1132-447b-ade3-4db87995315b',
--           '{"days_back": 30, "webhook_url": "https://hooks.slack.com/services/XXX/YYY/ZZZ"}'::jsonb,
--           now() + interval '1 minute');
