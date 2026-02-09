-- Migration: Create landing_page_analyses table
-- Date: 2026-02-09
-- Purpose: Store landing page analysis results from Skills 1-4 pipeline

CREATE TABLE IF NOT EXISTS landing_page_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    url TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('url', 'competitor_lp', 'brand_lp')),
    source_id UUID,

    -- Scraped content snapshot
    page_markdown TEXT,
    screenshot_storage_path TEXT,

    -- Skill 1: Classification (denormalized for filtering)
    classification JSONB DEFAULT '{}',
    awareness_level TEXT,
    market_sophistication INTEGER,
    architecture_type TEXT,

    -- Skill 2: Elements
    elements JSONB DEFAULT '{}',
    element_count INTEGER DEFAULT 0,

    -- Skill 3: Gaps
    gap_analysis JSONB DEFAULT '{}',
    completeness_score INTEGER,

    -- Skill 4: Copy Scores
    copy_scores JSONB DEFAULT '{}',
    overall_score INTEGER,
    overall_grade TEXT,

    -- Metadata
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'partial', 'failed')),
    error_message TEXT,
    processing_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_landing_page_analyses_org ON landing_page_analyses(organization_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_analyses_url ON landing_page_analyses(url);
CREATE INDEX IF NOT EXISTS idx_landing_page_analyses_status ON landing_page_analyses(status);
CREATE INDEX IF NOT EXISTS idx_landing_page_analyses_source ON landing_page_analyses(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_analyses_created ON landing_page_analyses(created_at DESC);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_landing_page_analyses_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_landing_page_analyses_updated_at ON landing_page_analyses;
CREATE TRIGGER trigger_landing_page_analyses_updated_at
    BEFORE UPDATE ON landing_page_analyses
    FOR EACH ROW
    EXECUTE FUNCTION update_landing_page_analyses_updated_at();

-- RLS
ALTER TABLE landing_page_analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow authenticated users to read landing_page_analyses"
    ON landing_page_analyses FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Allow authenticated users to insert landing_page_analyses"
    ON landing_page_analyses FOR INSERT
    TO authenticated
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users to update landing_page_analyses"
    ON landing_page_analyses FOR UPDATE
    TO authenticated
    USING (true);

COMMENT ON TABLE landing_page_analyses IS 'Landing page analysis results from the 4-skill analysis pipeline';
COMMENT ON COLUMN landing_page_analyses.source_type IS 'How the page was loaded: url (fresh scrape), competitor_lp, or brand_lp';
COMMENT ON COLUMN landing_page_analyses.source_id IS 'FK to source table (competitor_landing_pages or brand_landing_pages) if applicable';
COMMENT ON COLUMN landing_page_analyses.classification IS 'Skill 1 output: awareness level, sophistication, architecture, demographics, persona';
COMMENT ON COLUMN landing_page_analyses.elements IS 'Skill 2 output: detected elements by section with subtypes';
COMMENT ON COLUMN landing_page_analyses.gap_analysis IS 'Skill 3 output: critical/moderate/minor gaps, flow issues, quick wins';
COMMENT ON COLUMN landing_page_analyses.copy_scores IS 'Skill 4 output: per-element scores and compliance flags';
COMMENT ON COLUMN landing_page_analyses.status IS 'Processing status: pending, processing, completed, partial (some skills failed), failed';
