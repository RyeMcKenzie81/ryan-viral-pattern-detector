-- Migration: Create meta_ad_assets table for video asset storage
-- Date: 2026-02-02
-- Purpose: Store downloaded video assets from Meta Ads API in Supabase storage.
--          Provides direct lookup for classifier_service without bridging through
--          facebook_ads → scraped_ad_assets.

CREATE TABLE IF NOT EXISTS meta_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_id TEXT NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    asset_type TEXT NOT NULL DEFAULT 'video',
    storage_path TEXT NOT NULL,
    mime_type TEXT,
    file_size_bytes BIGINT,
    meta_video_id TEXT,
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'downloaded',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(meta_ad_id, asset_type)
);

-- Index for classifier lookup (most common query)
CREATE INDEX IF NOT EXISTS idx_meta_ad_assets_lookup
    ON meta_ad_assets (meta_ad_id, asset_type, status);

-- Index for brand-scoped queries
CREATE INDEX IF NOT EXISTS idx_meta_ad_assets_brand
    ON meta_ad_assets (brand_id);

COMMENT ON TABLE meta_ad_assets IS 'Downloaded video/image assets from Meta Marketing API for owned ads';
COMMENT ON COLUMN meta_ad_assets.meta_ad_id IS 'Meta ad ID from meta_ads_performance';
COMMENT ON COLUMN meta_ad_assets.storage_path IS 'Supabase storage path: meta-ad-assets/{brand_id}/{meta_ad_id}.mp4';
COMMENT ON COLUMN meta_ad_assets.source_url IS 'Original CDN URL for re-download if needed';
COMMENT ON COLUMN meta_ad_assets.status IS 'downloaded, failed, deleted, not_downloadable (Reel-type videos without source URL)';

-- NOTE: Also create "meta-ad-assets" bucket in Supabase Dashboard (Storage → New Bucket)
