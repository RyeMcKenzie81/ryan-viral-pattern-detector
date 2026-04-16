-- Migration: RPC function for job duration estimates
-- Date: 2026-04-16
-- Purpose: Provides average completion time per job type from last 30 days
--          Used by ops_agent to give data-driven time estimates when queuing jobs

CREATE OR REPLACE FUNCTION get_job_duration_estimates()
RETURNS TABLE(job_type TEXT, avg_minutes FLOAT, run_count BIGINT)
LANGUAGE sql STABLE
AS $$
    SELECT
        sj.job_type,
        AVG(EXTRACT(EPOCH FROM (sjr.completed_at - sjr.started_at)) / 60.0) AS avg_minutes,
        COUNT(*) AS run_count
    FROM scheduled_job_runs sjr
    JOIN scheduled_jobs sj ON sjr.scheduled_job_id = sj.id
    WHERE sjr.status = 'completed'
        AND sjr.started_at IS NOT NULL
        AND sjr.completed_at IS NOT NULL
        AND sjr.completed_at > NOW() - INTERVAL '30 days'
    GROUP BY sj.job_type
    HAVING COUNT(*) >= 3
$$;

COMMENT ON FUNCTION get_job_duration_estimates IS 'Returns avg completion minutes per job type from last 30 days (min 3 runs for statistical validity)';
