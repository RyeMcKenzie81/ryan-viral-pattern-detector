-- Migration: Experimentation Framework (Phase 7B)
-- Date: 2026-02-16
-- Purpose: Add structured A/B testing with Bayesian analysis and causal knowledge base.
--   4 tables: experiments, experiment_arms, experiment_analyses, causal_effects
-- Depends on: 2026-02-15_winner_evolution.sql (experiment_analysis job_type already added)

-- =============================================================================
-- 1. experiments — Hypothesis-driven experiments
-- =============================================================================

CREATE TABLE IF NOT EXISTS experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    test_variable TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','ready','deploying','running','analyzing','concluded','cancelled')),
    protocol JSONB NOT NULL DEFAULT '{}',
    meta_campaign_id TEXT,
    meta_campaign_name TEXT,
    started_at TIMESTAMPTZ,
    concluded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experiments_brand ON experiments(brand_id);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_product ON experiments(product_id);

COMMENT ON TABLE experiments IS 'Hypothesis-driven A/B experiments with Bayesian analysis';
COMMENT ON COLUMN experiments.test_variable IS 'Element being tested: hook_type, color_mode, template_category, etc.';
COMMENT ON COLUMN experiments.status IS 'draft → ready → deploying → running → analyzing → concluded | cancelled';
COMMENT ON COLUMN experiments.protocol IS 'Experiment config: method_type, budget_strategy, randomization_unit, audience_rules, min/max days, hold_constant, power_analysis results';
COMMENT ON COLUMN experiments.meta_campaign_id IS 'Meta campaign ID linked after manual deployment';

-- =============================================================================
-- 2. experiment_arms — Control and treatment arms
-- =============================================================================

CREATE TABLE IF NOT EXISTS experiment_arms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_control BOOLEAN NOT NULL DEFAULT FALSE,
    variable_value TEXT NOT NULL,
    generated_ad_id UUID REFERENCES generated_ads(id) ON DELETE SET NULL,
    meta_adset_id TEXT,
    meta_adset_name TEXT,
    meta_ad_id TEXT,
    meta_ad_account_id TEXT,
    hold_constant_tags JSONB,
    notes TEXT,
    arm_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experiment_arms_experiment ON experiment_arms(experiment_id);

-- DB backstops: enforce arm integrity at schema level
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms_one_control
    ON experiment_arms (experiment_id) WHERE is_control = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms_order
    ON experiment_arms (experiment_id, arm_order);
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms_meta_adset
    ON experiment_arms (experiment_id, meta_adset_id) WHERE meta_adset_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_arms_variable_value
    ON experiment_arms (experiment_id, variable_value);

COMMENT ON TABLE experiment_arms IS 'Control and treatment arms for experiments';
COMMENT ON COLUMN experiment_arms.variable_value IS 'Value of test_variable for this arm';
COMMENT ON COLUMN experiment_arms.is_control IS 'Exactly one arm per experiment must be control';
COMMENT ON COLUMN experiment_arms.meta_adset_id IS 'Meta ad set ID linked after manual deployment';
COMMENT ON COLUMN experiment_arms.meta_ad_account_id IS 'Meta ad account ID for cross-arm validation';
COMMENT ON COLUMN experiment_arms.hold_constant_tags IS 'Snapshot of element_tags minus test_variable';
COMMENT ON COLUMN experiment_arms.arm_order IS 'Display/processing order (0-based)';

-- =============================================================================
-- 3. experiment_analyses — Daily Bayesian analysis snapshots
-- =============================================================================

CREATE TABLE IF NOT EXISTS experiment_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    analysis_date DATE NOT NULL,
    arm_results JSONB NOT NULL,
    primary_metric TEXT NOT NULL DEFAULT 'ctr',
    winner_arm_id UUID,
    winner_p_best FLOAT,
    decision TEXT CHECK (decision IN ('collecting','leading','winner','futility','inconclusive')),
    quality_grade TEXT NOT NULL DEFAULT 'observational'
        CHECK (quality_grade IN ('causal','quasi','observational')),
    quality_notes TEXT,
    all_arms_met_min_impressions BOOLEAN DEFAULT FALSE,
    days_running INTEGER,
    monte_carlo_samples INTEGER DEFAULT 10000,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(experiment_id, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_experiment_analyses_experiment ON experiment_analyses(experiment_id);

COMMENT ON TABLE experiment_analyses IS 'Daily Bayesian analysis snapshots for experiments';
COMMENT ON COLUMN experiment_analyses.arm_results IS 'Per-arm: impressions, clicks, CTR, posteriors, P(best)';
COMMENT ON COLUMN experiment_analyses.decision IS 'collecting → leading → winner | futility | inconclusive';
COMMENT ON COLUMN experiment_analyses.quality_grade IS 'Evidence quality: causal (strict_ab), quasi (pragmatic_split), observational';

-- =============================================================================
-- 4. causal_effects — Knowledge base of measured effects
-- =============================================================================

CREATE TABLE IF NOT EXISTS causal_effects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    test_variable TEXT NOT NULL,
    control_value TEXT NOT NULL,
    treatment_value TEXT NOT NULL,
    metric TEXT NOT NULL,
    ate FLOAT NOT NULL,
    ate_relative FLOAT,
    ci_lower FLOAT NOT NULL,
    ci_upper FLOAT NOT NULL,
    p_best FLOAT,
    quality_grade TEXT NOT NULL CHECK (quality_grade IN ('causal','quasi','observational')),
    control_impressions INTEGER,
    treatment_impressions INTEGER,
    concluded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_causal_effects_brand ON causal_effects(brand_id);
CREATE INDEX IF NOT EXISTS idx_causal_effects_experiment ON causal_effects(experiment_id);
CREATE INDEX IF NOT EXISTS idx_causal_effects_variable ON causal_effects(test_variable);

COMMENT ON TABLE causal_effects IS 'Knowledge base of measured causal effects from concluded experiments';
COMMENT ON COLUMN causal_effects.ate IS 'Average Treatment Effect (absolute)';
COMMENT ON COLUMN causal_effects.ate_relative IS 'Relative ATE: (treatment - control) / control';
COMMENT ON COLUMN causal_effects.ci_lower IS '95% credible interval lower bound';
COMMENT ON COLUMN causal_effects.ci_upper IS '95% credible interval upper bound';
COMMENT ON COLUMN causal_effects.quality_grade IS 'Evidence quality: causal, quasi, or observational';
