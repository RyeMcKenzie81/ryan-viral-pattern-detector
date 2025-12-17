-- ============================================
-- Migration: Belief Plan Execution Pipeline
-- Date: 2025-12-16
-- Purpose: Add belief_plan_id to pipeline_runs for Phase 1-2 ad generation
-- ============================================

-- Add belief_plan_id column to pipeline_runs
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS belief_plan_id UUID REFERENCES belief_plans(id);

-- Add index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_belief_plan ON pipeline_runs(belief_plan_id);

-- Add product_id column for linking runs to products
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_product ON pipeline_runs(product_id);

COMMENT ON COLUMN pipeline_runs.belief_plan_id IS 'Reference to belief plan being executed (Phase 1-2)';
COMMENT ON COLUMN pipeline_runs.product_id IS 'Reference to product for ad generation runs';

-- ============================================
-- DONE
-- ============================================
