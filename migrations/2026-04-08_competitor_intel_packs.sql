-- Migration: Competitor Intelligence Packs
-- Date: 2026-04-08
-- Purpose: Stores aggregated ingredient packs from competitor video ad analysis

-- Create competitor_intel_packs table
CREATE TABLE IF NOT EXISTS competitor_intel_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    organization_id UUID NOT NULL,
    pack_data JSONB DEFAULT '{}',
    video_analyses JSONB DEFAULT '[]',
    scoring_metadata JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'complete', 'partial', 'failed')),
    video_count INTEGER NOT NULL DEFAULT 0 CHECK (video_count >= 0),
    videos_completed INTEGER NOT NULL DEFAULT 0 CHECK (videos_completed >= 0),
    error_summary TEXT,
    prompt_version TEXT DEFAULT 'v1',
    model_version TEXT DEFAULT 'gemini-3-pro-preview',
    field_coverage JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE competitor_intel_packs IS 'Aggregated marketing intelligence extracted from competitor video ads';
COMMENT ON COLUMN competitor_intel_packs.pack_data IS 'Aggregated ingredient pack JSON (hooks, personas, angles, benefits, etc.)';
COMMENT ON COLUMN competitor_intel_packs.video_analyses IS 'Array of per-video extraction results';
COMMENT ON COLUMN competitor_intel_packs.scoring_metadata IS 'Composite scoring details for ranked ads';
COMMENT ON COLUMN competitor_intel_packs.field_coverage IS 'Per-field extraction coverage: {field: {populated: N, total: N}}';
COMMENT ON COLUMN competitor_intel_packs.prompt_version IS 'Version of the extraction prompt used';
COMMENT ON COLUMN competitor_intel_packs.model_version IS 'Gemini model version used for extraction';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_competitor_intel_packs_org_competitor
    ON competitor_intel_packs (organization_id, competitor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_intel_packs_status
    ON competitor_intel_packs (status);

-- Add competitor_intel_analysis to scheduled_jobs job_type CHECK constraint
-- First drop existing constraint, then recreate with new value
DO $$
BEGIN
    -- Drop existing CHECK constraint on job_type (name may vary)
    ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;
    ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS valid_job_type;

    -- Recreate with competitor_intel_analysis included
    ALTER TABLE scheduled_jobs ADD CONSTRAINT valid_job_type CHECK (
        job_type IN (
            'ad_creation', 'ad_creation_v2', 'meta_sync', 'scorecard',
            'template_scrape', 'template_approval', 'congruence_reanalysis',
            'ad_classification', 'asset_download', 'competitor_scrape',
            'reddit_scrape', 'amazon_review_scrape', 'creative_genome_update',
            'creative_deep_analysis', 'genome_validation', 'winner_evolution',
            'experiment_analysis', 'quality_calibration', 'ad_intelligence_analysis',
            'analytics_sync', 'seo_status_sync', 'iteration_auto_run',
            'size_variant', 'smart_edit', 'seo_content_eval', 'seo_publish',
            'seo_auto_interlink', 'demographic_backfill', 'seo_opportunity_scan',
            'token_refresh', 'competitor_intel_analysis'
        )
    );
END $$;
