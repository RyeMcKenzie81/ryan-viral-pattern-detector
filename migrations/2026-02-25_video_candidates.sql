-- Migration: Video Recreation Candidates
-- Date: 2026-02-25
-- Purpose: Create video_recreation_candidates table for Phase 4 recreation pipeline.
--          Tracks scored candidates, adapted storyboards, audio segments,
--          generated clips, and final assembled videos.

CREATE TABLE IF NOT EXISTS video_recreation_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    post_id UUID NOT NULL REFERENCES posts(id),
    analysis_id UUID REFERENCES ad_video_analysis(id),
    status TEXT DEFAULT 'candidate',    -- candidate, approved, rejected, generating, completed, failed

    -- Scoring (extensible JSONB)
    composite_score FLOAT,
    score_components JSONB,             -- engagement, hook_quality, recreation_feasibility, avatar_compatibility
    scoring_version TEXT DEFAULT 'v1',
    scoring_notes TEXT,

    -- Scene classification
    has_talking_head BOOLEAN DEFAULT false,
    scene_types JSONB,                  -- e.g. talking_head, broll_product, broll_lifestyle

    -- Recreation plan
    adapted_storyboard JSONB,           -- LLM-adapted storyboard for our brand
    production_storyboard JSONB,        -- Detailed shot sheet from Pass 2
    adapted_hook TEXT,
    adapted_script TEXT,
    text_overlay_instructions JSONB,    -- instructions for human editor

    -- Avatar & generation
    avatar_id UUID REFERENCES brand_avatars(id),
    generation_engine TEXT,             -- 'veo', 'kling', 'mixed'
    target_aspect_ratio TEXT DEFAULT '9:16',

    -- Audio (audio-first workflow)
    audio_segments JSONB,               -- array of scene_idx, audio_storage_path, duration_sec
    total_audio_duration_sec FLOAT,

    -- Output
    generated_clips JSONB DEFAULT '[]', -- array of scene_idx, generation_id, storage_path, engine, duration_sec
    final_video_path TEXT,              -- concatenated final video in Supabase storage
    final_video_duration_sec FLOAT,
    total_generation_cost_usd FLOAT,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rec_candidates_brand ON video_recreation_candidates(brand_id);
CREATE INDEX IF NOT EXISTS idx_rec_candidates_status ON video_recreation_candidates(status);
CREATE INDEX IF NOT EXISTS idx_rec_candidates_org ON video_recreation_candidates(organization_id);
CREATE INDEX IF NOT EXISTS idx_rec_candidates_post ON video_recreation_candidates(post_id);
CREATE INDEX IF NOT EXISTS idx_rec_candidates_score ON video_recreation_candidates(composite_score DESC NULLS LAST);

COMMENT ON TABLE video_recreation_candidates IS 'Tracks video recreation candidates through the scoring → adaptation → generation → assembly pipeline';
COMMENT ON COLUMN video_recreation_candidates.composite_score IS 'Weighted score: engagement(0.30) + hook_quality(0.25) + recreation_feasibility(0.25) + avatar_compatibility(0.20)';
COMMENT ON COLUMN video_recreation_candidates.audio_segments IS 'Audio-first workflow: [{scene_idx, audio_storage_path, duration_sec}]';
COMMENT ON COLUMN video_recreation_candidates.generated_clips IS 'Per-scene clips: [{scene_idx, generation_id, storage_path, engine, duration_sec}]';
