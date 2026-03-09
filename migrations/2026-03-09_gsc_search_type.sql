-- Migration: Add search_type to seo_article_analytics
-- Date: 2026-03-09
-- Purpose: Store GSC data per search type (web, image, video, news, discover)
--          so the dashboard can filter by type. GSC defaults to "Web" — users
--          want to see web impressions separately from image search.

-- 1. Add search_type column (defaults to 'web' for backward compat)
ALTER TABLE seo_article_analytics
    ADD COLUMN IF NOT EXISTS search_type TEXT NOT NULL DEFAULT 'web';

COMMENT ON COLUMN seo_article_analytics.search_type
    IS 'GSC search type: web, image, video, news, discover. Non-GSC sources always use web.';

-- 2. Drop old unique constraint and create new one including search_type
ALTER TABLE seo_article_analytics
    DROP CONSTRAINT IF EXISTS seo_article_analytics_article_id_date_source_key;

ALTER TABLE seo_article_analytics
    ADD CONSTRAINT seo_article_analytics_article_id_date_source_type_key
    UNIQUE (article_id, date, source, search_type);

-- 3. Index for filtering by search_type
CREATE INDEX IF NOT EXISTS idx_seo_article_analytics_search_type
    ON seo_article_analytics(search_type);
