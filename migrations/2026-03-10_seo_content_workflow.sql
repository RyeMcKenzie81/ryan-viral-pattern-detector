-- Migration: SEO Content Workflow
-- Date: 2026-03-10
-- Purpose: Add seo_brand_config (per-brand content generation config) and
--          seo_workflow_jobs (async pipeline execution tracking)

-- seo_brand_config: Per-brand SEO content generation configuration
CREATE TABLE IF NOT EXISTS seo_brand_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    content_style_guide TEXT,          -- Writing instructions with GOOD/BAD voice examples
    available_tags JSONB DEFAULT '[]', -- [{slug, name, description, selection_rule}]
    image_style TEXT,                  -- Photography style prompt for image generation
    product_mention_rules TEXT,        -- Dos/don'ts for product references
    max_product_mentions INT DEFAULT 2,
    default_author_id UUID REFERENCES seo_authors(id) ON DELETE SET NULL,
    schema_publisher JSONB,            -- {name, logo_url} for schema.org
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id)
);

COMMENT ON TABLE seo_brand_config IS 'Per-brand SEO content generation configuration (style, tags, images)';

-- seo_workflow_jobs: Track async pipeline execution
CREATE TABLE IF NOT EXISTS seo_workflow_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    job_type TEXT NOT NULL CHECK (job_type IN ('one_off', 'cluster_batch')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed', 'cancelled')),
    progress JSONB DEFAULT '{}',
    config JSONB DEFAULT '{}',
    result JSONB DEFAULT '{}',
    error TEXT,
    paused_at TIMESTAMPTZ,             -- When step-through paused (for timeout detection)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE seo_workflow_jobs IS 'Async SEO content workflow jobs with progress, pause/resume, cancellation';
CREATE INDEX IF NOT EXISTS idx_seo_workflow_jobs_brand ON seo_workflow_jobs(brand_id);
CREATE INDEX IF NOT EXISTS idx_seo_workflow_jobs_status ON seo_workflow_jobs(status);
CREATE INDEX IF NOT EXISTS idx_seo_workflow_jobs_active ON seo_workflow_jobs(brand_id, status)
    WHERE status IN ('pending', 'running', 'paused');
CREATE INDEX IF NOT EXISTS idx_seo_workflow_jobs_org ON seo_workflow_jobs(organization_id, status);

-- Prevent duplicate running one_off jobs for same keyword+brand (race-condition-safe dedup)
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_workflow_jobs_dedup_keyword
    ON seo_workflow_jobs(brand_id, (config->>'keyword'))
    WHERE status IN ('pending', 'running', 'paused') AND job_type = 'one_off';

-- Prevent duplicate running cluster_batch jobs for same cluster+brand
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_workflow_jobs_dedup_cluster
    ON seo_workflow_jobs(brand_id, (config->>'cluster_id'))
    WHERE status IN ('pending', 'running', 'paused') AND job_type = 'cluster_batch';
