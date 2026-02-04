-- Migration: Create ad_video_analysis table for deep video analysis
-- Date: 2026-02-03
-- Purpose: Store comprehensive video analysis results from Gemini including
--          transcripts, hooks, storyboards, and messaging extraction.
--          Immutable, versioned rows with input_hash + prompt_version.

CREATE TABLE IF NOT EXISTS ad_video_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,

    -- Versioning (immutable history)
    input_hash TEXT NOT NULL,           -- sha256(storage_path:etag) or sha256(storage_path:updated_at_iso)
    prompt_version TEXT NOT NULL DEFAULT 'v1',

    -- Stable join keys + provenance (nullable, populate when available)
    creative_id TEXT,                   -- Meta creative ID if known
    video_id TEXT,                      -- Meta video ID if known
    storage_path TEXT,                  -- Supabase storage path used for this analysis

    -- Status & Error handling
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'validation_failed', 'error')),
    validation_errors JSONB DEFAULT '[]',
    error_message TEXT,

    -- Core transcript (timestamps are float seconds, ordered, non-overlapping)
    full_transcript TEXT,
    transcript_segments JSONB,  -- [{start_sec: float, end_sec: float, text: str, speaker?: str}]

    -- Text overlays (best effort - may be empty; timestamps are float seconds)
    text_overlays JSONB DEFAULT '[]',   -- [{start_sec: float, end_sec: float, text: str, position?: str, style?: str}]
    text_overlay_confidence NUMERIC(3,2),  -- 0.0-1.0, quality/reliability of overlay detection

    -- Hook analysis (spoken + visual)
    hook_transcript_spoken TEXT,      -- Words spoken in first 3-5 sec
    hook_transcript_overlay TEXT,     -- Text overlay in first 3-5 sec (may be null)
    hook_fingerprint TEXT,            -- SHA256 of normalized "spoken:<...>|overlay:<...>"
    hook_type TEXT,                   -- question, claim, story, callout, transformation, etc.
    hook_effectiveness_signals JSONB, -- {spoken_present: bool, overlay_present: bool, spoken_hook: str, visual_hook: str, combination_score: float}

    -- Storyboard (timestamp_sec is float seconds)
    storyboard JSONB,  -- [{timestamp_sec: float, scene_description: str, key_elements: [], text_overlay?: str}]

    -- Messaging extraction
    benefits_shown TEXT[],
    features_demonstrated TEXT[],
    pain_points_addressed TEXT[],
    angles_used TEXT[],
    jobs_to_be_done TEXT[],
    claims_made JSONB,  -- [{claim, timestamp_sec, proof_shown}]

    -- Psychology
    awareness_level TEXT CHECK (awareness_level IN
        ('unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware')),
    awareness_confidence NUMERIC(3,2),
    target_persona JSONB,
    emotional_drivers TEXT[],

    -- Production
    video_duration_sec INTEGER,
    production_quality TEXT,  -- raw, polished, professional
    format_type TEXT,         -- ugc, professional, testimonial, demo

    -- Raw
    raw_response JSONB,
    model_used TEXT,

    -- Timestamps
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique per version+hash (allows re-analysis with new prompt or changed file)
    UNIQUE(meta_ad_id, brand_id, prompt_version, input_hash)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_video_analysis_brand_ad_time
    ON ad_video_analysis(brand_id, meta_ad_id, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_analysis_brand_version
    ON ad_video_analysis(brand_id, prompt_version);
CREATE INDEX IF NOT EXISTS idx_video_analysis_hook_fingerprint
    ON ad_video_analysis(hook_fingerprint) WHERE hook_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_video_analysis_brand_creative
    ON ad_video_analysis(brand_id, creative_id) WHERE creative_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_video_analysis_brand_video
    ON ad_video_analysis(brand_id, video_id) WHERE video_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_video_analysis_status
    ON ad_video_analysis(status) WHERE status != 'ok';

COMMENT ON TABLE ad_video_analysis IS 'Deep video analysis results from Gemini. Immutable, versioned rows - new analyses create new rows, old rows never overwritten.';
COMMENT ON COLUMN ad_video_analysis.input_hash IS 'SHA256(storage_path:etag) or SHA256(storage_path:updated_at_iso) for change detection';
COMMENT ON COLUMN ad_video_analysis.prompt_version IS 'Prompt version for re-analysis with updated prompts';
COMMENT ON COLUMN ad_video_analysis.status IS 'ok = success, validation_failed = bad timestamps but raw stored, error = Gemini call failed';
COMMENT ON COLUMN ad_video_analysis.validation_errors IS 'Array of validation error messages when status=validation_failed';
COMMENT ON COLUMN ad_video_analysis.hook_fingerprint IS 'SHA256 of normalized spoken:<...>|overlay:<...> for hook deduplication';
COMMENT ON COLUMN ad_video_analysis.text_overlay_confidence IS '0.0-1.0 indicating reliability of overlay detection (may be null if not detected)';
