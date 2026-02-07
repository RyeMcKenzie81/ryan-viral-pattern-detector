-- Migration: Scheduler enhancements for pipeline control plane
-- Date: 2026-02-06
-- Purpose: Add trigger_source to distinguish manual/api from scheduled runs,
--          and archived status for completed one-time manual jobs.

-- trigger_source to distinguish manual/api from scheduled
ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS trigger_source TEXT DEFAULT 'scheduled';

-- Archived status for completed one-time manual jobs
-- Drop and recreate status check constraint to include 'archived'
ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS scheduled_jobs_status_check;
ALTER TABLE scheduled_jobs ADD CONSTRAINT scheduled_jobs_status_check
    CHECK (status IN ('active', 'paused', 'completed', 'archived'));

-- Add trigger_source check constraint
ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS scheduled_jobs_trigger_source_check;
ALTER TABLE scheduled_jobs ADD CONSTRAINT scheduled_jobs_trigger_source_check
    CHECK (trigger_source IN ('scheduled', 'manual', 'api'));
