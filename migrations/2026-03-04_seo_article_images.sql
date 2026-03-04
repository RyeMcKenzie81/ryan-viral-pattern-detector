-- Migration: Add image columns to seo_articles
-- Date: 2026-03-04
-- Purpose: Support hero image and inline image generation for SEO articles

ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS hero_image_url TEXT;
ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS image_metadata JSONB;

COMMENT ON COLUMN seo_articles.hero_image_url IS 'Public CDN URL of hero/featured image';
COMMENT ON COLUMN seo_articles.image_metadata IS 'JSONB array: [{index, type, description, status, cdn_url, storage_path, alt_text, error}]';
