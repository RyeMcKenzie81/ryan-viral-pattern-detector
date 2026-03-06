-- Migration: Add website_url to brands table
-- Date: 2026-03-06
-- Purpose: Store brand website URL for auto-fill features

ALTER TABLE brands ADD COLUMN IF NOT EXISTS website_url TEXT;

COMMENT ON COLUMN brands.website_url IS 'Brand main website URL for scraping and auto-fill';
