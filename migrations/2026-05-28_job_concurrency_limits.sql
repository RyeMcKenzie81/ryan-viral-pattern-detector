-- Migration: Scheduler concurrency caps and per-job-type runtime limits
-- Date: 2026-05-28
-- Purpose: Foundation tables for the scheduler worker upgrade. PR 1 of 2.
--
-- Adds:
--   - job_concurrency_limits: admission caps per scope (global/job_type/brand/brand_job_type)
--   - job_runtime_limits:    per-job-type max runtime for stuck-run recovery
--   - Partial indexes on scheduled_job_runs(status='running') to keep cap-count
--     queries O(running-set) instead of O(table size)
--
-- See design doc:
--   ~/.gstack/projects/.../scheduler-worker-upgrade-design-20260528-111848.md

-- ============================================================================
-- job_concurrency_limits
-- ============================================================================
-- Runtime-tunable concurrency caps. The scheduler reads these to decide
-- admission for each claim attempt.
--
-- scope_type hierarchy (most-specific first):
--   brand_job_type → brand → job_type → global
--
-- A row with scope_key = '__default__' acts as the default for that scope_type;
-- specific values (e.g. a brand UUID) override the default.
--
-- max_concurrent = 0 means PAUSED: the scope is not admitted (n < 0 is never
-- true), so jobs queue but never claim.

CREATE TABLE IF NOT EXISTS job_concurrency_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type TEXT NOT NULL CHECK (
        scope_type IN ('global', 'job_type', 'brand', 'brand_job_type', 'organization')
    ),
    scope_key TEXT NOT NULL DEFAULT '__default__',
    max_concurrent INT NOT NULL CHECK (max_concurrent >= 0),
    enabled BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope_type, scope_key)
);

COMMENT ON TABLE job_concurrency_limits IS
    'Admission caps for the scheduler worker pool. Runtime-tunable without redeploy. See scheduler-worker-upgrade design doc.';
COMMENT ON COLUMN job_concurrency_limits.scope_type IS
    'One of: global, job_type, brand, brand_job_type, organization. Lookup hierarchy is brand_job_type → brand → job_type → global.';
COMMENT ON COLUMN job_concurrency_limits.scope_key IS
    'Sentinel ''__default__'' for the default row of each scope_type; otherwise the specific value (e.g. a brand UUID or job_type name).';
COMMENT ON COLUMN job_concurrency_limits.max_concurrent IS
    'Maximum concurrent running runs admitted by this scope. 0 = paused.';

-- Auto-update updated_at on row update.
CREATE OR REPLACE FUNCTION _job_concurrency_limits_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_job_concurrency_limits_touch ON job_concurrency_limits;
CREATE TRIGGER trg_job_concurrency_limits_touch
    BEFORE UPDATE ON job_concurrency_limits
    FOR EACH ROW EXECUTE FUNCTION _job_concurrency_limits_touch_updated_at();

-- Seed defaults. PLACEHOLDERS — tune after the instrumentation week per the
-- design doc's "The Assignment" section. template_scrape kept high because
-- Apify ingestion is I/O-bound (mostly waiting on Apify) so concurrency is fine.
INSERT INTO job_concurrency_limits (scope_type, scope_key, max_concurrent, notes) VALUES
    ('global',   '__default__',     8, 'Total concurrent running runs across all workers'),
    ('job_type', 'template_scrape', 6, 'Apify-bound; mostly I/O wait; high cap is fine'),
    ('job_type', 'ad_creation',     4, 'Gemini-bound; tune after measurement'),
    ('job_type', 'ad_creation_v2',  4, 'Gemini-bound; tune after measurement'),
    ('job_type', 'meta_sync',       2, 'Meta API rate limit'),
    ('brand',    '__default__',     3, 'Default per-brand cap; override per-brand for premium tier')
ON CONFLICT (scope_type, scope_key) DO NOTHING;

-- ============================================================================
-- job_runtime_limits
-- ============================================================================
-- Per-job-type max runtime for stuck-run recovery. The existing 30-minute
-- hardcoded threshold in recover_stuck_runs() falsely kills hours-long
-- template_scrape runs. This table fixes that with per-job-type cutoffs.
-- Rows missing from this table fall back to a 3600s default in code +
-- WARNING log so the operator notices.

CREATE TABLE IF NOT EXISTS job_runtime_limits (
    job_type TEXT PRIMARY KEY,
    max_runtime_seconds INT NOT NULL CHECK (max_runtime_seconds > 0),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE job_runtime_limits IS
    'Per-job-type max runtime for stuck-run recovery. Missing rows fall back to 3600s in code with a WARNING log.';

DROP TRIGGER IF EXISTS trg_job_runtime_limits_touch ON job_runtime_limits;
CREATE TRIGGER trg_job_runtime_limits_touch
    BEFORE UPDATE ON job_runtime_limits
    FOR EACH ROW EXECUTE FUNCTION _job_concurrency_limits_touch_updated_at();

INSERT INTO job_runtime_limits (job_type, max_runtime_seconds, notes) VALUES
    ('template_scrape',           14400, '4h — Apify ingestion can be slow'),
    ('ad_creation',                 900, '15min generous cap for Gemini pipeline'),
    ('ad_creation_v2',              900, '15min generous cap for Gemini pipeline'),
    ('meta_sync',                   600, '10min'),
    ('competitor_scrape',          3600, '1h'),
    ('asset_download',             1800, '30min'),
    ('congruence_reanalysis',      1200, '20min — vision model heavy'),
    ('scorecard',                   600, '10min'),
    ('iteration_auto_run',         7200, '2h — multi-step graph'),
    ('ad_intelligence_analysis',   7200, '2h — full 4-layer analysis'),
    ('seo_opportunity_scan',       7200, '2h'),
    ('competitor_intel_analysis',  7200, '2h'),
    ('quick_intel_analysis',       3600, '1h'),
    ('creative_genome_update',     1200, '20min'),
    ('creative_deep_analysis',     1800, '30min'),
    ('genome_validation',           600, '10min'),
    ('winner_evolution',           1800, '30min'),
    ('experiment_analysis',        1800, '30min'),
    ('quality_calibration',         600, '10min'),
    ('template_approval',           600, '10min'),
    ('ad_classification',          1200, '20min'),
    ('reddit_scrape',              3600, '1h'),
    ('amazon_review_scrape',       3600, '1h'),
    ('analytics_sync',              600, '10min'),
    ('seo_status_sync',             600, '10min'),
    ('size_variant',                900, '15min'),
    ('smart_edit',                  900, '15min'),
    ('seo_content_eval',           1800, '30min'),
    ('seo_publish',                 900, '15min'),
    ('seo_auto_interlink',         1200, '20min'),
    ('demographic_backfill',       3600, '1h'),
    ('token_refresh',               300, '5min')
ON CONFLICT (job_type) DO NOTHING;

-- ============================================================================
-- Partial indexes on scheduled_job_runs
-- ============================================================================
-- The new claim path counts WHERE status='running' (joined by scheduled_job_id
-- back to scheduled_jobs). Without these partial indexes, every count is an
-- O(table size) scan. With them, each count is O(running-set) — at peak ~8
-- rows. Cheap to add now; expensive to retrofit later.

CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_running
    ON scheduled_job_runs (scheduled_job_id)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_running_started
    ON scheduled_job_runs (started_at)
    WHERE status = 'running';
