-- Migration: Comic panel audio segments for multi-speaker support
-- Date: 2025-12-09
-- Purpose: Store individual audio segments per speaker with customizable pauses

CREATE TABLE IF NOT EXISTS comic_panel_audio_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES comic_video_projects(id) ON DELETE CASCADE,
    panel_number INT NOT NULL,
    segment_index INT NOT NULL,
    speaker TEXT NOT NULL,
    text_content TEXT NOT NULL,

    -- Voice settings
    voice_id TEXT,
    voice_name TEXT,

    -- Generated audio
    audio_url TEXT,
    duration_ms INT DEFAULT 0,
    pause_after_ms INT DEFAULT 300,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure unique segments per panel
    UNIQUE(project_id, panel_number, segment_index)
);

-- Combined audio for multi-speaker panels
CREATE TABLE IF NOT EXISTS comic_panel_multi_speaker_audio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES comic_video_projects(id) ON DELETE CASCADE,
    panel_number INT NOT NULL,

    -- Combined output
    combined_audio_url TEXT,
    total_duration_ms INT DEFAULT 0,

    -- Approval
    is_approved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- One record per panel per project
    UNIQUE(project_id, panel_number)
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_audio_segments_project_panel
    ON comic_panel_audio_segments(project_id, panel_number);

CREATE INDEX IF NOT EXISTS idx_multi_speaker_audio_project
    ON comic_panel_multi_speaker_audio(project_id);

COMMENT ON TABLE comic_panel_audio_segments IS 'Individual audio segments for multi-speaker panels';
COMMENT ON TABLE comic_panel_multi_speaker_audio IS 'Combined multi-speaker audio with approval status';
COMMENT ON COLUMN comic_panel_audio_segments.speaker IS 'Speaker identifier (e.g., narrator, raccoon)';
COMMENT ON COLUMN comic_panel_audio_segments.pause_after_ms IS 'Pause after this segment (default 300ms)';
