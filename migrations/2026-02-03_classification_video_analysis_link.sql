-- Migration: Add video_analysis_id and congruence_components to ad_creative_classifications
-- Date: 2026-02-03
-- Purpose: Link classifications to deep video analysis and store per-dimension congruence results.

-- Add video_analysis_id FK to link classification to deep video analysis
ALTER TABLE ad_creative_classifications
ADD COLUMN IF NOT EXISTS video_analysis_id UUID REFERENCES ad_video_analysis(id) ON DELETE SET NULL;

-- Add congruence_components for per-dimension evaluation results
-- Schema: [{"dimension": "benefits_match", "assessment": "weak|aligned|missing", "explanation": "...", "suggestion": "..."}]
ALTER TABLE ad_creative_classifications
ADD COLUMN IF NOT EXISTS congruence_components JSONB DEFAULT '[]';

-- Index for finding classifications with video analysis
CREATE INDEX IF NOT EXISTS idx_acc_video_analysis
    ON ad_creative_classifications(video_analysis_id) WHERE video_analysis_id IS NOT NULL;

COMMENT ON COLUMN ad_creative_classifications.video_analysis_id IS 'FK to ad_video_analysis for deep video analysis results';
COMMENT ON COLUMN ad_creative_classifications.congruence_components IS 'Per-dimension congruence evaluation: [{dimension, assessment, explanation, suggestion}]';
