-- Migration: Lip Sync Jobs + Manual Video Projects
-- Date: 2026-03-05
-- Purpose: Add tables for clip-based lip-sync orchestration and persistent manual video projects

-- ============================================================================
-- Table: lip_sync_jobs
-- ============================================================================

CREATE TABLE IF NOT EXISTS lip_sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),

    -- Input
    original_filename TEXT,
    video_duration_ms INTEGER,
    video_resolution TEXT,

    -- Face detection results
    face_count INTEGER,
    face_data JSONB,              -- [{face_id, start_time, end_time, face_image}]

    -- Clip plan & results
    clip_plan JSONB,              -- {face_clips: [...], gap_clips: [...]}
    face_clip_results JSONB,      -- [{index, face_id, start_ms, end_ms, storage_path, status, generation_id}]
    gap_clip_results JSONB,       -- [{index, start_ms, end_ms, storage_path}]

    -- Final output
    final_video_path TEXT,
    final_video_duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,

    -- Settings used
    original_audio_volume FLOAT DEFAULT 0.0,
    padding_ms INTEGER DEFAULT 500,

    -- Tracking
    total_cost_usd FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    CONSTRAINT lip_sync_jobs_status_check
        CHECK (status IN ('pending', 'normalizing', 'detecting_faces', 'processing_clips', 'reassembling', 'completed', 'failed'))
);

-- Indexes
CREATE INDEX idx_lip_sync_jobs_brand ON lip_sync_jobs(brand_id, created_at DESC);
CREATE INDEX idx_lip_sync_jobs_org ON lip_sync_jobs(organization_id);
CREATE INDEX idx_lip_sync_jobs_status ON lip_sync_jobs(status);

-- RLS
ALTER TABLE lip_sync_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated users full access to lip_sync_jobs"
    ON lip_sync_jobs FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Updated_at trigger (reuses existing function)
CREATE TRIGGER set_updated_at BEFORE UPDATE ON lip_sync_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE lip_sync_jobs IS 'Tracks multi-clip lip sync jobs: face detection, per-clip processing, and reassembly';
COMMENT ON COLUMN lip_sync_jobs.face_data IS 'Face detection results: [{face_id, start_time, end_time, face_image}]';
COMMENT ON COLUMN lip_sync_jobs.clip_plan IS 'Planned clips: {face_clips: [{start_ms, end_ms, face_id}], gap_clips: [{start_ms, end_ms}]}';

-- FK on kling_video_generations to link individual generations back to the job
ALTER TABLE kling_video_generations
    ADD COLUMN IF NOT EXISTS lip_sync_job_id UUID REFERENCES lip_sync_jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_kling_lip_sync_job ON kling_video_generations(lip_sync_job_id)
    WHERE lip_sync_job_id IS NOT NULL;


-- ============================================================================
-- Table: manual_video_projects
-- ============================================================================

CREATE TABLE IF NOT EXISTS manual_video_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),

    -- Metadata
    name TEXT NOT NULL DEFAULT 'Untitled Project',
    status TEXT NOT NULL DEFAULT 'draft',

    -- Settings
    avatar_id UUID REFERENCES brand_avatars(id) ON DELETE SET NULL,
    quality_mode TEXT DEFAULT 'pro',
    aspect_ratio TEXT DEFAULT '9:16',

    -- Content (JSONB - same structure as session state)
    frame_gallery JSONB DEFAULT '[]'::jsonb,
    scenes JSONB DEFAULT '[]'::jsonb,

    -- Output
    final_video_path TEXT,
    final_video_duration_sec FLOAT,

    -- Tracking
    total_generation_cost_usd FLOAT DEFAULT 0.0,
    scene_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT manual_video_projects_status_check
        CHECK (status IN ('draft', 'in_progress', 'completed'))
);

-- Indexes
CREATE INDEX idx_mvp_brand ON manual_video_projects(brand_id, updated_at DESC);
CREATE INDEX idx_mvp_org ON manual_video_projects(organization_id);
CREATE INDEX idx_mvp_status ON manual_video_projects(status);

-- RLS
ALTER TABLE manual_video_projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated users full access to manual_video_projects"
    ON manual_video_projects FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Updated_at trigger
CREATE TRIGGER set_updated_at BEFORE UPDATE ON manual_video_projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE manual_video_projects IS 'Persisted Manual Video Creator projects with scenes, frames, and generation history';
COMMENT ON COLUMN manual_video_projects.frame_gallery IS 'JSONB array: [{id, storage_path, prompt, source}]';
COMMENT ON COLUMN manual_video_projects.scenes IS 'JSONB array: [{id, prompt, dialogue, duration, generations[], ...}]';
