-- Migration: Brand Research Pipeline & Template System
-- Date: 2025-12-03
-- Purpose: Add tables for Facebook ad scraping, AI analysis, and template management
-- Branch: feature/brand-research-pipeline
-- Version: 1.1.0 (updated after manual execution)
--
-- NOTE: This migration was run manually in parts due to existing table conflicts.
-- The facebook_ads table already existed - we added missing columns.
-- Renamed ad_templates -> scraped_templates to avoid conflict with existing table.

-- ============================================================================
-- FOUNDATION: Facebook Ads Storage (table already existed, added columns)
-- ============================================================================

-- Add missing columns to existing facebook_ads table
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS brand_id UUID;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS project_id UUID;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_id TEXT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_name TEXT;

-- Add foreign keys (skip if already exist)
-- ALTER TABLE facebook_ads ADD CONSTRAINT fk_facebook_ads_brand FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE SET NULL;
-- ALTER TABLE facebook_ads ADD CONSTRAINT fk_facebook_ads_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_facebook_ads_page ON facebook_ads(page_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_brand ON facebook_ads(brand_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_project ON facebook_ads(project_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_active ON facebook_ads(is_active);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_scraped ON facebook_ads(scraped_at);

-- ============================================================================
-- ASSET STORAGE: Downloaded Images and Videos
-- ============================================================================

CREATE TABLE IF NOT EXISTS scraped_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID REFERENCES facebook_ads(id) ON DELETE CASCADE,
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'video')),
    storage_path TEXT NOT NULL,
    original_url TEXT,
    file_size_bytes INT,
    mime_type TEXT,
    duration_sec FLOAT,
    dimensions JSONB,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    scrape_source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_assets_fb_ad ON scraped_ad_assets(facebook_ad_id);
CREATE INDEX IF NOT EXISTS idx_scraped_assets_brand ON scraped_ad_assets(brand_id);
CREATE INDEX IF NOT EXISTS idx_scraped_assets_type ON scraped_ad_assets(asset_type);

COMMENT ON TABLE scraped_ad_assets IS 'Downloaded images and videos from scraped Facebook ads';

-- Extracted ad copy
CREATE TABLE IF NOT EXISTS scraped_ad_copy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID REFERENCES facebook_ads(id) ON DELETE CASCADE,
    headline TEXT,
    body_text TEXT,
    cta_text TEXT,
    link_description TEXT,
    text_overlays JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_copy_fb_ad ON scraped_ad_copy(facebook_ad_id);

COMMENT ON TABLE scraped_ad_copy IS 'Extracted text/copy from scraped Facebook ads';

-- ============================================================================
-- WORKFLOW A: BRAND RESEARCH (Analysis & Onboarding)
-- ============================================================================

CREATE TABLE IF NOT EXISTS brand_ad_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    asset_id UUID REFERENCES scraped_ad_assets(id) ON DELETE CASCADE,
    facebook_ad_id UUID REFERENCES facebook_ads(id),
    analysis_type TEXT NOT NULL CHECK (analysis_type IN (
        'image_vision', 'video_storyboard', 'copy_analysis', 'synthesis'
    )),
    raw_response JSONB NOT NULL,
    extracted_hooks JSONB,
    extracted_benefits TEXT[],
    extracted_usps TEXT[],
    pain_points TEXT[],
    persona_signals JSONB,
    brand_voice_notes TEXT,
    visual_analysis JSONB,
    model_used TEXT,
    model_version TEXT,
    tokens_used INT,
    cost_usd DECIMAL(10,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brand_analysis_brand ON brand_ad_analysis(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_analysis_asset ON brand_ad_analysis(asset_id);
CREATE INDEX IF NOT EXISTS idx_brand_analysis_type ON brand_ad_analysis(analysis_type);

COMMENT ON TABLE brand_ad_analysis IS 'AI analysis results for scraped ad assets';

-- Consolidated brand research summary
CREATE TABLE IF NOT EXISTS brand_research_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    top_benefits TEXT[],
    top_usps TEXT[],
    common_pain_points TEXT[],
    recommended_hooks JSONB,
    persona_profile JSONB,
    brand_voice_summary TEXT,
    visual_style_guide JSONB,
    total_ads_analyzed INT,
    images_analyzed INT,
    videos_analyzed INT,
    copy_analyzed INT,
    date_range JSONB,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    model_used TEXT,
    UNIQUE(brand_id)
);

CREATE INDEX IF NOT EXISTS idx_research_summary_brand ON brand_research_summary(brand_id);

COMMENT ON TABLE brand_research_summary IS 'Consolidated AI-generated brand insights from ad analysis';

-- ============================================================================
-- WORKFLOW C: TEMPLATE QUEUE (Approval & Creative Library)
-- ============================================================================

CREATE TABLE IF NOT EXISTS template_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID REFERENCES scraped_ad_assets(id) ON DELETE CASCADE,
    facebook_ad_id UUID REFERENCES facebook_ads(id),
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'archived'
    )),
    ai_analysis JSONB,
    ai_quality_score DECIMAL(3,1),
    ai_suggested_category TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    template_category TEXT,
    template_name TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_queue_status ON template_queue(status);
CREATE INDEX IF NOT EXISTS idx_template_queue_asset ON template_queue(asset_id);

COMMENT ON TABLE template_queue IS 'Scraped ads queued for human review before becoming templates';

-- Scraped templates (renamed from ad_templates to avoid conflict)
CREATE TABLE IF NOT EXISTS scraped_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_asset_id UUID REFERENCES scraped_ad_assets(id),
    source_facebook_ad_id UUID REFERENCES facebook_ads(id),
    source_queue_id UUID REFERENCES template_queue(id),
    name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL CHECK (category IN (
        'testimonial', 'quote_card', 'before_after', 'product_showcase',
        'ugc_style', 'meme', 'carousel_frame', 'story_format', 'other'
    )),
    storage_path TEXT NOT NULL,
    thumbnail_path TEXT,
    layout_analysis JSONB,
    color_palette JSONB,
    format_type TEXT,
    canvas_size TEXT,
    recommended_for TEXT[],
    aspect_ratio TEXT,
    times_used INT DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    avg_approval_rate DECIMAL(3,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_templates_category ON scraped_templates(category);
CREATE INDEX IF NOT EXISTS idx_scraped_templates_active ON scraped_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_scraped_templates_times_used ON scraped_templates(times_used DESC);

COMMENT ON TABLE scraped_templates IS 'Approved templates from scraped competitor ads, used for ad generation';

-- ============================================================================
-- PIPELINE STATE PERSISTENCE (for Graph resumption)
-- ============================================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name TEXT NOT NULL,
    state_snapshot JSONB NOT NULL,
    current_node TEXT NOT NULL,
    status TEXT DEFAULT 'running' CHECK (status IN (
        'running', 'paused', 'complete', 'failed'
    )),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    brand_id UUID REFERENCES brands(id),
    initiated_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_name ON pipeline_runs(pipeline_name);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_brand ON pipeline_runs(brand_id);

COMMENT ON TABLE pipeline_runs IS 'Pydantic Graph pipeline state for resumable workflows';

-- ============================================================================
-- AD CREATOR INTEGRATION
-- ============================================================================

ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS source_scraped_template_id UUID REFERENCES scraped_templates(id);
CREATE INDEX IF NOT EXISTS idx_ad_runs_scraped_template ON ad_runs(source_scraped_template_id);

-- ============================================================================
-- HELPFUL VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_pending_templates AS
SELECT
    tq.id as queue_id,
    tq.status,
    tq.ai_quality_score,
    tq.ai_suggested_category,
    tq.created_at as queued_at,
    sa.asset_type,
    sa.storage_path,
    sa.dimensions,
    fa.page_name,
    fa.snapshot
FROM template_queue tq
JOIN scraped_ad_assets sa ON tq.asset_id = sa.id
LEFT JOIN facebook_ads fa ON tq.facebook_ad_id = fa.id
WHERE tq.status = 'pending'
ORDER BY tq.created_at DESC;

CREATE OR REPLACE VIEW v_brand_research_progress AS
SELECT
    b.id as brand_id,
    b.name as brand_name,
    COUNT(DISTINCT fa.id) as total_ads_scraped,
    COUNT(DISTINCT sa.id) as total_assets_downloaded,
    COUNT(DISTINCT CASE WHEN sa.asset_type = 'image' THEN sa.id END) as images,
    COUNT(DISTINCT CASE WHEN sa.asset_type = 'video' THEN sa.id END) as videos,
    COUNT(DISTINCT baa.id) as analyses_complete,
    brs.generated_at as summary_generated_at
FROM brands b
LEFT JOIN facebook_ads fa ON fa.brand_id = b.id
LEFT JOIN scraped_ad_assets sa ON sa.brand_id = b.id
LEFT JOIN brand_ad_analysis baa ON baa.brand_id = b.id
LEFT JOIN brand_research_summary brs ON brs.brand_id = b.id
GROUP BY b.id, b.name, brs.generated_at;

COMMENT ON VIEW v_pending_templates IS 'Templates awaiting human review';
COMMENT ON VIEW v_brand_research_progress IS 'Progress of brand research pipeline by brand';
