-- Migration: Angle Candidates Pipeline
-- Date: 2026-01-05
-- Purpose: Create unified staging tables for research insights before they become angles
-- Part of: Angle Pipeline (see docs/plans/angle-pipeline/)

-- ============================================
-- Table: angle_candidates
-- Unified staging table for insights from any source before they become angles
-- ============================================
CREATE TABLE IF NOT EXISTS angle_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,

    -- Core content
    name TEXT NOT NULL,
    belief_statement TEXT NOT NULL,
    explanation TEXT,
    candidate_type TEXT NOT NULL,  -- 'pain_signal', 'pattern', 'jtbd', 'ad_hypothesis', 'quote', 'ump', 'ums'

    -- Source tracking
    source_type TEXT NOT NULL,  -- 'belief_reverse_engineer', 'reddit_research', 'ad_performance', 'competitor_research', 'brand_research'
    source_run_id UUID,  -- FK to source run table (flexible, not enforced)
    competitor_id UUID,  -- If from competitor research

    -- Frequency/confidence scoring
    frequency_score INT DEFAULT 1,  -- Number of evidence items
    confidence TEXT DEFAULT 'LOW',  -- 'LOW', 'MEDIUM', 'HIGH'

    -- Workflow status
    status TEXT DEFAULT 'candidate',  -- 'candidate', 'approved', 'rejected', 'merged'
    promoted_angle_id UUID REFERENCES belief_angles(id) ON DELETE SET NULL,

    -- Metadata
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID
);

-- ============================================
-- Table: angle_candidate_evidence
-- Links candidates to their source evidence for frequency tracking
-- ============================================
CREATE TABLE IF NOT EXISTS angle_candidate_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES angle_candidates(id) ON DELETE CASCADE,

    -- Evidence content
    evidence_type TEXT NOT NULL,  -- 'pain_signal', 'quote', 'pattern', 'solution', 'hypothesis'
    evidence_text TEXT NOT NULL,

    -- Source details
    source_type TEXT NOT NULL,
    source_run_id UUID,
    source_post_id TEXT,  -- Reddit post ID if applicable
    source_url TEXT,

    -- Quality indicators
    engagement_score INT,  -- Upvotes/comments from source
    confidence_score FLOAT,  -- LLM confidence 0-1

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_angle_candidates_product ON angle_candidates(product_id);
CREATE INDEX IF NOT EXISTS idx_angle_candidates_brand ON angle_candidates(brand_id);
CREATE INDEX IF NOT EXISTS idx_angle_candidates_status ON angle_candidates(status);
CREATE INDEX IF NOT EXISTS idx_angle_candidates_frequency ON angle_candidates(frequency_score DESC);
CREATE INDEX IF NOT EXISTS idx_angle_candidates_source ON angle_candidates(source_type);
CREATE INDEX IF NOT EXISTS idx_angle_candidates_competitor ON angle_candidates(competitor_id) WHERE competitor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_angle_candidates_created ON angle_candidates(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_candidate ON angle_candidate_evidence(candidate_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON angle_candidate_evidence(source_type);

-- ============================================
-- Comments
-- ============================================
COMMENT ON TABLE angle_candidates IS 'Unified staging table for research insights from all sources before promotion to belief_angles';
COMMENT ON COLUMN angle_candidates.candidate_type IS 'Type: pain_signal, pattern, jtbd, ad_hypothesis, quote, ump (unique mechanism problem), ums (unique mechanism solution)';
COMMENT ON COLUMN angle_candidates.source_type IS 'Source: belief_reverse_engineer, reddit_research, ad_performance, competitor_research, brand_research';
COMMENT ON COLUMN angle_candidates.frequency_score IS 'Count of evidence items - higher means more frequently observed';
COMMENT ON COLUMN angle_candidates.confidence IS 'Confidence level based on evidence count: LOW (1), MEDIUM (2-4), HIGH (5+)';
COMMENT ON COLUMN angle_candidates.status IS 'Workflow status: candidate (pending review), approved (promoted), rejected, merged';
COMMENT ON COLUMN angle_candidates.promoted_angle_id IS 'Reference to belief_angles if this candidate was promoted';
COMMENT ON COLUMN angle_candidates.competitor_id IS 'Competitor ID if sourced from competitor research';

COMMENT ON TABLE angle_candidate_evidence IS 'Evidence supporting angle candidates, tracks source and quality';
COMMENT ON COLUMN angle_candidate_evidence.evidence_type IS 'Type: pain_signal, quote, pattern, solution, hypothesis';
COMMENT ON COLUMN angle_candidate_evidence.source_post_id IS 'Original source identifier (e.g., Reddit post ID)';
COMMENT ON COLUMN angle_candidate_evidence.engagement_score IS 'Engagement from source (upvotes, comments) - indicates social proof';
COMMENT ON COLUMN angle_candidate_evidence.confidence_score IS 'LLM confidence in this evidence (0-1)';

-- ============================================
-- Trigger for updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_angle_candidates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_angle_candidates_updated_at ON angle_candidates;
CREATE TRIGGER trigger_angle_candidates_updated_at
    BEFORE UPDATE ON angle_candidates
    FOR EACH ROW
    EXECUTE FUNCTION update_angle_candidates_updated_at();

-- ============================================
-- Row Level Security
-- ============================================
ALTER TABLE angle_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE angle_candidate_evidence ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users full access (same pattern as belief_angles)
CREATE POLICY "Allow authenticated users full access to angle_candidates"
    ON angle_candidates FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to angle_candidate_evidence"
    ON angle_candidate_evidence FOR ALL TO authenticated USING (true) WITH CHECK (true);
