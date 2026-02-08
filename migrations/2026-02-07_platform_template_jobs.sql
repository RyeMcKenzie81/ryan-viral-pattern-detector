-- Migration: Move template jobs to platform-level (brand_id = NULL)
-- Date: 2026-02-07
-- Purpose: template_scrape and template_approval jobs operate on shared template pools,
--          not brand-specific data. Moving them to brand_id=NULL allows proper scheduling
--          and monitoring in the new Platform Schedules sub-tab.

UPDATE scheduled_jobs SET brand_id = NULL
WHERE job_type IN ('template_scrape', 'template_approval')
  AND brand_id IS NOT NULL;
