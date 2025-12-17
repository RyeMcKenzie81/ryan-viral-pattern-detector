-- Migration: Add unique constraint to competitor_landing_pages
-- Date: 2025-12-17
-- Purpose: Enable upsert on (competitor_id, url) for landing page scraping

-- First, remove any duplicates (keep the most recent one)
DELETE FROM competitor_landing_pages a
USING competitor_landing_pages b
WHERE a.competitor_id = b.competitor_id
  AND a.url = b.url
  AND a.created_at < b.created_at;

-- Add unique constraint
ALTER TABLE competitor_landing_pages
ADD CONSTRAINT competitor_landing_pages_competitor_url_unique
UNIQUE (competitor_id, url);

COMMENT ON CONSTRAINT competitor_landing_pages_competitor_url_unique
ON competitor_landing_pages IS 'Ensures one landing page record per competitor+URL combination';
