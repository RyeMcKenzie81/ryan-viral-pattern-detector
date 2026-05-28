-- Migration: Add worker_id to scheduled_job_runs for debugging
-- Date: 2026-05-28
-- Purpose: PR 1 of 2 — scheduler worker upgrade. Adds worker_id column so that
--          when a claim is made, the operator can see which worker took which
--          run (useful for debugging "why didn't my job run" type questions).
--          Format: {boot_id}:{slot_idx} where boot_id is a short random suffix
--          generated at scheduler startup, so IDs don't collide across restarts.

ALTER TABLE scheduled_job_runs
    ADD COLUMN IF NOT EXISTS worker_id TEXT;

COMMENT ON COLUMN scheduled_job_runs.worker_id IS
    'Worker that claimed this run. Format: {boot_id}:{slot_idx}. NULL for pre-upgrade rows.';

-- Index on worker_id for "what is worker X currently running" queries during
-- debugging. Partial: only useful for active runs.
CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_worker_id
    ON scheduled_job_runs (worker_id)
    WHERE status = 'running' AND worker_id IS NOT NULL;
