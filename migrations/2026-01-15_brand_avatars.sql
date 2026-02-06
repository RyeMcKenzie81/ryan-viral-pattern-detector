-- Migration: Brand Avatars for Veo Video Generation
-- Date: 2026-01-15
-- Purpose: Store avatar configurations and generated videos for brands

-- Brand avatars table - stores avatar characters linked to brands
CREATE TABLE IF NOT EXISTS brand_avatars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Reference images for character consistency (up to 3 stored in Supabase Storage)
    reference_image_1 TEXT,  -- Storage path: avatars/{brand_id}/{avatar_id}/ref1.png
    reference_image_2 TEXT,  -- Storage path
    reference_image_3 TEXT,  -- Storage path

    -- Avatar generation prompt used to create this character via Nano Banana/Gemini
    generation_prompt TEXT,

    -- Style settings for video generation
    default_negative_prompt TEXT DEFAULT 'blurry, low quality, distorted, deformed, ugly, bad anatomy',
    default_aspect_ratio VARCHAR(10) DEFAULT '16:9',  -- 16:9 or 9:16
    default_resolution VARCHAR(10) DEFAULT '1080p',    -- 720p, 1080p, 4k
    default_duration_seconds INTEGER DEFAULT 8,        -- 4, 6, or 8

    -- Metadata
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient brand lookups
CREATE INDEX IF NOT EXISTS idx_brand_avatars_brand_id ON brand_avatars(brand_id);

-- Veo video generations table - stores generated videos
CREATE TABLE IF NOT EXISTS veo_video_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    avatar_id UUID REFERENCES brand_avatars(id) ON DELETE SET NULL,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,

    -- Video prompt and settings
    prompt TEXT NOT NULL,
    action_description TEXT,  -- What the avatar should do
    dialogue TEXT,            -- What the avatar should say
    background_description TEXT,  -- Background scene description

    -- Generation settings
    aspect_ratio VARCHAR(10) NOT NULL DEFAULT '16:9',
    resolution VARCHAR(10) NOT NULL DEFAULT '1080p',
    duration_seconds INTEGER NOT NULL DEFAULT 8,
    negative_prompt TEXT,
    seed INTEGER,  -- For reproducibility

    -- Reference images used (can include product images)
    reference_images JSONB DEFAULT '[]'::jsonb,  -- Array of storage paths

    -- Model info
    model_name VARCHAR(100) DEFAULT 'veo-3.1-generate-preview',
    model_variant VARCHAR(50) DEFAULT 'standard',  -- standard or fast

    -- Output
    video_storage_path TEXT,  -- Storage path for generated video
    thumbnail_storage_path TEXT,  -- Auto-generated thumbnail

    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',  -- pending, generating, completed, failed
    error_message TEXT,

    -- Cost tracking
    generation_time_seconds NUMERIC(10,2),
    estimated_cost_usd NUMERIC(10,4),  -- Based on duration * rate

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_veo_generations_brand_id ON veo_video_generations(brand_id);
CREATE INDEX IF NOT EXISTS idx_veo_generations_avatar_id ON veo_video_generations(avatar_id);
CREATE INDEX IF NOT EXISTS idx_veo_generations_status ON veo_video_generations(status);
CREATE INDEX IF NOT EXISTS idx_veo_generations_created_at ON veo_video_generations(created_at DESC);

-- Comments for documentation
COMMENT ON TABLE brand_avatars IS 'Avatar characters for brands, used with Veo 3.1 for video generation';
COMMENT ON COLUMN brand_avatars.reference_image_1 IS 'Primary reference image for character consistency';
COMMENT ON COLUMN brand_avatars.generation_prompt IS 'Prompt used to generate avatar via Gemini (Nano Banana)';

COMMENT ON TABLE veo_video_generations IS 'Generated videos using Google Veo 3.1 API';
COMMENT ON COLUMN veo_video_generations.reference_images IS 'Array of up to 3 image paths for character/product consistency';
COMMENT ON COLUMN veo_video_generations.model_variant IS 'standard ($0.40/sec) or fast ($0.15/sec)';

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_brand_avatars_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS brand_avatars_updated_at ON brand_avatars;
CREATE TRIGGER brand_avatars_updated_at
    BEFORE UPDATE ON brand_avatars
    FOR EACH ROW
    EXECUTE FUNCTION update_brand_avatars_updated_at();
