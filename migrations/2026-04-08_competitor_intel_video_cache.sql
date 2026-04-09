-- Migration: Competitor Intel Video Extraction Cache
-- Date: 2026-04-08
-- Purpose: Cache per-video Gemini extractions to avoid re-analyzing the same video

CREATE TABLE IF NOT EXISTS competitor_intel_video_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT 'v1',
    model_version TEXT NOT NULL DEFAULT 'gemini-3-pro-preview',
    extraction JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE competitor_intel_video_cache IS 'Caches Gemini extraction results per video asset + prompt version to avoid redundant API calls';
COMMENT ON COLUMN competitor_intel_video_cache.asset_id IS 'References competitor_ad_assets.id';
COMMENT ON COLUMN competitor_intel_video_cache.prompt_version IS 'Version of extraction prompt used';

-- Unique constraint: one extraction per asset per prompt version
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_intel_video_cache_lookup
    ON competitor_intel_video_cache (asset_id, prompt_version);
