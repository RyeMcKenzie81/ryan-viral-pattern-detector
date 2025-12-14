-- ============================================================================
-- Editor Handoffs Migration
-- ============================================================================
-- Purpose: Create table for editor handoff packages
-- Date: 2025-12-12
-- Branch: feature/trash-panda-content-pipeline
-- MVP: 6 (Editor Handoff)
--
-- This table stores generated handoff packages that can be shared with editors.
-- Each handoff contains beat-by-beat breakdown with script, audio, and assets.
-- ============================================================================

-- ============================================================================
-- TABLE: editor_handoffs
-- Stores handoff packages for sharing with video editors
-- ============================================================================

CREATE TABLE IF NOT EXISTS editor_handoffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    -- Package info
    title TEXT NOT NULL,
    brand_name TEXT NOT NULL,

    -- Beat-by-beat data (denormalized for fast loading)
    -- Contains: beat_id, beat_number, beat_name, script_text, visual_notes,
    --           character, audio_url, audio_storage_path, audio_duration_ms,
    --           assets (array), sfx (array), timestamp_start, timestamp_end
    beats_json JSONB NOT NULL,

    -- Summary
    total_duration_ms INT DEFAULT 0,
    full_audio_storage_path TEXT,

    -- Additional metadata
    metadata JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_editor_handoffs_project_id ON editor_handoffs(project_id);
CREATE INDEX idx_editor_handoffs_created_at ON editor_handoffs(created_at DESC);

COMMENT ON TABLE editor_handoffs IS 'Handoff packages for video editors with beat-by-beat breakdown';
COMMENT ON COLUMN editor_handoffs.beats_json IS 'Denormalized beat data for fast loading without joins';
COMMENT ON COLUMN editor_handoffs.metadata IS 'Additional metadata like script_version, beat_count, has_audio, etc.';

-- ============================================================================
-- Add asset_type column to project_asset_requirements if missing
-- (May have been missed in earlier migration)
-- ============================================================================

ALTER TABLE project_asset_requirements
    ADD COLUMN IF NOT EXISTS asset_type TEXT;

COMMENT ON COLUMN project_asset_requirements.asset_type IS 'Asset type: character, prop, background, effect';

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Run these after migration to verify:

-- SELECT
--     table_name,
--     column_name,
--     data_type
-- FROM information_schema.columns
-- WHERE table_name = 'editor_handoffs'
-- ORDER BY ordinal_position;

-- Check handoff count:
-- SELECT COUNT(*) FROM editor_handoffs;
