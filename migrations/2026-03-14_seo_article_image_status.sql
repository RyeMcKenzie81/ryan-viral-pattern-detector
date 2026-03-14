-- Migration: Add image_status column for async image generation tracking
-- Date: 2026-03-14
-- Purpose: Track deferred image generation status per article

ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS image_status TEXT DEFAULT 'none';

COMMENT ON COLUMN seo_articles.image_status IS 'Async image gen status: none, pending, processing, complete, failed';
