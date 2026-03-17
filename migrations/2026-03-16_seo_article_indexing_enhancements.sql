-- Migration: Add indexing enhancement columns to seo_articles
-- Date: 2026-03-16
-- Purpose: Store GSC inspection deep links and allow ignoring articles from indexing tracking

ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_inspection_link TEXT;
ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_tracking_ignored BOOLEAN DEFAULT FALSE;

-- Backfill existing rows so .eq(False) works (not NULL)
UPDATE seo_articles SET index_tracking_ignored = FALSE WHERE index_tracking_ignored IS NULL;

COMMENT ON COLUMN seo_articles.index_inspection_link IS 'GSC URL Inspection deep link from API response';
COMMENT ON COLUMN seo_articles.index_tracking_ignored IS 'When true, excluded from indexing KPIs and non-indexed lists';
