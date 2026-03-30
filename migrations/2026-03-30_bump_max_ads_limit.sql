-- Migration: Bump max ads per scheduled run from 50 to 200
-- Date: 2026-03-30
-- Purpose: Allow overnight batch runs to generate up to 200 ads

UPDATE system_settings
SET value = '200'
WHERE key = 'angle_pipeline.max_ads_per_scheduled_run'
  AND value = '50';
