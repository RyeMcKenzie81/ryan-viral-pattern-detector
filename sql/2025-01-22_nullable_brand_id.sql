-- Migration: Make brand_id nullable for system-wide jobs like template_approval
-- Date: 2025-01-22
-- Purpose: Allow scheduled jobs that don't require a brand association

ALTER TABLE scheduled_jobs ALTER COLUMN brand_id DROP NOT NULL;
