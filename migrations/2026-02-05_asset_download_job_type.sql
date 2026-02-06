-- Migration: Add asset_download to scheduled_jobs job_type CHECK constraint
-- Date: 2026-02-05
-- Purpose: Allow asset_download as a standalone scheduled job type

ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN ('ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
  'template_approval', 'congruence_reanalysis', 'ad_classification', 'asset_download'));
