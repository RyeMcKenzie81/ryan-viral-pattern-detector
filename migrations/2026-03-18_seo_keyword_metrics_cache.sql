-- Migration: SEO Keyword Metrics Cache
-- Date: 2026-03-18
-- Purpose: Add CPC/competition columns to seo_keywords and create a
--          keyword metrics cache table to avoid redundant DataForSEO API calls.
--          Cache has 7-day freshness window (enforced in application code).

-- ============================================================================
-- 1. Extend seo_keywords with new metric columns
-- ============================================================================

ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS cpc FLOAT;
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS competition FLOAT;
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS metrics_refreshed_at TIMESTAMPTZ;

COMMENT ON COLUMN seo_keywords.cpc IS 'Average cost per click from Google Ads (USD)';
COMMENT ON COLUMN seo_keywords.competition IS 'Competition level from Google Ads (0.0-1.0)';
COMMENT ON COLUMN seo_keywords.metrics_refreshed_at IS 'When volume/KD/CPC were last fetched from DataForSEO';

-- ============================================================================
-- 2. Keyword metrics cache — stores DataForSEO results for any keyword
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_keyword_metrics_cache (
    keyword TEXT NOT NULL,
    location_code INT NOT NULL DEFAULT 2840,
    search_volume INT,
    keyword_difficulty FLOAT,
    cpc FLOAT,
    competition FLOAT,
    search_intent TEXT,
    refreshed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (keyword, location_code)
);

COMMENT ON TABLE seo_keyword_metrics_cache IS 'Cache for DataForSEO keyword metrics. Keyed on (keyword, location_code). 7-day freshness enforced in app code.';
COMMENT ON COLUMN seo_keyword_metrics_cache.keyword IS 'Lowercase keyword text';
COMMENT ON COLUMN seo_keyword_metrics_cache.search_volume IS 'Monthly average search volume from Google Ads';
COMMENT ON COLUMN seo_keyword_metrics_cache.keyword_difficulty IS 'Keyword difficulty score (0-100)';
COMMENT ON COLUMN seo_keyword_metrics_cache.cpc IS 'Average cost per click (USD)';
COMMENT ON COLUMN seo_keyword_metrics_cache.competition IS 'Competition level (0.0-1.0)';
COMMENT ON COLUMN seo_keyword_metrics_cache.search_intent IS 'Primary search intent (informational, commercial, transactional, navigational)';
COMMENT ON COLUMN seo_keyword_metrics_cache.refreshed_at IS 'When this row was last refreshed from DataForSEO API';

-- Index for cache lookups by freshness
CREATE INDEX IF NOT EXISTS idx_seo_kw_cache_refreshed ON seo_keyword_metrics_cache(refreshed_at);

-- RLS policy (same open policy as other seo_ tables)
ALTER TABLE seo_keyword_metrics_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY seo_keyword_metrics_cache_policy ON seo_keyword_metrics_cache FOR ALL TO authenticated USING (true) WITH CHECK (true);
