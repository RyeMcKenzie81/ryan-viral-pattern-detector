-- ============================================================================
-- Migration: Content Buckets & Video Categorization
-- Date: 2026-02-18
-- Purpose: Schema for organizing bulk video uploads into user-defined
--          "content buckets" for Facebook ad campaigns. Gemini analyzes
--          each video and maps it to the best-fit bucket.
--
-- Tables:
--   content_buckets              — user-defined bucket definitions per product
--   video_bucket_categorizations — per-video analysis results + bucket mapping
-- ============================================================================


-- ============================================================================
-- content_buckets
-- ============================================================================
CREATE TABLE IF NOT EXISTS content_buckets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    product_id      UUID NOT NULL REFERENCES products(id),

    name            TEXT NOT NULL,
    best_for        TEXT,
    angle           TEXT,
    avatar          TEXT,
    pain_points     JSONB DEFAULT '[]'::jsonb,
    solution_mechanism JSONB DEFAULT '[]'::jsonb,
    key_copy_hooks  JSONB DEFAULT '[]'::jsonb,
    display_order   INTEGER DEFAULT 0,

    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),

    UNIQUE (product_id, name)
);

COMMENT ON TABLE content_buckets IS 'User-defined content buckets for organizing video assets by theme/angle.';
COMMENT ON COLUMN content_buckets.best_for IS 'Description of what types of videos belong in this bucket.';
COMMENT ON COLUMN content_buckets.pain_points IS 'JSON array of pain point strings.';
COMMENT ON COLUMN content_buckets.solution_mechanism IS 'JSON array of solution mechanism strings.';
COMMENT ON COLUMN content_buckets.key_copy_hooks IS 'JSON array of key copy hook strings.';


-- ============================================================================
-- video_bucket_categorizations
-- ============================================================================
CREATE TABLE IF NOT EXISTS video_bucket_categorizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    product_id      UUID NOT NULL REFERENCES products(id),

    bucket_id       UUID REFERENCES content_buckets(id) ON DELETE SET NULL,
    filename        TEXT NOT NULL,
    bucket_name     TEXT,
    confidence_score FLOAT,
    reasoning       TEXT,
    video_summary   TEXT,
    transcript      TEXT,
    analysis_data   JSONB DEFAULT '{}'::jsonb,

    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'analyzed', 'categorized', 'error')),
    error_message   TEXT,
    session_id      UUID NOT NULL,

    created_at      TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE video_bucket_categorizations IS 'Per-video analysis results and bucket assignments from Gemini.';
COMMENT ON COLUMN video_bucket_categorizations.session_id IS 'Groups videos from one upload batch.';
COMMENT ON COLUMN video_bucket_categorizations.bucket_name IS 'Denormalized bucket name for display even if bucket is deleted.';
COMMENT ON COLUMN video_bucket_categorizations.confidence_score IS 'Model confidence 0.0-1.0 in the bucket assignment.';

-- Index for session lookups
CREATE INDEX IF NOT EXISTS idx_video_bucket_cat_session
    ON video_bucket_categorizations(session_id);

-- Index for product + org lookups
CREATE INDEX IF NOT EXISTS idx_video_bucket_cat_product_org
    ON video_bucket_categorizations(product_id, organization_id);

-- Index for bucket lookups on content_buckets
CREATE INDEX IF NOT EXISTS idx_content_buckets_product_org
    ON content_buckets(product_id, organization_id);
