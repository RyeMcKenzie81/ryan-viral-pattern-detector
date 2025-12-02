-- =====================================================
-- AUDIO PRODUCTION WORKFLOW SCHEMA
-- Version: 1.0
-- Date: 2025-12-01
-- =====================================================

-- Character voice profiles
-- Stores ElevenLabs voice IDs and default settings per character
CREATE TABLE IF NOT EXISTS character_voice_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    character VARCHAR(50) NOT NULL UNIQUE,
    voice_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    stability FLOAT DEFAULT 0.35 CHECK (stability >= 0 AND stability <= 1),
    similarity_boost FLOAT DEFAULT 0.78 CHECK (similarity_boost >= 0 AND similarity_boost <= 1),
    style FLOAT DEFAULT 0.45 CHECK (style >= 0 AND style <= 1),
    speed FLOAT DEFAULT 1.0 CHECK (speed >= 0.7 AND speed <= 1.2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Production sessions
CREATE TABLE IF NOT EXISTS audio_production_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_title VARCHAR(255) NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'generating', 'in_progress', 'completed', 'exported')),
    source_els TEXT,
    beats_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual audio takes
CREATE TABLE IF NOT EXISTS audio_takes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES audio_production_sessions(id) ON DELETE CASCADE,
    beat_id VARCHAR(100) NOT NULL,
    audio_path VARCHAR(500) NOT NULL,
    audio_duration_ms INT,
    settings_json JSONB NOT NULL,
    direction_used TEXT,
    is_selected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audio_sessions_project ON audio_production_sessions(project_name);
CREATE INDEX IF NOT EXISTS idx_audio_sessions_status ON audio_production_sessions(status);
CREATE INDEX IF NOT EXISTS idx_audio_takes_session ON audio_takes(session_id);
CREATE INDEX IF NOT EXISTS idx_audio_takes_session_beat ON audio_takes(session_id, beat_id);

-- =====================================================
-- SEED DATA: Trash Panda character profiles
-- All use same voice ID with different settings
-- Voice ID: BRruTxiLM2nszrcCIpz1
-- =====================================================

INSERT INTO character_voice_profiles
(character, voice_id, display_name, description, stability, similarity_boost, style, speed)
VALUES
(
    'every-coon',
    'BRruTxiLM2nszrcCIpz1',
    'Every-Coon',
    'Main narrator. Deadpan curious raccoon. Confused but trying. Caveman speech pattern.',
    0.35, 0.78, 0.45, 1.0
),
(
    'boomer',
    'BRruTxiLM2nszrcCIpz1',
    'Boomer',
    'Old raccoon. Slow, grumbly, nostalgic. Slightly condescending.',
    0.50, 0.78, 0.30, 0.85
),
(
    'fed',
    'BRruTxiLM2nszrcCIpz1',
    'Fed',
    'Federal Reserve raccoon. Monotone, bureaucratic, completely detached.',
    0.65, 0.78, 0.20, 0.70
),
(
    'whale',
    'BRruTxiLM2nszrcCIpz1',
    'Whale',
    'Big money raccoon. Deep, confident, slightly menacing.',
    0.40, 0.78, 0.50, 0.95
),
(
    'wojak',
    'BRruTxiLM2nszrcCIpz1',
    'Wojak',
    'Panic raccoon. Whiny, panicked, defeated. Always losing.',
    0.30, 0.78, 0.60, 1.10
),
(
    'chad',
    'BRruTxiLM2nszrcCIpz1',
    'Chad',
    'Overconfident raccoon. Fast-talking, uses crypto slang. WAGMI energy.',
    0.40, 0.78, 0.55, 1.05
)
ON CONFLICT (character) DO UPDATE SET
    voice_id = EXCLUDED.voice_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    stability = EXCLUDED.stability,
    similarity_boost = EXCLUDED.similarity_boost,
    style = EXCLUDED.style,
    speed = EXCLUDED.speed,
    updated_at = NOW();

-- =====================================================
-- TRIGGER: Auto-update updated_at timestamp
-- =====================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_audio_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_voice_profiles_updated_at ON character_voice_profiles;
CREATE TRIGGER update_voice_profiles_updated_at
    BEFORE UPDATE ON character_voice_profiles
    FOR EACH ROW EXECUTE FUNCTION update_audio_updated_at_column();

DROP TRIGGER IF EXISTS update_audio_sessions_updated_at ON audio_production_sessions;
CREATE TRIGGER update_audio_sessions_updated_at
    BEFORE UPDATE ON audio_production_sessions
    FOR EACH ROW EXECUTE FUNCTION update_audio_updated_at_column();

-- =====================================================
-- STORAGE BUCKET (Run in Supabase Dashboard if needed)
-- =====================================================
-- Create bucket: audio-production
-- Settings: Public bucket, 50MB max file size
-- Allowed MIME types: audio/mpeg, audio/mp3
