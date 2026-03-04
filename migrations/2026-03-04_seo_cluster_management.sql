-- ============================================================================
-- SEO Cluster Management Migration
-- ============================================================================
-- Purpose: Enhance seo_clusters table and add spoke/gap-suggestion tables
--          for full topic cluster management workflow.
-- Date: 2026-03-04
-- Branch: feat/ad-creator-v2-phase0
--
-- Changes:
--   1. ALTER seo_clusters: add description, intent, status, pillar_status,
--      target_spoke_count, metadata columns + unique constraint
--   2. CREATE seo_cluster_spokes: join table for keyword-cluster assignments
--      with per-spoke metadata (role, priority, status, article link)
--   3. CREATE seo_cluster_gap_suggestions: AI-suggested keywords to fill
--      cluster content gaps

-- ============================================================================
-- 1. Enhance seo_clusters (non-breaking ALTERs)
-- ============================================================================

ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS intent TEXT DEFAULT 'informational';
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS pillar_status TEXT DEFAULT 'planned';
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS target_spoke_count INT DEFAULT 0;
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Unique constraint: one cluster name per project
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_seo_clusters_project_name'
    ) THEN
        ALTER TABLE seo_clusters ADD CONSTRAINT uq_seo_clusters_project_name
            UNIQUE (project_id, name);
    END IF;
END$$;

COMMENT ON COLUMN seo_clusters.intent IS 'Search intent: informational, commercial, navigational, transactional';
COMMENT ON COLUMN seo_clusters.status IS 'Cluster lifecycle: draft, active, publishing, complete, archived';
COMMENT ON COLUMN seo_clusters.pillar_status IS 'Pillar article state: planned, draft, published';
COMMENT ON COLUMN seo_clusters.metadata IS 'JSONB: target KD range, volume min, scheduling config, notes';

-- ============================================================================
-- 2. seo_cluster_spokes - Keyword-to-cluster assignments with metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_cluster_spokes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES seo_clusters(id) ON DELETE CASCADE,
    keyword_id UUID NOT NULL REFERENCES seo_keywords(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'spoke',
    priority INT DEFAULT 2,
    target_kd FLOAT,
    target_volume INT,
    article_id UUID REFERENCES seo_articles(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'planned',
    notes TEXT,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(cluster_id, keyword_id)
);

CREATE INDEX IF NOT EXISTS idx_seo_cluster_spokes_cluster_id ON seo_cluster_spokes(cluster_id);
CREATE INDEX IF NOT EXISTS idx_seo_cluster_spokes_keyword_id ON seo_cluster_spokes(keyword_id);
CREATE INDEX IF NOT EXISTS idx_seo_cluster_spokes_article_id ON seo_cluster_spokes(article_id);
CREATE INDEX IF NOT EXISTS idx_seo_cluster_spokes_status ON seo_cluster_spokes(status);

COMMENT ON TABLE seo_cluster_spokes IS 'Keyword-to-cluster assignments with per-spoke metadata (role, priority, article link)';
COMMENT ON COLUMN seo_cluster_spokes.role IS 'Spoke role: pillar or spoke';
COMMENT ON COLUMN seo_cluster_spokes.priority IS '1=high, 2=medium, 3=low';
COMMENT ON COLUMN seo_cluster_spokes.status IS 'Spoke lifecycle: planned, writing, published, skipped';

-- ============================================================================
-- 3. seo_cluster_gap_suggestions - AI-suggested keywords for gaps
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_cluster_gap_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES seo_clusters(id) ON DELETE CASCADE,
    suggested_keyword TEXT NOT NULL,
    reason TEXT,
    search_volume INT,
    keyword_difficulty FLOAT,
    status TEXT DEFAULT 'suggested',
    accepted_keyword_id UUID REFERENCES seo_keywords(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_cluster_gap_suggestions_cluster_id ON seo_cluster_gap_suggestions(cluster_id);
CREATE INDEX IF NOT EXISTS idx_seo_cluster_gap_suggestions_status ON seo_cluster_gap_suggestions(status);

COMMENT ON TABLE seo_cluster_gap_suggestions IS 'AI-suggested keywords to fill content gaps in topic clusters';

-- ============================================================================
-- TRIGGERS: updated_at for new table
-- ============================================================================

CREATE OR REPLACE FUNCTION update_seo_cluster_spokes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_seo_cluster_spokes_updated_at ON seo_cluster_spokes;
CREATE TRIGGER update_seo_cluster_spokes_updated_at
    BEFORE UPDATE ON seo_cluster_spokes
    FOR EACH ROW EXECUTE FUNCTION update_seo_cluster_spokes_updated_at();

-- ============================================================================
-- ROW LEVEL SECURITY (matching existing SEO tables pattern)
-- ============================================================================

ALTER TABLE seo_cluster_spokes ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_cluster_gap_suggestions ENABLE ROW LEVEL SECURITY;

CREATE POLICY seo_cluster_spokes_policy ON seo_cluster_spokes
    FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_cluster_gap_suggestions_policy ON seo_cluster_gap_suggestions
    FOR ALL TO authenticated USING (true) WITH CHECK (true);
