-- Migration: Add started_running column to competitor_ads
-- Date: 2026-04-08
-- Purpose: The save_competitor_ad() method writes start_date to started_running,
--          but the column was never created. Only stopped_running was added in 2025-12-11.

ALTER TABLE competitor_ads ADD COLUMN IF NOT EXISTS started_running DATE;

COMMENT ON COLUMN competitor_ads.started_running IS 'Date the ad started running (start_date from Ad Library)';

-- Backfill from snapshot_data where available
UPDATE competitor_ads
SET started_running = (snapshot_data::jsonb->>'start_date')::date
WHERE started_running IS NULL
  AND snapshot_data IS NOT NULL
  AND snapshot_data::jsonb->>'start_date' IS NOT NULL;
