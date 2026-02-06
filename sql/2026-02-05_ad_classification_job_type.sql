-- Migration: Add ad_classification and congruence_reanalysis job types
-- Date: 2026-02-05
-- Purpose: Allow scheduling background ad classification jobs and congruence re-analysis

-- Update job_type constraint to include all current job types
ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard', 'template_scrape', 'template_approval', 'congruence_reanalysis', 'ad_classification'));
