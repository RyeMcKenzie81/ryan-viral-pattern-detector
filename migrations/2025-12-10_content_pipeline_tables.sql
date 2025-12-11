-- ============================================================================
-- Content Pipeline Tables Migration
-- ============================================================================
-- Purpose: Create tables for the Trash Panda Content Pipeline workflow
-- Date: 2025-12-10
-- Branch: feature/trash-panda-content-pipeline
--
-- Tables created:
-- 1. content_projects - Main project tracking with workflow state
-- 2. topic_suggestions - Discovered and evaluated topics
-- 3. script_versions - Version history for full scripts
-- 4. els_versions - ElevenLabs script format versions
-- 5. comic_versions - Condensed comic scripts
-- 6. comic_assets - Visual asset library
-- 7. project_asset_requirements - Assets needed per project
-- 8. project_metadata - SEO metadata for YouTube publishing
--
-- Note: character_voice_profiles already exists in migration_audio_production.sql
-- ============================================================================

-- ============================================================================
-- TABLE 1: content_projects
-- Main project tracking with pydantic-graph workflow state
-- ============================================================================

CREATE TABLE IF NOT EXISTS content_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Topic (populated after selection)
    topic_title TEXT,
    topic_description TEXT,
    topic_score INT CHECK (topic_score >= 0 AND topic_score <= 100),
    topic_reasoning TEXT,
    hook_options JSONB,

    -- Workflow state (pydantic-graph)
    workflow_state TEXT DEFAULT 'topic_discovery',
    workflow_data JSONB,  -- Serialized graph state

    -- Current versions (FKs added after tables exist)
    current_script_version_id UUID,
    current_els_version_id UUID,
    current_comic_version_id UUID,

    -- Links to other systems
    audio_session_id UUID REFERENCES audio_production_sessions(id) ON DELETE SET NULL,

    -- Editor handoff
    public_slug TEXT UNIQUE,
    handoff_created_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_content_projects_brand_id ON content_projects(brand_id);
CREATE INDEX idx_content_projects_workflow_state ON content_projects(workflow_state);
CREATE INDEX idx_content_projects_public_slug ON content_projects(public_slug);

COMMENT ON TABLE content_projects IS 'Main project tracking for content pipeline with workflow state';
COMMENT ON COLUMN content_projects.workflow_state IS 'Current step in pydantic-graph workflow';
COMMENT ON COLUMN content_projects.workflow_data IS 'Serialized pydantic-graph state for resumption';
COMMENT ON COLUMN content_projects.public_slug IS 'Unique slug for public editor handoff page';


-- ============================================================================
-- TABLE 2: topic_suggestions
-- Discovered and evaluated topics (batch of 10-20 per discovery run)
-- ============================================================================

CREATE TABLE IF NOT EXISTS topic_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    title TEXT NOT NULL,
    description TEXT,
    score INT CHECK (score >= 0 AND score <= 100),
    reasoning TEXT,
    hook_options JSONB,  -- Array of hook suggestions

    -- Selection
    is_selected BOOLEAN DEFAULT FALSE,

    -- Quick Approve tracking
    quick_approve_eligible BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_topic_suggestions_project_id ON topic_suggestions(project_id);
CREATE INDEX idx_topic_suggestions_score ON topic_suggestions(score DESC);
CREATE INDEX idx_topic_suggestions_is_selected ON topic_suggestions(is_selected);

COMMENT ON TABLE topic_suggestions IS 'Batch-discovered topics with AI evaluation scores';
COMMENT ON COLUMN topic_suggestions.score IS 'AI evaluation score (0-100), Quick Approve if > 90';
COMMENT ON COLUMN topic_suggestions.quick_approve_eligible IS 'True if score >= 90 threshold';


-- ============================================================================
-- TABLE 3: script_versions
-- Version history for full scripts with revision tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS script_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    version_number INT NOT NULL,

    -- Content
    script_content TEXT NOT NULL,
    storyboard_json JSONB,

    -- Review
    checklist_results JSONB,  -- Bible checklist pass/fail items
    reviewer_notes TEXT,
    improvement_suggestions JSONB,

    -- Approval
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'reviewing', 'revision_requested', 'approved')),
    human_notes TEXT,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,

    -- Quick Approve tracking
    checklist_pass_rate DECIMAL(5,2),  -- Percentage passed
    quick_approve_eligible BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(project_id, version_number)
);

CREATE INDEX idx_script_versions_project_id ON script_versions(project_id);
CREATE INDEX idx_script_versions_status ON script_versions(status);

COMMENT ON TABLE script_versions IS 'Full script versions with bible checklist review results';
COMMENT ON COLUMN script_versions.checklist_pass_rate IS 'Percentage of checklist items passed, Quick Approve if 100%';


-- ============================================================================
-- TABLE 4: els_versions
-- ElevenLabs script format versions
-- ============================================================================

CREATE TABLE IF NOT EXISTS els_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    script_version_id UUID REFERENCES script_versions(id) ON DELETE SET NULL,
    version_number INT NOT NULL,

    els_content TEXT NOT NULL,

    -- Link to audio session (when audio is generated)
    audio_session_id UUID REFERENCES audio_production_sessions(id) ON DELETE SET NULL,

    -- Source type: 'video' for main script, 'comic' for comic-specific audio
    source_type TEXT DEFAULT 'video' CHECK (source_type IN ('video', 'comic')),

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(project_id, version_number, source_type)
);

CREATE INDEX idx_els_versions_project_id ON els_versions(project_id);
CREATE INDEX idx_els_versions_script_version_id ON els_versions(script_version_id);

COMMENT ON TABLE els_versions IS 'ElevenLabs script format for audio production';
COMMENT ON COLUMN els_versions.source_type IS 'video=from main script, comic=from comic panel dialogue';


-- ============================================================================
-- TABLE 5: comic_versions
-- Condensed comic scripts with evaluation
-- ============================================================================

CREATE TABLE IF NOT EXISTS comic_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    script_version_id UUID REFERENCES script_versions(id) ON DELETE SET NULL,
    version_number INT NOT NULL,

    -- Configuration
    target_platform TEXT,  -- instagram, twitter, tiktok
    panel_count INT CHECK (panel_count >= 1 AND panel_count <= 16),
    grid_layout TEXT,  -- e.g., "3x5", "4x4"

    -- Content
    comic_script TEXT NOT NULL,  -- Condensed dialogue per panel
    panel_details JSONB,  -- Array of panel objects with dialogue, characters, etc.

    -- Script Evaluation (clarity, humor, flow)
    evaluation_results JSONB,
    evaluation_notes TEXT,
    evaluation_score INT CHECK (evaluation_score >= 0 AND evaluation_score <= 100),

    -- Image Generation
    comic_image_url TEXT,
    image_generation_prompt TEXT,
    image_evaluation_results JSONB,
    image_evaluation_score INT CHECK (image_evaluation_score >= 0 AND image_evaluation_score <= 100),

    -- Audio (comic-specific ELS)
    comic_els_version_id UUID,  -- FK added after constraint

    -- Final JSON for comic video tool
    comic_json JSONB,

    -- Approval
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'evaluating', 'revision_requested', 'approved', 'generating_image', 'image_review', 'complete')),
    human_notes TEXT,
    approved_at TIMESTAMPTZ,

    -- Quick Approve tracking
    quick_approve_eligible BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(project_id, version_number)
);

CREATE INDEX idx_comic_versions_project_id ON comic_versions(project_id);
CREATE INDEX idx_comic_versions_status ON comic_versions(status);
CREATE INDEX idx_comic_versions_target_platform ON comic_versions(target_platform);

COMMENT ON TABLE comic_versions IS 'Condensed comic scripts with panel layout and evaluation';
COMMENT ON COLUMN comic_versions.evaluation_score IS 'Average of clarity/humor/flow, Quick Approve if all > 85';
COMMENT ON COLUMN comic_versions.image_evaluation_score IS 'Image quality check, must pass 90%+ before human review';


-- ============================================================================
-- TABLE 6: comic_assets
-- Visual asset library (characters, props, backgrounds)
-- ============================================================================

CREATE TABLE IF NOT EXISTS comic_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    asset_type TEXT NOT NULL CHECK (asset_type IN ('character', 'prop', 'background', 'effect')),
    name TEXT NOT NULL,
    description TEXT,
    tags TEXT[],

    -- Generation
    prompt_template TEXT,
    style_suffix TEXT DEFAULT 'flat vector cartoon art, minimal design, thick black outlines, simple geometric shapes, style of Cyanide and Happiness, 2D, high contrast',

    -- Storage (Supabase)
    image_url TEXT,
    thumbnail_url TEXT,

    -- Metadata
    is_core_asset BOOLEAN DEFAULT FALSE,  -- True for main characters, etc.

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, name)
);

CREATE INDEX idx_comic_assets_brand_id ON comic_assets(brand_id);
CREATE INDEX idx_comic_assets_asset_type ON comic_assets(asset_type);
CREATE INDEX idx_comic_assets_tags ON comic_assets USING GIN(tags);

COMMENT ON TABLE comic_assets IS 'Visual asset library shared between video and comic paths';
COMMENT ON COLUMN comic_assets.is_core_asset IS 'True for main characters like Every-Coon, The Fed, etc.';


-- ============================================================================
-- TABLE 7: project_asset_requirements
-- Assets needed per project (matched or to be generated)
-- ============================================================================

CREATE TABLE IF NOT EXISTS project_asset_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    -- Existing asset match
    asset_id UUID REFERENCES comic_assets(id) ON DELETE SET NULL,

    -- For new assets
    asset_name TEXT,
    asset_description TEXT,
    suggested_prompt TEXT,

    -- Script reference
    script_reference TEXT,  -- Where in script this asset is needed

    -- Status
    status TEXT DEFAULT 'needed' CHECK (status IN ('needed', 'matched', 'generating', 'generated', 'approved', 'rejected')),

    -- Generated result
    generated_image_url TEXT,
    human_approved BOOLEAN DEFAULT FALSE,
    rejection_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_project_asset_requirements_project_id ON project_asset_requirements(project_id);
CREATE INDEX idx_project_asset_requirements_asset_id ON project_asset_requirements(asset_id);
CREATE INDEX idx_project_asset_requirements_status ON project_asset_requirements(status);

COMMENT ON TABLE project_asset_requirements IS 'Assets needed per project, matched to library or generated';


-- ============================================================================
-- TABLE 8: project_metadata
-- SEO metadata for YouTube publishing (video and comic paths)
-- ============================================================================

CREATE TABLE IF NOT EXISTS project_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    -- Content type (video or comic)
    content_type TEXT NOT NULL CHECK (content_type IN ('video', 'comic')),

    -- Title options (ranked)
    title_options JSONB,  -- [{rank: 1, title: "...", score: 95, reasoning: "..."}, ...]
    selected_title TEXT,

    -- Description
    description TEXT,
    description_with_timestamps TEXT,

    -- Tags
    tags TEXT[],

    -- Thumbnail
    thumbnail_concepts JSONB,  -- AI-generated concepts based on Derral Eves
    thumbnail_options JSONB,  -- Generated thumbnail URLs with metadata
    selected_thumbnail_url TEXT,

    -- Sizes generated
    thumbnail_16x9_url TEXT,  -- 1280×720 - YouTube landscape
    thumbnail_9x16_url TEXT,  -- 720×1280 - YouTube Shorts

    -- Quick Approve tracking
    top_title_score INT,  -- Score of rank 1 title
    quick_approve_eligible BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(project_id, content_type)
);

CREATE INDEX idx_project_metadata_project_id ON project_metadata(project_id);
CREATE INDEX idx_project_metadata_content_type ON project_metadata(content_type);

COMMENT ON TABLE project_metadata IS 'SEO metadata (titles, descriptions, thumbnails) for YouTube publishing';
COMMENT ON COLUMN project_metadata.top_title_score IS 'Score of rank 1 title, Quick Approve if > 90';


-- ============================================================================
-- ADD FOREIGN KEY CONSTRAINTS (after all tables exist)
-- ============================================================================

-- Add FK from content_projects to version tables
ALTER TABLE content_projects
    ADD CONSTRAINT fk_content_projects_script_version
    FOREIGN KEY (current_script_version_id)
    REFERENCES script_versions(id) ON DELETE SET NULL;

ALTER TABLE content_projects
    ADD CONSTRAINT fk_content_projects_els_version
    FOREIGN KEY (current_els_version_id)
    REFERENCES els_versions(id) ON DELETE SET NULL;

ALTER TABLE content_projects
    ADD CONSTRAINT fk_content_projects_comic_version
    FOREIGN KEY (current_comic_version_id)
    REFERENCES comic_versions(id) ON DELETE SET NULL;

-- Add FK from comic_versions to els_versions
ALTER TABLE comic_versions
    ADD CONSTRAINT fk_comic_versions_els
    FOREIGN KEY (comic_els_version_id)
    REFERENCES els_versions(id) ON DELETE SET NULL;


-- ============================================================================
-- TRIGGER: Auto-update updated_at timestamp
-- ============================================================================

-- Function (reuse if exists, else create)
CREATE OR REPLACE FUNCTION update_content_pipeline_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for tables with updated_at
DROP TRIGGER IF EXISTS update_content_projects_updated_at ON content_projects;
CREATE TRIGGER update_content_projects_updated_at
    BEFORE UPDATE ON content_projects
    FOR EACH ROW EXECUTE FUNCTION update_content_pipeline_updated_at();

DROP TRIGGER IF EXISTS update_comic_assets_updated_at ON comic_assets;
CREATE TRIGGER update_comic_assets_updated_at
    BEFORE UPDATE ON comic_assets
    FOR EACH ROW EXECUTE FUNCTION update_content_pipeline_updated_at();


-- ============================================================================
-- WORKFLOW STATE ENUM (for reference, stored as TEXT)
-- ============================================================================

-- Valid workflow states for content_projects.workflow_state:
--
-- Shared Path:
--   topic_discovery, topic_evaluation, topic_selection,
--   script_generation, script_review, script_approval
--
-- Video Path:
--   els_conversion, audio_production,
--   asset_extraction, asset_matching, asset_generation, asset_review,
--   seo_metadata_generation, metadata_selection,
--   thumbnail_generation, thumbnail_selection,
--   editor_handoff
--
-- Comic Path:
--   comic_condensation, comic_script_evaluation, comic_script_approval,
--   comic_image_generation, comic_image_evaluation, comic_image_review,
--   comic_audio_script, comic_audio_review,
--   comic_json_conversion, comic_video,
--   comic_seo_metadata, comic_metadata_selection,
--   comic_thumbnail_generation, comic_thumbnail_selection
--
-- Terminal:
--   completed, error


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Run these after migration to verify:

-- SELECT
--     table_name,
--     column_name,
--     data_type
-- FROM information_schema.columns
-- WHERE table_name IN (
--     'content_projects', 'topic_suggestions', 'script_versions',
--     'els_versions', 'comic_versions', 'comic_assets',
--     'project_asset_requirements', 'project_metadata'
-- )
-- ORDER BY table_name, ordinal_position;

-- Check FK relationships:
-- SELECT
--     tc.table_name,
--     kcu.column_name,
--     ccu.table_name AS foreign_table_name,
--     ccu.column_name AS foreign_column_name
-- FROM information_schema.table_constraints AS tc
-- JOIN information_schema.key_column_usage AS kcu
--     ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--     ON ccu.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
-- AND tc.table_name LIKE '%content%' OR tc.table_name LIKE '%comic%' OR tc.table_name LIKE '%topic%';
