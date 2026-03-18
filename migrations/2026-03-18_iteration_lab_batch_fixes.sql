-- Migration: Iteration Lab batch iterate fixes
-- Date: 2026-03-18
-- Purpose: 1) Add 'queued' to iteration_opportunities status CHECK constraint
--          2) Create ad_lineage table if missing (required by winner_evolution_service)

-- =============================================================================
-- 1. Add 'queued' to iteration_opportunities status CHECK
-- =============================================================================

ALTER TABLE iteration_opportunities
DROP CONSTRAINT IF EXISTS iteration_opportunities_status_check;

ALTER TABLE iteration_opportunities
ADD CONSTRAINT iteration_opportunities_status_check
CHECK (status IN ('detected', 'actioned', 'dismissed', 'expired', 'queued'));

-- =============================================================================
-- 2. ad_lineage table (from 2026-02-15_winner_evolution.sql, may not have been run)
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

    -- Performance tracking
    parent_reward_score FLOAT,
    child_reward_score FLOAT,
    outperformed_parent BOOLEAN,

    -- Tracking
    evolution_job_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(parent_ad_id, child_ad_id)
);

CREATE INDEX IF NOT EXISTS idx_ad_lineage_parent ON ad_lineage(parent_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_child ON ad_lineage(child_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_ancestor ON ad_lineage(ancestor_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_mode ON ad_lineage(evolution_mode);
