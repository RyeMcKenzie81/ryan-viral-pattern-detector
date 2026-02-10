-- Migration: Add content versioning support to brand_landing_pages
-- Date: 2026-02-10
-- Purpose: Add content_hash for deduplication and last_scraped_at for freshness tracking.
--          UNIQUE(brand_id, url) already exists as idx_brand_landing_pages_brand_url
--          from 2025-12-07 migration, so no constraint change needed.

ALTER TABLE brand_landing_pages
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

ALTER TABLE brand_landing_pages
    ADD COLUMN IF NOT EXISTS last_scraped_at TIMESTAMPTZ DEFAULT NOW();

COMMENT ON COLUMN brand_landing_pages.content_hash IS 'SHA-256 hash of raw_markdown for deduplication — skip re-storing identical content';
COMMENT ON COLUMN brand_landing_pages.last_scraped_at IS 'When this page was last scraped (bumped even if content unchanged)';
