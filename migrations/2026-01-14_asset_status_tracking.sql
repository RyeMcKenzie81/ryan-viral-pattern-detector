-- Migration: Add status tracking for media assets
-- Date: 2026-01-14
-- Purpose: Track download status of scraped assets to handle 404s and expired URLs

-- Add status column to scraped_ad_assets
ALTER TABLE scraped_ad_assets
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'downloaded';

-- Valid statuses: 'downloaded', 'failed', 'expired', 'pending'
COMMENT ON COLUMN scraped_ad_assets.status IS
  'Asset status: downloaded (ok), failed (download failed), expired (404 on re-check), pending (queued)';

-- Add index for filtering by status
CREATE INDEX IF NOT EXISTS idx_scraped_ad_assets_status
ON scraped_ad_assets(status);

-- Update existing records to have 'downloaded' status where storage_path exists
UPDATE scraped_ad_assets
SET status = 'downloaded'
WHERE status IS NULL AND storage_path IS NOT NULL;

-- Mark records without storage_path as 'failed'
UPDATE scraped_ad_assets
SET status = 'failed'
WHERE status IS NULL AND storage_path IS NULL;
