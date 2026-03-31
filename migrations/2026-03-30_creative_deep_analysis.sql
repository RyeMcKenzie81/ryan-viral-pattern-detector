-- Migration: Create ad_image_analysis and creative_performance_correlations tables
-- Date: 2026-03-30
-- Purpose: Phase 2 of Strategic Leverage Engine — Gemini deep analysis for all ad
--          creatives (images and videos) and performance correlation engine.
-- VERIFIED: No naming collisions with existing tables.

-- =============================================================================
-- 1. ad_image_analysis — Deep image analysis results from Gemini
-- =============================================================================
-- Parallel to ad_video_analysis but for static image ads.
-- Extracts messaging, persona signals, emotional tone, and visual style.

CREATE TABLE IF NOT EXISTS ad_image_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,

    -- Versioning (immutable history, same pattern as ad_video_analysis)
    input_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT 'v1',

    -- Status & Error handling
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error')),
    error_message TEXT,

    -- Messaging extraction
    messaging_theme TEXT,              -- Core message/proposition of the ad
    emotional_tone TEXT[],             -- fear, aspiration, urgency, empathy, humor, curiosity, etc.
    hook_pattern TEXT,                 -- question, statement, testimonial, statistic, story, before_after
    cta_style TEXT,                    -- direct, soft, curiosity, none
    benefits_shown TEXT[],
    pain_points_addressed TEXT[],
    claims_made JSONB,                 -- [{claim: str, proof_shown: bool}]

    -- Text extracted from image
    headline_text TEXT,                -- Primary headline/text overlay
    body_text TEXT,                    -- Secondary text
    text_overlays JSONB DEFAULT '[]',  -- [{text: str, position: str, style: str}]

    -- People in the ad
    people_in_ad JSONB DEFAULT '[]',   -- [{role: str, age_range: str, gender: str, description: str}]
    -- role: spokesperson, customer_testimonial, lifestyle_model, ugc_creator, founder, expert, none
    -- age_range: 18-24, 25-34, 35-44, 45-54, 55-64, 65+
    -- gender: male, female, non_binary, unclear

    -- Persona & targeting signals
    target_persona_signals JSONB,      -- {age_group, gender_signals, pain_points, aspirations, lifestyle}

    -- Visual style
    visual_style JSONB,                -- {color_mood, imagery_type, setting, production_quality, composition}
    -- color_mood: warm, cool, neutral, vibrant, muted, dark
    -- imagery_type: product_hero, lifestyle, before_after, infographic, testimonial_card, ugc
    -- setting: studio, home, outdoor, office, gym, kitchen, etc.
    -- production_quality: raw, polished, professional
    -- composition: centered, rule_of_thirds, text_heavy, image_heavy, split

    -- Psychology
    awareness_level TEXT CHECK (awareness_level IN
        ('unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware')),
    awareness_confidence NUMERIC(3,2),

    -- Provenance
    raw_analysis JSONB,                -- Full Gemini response for future mining
    model_used TEXT,
    source_url TEXT,                   -- Image URL or storage path used

    -- Timestamps
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique per version+hash
    UNIQUE(meta_ad_id, brand_id, prompt_version, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_image_analysis_brand_ad
    ON ad_image_analysis(brand_id, meta_ad_id, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_image_analysis_brand_version
    ON ad_image_analysis(brand_id, prompt_version);

COMMENT ON TABLE ad_image_analysis IS 'Deep image ad analysis from Gemini. Extracts messaging themes, persona signals, emotional tone, people in ad, and visual style. Immutable, versioned rows.';
COMMENT ON COLUMN ad_image_analysis.input_hash IS 'SHA256 of image URL/path for change detection and dedup';
COMMENT ON COLUMN ad_image_analysis.people_in_ad IS 'Array of people visible in the ad with role (ugc_creator, testimonial, etc.), age_range, gender';
COMMENT ON COLUMN ad_image_analysis.raw_analysis IS 'Full Gemini JSON response preserved for future field extraction';

-- =============================================================================
-- 2. creative_performance_correlations — Computed correlation insights
-- =============================================================================
-- Stores aggregated correlations between creative analysis fields and performance.
-- Recomputed periodically by CreativeCorrelationService.

CREATE TABLE IF NOT EXISTS creative_performance_correlations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- What was correlated
    analysis_field TEXT NOT NULL,       -- e.g., "emotional_tone", "hook_pattern", "people_role"
    field_value TEXT NOT NULL,          -- e.g., "empathy", "testimonial", "ugc_creator"
    source_table TEXT NOT NULL,         -- "ad_image_analysis" or "ad_video_analysis"

    -- Sample
    ad_count INTEGER NOT NULL,
    meta_ad_ids TEXT[],                 -- Ads in this group (for drill-down)

    -- Performance metrics
    mean_reward FLOAT,
    mean_ctr FLOAT,
    mean_conv_rate FLOAT,
    mean_roas FLOAT,
    mean_cpa FLOAT,

    -- Relative performance
    vs_account_avg FLOAT,              -- Multiplier vs account average (1.0 = average, 2.3 = 2.3x better)
    confidence FLOAT NOT NULL,         -- 0-1 based on sample size

    -- Timestamps
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    -- One row per field+value+source per brand (recomputed in place)
    UNIQUE(brand_id, analysis_field, field_value, source_table)
);

CREATE INDEX IF NOT EXISTS idx_correlations_brand_confidence
    ON creative_performance_correlations(brand_id, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_correlations_brand_field
    ON creative_performance_correlations(brand_id, analysis_field);

COMMENT ON TABLE creative_performance_correlations IS 'Aggregated correlations between creative analysis fields (tone, hook, persona) and ad performance. Recomputed periodically.';
COMMENT ON COLUMN creative_performance_correlations.vs_account_avg IS 'Performance multiplier vs account average. 2.3 means this field value performs 2.3x better than average.';
COMMENT ON COLUMN creative_performance_correlations.confidence IS '0-1 based on sample size. Higher = more reliable. Minimum threshold for leverage moves is 0.3.';

-- =============================================================================
-- 3. Extend ad_video_analysis with people_in_ad
-- =============================================================================

ALTER TABLE ad_video_analysis
    ADD COLUMN IF NOT EXISTS people_in_ad JSONB DEFAULT '[]';

COMMENT ON COLUMN ad_video_analysis.people_in_ad IS 'Array of people visible in the video with role (ugc_creator, testimonial, spokesperson, etc.), age_range, gender';
