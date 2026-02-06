-- Migration: Ad Intelligence Agent tables
-- Date: 2026-02-02
-- Purpose: Create all tables for the 4-layer Ad Intelligence system:
--   Layer 1: Creative classifications (awareness level, format, congruence)
--   Layer 2: Contextual cohort baselines (percentile benchmarks)
--   Layer 3: Rules-based diagnostics (per-ad health assessment)
--   Layer 4: Actionable recommendations (with human feedback)
--   Plus: Analysis run anchor, asset seams for future Advantage+ support
--
-- Tables created:
--   - ad_intelligence_runs: Analysis run anchor for auditability
--   - ad_creative_classifications: LLM-derived awareness classifications (immutable snapshots)
--   - ad_intelligence_baselines: Cohort-level aggregate baselines (versionable)
--   - ad_intelligence_diagnostics: Per-ad diagnostic results with fired rules
--   - ad_intelligence_recommendations: Actionable recommendations with feedback
--   - meta_creative_assets: Individual creative assets (schema-only seam for v2)
--   - meta_ad_asset_map: Many-to-many ad-to-asset mapping (schema-only seam for v2)

-- =============================================================================
-- 1. ad_intelligence_runs (Analysis Run Anchor)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ad_intelligence_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Run configuration
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    goal TEXT,
    triggered_by UUID,
    config JSONB DEFAULT '{}',
    -- Config schema (documented, not enforced in DDL):
    -- {
    --   "days_back": 30,
    --   "active_window_days": 7,
    --   "force_reclassify": false,
    --   "primary_conversion_event": "purchase",
    --   "value_field": "purchase_value",
    --   "kpi": "cpa",
    --   "thresholds": {}
    -- }

    -- Run summary (populated after completion)
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    summary JSONB,
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_air_run_brand ON ad_intelligence_runs(brand_id);
CREATE INDEX IF NOT EXISTS idx_air_run_org ON ad_intelligence_runs(organization_id);
CREATE INDEX IF NOT EXISTS idx_air_run_created ON ad_intelligence_runs(created_at DESC);

COMMENT ON TABLE ad_intelligence_runs IS 'Analysis run anchor for ad intelligence. Every analysis invocation creates a run for auditability and time-windowed comparison.';
COMMENT ON COLUMN ad_intelligence_runs.config IS 'Run configuration: days_back, active_window_days, force_reclassify, primary_conversion_event, value_field, kpi, thresholds';
COMMENT ON COLUMN ad_intelligence_runs.goal IS 'Analysis goal: lower_cpa, scale, stability, etc.';
COMMENT ON COLUMN ad_intelligence_runs.triggered_by IS 'user_id who triggered the run, NULL if scheduled';

-- =============================================================================
-- 2. ad_creative_classifications (Layer 1 - Awareness Classification)
-- =============================================================================
-- Immutable snapshots: new classifications create new rows, old rows never overwritten.
-- No UNIQUE constraint: deduplication handled in code via _needs_new_classification().

CREATE TABLE IF NOT EXISTS ad_creative_classifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,
    run_id UUID REFERENCES ad_intelligence_runs(id) ON DELETE SET NULL,

    -- Creative classification
    creative_awareness_level TEXT CHECK (creative_awareness_level IN
        ('unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware')),
    creative_awareness_confidence NUMERIC(4,3),
    creative_format TEXT CHECK (creative_format IN
        ('video_ugc', 'video_professional', 'video_testimonial', 'video_demo',
         'image_static', 'image_before_after', 'image_testimonial', 'image_product',
         'carousel', 'collection', 'other')),
    creative_angle TEXT,
    video_length_bucket TEXT CHECK (video_length_bucket IN
        ('short_0_15', 'medium_15_30', 'long_30_60', 'very_long_60_plus')),

    -- Copy classification
    copy_awareness_level TEXT CHECK (copy_awareness_level IN
        ('unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware')),
    copy_awareness_confidence NUMERIC(4,3),
    hook_type TEXT,
    primary_cta TEXT,

    -- Landing page classification (nullable)
    landing_page_awareness_level TEXT CHECK (landing_page_awareness_level IN
        ('unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware')),
    landing_page_confidence NUMERIC(4,3),
    landing_page_id UUID REFERENCES brand_landing_pages(id) ON DELETE SET NULL,

    -- Congruence
    congruence_score NUMERIC(4,3),
    congruence_notes TEXT,

    -- Versioning & provenance
    source TEXT NOT NULL DEFAULT 'gemini_light',
    prompt_version TEXT NOT NULL DEFAULT 'v1',
    schema_version TEXT NOT NULL DEFAULT '1.0',
    input_hash TEXT NOT NULL,
    model_used TEXT,
    raw_classification JSONB DEFAULT '{}',

    -- Staleness
    classified_at TIMESTAMPTZ DEFAULT NOW(),
    stale_after TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_acc_brand ON ad_creative_classifications(brand_id);
CREATE INDEX IF NOT EXISTS idx_acc_awareness ON ad_creative_classifications(creative_awareness_level);
CREATE INDEX IF NOT EXISTS idx_acc_org ON ad_creative_classifications(organization_id);
CREATE INDEX IF NOT EXISTS idx_acc_source ON ad_creative_classifications(source);
CREATE INDEX IF NOT EXISTS idx_acc_meta_ad ON ad_creative_classifications(meta_ad_id, brand_id);
-- Fast lookup of latest classification per ad (supports get_classification_for_run fallback)
CREATE INDEX IF NOT EXISTS idx_acc_meta_ad_classified_at
    ON ad_creative_classifications(brand_id, meta_ad_id, classified_at DESC);
-- Fast lookup of classifications created during a specific run
CREATE INDEX IF NOT EXISTS idx_acc_run_ad
    ON ad_creative_classifications(run_id, meta_ad_id);

COMMENT ON TABLE ad_creative_classifications IS 'LLM-derived awareness classifications per ad. Immutable snapshots - new classifications create new rows, old rows never overwritten.';
COMMENT ON COLUMN ad_creative_classifications.source IS 'Classification source: existing_brand_ad_analysis, gemini_light, or gemini_full';
COMMENT ON COLUMN ad_creative_classifications.input_hash IS 'SHA256(thumbnail_url + ad_copy + lp_id) for change detection';
COMMENT ON COLUMN ad_creative_classifications.stale_after IS 'When this classification should be considered stale and reclassified';

-- =============================================================================
-- 3. ad_intelligence_baselines (Layer 2 - Cohort Baselines)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ad_intelligence_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Cohort definition
    awareness_level TEXT NOT NULL,
    creative_format TEXT NOT NULL,
    video_length_bucket TEXT DEFAULT 'all',
    campaign_objective TEXT DEFAULT 'all',

    -- Audit linkage (nullable - baselines can exist independently of runs)
    run_id UUID REFERENCES ad_intelligence_runs(id) ON DELETE SET NULL,

    -- Sample info
    sample_size INTEGER NOT NULL,
    unique_ads INTEGER NOT NULL,

    -- Performance baselines (p25 / median / p75)
    median_ctr NUMERIC(10,6), p25_ctr NUMERIC(10,6), p75_ctr NUMERIC(10,6),
    median_cpc NUMERIC(10,4), p25_cpc NUMERIC(10,4), p75_cpc NUMERIC(10,4),
    median_cpm NUMERIC(10,4), p25_cpm NUMERIC(10,4), p75_cpm NUMERIC(10,4),
    median_roas NUMERIC(8,4), p25_roas NUMERIC(8,4), p75_roas NUMERIC(8,4),
    median_conversion_rate NUMERIC(10,4), p25_conversion_rate NUMERIC(10,4), p75_conversion_rate NUMERIC(10,4),
    median_cost_per_purchase NUMERIC(10,4),

    -- Video-specific (only for video cohorts)
    median_hook_rate NUMERIC(6,4),
    median_hold_rate NUMERIC(6,4),
    median_completion_rate NUMERIC(6,4),

    -- Frequency
    median_frequency NUMERIC(6,3),
    p75_frequency NUMERIC(6,3),

    -- Date range (included in uniqueness for versioning)
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, awareness_level, creative_format, video_length_bucket,
           campaign_objective, date_range_start, date_range_end)
);

CREATE INDEX IF NOT EXISTS idx_aib_brand ON ad_intelligence_baselines(brand_id);
CREATE INDEX IF NOT EXISTS idx_aib_org ON ad_intelligence_baselines(organization_id);
CREATE INDEX IF NOT EXISTS idx_aib_cohort ON ad_intelligence_baselines(brand_id, awareness_level, creative_format);

COMMENT ON TABLE ad_intelligence_baselines IS 'Cohort-level aggregate baselines with p25/median/p75 percentiles. Versionable by date range.';
COMMENT ON COLUMN ad_intelligence_baselines.sample_size IS 'Number of ad-days in cohort';
COMMENT ON COLUMN ad_intelligence_baselines.unique_ads IS 'Number of distinct ads in cohort';

-- =============================================================================
-- 4. ad_intelligence_diagnostics (Layer 3 - Per-Ad Diagnostics)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ad_intelligence_diagnostics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,
    run_id UUID NOT NULL REFERENCES ad_intelligence_runs(id) ON DELETE CASCADE,

    overall_health TEXT NOT NULL CHECK (overall_health IN ('healthy', 'warning', 'critical', 'insufficient_data')),
    kill_recommendation BOOLEAN DEFAULT FALSE,
    kill_reason TEXT,

    -- Fired rules: [{rule_id, rule_name, category, severity, confidence, ...}]
    fired_rules JSONB NOT NULL DEFAULT '[]',

    trend_direction TEXT CHECK (trend_direction IN ('improving', 'stable', 'declining', 'volatile')),
    days_analyzed INTEGER,

    baseline_id UUID REFERENCES ad_intelligence_baselines(id) ON DELETE SET NULL,
    classification_id UUID NOT NULL REFERENCES ad_creative_classifications(id) ON DELETE RESTRICT,
    diagnosed_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(meta_ad_id, brand_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_aid_brand ON ad_intelligence_diagnostics(brand_id);
CREATE INDEX IF NOT EXISTS idx_aid_run ON ad_intelligence_diagnostics(run_id);
CREATE INDEX IF NOT EXISTS idx_aid_health ON ad_intelligence_diagnostics(overall_health);
CREATE INDEX IF NOT EXISTS idx_aid_kill ON ad_intelligence_diagnostics(kill_recommendation) WHERE kill_recommendation = TRUE;

COMMENT ON TABLE ad_intelligence_diagnostics IS 'Per-ad diagnostic results with fired rules. Tied to a run for auditability.';
COMMENT ON COLUMN ad_intelligence_diagnostics.classification_id IS 'NOT NULL: every diagnostic must reference the exact classification row it evaluated';
COMMENT ON COLUMN ad_intelligence_diagnostics.fired_rules IS 'Array of fired/skipped rules with metrics, explanations, and confidence scores';

-- =============================================================================
-- 5. ad_intelligence_recommendations (Layer 4 - Actionable Recommendations)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ad_intelligence_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES ad_intelligence_runs(id) ON DELETE CASCADE,

    -- Content
    title TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN
        ('kill', 'scale', 'iterate', 'test', 'refresh', 'coverage_gap',
         'congruence_fix', 'budget_realloc', 'creative_test')),
    priority TEXT NOT NULL CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    confidence NUMERIC(4,3) NOT NULL,

    -- Explainable context
    summary TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]',

    -- Affected entities
    affected_ad_ids TEXT[] DEFAULT '{}',
    affected_campaign_ids TEXT[] DEFAULT '{}',
    affected_ads JSONB DEFAULT '[]',

    -- Suggested action
    action_description TEXT NOT NULL,
    action_type TEXT CHECK (action_type IN
        ('pause_ad', 'increase_budget', 'decrease_budget', 'create_variation',
         'change_audience', 'update_creative', 'launch_test', 'monitor', 'no_action')),

    -- Human feedback
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
        ('pending', 'acknowledged', 'acted_on', 'partially_acted', 'ignored', 'dismissed')),
    user_note TEXT,
    acted_at TIMESTAMPTZ,
    acted_by UUID,

    -- Outcome tracking (filled later)
    outcome_measured_at TIMESTAMPTZ,
    outcome_data JSONB,

    diagnostic_id UUID REFERENCES ad_intelligence_diagnostics(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_airec_brand ON ad_intelligence_recommendations(brand_id);
CREATE INDEX IF NOT EXISTS idx_airec_run ON ad_intelligence_recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_airec_status ON ad_intelligence_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_airec_priority ON ad_intelligence_recommendations(priority);
CREATE INDEX IF NOT EXISTS idx_airec_org ON ad_intelligence_recommendations(organization_id);
CREATE INDEX IF NOT EXISTS idx_airec_created ON ad_intelligence_recommendations(created_at DESC);
-- Efficient filtering by affected_ad_ids array
CREATE INDEX IF NOT EXISTS idx_airec_affected_ad_ids_gin
    ON ad_intelligence_recommendations USING GIN (affected_ad_ids);

COMMENT ON TABLE ad_intelligence_recommendations IS 'Actionable recommendations with human feedback and outcome tracking. Tied to a run.';
COMMENT ON COLUMN ad_intelligence_recommendations.affected_ads IS 'Structured JSONB: [{ad_id, ad_name, reason}] for display';
COMMENT ON COLUMN ad_intelligence_recommendations.affected_ad_ids IS 'Flat array for GIN index filtering';
COMMENT ON COLUMN ad_intelligence_recommendations.evidence IS 'Array of evidence points: [{metric, observation, data:{current, previous, baseline}}]';

-- =============================================================================
-- 6. meta_creative_assets (Schema-only seam for v2)
-- =============================================================================
-- Empty in v1: no code writes to this table yet.

CREATE TABLE IF NOT EXISTS meta_creative_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    asset_type TEXT NOT NULL CHECK (asset_type IN
        ('image', 'video', 'headline', 'primary_text', 'description')),
    asset_key TEXT NOT NULL,
    content TEXT,
    url TEXT,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, asset_type, asset_key)
);

CREATE INDEX IF NOT EXISTS idx_mca_brand ON meta_creative_assets(brand_id);
CREATE INDEX IF NOT EXISTS idx_mca_type ON meta_creative_assets(asset_type);

COMMENT ON TABLE meta_creative_assets IS 'Individual creative assets (headlines, primary text, images, videos). Schema-only seam for future Advantage+ copy learning - empty in v1.';

-- =============================================================================
-- 7. meta_ad_asset_map (Schema-only seam for v2)
-- =============================================================================
-- Empty in v1: no code writes to this table yet.

CREATE TABLE IF NOT EXISTS meta_ad_asset_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,
    asset_id UUID NOT NULL REFERENCES meta_creative_assets(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN
        ('headline', 'primary_text', 'image', 'video', 'description', 'thumbnail')),

    UNIQUE(meta_ad_id, asset_id, role)
);

CREATE INDEX IF NOT EXISTS idx_maam_ad ON meta_ad_asset_map(meta_ad_id);
CREATE INDEX IF NOT EXISTS idx_maam_asset ON meta_ad_asset_map(asset_id);

COMMENT ON TABLE meta_ad_asset_map IS 'Many-to-many mapping of ads to creative assets. Schema-only seam for v2 - empty in v1.';
