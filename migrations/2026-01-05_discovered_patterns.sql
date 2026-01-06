-- Migration: Add discovered_patterns table for Pattern Discovery Engine
-- Date: 2026-01-05
-- Purpose: Store automatically discovered pattern clusters from angle candidates

-- ============================================================================
-- Table: discovered_patterns
-- ============================================================================
-- Stores pattern clusters discovered by analyzing angle_candidates
-- Patterns represent recurring themes across multiple candidates/evidence

CREATE TABLE IF NOT EXISTS discovered_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) NOT NULL,
    brand_id UUID REFERENCES brands(id),

    -- Pattern content
    name TEXT NOT NULL,
    theme_description TEXT NOT NULL,
    pattern_type TEXT NOT NULL,  -- 'pain_cluster', 'jtbd_cluster', 'emerging_topic', 'correlation'

    -- Evidence tracking
    candidate_count INT DEFAULT 0,
    evidence_count INT DEFAULT 0,
    source_breakdown JSONB DEFAULT '{}',  -- {"reddit": 5, "competitor": 3, "brand": 2}

    -- Quality scores
    confidence_score FLOAT,  -- 0-1 based on evidence strength
    novelty_score FLOAT,  -- How different from existing angles (0=duplicate, 1=novel)

    -- Status workflow
    status TEXT DEFAULT 'discovered',  -- 'discovered', 'reviewed', 'promoted', 'dismissed'
    promoted_angle_id UUID REFERENCES belief_angles(id),

    -- Clustering metadata
    centroid_embedding VECTOR(1536),  -- OpenAI text-embedding-3-small centroid
    cluster_radius FLOAT,  -- Average distance from centroid

    -- Linked candidates
    candidate_ids UUID[] DEFAULT '{}',

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID

);

-- Add check constraint for valid pattern types
ALTER TABLE discovered_patterns ADD CONSTRAINT discovered_patterns_type_check
    CHECK (pattern_type IN ('pain_cluster', 'jtbd_cluster', 'emerging_topic', 'correlation', 'quote_cluster'));

-- Add check constraint for valid statuses
ALTER TABLE discovered_patterns ADD CONSTRAINT discovered_patterns_status_check
    CHECK (status IN ('discovered', 'reviewed', 'promoted', 'dismissed'));

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_discovered_patterns_product ON discovered_patterns(product_id);
CREATE INDEX IF NOT EXISTS idx_discovered_patterns_brand ON discovered_patterns(brand_id);
CREATE INDEX IF NOT EXISTS idx_discovered_patterns_status ON discovered_patterns(status);
CREATE INDEX IF NOT EXISTS idx_discovered_patterns_confidence ON discovered_patterns(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_discovered_patterns_novelty ON discovered_patterns(novelty_score DESC);

-- ============================================================================
-- Add embedding column to angle_candidates for similarity search
-- ============================================================================

ALTER TABLE angle_candidates
ADD COLUMN IF NOT EXISTS embedding VECTOR(1536);

-- Index for fast similarity search (requires pgvector extension)
-- Note: If pgvector not installed, this will fail gracefully
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_angle_candidates_embedding
    ON angle_candidates USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
EXCEPTION
    WHEN undefined_object THEN
        RAISE NOTICE 'pgvector extension not available, skipping vector index';
END
$$;

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE discovered_patterns IS 'Automatically discovered pattern clusters from angle candidates';
COMMENT ON COLUMN discovered_patterns.pattern_type IS 'Type: pain_cluster, jtbd_cluster, emerging_topic, correlation, quote_cluster';
COMMENT ON COLUMN discovered_patterns.confidence_score IS 'Evidence strength score 0-1';
COMMENT ON COLUMN discovered_patterns.novelty_score IS 'Uniqueness vs existing angles 0-1 (1=novel)';
COMMENT ON COLUMN discovered_patterns.centroid_embedding IS 'Cluster centroid embedding for similarity';
COMMENT ON COLUMN discovered_patterns.candidate_ids IS 'Array of angle_candidate IDs in this pattern';
COMMENT ON COLUMN angle_candidates.embedding IS 'OpenAI text-embedding-3-small vector for similarity search';
