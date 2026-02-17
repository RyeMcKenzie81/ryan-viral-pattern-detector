-- Migration: Winner Evolution (Phase 7A) — Ad Lineage + Job Type
-- Date: 2026-02-15
-- Purpose: Add ad_lineage table for tracking parent→child evolution relationships
--   and add 'winner_evolution' to scheduled_jobs job_type constraint.
-- Depends on: 2026-02-15_creative_genome.sql (creative_element_rewards for winner criteria)

-- =============================================================================
-- 1. ad_lineage — Parent→child evolution tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS ad_lineage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Lineage links
    parent_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    child_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    ancestor_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,

    -- Evolution metadata
    evolution_mode TEXT NOT NULL,
    variable_changed TEXT,
    variable_old_value TEXT,
    variable_new_value TEXT,
    iteration_round INTEGER NOT NULL DEFAULT 1,

    -- Performance tracking (child_reward_score + outperformed_parent populated after child matures)
    parent_reward_score FLOAT,
    child_reward_score FLOAT,
    outperformed_parent BOOLEAN,

    -- Tracking
    evolution_job_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(parent_ad_id, child_ad_id)
);

COMMENT ON TABLE ad_lineage IS 'Tracks parent→child relationships for winner evolution. Each row = one parent ad evolved into one child ad.';
COMMENT ON COLUMN ad_lineage.parent_ad_id IS 'The winning ad that was evolved from';
COMMENT ON COLUMN ad_lineage.child_ad_id IS 'The evolved ad that was generated';
COMMENT ON COLUMN ad_lineage.ancestor_ad_id IS 'Root ancestor in the lineage chain (original winner)';
COMMENT ON COLUMN ad_lineage.evolution_mode IS 'winner_iteration | anti_fatigue_refresh | cross_size_expansion';
COMMENT ON COLUMN ad_lineage.variable_changed IS 'Element that was changed: hook_type, color_mode, canvas_size, template_category, awareness_stage';
COMMENT ON COLUMN ad_lineage.variable_old_value IS 'Parent value for the changed variable';
COMMENT ON COLUMN ad_lineage.variable_new_value IS 'Child value for the changed variable';
COMMENT ON COLUMN ad_lineage.iteration_round IS 'Which round of evolution from ancestor (1-based). Max 3 rounds on same ancestor.';
COMMENT ON COLUMN ad_lineage.parent_reward_score IS 'Parent reward_score at time of evolution (from creative_element_rewards)';
COMMENT ON COLUMN ad_lineage.child_reward_score IS 'Child reward_score after maturation (populated by update_evolution_outcomes)';
COMMENT ON COLUMN ad_lineage.outperformed_parent IS 'Whether child reward > parent reward (populated after child matures)';
COMMENT ON COLUMN ad_lineage.evolution_job_id IS 'scheduled_job ID that triggered this evolution';

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ad_lineage_parent ON ad_lineage(parent_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_child ON ad_lineage(child_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_ancestor ON ad_lineage(ancestor_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_mode ON ad_lineage(evolution_mode);

-- =============================================================================
-- 2. CHECK constraint: Add 'winner_evolution' to scheduled_jobs.job_type
-- =============================================================================

ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN (
    -- Existing
    'ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
    'template_approval', 'congruence_reanalysis', 'ad_classification',
    'asset_download', 'competitor_scrape', 'reddit_scrape',
    'amazon_review_scrape',
    -- V2
    'ad_creation_v2',
    -- Phase 6: Creative Genome
    'creative_genome_update', 'genome_validation',
    'quality_calibration',
    -- Phase 7: Winner Evolution + Experiments
    'winner_evolution', 'experiment_analysis'
));
