-- Migration: Add Google indexing status columns to seo_articles
-- Date: 2026-03-16
-- Purpose: Track per-article indexing status from GSC URL Inspection API

ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_status TEXT;
ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_coverage_state TEXT;
ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_last_crawl_time TIMESTAMPTZ;
ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS index_checked_at TIMESTAMPTZ;

COMMENT ON COLUMN seo_articles.index_status IS 'Google indexing status: indexed, not_indexed, or NULL (not checked)';
COMMENT ON COLUMN seo_articles.index_coverage_state IS 'GSC coverage state string, e.g. "Submitted and indexed", "Crawled - currently not indexed"';
COMMENT ON COLUMN seo_articles.index_last_crawl_time IS 'When Google last crawled this URL (from URL Inspection API)';
COMMENT ON COLUMN seo_articles.index_checked_at IS 'When we last checked indexing status via URL Inspection API';

CREATE INDEX IF NOT EXISTS idx_seo_articles_index_status ON seo_articles(index_status) WHERE index_status IS NOT NULL;
