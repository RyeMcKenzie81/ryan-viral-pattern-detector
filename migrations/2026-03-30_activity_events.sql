-- Migration: Activity Feed tables
-- Date: 2026-03-30
-- Purpose: Add activity_events and user_feed_state tables for the Activity Feed feature

-- Central event store
CREATE TABLE IF NOT EXISTS activity_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID,                -- nullable for platform-level events
  brand_id UUID,                       -- nullable for org-level events
  product_id UUID,                     -- nullable
  event_type TEXT NOT NULL,            -- job_started, job_completed, job_failed, job_retrying, etc.
  severity TEXT NOT NULL DEFAULT 'info', -- info, warning, error, success
  title TEXT NOT NULL,                 -- human-readable: "Ad Creation completed (12 ads)"
  details JSONB DEFAULT '{}',          -- structured payload
  source_type TEXT NOT NULL DEFAULT 'scheduler',
  source_id TEXT,                      -- originating record ID (job run UUID as text)
  link_page TEXT,                      -- page slug for deep linking (e.g. "ad_scheduler")
  link_params JSONB DEFAULT '{}',      -- query params for deep link
  duration_ms INTEGER,                 -- job duration in milliseconds
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Per-user feed state for "while you were away"
CREATE TABLE IF NOT EXISTS user_feed_state (
  user_id UUID PRIMARY KEY,
  last_seen_at TIMESTAMPTZ DEFAULT now(),
  filter_preferences JSONB DEFAULT '{}'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_activity_events_org_brand_created
  ON activity_events (organization_id, brand_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_events_org_created
  ON activity_events (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_events_severity_created
  ON activity_events (severity, created_at DESC)
  WHERE severity IN ('error', 'warning');

-- RLS
ALTER TABLE activity_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_feed_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read activity events"
  ON activity_events FOR SELECT TO authenticated
  USING (true);

CREATE POLICY "Service role can insert activity events"
  ON activity_events FOR INSERT TO authenticated
  WITH CHECK (true);

CREATE POLICY "Authenticated users can manage own feed state"
  ON user_feed_state FOR ALL TO authenticated
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE activity_events IS 'Centralized activity feed for all system events';
COMMENT ON TABLE user_feed_state IS 'Per-user feed state for while-you-were-away tracking';

-- Backfill: import recent job runs as activity events (idempotent)
INSERT INTO activity_events (
  organization_id, brand_id, event_type, severity, title, details,
  source_type, source_id, created_at
)
SELECT
  b.organization_id,
  sj.brand_id,
  CASE sjr.status
    WHEN 'completed' THEN 'job_completed'
    WHEN 'failed' THEN 'job_failed'
    ELSE 'job_started'
  END,
  CASE sjr.status
    WHEN 'completed' THEN 'success'
    WHEN 'failed' THEN 'error'
    ELSE 'info'
  END,
  CASE sj.job_type
    WHEN 'ad_creation' THEN 'Ad Creation'
    WHEN 'ad_creation_v2' THEN 'Ad Creation V2'
    WHEN 'meta_sync' THEN 'Meta Sync'
    WHEN 'scorecard' THEN 'Scorecard'
    WHEN 'template_scrape' THEN 'Template Scrape'
    WHEN 'template_approval' THEN 'Template Approval'
    WHEN 'congruence_reanalysis' THEN 'Congruence Reanalysis'
    WHEN 'ad_classification' THEN 'Ad Classification'
    WHEN 'asset_download' THEN 'Asset Download'
    WHEN 'competitor_scrape' THEN 'Competitor Scrape'
    WHEN 'reddit_scrape' THEN 'Reddit Scrape'
    WHEN 'amazon_review_scrape' THEN 'Amazon Reviews'
    WHEN 'ad_intelligence_analysis' THEN 'Ad Intelligence'
    WHEN 'analytics_sync' THEN 'Analytics Sync'
    WHEN 'seo_status_sync' THEN 'SEO Status Sync'
    WHEN 'creative_genome_update' THEN 'Creative Genome Update'
    WHEN 'genome_validation' THEN 'Genome Validation'
    WHEN 'winner_evolution' THEN 'Winner Evolution'
    WHEN 'experiment_analysis' THEN 'Experiment Analysis'
    WHEN 'quality_calibration' THEN 'Quality Calibration'
    WHEN 'iteration_auto_run' THEN 'Iteration Auto Run'
    WHEN 'size_variant' THEN 'Size Variant'
    WHEN 'smart_edit' THEN 'Smart Edit'
    ELSE REPLACE(sj.job_type, '_', ' ')
  END || ' ' || sjr.status,
  jsonb_build_object(
    'job_id', sj.id,
    'run_id', sjr.id,
    'job_name', sj.name,
    'error', sjr.error_message
  ),
  'scheduler',
  sjr.id::text,
  COALESCE(sjr.completed_at, sjr.started_at, now())
FROM scheduled_job_runs sjr
JOIN scheduled_jobs sj ON sj.id = sjr.scheduled_job_id
LEFT JOIN brands b ON sj.brand_id = b.id
WHERE sjr.started_at > now() - interval '30 days'
AND NOT EXISTS (
  SELECT 1 FROM activity_events ae
  WHERE ae.source_id = sjr.id::text
  AND ae.source_type = 'scheduler'
);
