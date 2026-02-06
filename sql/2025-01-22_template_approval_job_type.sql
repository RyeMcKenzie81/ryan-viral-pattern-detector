-- Migration: Add template_approval job type for batch AI analysis of template queue
-- Date: 2025-01-22
-- Purpose: Allow scheduling automated batch approval of template queue items

-- Update job_type constraint to include template_approval
ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard', 'template_scrape', 'template_approval'));
