-- Migration: Creative Genome (Phase 6) — Learning Loop
-- Date: 2026-02-15
-- Purpose: Add tables and columns for the Creative Genome feedback loop:
--   - element_tags + pre_gen_score on generated_ads
--   - creative_element_scores: Beta(α,β) distributions per element
--   - creative_element_rewards: Composite reward scores per matured ad
--   - system_alerts: Monitoring alerts for genome health

-- =============================================================================
-- 1. generated_ads — element tagging + pre-generation genome score
-- =============================================================================

ALTER TABLE generated_ads
    ADD COLUMN IF NOT EXISTS element_tags JSONB;

ALTER TABLE generated_ads
    ADD COLUMN IF NOT EXISTS pre_gen_score NUMERIC(5,4);

COMMENT ON COLUMN generated_ads.element_tags IS 'Creative element tags for genome tracking: hook_type, persona_id, color_mode, template_category, awareness_stage, canvas_size, template_id, prompt_version, content_source';
COMMENT ON COLUMN generated_ads.pre_gen_score IS 'Pre-generation genome score [0,1] from Thompson Sampling posteriors';

CREATE INDEX IF NOT EXISTS idx_generated_ads_element_tags
    ON generated_ads USING gin(element_tags);

-- =============================================================================
-- 2. creative_element_scores — Beta distribution parameters per element
-- =============================================================================

CREATE TABLE IF NOT EXISTS creative_element_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    element_name TEXT NOT NULL,
    element_value TEXT NOT NULL,
    alpha FLOAT NOT NULL DEFAULT 1.0,
    beta FLOAT NOT NULL DEFAULT 1.0,
    total_observations INTEGER NOT NULL DEFAULT 0,
    mean_reward FLOAT,
    last_updated TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, element_name, element_value)
);

CREATE INDEX IF NOT EXISTS idx_ces_brand ON creative_element_scores(brand_id);
CREATE INDEX IF NOT EXISTS idx_ces_element ON creative_element_scores(element_name);

COMMENT ON TABLE creative_element_scores IS 'Beta(α,β) distribution parameters per creative element for Thompson Sampling. Updated weekly by creative_genome_update job.';
COMMENT ON COLUMN creative_element_scores.element_name IS 'Element dimension: hook_type, color_mode, template_category, awareness_stage, canvas_size, content_source';
COMMENT ON COLUMN creative_element_scores.element_value IS 'Element value within the dimension, e.g. curiosity_gap, complementary, Testimonial';
COMMENT ON COLUMN creative_element_scores.alpha IS 'Beta distribution success parameter (incremented on reward >= 0.5)';
COMMENT ON COLUMN creative_element_scores.beta IS 'Beta distribution failure parameter (incremented on reward < 0.5)';
COMMENT ON COLUMN creative_element_scores.mean_reward IS 'Running mean reward for diagnostics (not used in sampling)';

-- =============================================================================
-- 3. creative_element_rewards — Composite reward per matured ad
-- =============================================================================

CREATE TABLE IF NOT EXISTS creative_element_rewards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    reward_score FLOAT,
    reward_components JSONB,
    campaign_objective TEXT,
    matured_at TIMESTAMPTZ,
    impressions_at_maturity INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(generated_ad_id)
);

CREATE INDEX IF NOT EXISTS idx_cer_brand ON creative_element_rewards(brand_id);
CREATE INDEX IF NOT EXISTS idx_cer_generated_ad ON creative_element_rewards(generated_ad_id);
CREATE INDEX IF NOT EXISTS idx_cer_matured ON creative_element_rewards(matured_at);

COMMENT ON TABLE creative_element_rewards IS 'Composite reward scores for matured ads. Links generated_ads performance data to genome scoring.';
COMMENT ON COLUMN creative_element_rewards.reward_score IS 'Composite reward [0,1]: weighted combination of normalized CTR, conversion rate, ROAS';
COMMENT ON COLUMN creative_element_rewards.reward_components IS 'Breakdown: {ctr_norm, conv_norm, roas_norm, weights, strata_count, consistent_across_strata}';
COMMENT ON COLUMN creative_element_rewards.campaign_objective IS 'Campaign objective (CONVERSIONS, TRAFFIC, etc.) — determines reward weights';
COMMENT ON COLUMN creative_element_rewards.impressions_at_maturity IS 'Total impressions when reward was computed (maturity check)';

-- =============================================================================
-- 4. system_alerts — Monitoring alerts for genome health
-- =============================================================================

CREATE TABLE IF NOT EXISTS system_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
    metric_value FLOAT,
    threshold_value FLOAT,
    message TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_system_alerts_brand ON system_alerts(brand_id);
CREATE INDEX IF NOT EXISTS idx_system_alerts_type ON system_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_system_alerts_unacked
    ON system_alerts(brand_id, acknowledged) WHERE NOT acknowledged;

COMMENT ON TABLE system_alerts IS 'System monitoring alerts for genome health, data freshness, and pipeline quality.';
COMMENT ON COLUMN system_alerts.alert_type IS 'Alert type: approval_rate, prediction_accuracy, data_freshness, generation_success_rate, winner_rate';
COMMENT ON COLUMN system_alerts.severity IS 'Alert severity: warning or critical';
