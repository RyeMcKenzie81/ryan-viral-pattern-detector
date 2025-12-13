-- SFX Requirements Table
-- Date: 2025-12-13
-- Purpose: Track sound effect requirements for content projects

CREATE TABLE IF NOT EXISTS project_sfx_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    sfx_name TEXT NOT NULL,
    description TEXT NOT NULL,
    script_reference JSONB DEFAULT '[]',
    duration_seconds FLOAT DEFAULT 2.0,
    status TEXT NOT NULL DEFAULT 'needed' CHECK (status IN ('needed', 'generating', 'generated', 'approved', 'rejected', 'skipped')),
    generated_audio_url TEXT,
    storage_path TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast project lookups
CREATE INDEX IF NOT EXISTS idx_sfx_requirements_project ON project_sfx_requirements(project_id);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_sfx_requirements_status ON project_sfx_requirements(status);

COMMENT ON TABLE project_sfx_requirements IS 'Sound effect requirements extracted from content scripts';
COMMENT ON COLUMN project_sfx_requirements.script_reference IS 'JSON array of beat_ids that reference this SFX';
COMMENT ON COLUMN project_sfx_requirements.status IS 'needed=not generated, generating=in progress, generated=ready for review, approved=ready for handoff, rejected=needs regeneration, skipped=editor will handle';
