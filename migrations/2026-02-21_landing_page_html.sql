-- Migration: Add page_html column for multipass v4
-- Date: 2026-02-21
-- Purpose: Store full original page HTML (with <head> CSS) for multipass v4
--          image extraction and responsive CSS harvesting.

ALTER TABLE landing_page_analyses
ADD COLUMN IF NOT EXISTS page_html TEXT;

COMMENT ON COLUMN landing_page_analyses.page_html
IS 'Full original page HTML (with <head> CSS) for multipass v4 extraction. Capped at 2MB.';
