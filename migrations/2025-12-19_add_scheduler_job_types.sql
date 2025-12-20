-- Migration: Add job_type support to scheduler
-- Date: 2025-12-19
-- Purpose: Enable meta_sync and scorecard jobs alongside ad_creation jobs

-- Add job_type column with default 'ad_creation' for backward compatibility
ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS
    job_type TEXT DEFAULT 'ad_creation';

-- Add check constraint for valid job types
-- Note: Using DO block to handle case where constraint already exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'scheduled_jobs_job_type_check'
    ) THEN
        ALTER TABLE scheduled_jobs ADD CONSTRAINT scheduled_jobs_job_type_check
            CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard'));
    END IF;
END
$$;

-- Make product_id nullable for jobs that only need brand_id (meta_sync, scorecard)
-- Note: Drop FK constraint first, then alter, then re-add with nullable
ALTER TABLE scheduled_jobs ALTER COLUMN product_id DROP NOT NULL;

-- Make template_mode nullable (not needed for non-ad jobs)
ALTER TABLE scheduled_jobs ALTER COLUMN template_mode DROP NOT NULL;

-- Add index for job_type filtering
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_job_type ON scheduled_jobs(job_type);

-- Update view to include job_type
CREATE OR REPLACE VIEW v_active_scheduled_jobs AS
SELECT
    sj.id,
    sj.name,
    sj.job_type,
    sj.product_id,
    sj.brand_id,
    p.name AS product_name,
    b.name AS brand_name,
    sj.schedule_type,
    sj.next_run_at,
    sj.runs_completed,
    sj.max_runs,
    sj.template_mode,
    sj.template_count,
    sj.status,
    sj.parameters,
    sj.created_at
FROM scheduled_jobs sj
LEFT JOIN products p ON sj.product_id = p.id
LEFT JOIN brands b ON sj.brand_id = b.id
WHERE sj.status = 'active'
ORDER BY sj.next_run_at ASC NULLS LAST;

COMMENT ON COLUMN scheduled_jobs.job_type IS 'Type of job: ad_creation, meta_sync, or scorecard';
