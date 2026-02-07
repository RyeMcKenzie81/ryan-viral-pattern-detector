-- Migration: Retry and stuck-run recovery columns
-- Date: 2026-02-06
-- Purpose: Add retry configuration to jobs and attempt tracking to runs.

-- Retry config on jobs
ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS max_retries INT DEFAULT 3;
ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS last_error TEXT;

-- Attempt tracking on runs
ALTER TABLE scheduled_job_runs ADD COLUMN IF NOT EXISTS attempt_number INT DEFAULT 1;
