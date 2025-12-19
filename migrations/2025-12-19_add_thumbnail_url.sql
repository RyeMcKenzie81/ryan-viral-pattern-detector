-- Migration: Add thumbnail_url to meta_ads_performance
-- Date: 2025-12-19
-- Purpose: Store Meta ad thumbnail URLs for visual comparison in linking UI

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    thumbnail_url TEXT;

COMMENT ON COLUMN meta_ads_performance.thumbnail_url IS 'Meta ad creative thumbnail URL for visual verification';
