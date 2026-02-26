-- Migration: Instagram Content Library
-- Date: 2026-02-25
-- Purpose: Per-brand watched accounts, media storage for outlier content,
--          and outlier tracking columns on existing posts table.
-- Phase: Video Tools Suite - Phase 1

-- ============================================================================
-- 1. Per-brand watched accounts (extends existing accounts system)
-- ============================================================================

CREATE TABLE IF NOT EXISTS instagram_watched_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    account_id UUID NOT NULL REFERENCES accounts(id),
    is_active BOOLEAN DEFAULT true,
    scrape_frequency_hours INTEGER DEFAULT 168,       -- weekly default
    min_scrape_interval_hours INTEGER DEFAULT 24,     -- prevent over-scraping
    last_scraped_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(brand_id, account_id)
);

COMMENT ON TABLE instagram_watched_accounts IS 'Per-brand Instagram accounts to monitor for content research';
COMMENT ON COLUMN instagram_watched_accounts.scrape_frequency_hours IS 'How often to auto-scrape (168 = weekly)';
COMMENT ON COLUMN instagram_watched_accounts.min_scrape_interval_hours IS 'Minimum hours between scrapes to prevent over-scraping';

CREATE INDEX IF NOT EXISTS idx_ig_watched_brand ON instagram_watched_accounts(brand_id);
CREATE INDEX IF NOT EXISTS idx_ig_watched_org ON instagram_watched_accounts(organization_id);
CREATE INDEX IF NOT EXISTS idx_ig_watched_active ON instagram_watched_accounts(is_active) WHERE is_active = true;

-- ============================================================================
-- 2. Media files for downloaded content (only outliers get downloaded)
-- ============================================================================

CREATE TABLE IF NOT EXISTS instagram_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    media_type TEXT NOT NULL,                    -- 'image', 'video'
    media_index INTEGER DEFAULT 0,              -- carousel order
    original_cdn_url TEXT,                       -- CDN URL (expires, for reference only)
    cdn_url_captured_at TIMESTAMPTZ,            -- when URL was captured (track staleness)
    storage_path TEXT,                           -- Supabase storage path (persistent)
    thumbnail_path TEXT,
    width INTEGER,
    height INTEGER,
    file_size_bytes BIGINT,
    duration_sec FLOAT,                         -- video duration
    download_status TEXT DEFAULT 'pending',      -- pending, downloading, downloaded, failed
    download_error TEXT,
    downloaded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE instagram_media IS 'Downloaded media files for outlier Instagram posts (only outliers get downloaded to save storage)';
COMMENT ON COLUMN instagram_media.original_cdn_url IS 'Instagram CDN URL - expires quickly, stored for reference';
COMMENT ON COLUMN instagram_media.storage_path IS 'Persistent Supabase storage path after download';
COMMENT ON COLUMN instagram_media.download_status IS 'pending, downloading, downloaded, failed';

CREATE INDEX IF NOT EXISTS idx_ig_media_post ON instagram_media(post_id);
CREATE INDEX IF NOT EXISTS idx_ig_media_status ON instagram_media(download_status);

-- ============================================================================
-- 3. Add outlier tracking columns to existing posts table
-- ============================================================================

ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_outlier BOOLEAN DEFAULT false;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS outlier_score FLOAT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS outlier_method TEXT;           -- 'zscore', 'percentile'
ALTER TABLE posts ADD COLUMN IF NOT EXISTS outlier_calculated_at TIMESTAMPTZ;

COMMENT ON COLUMN posts.is_outlier IS 'Whether this post was flagged as an engagement outlier';
COMMENT ON COLUMN posts.outlier_score IS 'Z-score or percentile score from outlier detection';
COMMENT ON COLUMN posts.outlier_method IS 'Method used: zscore or percentile';
COMMENT ON COLUMN posts.outlier_calculated_at IS 'When outlier detection was last run for this post';

-- Index for efficient outlier queries
CREATE INDEX IF NOT EXISTS idx_posts_outlier ON posts(is_outlier) WHERE is_outlier = true;
CREATE INDEX IF NOT EXISTS idx_posts_account_outlier ON posts(account_id, is_outlier);
