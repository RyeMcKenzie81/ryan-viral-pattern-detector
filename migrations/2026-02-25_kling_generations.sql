-- Migration: Kling video generation tracking
-- Date: 2026-02-25
-- Purpose: Track all Kling AI video generation requests and results.
-- Supports: avatar, text_to_video, image_to_video, identify_face, lip_sync, video_extend, multi_shot.
-- Official API: https://api-singapore.klingai.com

CREATE TABLE kling_video_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    avatar_id UUID REFERENCES brand_avatars(id),
    candidate_id UUID REFERENCES video_recreation_candidates(id),
    parent_generation_id UUID REFERENCES kling_video_generations(id),  -- links lip-sync step 2 to step 1, extend to original

    -- Request
    generation_type TEXT NOT NULL,       -- 'avatar', 'text_to_video', 'image_to_video', 'identify_face', 'lip_sync', 'video_extend', 'multi_shot'
    model_name TEXT,                     -- 'kling-v2-6', etc. (NULL for avatar, identify_face)
    mode TEXT DEFAULT 'std',
    prompt TEXT,
    negative_prompt TEXT,
    input_image_url TEXT,
    input_audio_url TEXT,
    duration TEXT,                       -- STRING: "5" or "10" (matches API)
    aspect_ratio TEXT,
    cfg_scale FLOAT,
    sound TEXT DEFAULT 'off',

    -- Kling task tracking
    kling_task_id TEXT,                  -- Kling's task_id for polling
    kling_external_task_id TEXT,         -- our custom task_id sent to Kling
    kling_request_id TEXT,              -- Kling's request_id for debugging
    status TEXT DEFAULT 'pending',      -- pending, submitted, processing, succeed, failed, awaiting_face_selection, cancelled

    -- Lip-sync specific
    lip_sync_session_id TEXT,           -- session_id from identify-face (valid 24h)
    lip_sync_session_expires_at TIMESTAMPTZ,
    lip_sync_face_id TEXT,             -- selected face_id
    lip_sync_face_data JSONB,          -- full face detection response for UI

    -- Multi-shot specific
    multi_shot_images JSONB,           -- [{index, storage_path, kling_url}]

    -- Result
    video_url TEXT,                     -- Kling CDN output URL (expires in 30 days)
    video_storage_path TEXT,           -- Supabase storage (persistent)
    download_status TEXT DEFAULT 'pending',  -- pending, downloaded, failed
    error_message TEXT,
    error_code INTEGER,                -- Kling error code (1301, 1303, etc.)
    task_status_msg TEXT,             -- Kling's failure reason

    -- Cost
    estimated_cost_usd FLOAT,
    actual_kling_units TEXT,           -- final_unit_deduction from API (string)
    generation_time_seconds FLOAT,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

COMMENT ON TABLE kling_video_generations IS 'Tracks all Kling AI video generation requests and results';
COMMENT ON COLUMN kling_video_generations.generation_type IS 'avatar, text_to_video, image_to_video, identify_face, lip_sync, video_extend, multi_shot';
COMMENT ON COLUMN kling_video_generations.status IS 'pending, submitted, processing, succeed, failed, awaiting_face_selection, cancelled';
COMMENT ON COLUMN kling_video_generations.duration IS 'String value: "5" or "10" (matches Kling API format)';
COMMENT ON COLUMN kling_video_generations.parent_generation_id IS 'Links lip-sync step 2 to step 1, or extend to original generation';
COMMENT ON COLUMN kling_video_generations.video_url IS 'Kling CDN URL, expires after 30 days - download to Supabase immediately';
COMMENT ON COLUMN kling_video_generations.actual_kling_units IS 'final_unit_deduction from Kling API response (string format)';

CREATE INDEX idx_kling_brand ON kling_video_generations(brand_id);
CREATE INDEX idx_kling_org ON kling_video_generations(organization_id);
CREATE INDEX idx_kling_status ON kling_video_generations(status);
CREATE INDEX idx_kling_candidate ON kling_video_generations(candidate_id);
CREATE INDEX idx_kling_task_id ON kling_video_generations(kling_task_id);
CREATE INDEX idx_kling_parent ON kling_video_generations(parent_generation_id);
