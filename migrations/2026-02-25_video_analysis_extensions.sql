-- Migration: Extend ad_video_analysis for Instagram content + create image analysis table
-- Date: 2026-02-25
-- Purpose: Generalize ad_video_analysis to support Instagram scraped content
--          (not just Meta ads), add production storyboard fields for Pass 2,
--          and create instagram_image_analysis for image/carousel posts.

-- ============================================================================
-- 1. Extend ad_video_analysis: source_type + source_post_id
-- ============================================================================

-- Source type: 'meta_ad' (existing), 'instagram_scrape' (new), 'upload' (future)
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'meta_ad';

COMMENT ON COLUMN ad_video_analysis.source_type IS
'Source of the analyzed video: meta_ad, instagram_scrape, upload';

-- Link to posts table for Instagram-scraped content
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS source_post_id UUID REFERENCES posts(id);

COMMENT ON COLUMN ad_video_analysis.source_post_id IS
'FK to posts table when source_type=instagram_scrape';

CREATE INDEX IF NOT EXISTS idx_video_analysis_source_post
    ON ad_video_analysis(source_post_id) WHERE source_post_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_video_analysis_source_type
    ON ad_video_analysis(source_type);

-- ============================================================================
-- 2. Extend ad_video_analysis: production storyboard (Pass 2)
-- ============================================================================

-- Detailed per-beat production shot sheet from Gemini Pro analysis
ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS production_storyboard JSONB;

COMMENT ON COLUMN ad_video_analysis.production_storyboard IS
'Pass 2 production shot sheet: per-beat camera_shot_type, camera_movement, camera_angle, subject_action, subject_emotion, lighting, transition, pacing, duration_sec';

-- ============================================================================
-- 3. Extend ad_video_analysis: people detection
-- ============================================================================

ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS people_detected INTEGER DEFAULT 0;

COMMENT ON COLUMN ad_video_analysis.people_detected IS
'Number of distinct people detected in the video';

ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS has_talking_head BOOLEAN DEFAULT false;

COMMENT ON COLUMN ad_video_analysis.has_talking_head IS
'Whether the video features a talking-head format (person speaking to camera)';

-- ============================================================================
-- 4. Extend ad_video_analysis: eval scores (VA-1 through VA-8)
-- ============================================================================

ALTER TABLE ad_video_analysis
ADD COLUMN IF NOT EXISTS eval_scores JSONB;

COMMENT ON COLUMN ad_video_analysis.eval_scores IS
'Automated consistency check scores: VA-1 duration, VA-2 transcript, VA-3 storyboard coverage, VA-4 timestamp monotonicity, VA-5 segment coverage, VA-6 hook window, VA-7 JSON completeness, VA-8 overlay coherence. Overall score 0.0-1.0.';

-- ============================================================================
-- 5. Relax UNIQUE constraint for Instagram content (meta_ad_id can be NULL)
-- ============================================================================

-- Make meta_ad_id nullable for Instagram-sourced analyses
ALTER TABLE ad_video_analysis ALTER COLUMN meta_ad_id DROP NOT NULL;

-- Add partial unique index for Instagram-sourced analyses
CREATE UNIQUE INDEX IF NOT EXISTS idx_video_analysis_post_version_hash
    ON ad_video_analysis(source_post_id, prompt_version, input_hash)
    WHERE source_post_id IS NOT NULL;

-- ============================================================================
-- 6. Create instagram_image_analysis table
-- ============================================================================

CREATE TABLE IF NOT EXISTS instagram_image_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    post_id UUID NOT NULL REFERENCES posts(id),
    media_id UUID REFERENCES instagram_media(id),

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'analyzing', 'ok', 'error')),
    error_message TEXT,

    -- Image analysis fields
    image_description TEXT,
    image_style TEXT,                    -- art style, color palette, composition
    image_elements JSONB,               -- [{element, position, description}]
    image_text_content TEXT,             -- text visible in the image
    recreation_notes TEXT,               -- notes for recreating this image

    -- Person detection
    people_detected INTEGER DEFAULT 0,
    has_talking_head BOOLEAN DEFAULT false,
    people_details JSONB,                -- [{description, position, emotion, action}]

    -- Versioning (immutable rows, same pattern as ad_video_analysis)
    model_used TEXT,
    prompt_version TEXT DEFAULT 'v1',
    input_hash TEXT,
    raw_response JSONB,

    -- Eval scores
    eval_scores JSONB,

    -- Timestamps
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Unique per post+media+version+hash
    UNIQUE(post_id, media_id, prompt_version, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_ig_image_analysis_post
    ON instagram_image_analysis(post_id);
CREATE INDEX IF NOT EXISTS idx_ig_image_analysis_org
    ON instagram_image_analysis(organization_id);
CREATE INDEX IF NOT EXISTS idx_ig_image_analysis_status
    ON instagram_image_analysis(status) WHERE status != 'ok';

COMMENT ON TABLE instagram_image_analysis IS
'Image analysis results for Instagram image/carousel posts. Immutable versioned rows.';
COMMENT ON COLUMN instagram_image_analysis.input_hash IS
'SHA256 of storage_path + file metadata for change detection';
COMMENT ON COLUMN instagram_image_analysis.eval_scores IS
'Automated consistency check scores for image analysis quality';
