-- Create product_scripts table for storing script versions and iterations
-- Enables tracking of AI-generated scripts and manual revisions

CREATE TABLE IF NOT EXISTS product_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relationships
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    source_video_id UUID REFERENCES posts(id) ON DELETE SET NULL,
    video_analysis_id UUID REFERENCES video_analysis(id) ON DELETE SET NULL,
    parent_script_id UUID REFERENCES product_scripts(id) ON DELETE SET NULL,

    -- Script metadata
    title VARCHAR(255) NOT NULL,
    description TEXT,
    script_type VARCHAR(50) DEFAULT 'adaptation', -- 'adaptation', 'original', 'revision'
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'review', 'approved', 'produced', 'published'

    -- Script content
    script_content TEXT NOT NULL, -- Full script text
    script_structure JSONB, -- Structured breakdown (scenes, hooks, transitions)

    -- Production details
    estimated_duration_sec INTEGER, -- Target video duration
    production_difficulty VARCHAR(20), -- 'easy', 'medium', 'hard'
    required_props JSONB, -- List of props/items needed
    required_locations JSONB, -- List of locations/settings
    talent_requirements TEXT, -- Who needs to be in the video

    -- AI generation details
    generated_by_ai BOOLEAN DEFAULT false,
    ai_model VARCHAR(100), -- e.g., 'gemini-flash-latest'
    ai_prompt TEXT, -- Prompt used for generation
    ai_generation_params JSONB, -- Temperature, etc.

    -- Viral pattern tracking
    source_viral_patterns JSONB, -- What patterns from source video are being adapted
    target_viral_score FLOAT, -- Predicted/target viral score

    -- Version control
    version_number INTEGER DEFAULT 1,
    version_notes TEXT,
    is_current_version BOOLEAN DEFAULT true,

    -- Performance tracking (if produced)
    produced_post_id UUID REFERENCES posts(id) ON DELETE SET NULL,
    actual_views INTEGER,
    actual_engagement_rate FLOAT,
    performance_vs_prediction JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT valid_script_type CHECK (script_type IN ('adaptation', 'original', 'revision', 'iteration')),
    CONSTRAINT valid_status CHECK (status IN ('draft', 'review', 'approved', 'in_production', 'produced', 'published', 'archived')),
    CONSTRAINT valid_difficulty CHECK (production_difficulty IN ('easy', 'medium', 'hard'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_product_scripts_product_id ON product_scripts(product_id);
CREATE INDEX IF NOT EXISTS idx_product_scripts_brand_id ON product_scripts(brand_id);
CREATE INDEX IF NOT EXISTS idx_product_scripts_source_video ON product_scripts(source_video_id);
CREATE INDEX IF NOT EXISTS idx_product_scripts_video_analysis ON product_scripts(video_analysis_id);
CREATE INDEX IF NOT EXISTS idx_product_scripts_parent ON product_scripts(parent_script_id);
CREATE INDEX IF NOT EXISTS idx_product_scripts_status ON product_scripts(status);
CREATE INDEX IF NOT EXISTS idx_product_scripts_current_version ON product_scripts(is_current_version) WHERE is_current_version = true;
CREATE INDEX IF NOT EXISTS idx_product_scripts_created_at ON product_scripts(created_at DESC);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_product_scripts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS product_scripts_updated_at ON product_scripts;
CREATE TRIGGER product_scripts_updated_at
    BEFORE UPDATE ON product_scripts
    FOR EACH ROW
    EXECUTE FUNCTION update_product_scripts_updated_at();

-- Comments
COMMENT ON TABLE product_scripts IS 'Stores script versions for product videos, including AI-generated adaptations and manual revisions';
COMMENT ON COLUMN product_scripts.parent_script_id IS 'References previous version if this is a revision';
COMMENT ON COLUMN product_scripts.script_structure IS 'JSON structure: {scenes: [{hook, body, cta, duration_sec, visual_notes}]}';
COMMENT ON COLUMN product_scripts.source_viral_patterns IS 'JSON array of viral patterns being adapted from source video';

-- Example script_structure:
-- {
--   "scenes": [
--     {
--       "scene_number": 1,
--       "type": "hook",
--       "duration_sec": 5,
--       "script_text": "POV: You're trying to get your kid off Fortnite...",
--       "visual_notes": "Parent looking frustrated at camera, text overlay appears",
--       "audio_notes": "Upbeat trending audio"
--     },
--     {
--       "scene_number": 2,
--       "type": "problem",
--       "duration_sec": 10,
--       "script_text": "But they just won't listen...",
--       "visual_notes": "Quick cuts of typical arguments",
--       "audio_notes": "Audio continues"
--     }
--   ],
--   "transitions": ["cut", "fade"],
--   "text_overlays": ["Screen time = war zone", "Until I discovered this..."]
-- }

-- Example source_viral_patterns:
-- [
--   {"pattern": "POV format", "effectiveness_score": 9.0},
--   {"pattern": "Problem-solution narrative", "effectiveness_score": 8.5},
--   {"pattern": "Relatable parent frustration", "effectiveness_score": 9.0}
-- ]
