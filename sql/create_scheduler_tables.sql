-- ============================================================================
-- Ad Scheduler Database Tables
-- ============================================================================
-- Created: 2025-12-01
-- Purpose: Support scheduled ad generation with templates, runs, and tracking
--
-- Tables:
--   1. scheduled_jobs       - Job configuration and scheduling
--   2. scheduled_job_runs   - Execution history and logs
--   3. product_template_usage - Track which templates have been used per product
-- ============================================================================

-- ============================================================================
-- Table: scheduled_jobs
-- ============================================================================
-- Stores scheduled ad generation jobs with their configuration.
-- Each job is tied to a product and defines when/how to generate ads.

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Product/Brand references
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL,  -- Denormalized for efficient filtering

    -- Job identification
    name TEXT NOT NULL,

    -- Schedule configuration
    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('one_time', 'recurring')),
    cron_expression TEXT,  -- For recurring jobs (e.g., "0 9 * * 1" = Mondays 9am PST)
    scheduled_at TIMESTAMP WITH TIME ZONE,  -- For one-time jobs
    next_run_at TIMESTAMP WITH TIME ZONE,  -- Calculated next execution time

    -- Run limits
    max_runs INT,  -- NULL = unlimited
    runs_completed INT DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed')),

    -- Template configuration
    template_mode TEXT NOT NULL CHECK (template_mode IN ('unused', 'specific', 'uploaded')),
    template_count INT,  -- Number of templates per run (if mode='unused')
    template_ids TEXT[],  -- Specific template storage names (if mode='specific' or 'uploaded')

    -- Ad creation parameters (stored as JSONB for flexibility)
    -- Contains: num_variations, content_source, color_mode,
    --           image_selection_mode, export_destination, etc.
    parameters JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Multi-tenancy prep (nullable for now)
    tenant_id UUID
);

-- Indexes for scheduled_jobs
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_product ON scheduled_jobs(product_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_brand ON scheduled_jobs(brand_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_status ON scheduled_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run ON scheduled_jobs(next_run_at)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_tenant ON scheduled_jobs(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_scheduled_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_scheduled_jobs_updated_at ON scheduled_jobs;
CREATE TRIGGER trigger_scheduled_jobs_updated_at
    BEFORE UPDATE ON scheduled_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_jobs_updated_at();


-- ============================================================================
-- Table: scheduled_job_runs
-- ============================================================================
-- Stores execution history for scheduled jobs.
-- Each run links to the job and tracks the ad_runs it created.

CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Parent job reference
    scheduled_job_id UUID NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,

    -- Execution timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Status tracking
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,

    -- Results
    ad_run_ids UUID[],  -- References to ad_runs table
    templates_used TEXT[],  -- Template storage names used in this run

    -- Execution logs (for debugging)
    logs TEXT,

    -- Multi-tenancy prep
    tenant_id UUID
);

-- Indexes for scheduled_job_runs
CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job ON scheduled_job_runs(scheduled_job_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_status ON scheduled_job_runs(status);
CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_started ON scheduled_job_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_tenant ON scheduled_job_runs(tenant_id)
    WHERE tenant_id IS NOT NULL;


-- ============================================================================
-- Table: product_template_usage
-- ============================================================================
-- Tracks which templates have been used for each product.
-- Used by the "unused templates" feature to ensure variety.

CREATE TABLE IF NOT EXISTS product_template_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Product reference
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

    -- Template identification (storage filename)
    template_storage_name TEXT NOT NULL,

    -- Usage tracking
    used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ad_run_id UUID REFERENCES ad_runs(id) ON DELETE SET NULL,

    -- Multi-tenancy prep
    tenant_id UUID,

    -- Ensure each template is only tracked once per product
    UNIQUE(product_id, template_storage_name)
);

-- Indexes for product_template_usage
CREATE INDEX IF NOT EXISTS idx_product_template_usage_product ON product_template_usage(product_id);
CREATE INDEX IF NOT EXISTS idx_product_template_usage_template ON product_template_usage(template_storage_name);
CREATE INDEX IF NOT EXISTS idx_product_template_usage_tenant ON product_template_usage(tenant_id)
    WHERE tenant_id IS NOT NULL;


-- ============================================================================
-- Helper Views
-- ============================================================================

-- View: Active scheduled jobs with next run info
CREATE OR REPLACE VIEW v_active_scheduled_jobs AS
SELECT
    sj.id,
    sj.name,
    sj.product_id,
    sj.brand_id,
    p.name AS product_name,
    sj.schedule_type,
    sj.next_run_at,
    sj.runs_completed,
    sj.max_runs,
    sj.template_mode,
    sj.template_count,
    sj.status,
    sj.created_at
FROM scheduled_jobs sj
LEFT JOIN products p ON sj.product_id = p.id
WHERE sj.status = 'active'
ORDER BY sj.next_run_at ASC NULLS LAST;

-- View: Recent job runs with job details
CREATE OR REPLACE VIEW v_recent_job_runs AS
SELECT
    sjr.id AS run_id,
    sjr.scheduled_job_id,
    sj.name AS job_name,
    sj.product_id,
    p.name AS product_name,
    sjr.status,
    sjr.started_at,
    sjr.completed_at,
    sjr.error_message,
    array_length(sjr.ad_run_ids, 1) AS ads_generated,
    array_length(sjr.templates_used, 1) AS templates_used
FROM scheduled_job_runs sjr
LEFT JOIN scheduled_jobs sj ON sjr.scheduled_job_id = sj.id
LEFT JOIN products p ON sj.product_id = p.id
ORDER BY sjr.started_at DESC NULLS LAST;


-- ============================================================================
-- Sample Data (commented out - uncomment to test)
-- ============================================================================
/*
-- Example: Create a weekly recurring job
INSERT INTO scheduled_jobs (
    product_id,
    brand_id,
    name,
    schedule_type,
    cron_expression,
    next_run_at,
    max_runs,
    template_mode,
    template_count,
    parameters
) VALUES (
    '00000000-0000-0000-0000-000000000001',  -- Replace with real product_id
    '00000000-0000-0000-0000-000000000001',  -- Replace with real brand_id
    'Weekly Ad Refresh',
    'recurring',
    '0 9 * * 1',  -- Mondays at 9am
    NOW() + INTERVAL '7 days',
    4,  -- Run 4 times total
    'unused',
    5,  -- Use 5 unused templates per run
    '{
        "num_variations": 5,
        "content_source": "hooks",
        "color_mode": "original",
        "image_selection_mode": "auto",
        "export_destination": "slack"
    }'::jsonb
);
*/


-- ============================================================================
-- Cleanup / Reset (for development - be careful!)
-- ============================================================================
/*
DROP VIEW IF EXISTS v_recent_job_runs;
DROP VIEW IF EXISTS v_active_scheduled_jobs;
DROP TABLE IF EXISTS product_template_usage;
DROP TABLE IF EXISTS scheduled_job_runs;
DROP TABLE IF EXISTS scheduled_jobs;
*/
