-- Migration: Quick URL Competitor Intel
-- Date: 2026-05-06
-- Purpose: Extends competitor_intel_packs to support "Quick URL" mode (single FB
-- video URL or upload, no competitor required). Also registers the new
-- quick_intel_analysis worker job type.

-- 1. Allow packs to exist without a competitor (Quick URL / Quick Upload packs)
ALTER TABLE competitor_intel_packs
    ALTER COLUMN competitor_id DROP NOT NULL;

-- 2. Provenance + per-pack source video storage path
ALTER TABLE competitor_intel_packs
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'competitor'
        CHECK (source_type IN ('competitor', 'quick_url', 'quick_upload')),
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_video_storage_path TEXT;

COMMENT ON COLUMN competitor_intel_packs.source_type IS
    'Pack provenance: competitor (existing flow), quick_url (yt-dlp from FB URL), quick_upload (user-uploaded file)';
COMMENT ON COLUMN competitor_intel_packs.source_url IS
    'Canonicalized FB URL for quick_url packs; null otherwise';
COMMENT ON COLUMN competitor_intel_packs.source_video_storage_path IS
    'Supabase storage path for the single video in quick packs; null for competitor packs (which reference competitor_ad_assets)';

-- 3. Indexes
-- For listing quick packs separately and dup-URL lookups
CREATE INDEX IF NOT EXISTS idx_competitor_intel_packs_source_type
    ON competitor_intel_packs (organization_id, source_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_intel_packs_source_url
    ON competitor_intel_packs (organization_id, source_url)
    WHERE source_url IS NOT NULL;

-- Concurrency guard: prevent two simultaneous resolves of the same URL.
-- Allows multiple complete rows over time (intentional re-runs);
-- only blocks two rows being 'pending' on the same URL at once.
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_intel_packs_pending_url
    ON competitor_intel_packs (organization_id, source_url)
    WHERE source_url IS NOT NULL AND status = 'pending';

-- 4. Register quick_intel_analysis as a valid scheduled_jobs.job_type
DO $$
BEGIN
    ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;
    ALTER TABLE scheduled_jobs DROP CONSTRAINT IF EXISTS valid_job_type;

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
            'token_refresh', 'competitor_intel_analysis', 'quick_intel_analysis'
        )
    );
END $$;
