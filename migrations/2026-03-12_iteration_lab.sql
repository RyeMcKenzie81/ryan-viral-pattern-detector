-- ============================================================================
-- Iteration Lab Tables Migration
-- ============================================================================
-- Purpose: Create tables for the Iteration Opportunity Detector and Winner
--          DNA Analyzer, plus add iteration_auto_run job type.
-- Date: 2026-03-12
--
-- Tables: ad_visual_properties, iteration_opportunities, winner_dna_analyses
-- ============================================================================

-- ============================================================================
-- 1. ad_visual_properties — Cached Gemini visual extraction per ad
-- ============================================================================

CREATE TABLE IF NOT EXISTS ad_visual_properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,

    -- Visual properties (all extracted by Gemini)
    contrast_level TEXT,
    color_palette_type TEXT,
    dominant_colors JSONB,
    text_density TEXT,
    headline_word_count INT,
    visual_hierarchy TEXT,
    composition_style TEXT,
    face_presence BOOLEAN DEFAULT FALSE,
    face_count INT DEFAULT 0,
    face_emotion TEXT,
    person_framing TEXT,
    product_visible BOOLEAN DEFAULT FALSE,
    product_prominence TEXT,
    before_after_present BOOLEAN DEFAULT FALSE,
    headline_style TEXT,
    cta_visual_treatment TEXT,
    visual_quality_score FLOAT,
    thumb_stop_prediction FLOAT,
    raw_extraction JSONB,

    -- Provenance
    model_used TEXT,
    prompt_version TEXT DEFAULT 'v1',
    input_hash TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_visual_props UNIQUE (meta_ad_id, brand_id, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_avp_brand ON ad_visual_properties(brand_id);
CREATE INDEX IF NOT EXISTS idx_avp_meta ON ad_visual_properties(meta_ad_id);

COMMENT ON TABLE ad_visual_properties IS 'Cached Gemini vision extraction of visual properties per ad creative';

-- ============================================================================
-- 2. iteration_opportunities — Detected mixed-signal iteration opportunities
-- ============================================================================

CREATE TABLE IF NOT EXISTS iteration_opportunities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,

    pattern_type TEXT NOT NULL,
    pattern_label TEXT NOT NULL,
    confidence FLOAT NOT NULL,

    strong_metric TEXT NOT NULL,
    strong_value FLOAT,
    strong_percentile TEXT,
    weak_metric TEXT NOT NULL,
    weak_value FLOAT,
    weak_percentile TEXT,

    strategy_category TEXT NOT NULL,
    strategy_description TEXT NOT NULL,
    strategy_actions JSONB,

    evolution_mode TEXT,
    status TEXT DEFAULT 'detected' CHECK (status IN ('detected', 'actioned', 'dismissed', 'expired')),
    actioned_at TIMESTAMPTZ,
    evolved_ad_id UUID,

    detected_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '14 days'),

    CONSTRAINT uq_opp UNIQUE (meta_ad_id, brand_id, pattern_type, detected_at)
);

CREATE INDEX IF NOT EXISTS idx_io_brand_status ON iteration_opportunities(brand_id, status);
CREATE INDEX IF NOT EXISTS idx_io_pattern ON iteration_opportunities(pattern_type);

COMMENT ON TABLE iteration_opportunities IS 'Mixed-signal ads that could be improved with targeted iteration';

-- ============================================================================
-- 3. winner_dna_analyses — Per-winner and cross-winner DNA decompositions
-- ============================================================================

CREATE TABLE IF NOT EXISTS winner_dna_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL CHECK (analysis_type IN ('per_winner', 'cross_winner')),
    meta_ad_ids TEXT[] NOT NULL,

    element_scores JSONB,
    top_elements JSONB,
    weak_elements JSONB,
    visual_properties JSONB,
    messaging_properties JSONB,
    cohort_comparison JSONB,
    active_synergies JSONB,
    active_conflicts JSONB,

    -- Cross-winner only
    common_elements JSONB,
    common_visual_traits JSONB,
    anti_patterns JSONB,
    iteration_directions JSONB,
    replication_blueprint JSONB,

    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wda_brand_type ON winner_dna_analyses(brand_id, analysis_type);

COMMENT ON TABLE winner_dna_analyses IS 'Winner DNA decomposition results (per-winner and cross-winner)';

-- ============================================================================
-- 4. RLS policies (permissive for authenticated users)
-- ============================================================================

ALTER TABLE ad_visual_properties ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated access to ad_visual_properties"
    ON ad_visual_properties FOR ALL TO authenticated USING (true);

ALTER TABLE iteration_opportunities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated access to iteration_opportunities"
    ON iteration_opportunities FOR ALL TO authenticated USING (true);

ALTER TABLE winner_dna_analyses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated access to winner_dna_analyses"
    ON winner_dna_analyses FOR ALL TO authenticated USING (true);

-- ============================================================================
-- 5. Add iteration_auto_run to scheduled_jobs CHECK constraint
-- ============================================================================

ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN (
    'ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
    'template_approval', 'congruence_reanalysis', 'ad_classification',
    'asset_download', 'competitor_scrape', 'reddit_scrape',
    'amazon_review_scrape',
    'ad_creation_v2',
    'creative_genome_update', 'genome_validation',
    'quality_calibration',
    'winner_evolution', 'experiment_analysis',
    'ad_intelligence_analysis',
    'iteration_auto_run'
));
