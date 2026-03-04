-- Migration: Ad Creator V2 Phase 8B — Advanced Intelligence
-- Date: 2026-02-16
-- Purpose: Learned scorer weights, generation experiments, cross-brand transfer,
--          competitive whitespace, visual style clustering

-- ============================================================================
-- 1. Scorer Weight Posteriors — Beta(α,β) per scorer per brand
-- ============================================================================

CREATE TABLE IF NOT EXISTS scorer_weight_posteriors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    scorer_name TEXT NOT NULL,  -- asset_match, unused_bonus, etc.
    alpha FLOAT NOT NULL DEFAULT 1.0,
    beta FLOAT NOT NULL DEFAULT 1.0,
    total_observations INT NOT NULL DEFAULT 0,
    mean_reward FLOAT,
    static_weight FLOAT NOT NULL,  -- seed from SMART_SELECT_WEIGHTS
    learning_phase TEXT NOT NULL DEFAULT 'cold',  -- cold/warm/hot
    last_updated TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, scorer_name)
);

COMMENT ON TABLE scorer_weight_posteriors IS 'Beta(α,β) posteriors for Thompson Sampling on scorer weights per brand';
COMMENT ON COLUMN scorer_weight_posteriors.learning_phase IS 'cold (0-29 obs), warm (30-99), hot (100+)';

-- ============================================================================
-- 2. Selection Weight Snapshots — Records weights used at selection time
-- ============================================================================

CREATE TABLE IF NOT EXISTS selection_weight_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL,
    ad_run_id UUID NOT NULL,
    template_id UUID,
    weights_used JSONB NOT NULL,
    scorer_breakdown JSONB,
    composite_score FLOAT,
    learning_phase TEXT NOT NULL DEFAULT 'cold',
    selection_mode TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sws_brand_run
    ON selection_weight_snapshots(brand_id, ad_run_id);

COMMENT ON TABLE selection_weight_snapshots IS 'Snapshot of scorer weights and scores at template selection time for reward attribution';

-- ============================================================================
-- 3. Whitespace Candidates — High-potential untested element combos
-- ============================================================================

CREATE TABLE IF NOT EXISTS whitespace_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    element_a_name TEXT NOT NULL,
    element_a_value TEXT NOT NULL,
    element_b_name TEXT NOT NULL,
    element_b_value TEXT NOT NULL,
    predicted_potential FLOAT NOT NULL,
    individual_a_score FLOAT,
    individual_b_score FLOAT,
    synergy_bonus FLOAT DEFAULT 0.0,
    usage_count INT NOT NULL DEFAULT 0,
    whitespace_rank INT,
    status TEXT NOT NULL DEFAULT 'identified',  -- identified/injected/tested/dismissed
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, element_a_name, element_a_value, element_b_name, element_b_value)
);

COMMENT ON TABLE whitespace_candidates IS 'Untested element combos with high predicted potential for competitive whitespace';

-- ============================================================================
-- 4. Generation Experiments — Pipeline-level A/B tests
-- ============================================================================

CREATE TABLE IF NOT EXISTS generation_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    hypothesis TEXT,
    experiment_type TEXT NOT NULL
        CHECK (experiment_type IN ('prompt_version', 'pipeline_config', 'review_rubric', 'element_strategy')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'completed', 'cancelled')),
    control_config JSONB NOT NULL,
    variant_config JSONB NOT NULL,
    split_ratio NUMERIC(3,2) DEFAULT 0.50,
    min_sample_size INTEGER DEFAULT 20,
    control_metrics JSONB,     -- aggregated: {ads_generated, ads_approved, ads_rejected, defects, review_score_sum}
    variant_metrics JSONB,     -- same shape
    winner TEXT,               -- 'control', 'variant', 'inconclusive', NULL
    confidence NUMERIC(4,3),   -- Mann-Whitney U p-value
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Max 1 active experiment per brand (partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_gen_exp_one_active_per_brand
    ON generation_experiments(brand_id) WHERE status = 'active';

COMMENT ON TABLE generation_experiments IS 'Generation-level A/B experiments with 2-arm control/variant design';

-- ============================================================================
-- 5. Generation Experiment Runs — Per-run experiment assignment
-- ============================================================================

CREATE TABLE IF NOT EXISTS generation_experiment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES generation_experiments(id),
    arm TEXT NOT NULL CHECK (arm IN ('control', 'variant')),
    ad_run_id UUID NOT NULL,
    ads_generated INT DEFAULT 0,
    ads_approved INT DEFAULT 0,
    ads_rejected INT DEFAULT 0,
    ads_flagged INT DEFAULT 0,
    defects_found INT DEFAULT 0,
    avg_review_score FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ad_run_id)
);

COMMENT ON TABLE generation_experiment_runs IS 'Per-pipeline-run experiment arm assignment and outcome metrics';

-- ============================================================================
-- 6. Visual Style Clusters — DBSCAN cluster assignments
-- ============================================================================

CREATE TABLE IF NOT EXISTS visual_style_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    cluster_label INT NOT NULL,      -- DBSCAN cluster ID (-1 = noise)
    cluster_size INT NOT NULL,
    centroid_embedding VECTOR(1536),  -- cluster mean
    avg_reward_score FLOAT,           -- average reward of ads in cluster
    top_descriptors JSONB,            -- dominant visual features in cluster
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE visual_style_clusters IS 'DBSCAN visual style clusters from ad visual embeddings';

CREATE TABLE IF NOT EXISTS visual_style_cluster_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES visual_style_clusters(id) ON DELETE CASCADE,
    generated_ad_id UUID NOT NULL,
    visual_embedding_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(generated_ad_id)
);

COMMENT ON TABLE visual_style_cluster_members IS 'Membership mapping from generated ads to visual style clusters';

-- ============================================================================
-- 7. Schema Changes — Cross-brand sharing toggle on brands
-- ============================================================================

ALTER TABLE brands ADD COLUMN IF NOT EXISTS cross_brand_sharing BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN brands.cross_brand_sharing IS 'Opt-in flag for cross-brand transfer learning within the same organization';
