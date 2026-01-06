-- Migration: Belief-First Reverse Engineer Pipeline
-- Date: 2026-01-02
-- Purpose: Create table for tracking belief reverse engineer pipeline runs

-- Table: belief_reverse_engineer_runs
-- Stores pipeline runs, inputs, outputs, and tracking data
CREATE TABLE IF NOT EXISTS belief_reverse_engineer_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,

    -- Input
    messages JSONB NOT NULL,
    draft_mode BOOLEAN DEFAULT true,
    research_mode BOOLEAN DEFAULT false,
    format_hint TEXT,
    persona_hint TEXT,
    subreddits TEXT[],
    search_terms TEXT[],
    scrape_config JSONB,

    -- Output
    status TEXT DEFAULT 'pending',  -- pending, running, complete, failed
    canvas JSONB,
    research_canvas JSONB,
    belief_canvas JSONB,
    gaps JSONB,
    risk_flags JSONB,
    trace_map JSONB,
    rendered_markdown TEXT,

    -- Research (if applicable)
    reddit_bundle JSONB,
    research_plan JSONB,

    -- Metrics
    posts_analyzed INTEGER DEFAULT 0,
    comments_analyzed INTEGER DEFAULT 0,
    completeness_score FLOAT,

    -- Tracking
    current_step TEXT DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    pipeline_run_id TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_belief_re_runs_product_id ON belief_reverse_engineer_runs(product_id);
CREATE INDEX IF NOT EXISTS idx_belief_re_runs_brand_id ON belief_reverse_engineer_runs(brand_id);
CREATE INDEX IF NOT EXISTS idx_belief_re_runs_status ON belief_reverse_engineer_runs(status);
CREATE INDEX IF NOT EXISTS idx_belief_re_runs_created_at ON belief_reverse_engineer_runs(created_at DESC);

-- Comments
COMMENT ON TABLE belief_reverse_engineer_runs IS 'Tracks belief-first reverse engineer pipeline runs';
COMMENT ON COLUMN belief_reverse_engineer_runs.messages IS 'Input messages (hooks, claims, ad copy) to reverse engineer';
COMMENT ON COLUMN belief_reverse_engineer_runs.draft_mode IS 'If true, skip Reddit research and fill from inference + DB';
COMMENT ON COLUMN belief_reverse_engineer_runs.research_mode IS 'If true, run Reddit research to populate canvas';
COMMENT ON COLUMN belief_reverse_engineer_runs.canvas IS 'Full BeliefFirstMasterCanvas output (sections 1-15)';
COMMENT ON COLUMN belief_reverse_engineer_runs.trace_map IS 'Field-level source attribution for audit trail';
COMMENT ON COLUMN belief_reverse_engineer_runs.risk_flags IS 'Compliance and messaging risk flags detected';
COMMENT ON COLUMN belief_reverse_engineer_runs.reddit_bundle IS 'RedditResearchBundle with extracted signals';

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_belief_re_runs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_belief_re_runs_updated_at ON belief_reverse_engineer_runs;
CREATE TRIGGER trigger_belief_re_runs_updated_at
    BEFORE UPDATE ON belief_reverse_engineer_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_belief_re_runs_updated_at();
