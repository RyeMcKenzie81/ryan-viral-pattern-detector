-- Migration: Create onboarding_scrape_cache table for pre-import LP storage
-- Date: 2026-02-10
-- Purpose: Store full scraped markdown server-side during onboarding (before brand import).
--          Avoids putting large markdown blobs in client_onboarding_sessions.data JSONB.
--          Rows are cleaned up automatically via CASCADE when the session is deleted.

CREATE TABLE IF NOT EXISTS onboarding_scrape_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES client_onboarding_sessions(id) ON DELETE CASCADE,
    url_hash TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_markdown TEXT NOT NULL,
    content_hash TEXT,
    content_length INTEGER,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, url_hash)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_scrape_cache_session
ON onboarding_scrape_cache(session_id);

COMMENT ON TABLE onboarding_scrape_cache IS 'Server-side cache for landing page content scraped during onboarding (before brand import)';
COMMENT ON COLUMN onboarding_scrape_cache.url_hash IS 'SHA-256 hash of URL for fast lookup + uniqueness';
COMMENT ON COLUMN onboarding_scrape_cache.content_hash IS 'SHA-256 hash of raw_markdown for change detection';
