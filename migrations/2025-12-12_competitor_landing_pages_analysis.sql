-- Migration: Add analysis columns to competitor_landing_pages
-- Date: 2025-12-12
-- Purpose: Add missing columns for landing page scraping and analysis

-- Add scraped content columns
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS scraped_content TEXT;
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS scraped_html TEXT;
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ;

-- Add analysis columns
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS analysis_data JSONB;
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMPTZ;

COMMENT ON COLUMN competitor_landing_pages.scraped_content IS 'Markdown content scraped from landing page';
COMMENT ON COLUMN competitor_landing_pages.scraped_html IS 'Raw HTML content from landing page';
COMMENT ON COLUMN competitor_landing_pages.scraped_at IS 'When the page was scraped';
COMMENT ON COLUMN competitor_landing_pages.analysis_data IS 'AI analysis of landing page content (JSON)';
COMMENT ON COLUMN competitor_landing_pages.analyzed_at IS 'When the page was analyzed';
