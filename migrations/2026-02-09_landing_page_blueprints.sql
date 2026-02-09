-- Migration: Create landing_page_blueprints table
-- Date: 2026-02-09
-- Purpose: Store reconstruction blueprints mapping competitor analysis to brand-specific creative briefs

CREATE TABLE IF NOT EXISTS landing_page_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    analysis_id UUID NOT NULL REFERENCES landing_page_analyses(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID NOT NULL REFERENCES products(id),
    offer_variant_id UUID,

    -- Blueprint output
    blueprint JSONB NOT NULL DEFAULT '{}',
    source_url TEXT,

    -- Denormalized counts for listing
    sections_count INTEGER DEFAULT 0,
    elements_mapped INTEGER DEFAULT 0,
    content_needed_count INTEGER DEFAULT 0,

    -- Snapshot of brand profile used for generation (audit trail)
    brand_profile_snapshot JSONB DEFAULT '{}',
    content_gaps JSONB DEFAULT '[]',

    -- Metadata
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,
    processing_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_landing_page_blueprints_org ON landing_page_blueprints(organization_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_blueprints_analysis ON landing_page_blueprints(analysis_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_blueprints_brand ON landing_page_blueprints(brand_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_blueprints_product ON landing_page_blueprints(product_id);
CREATE INDEX IF NOT EXISTS idx_landing_page_blueprints_created ON landing_page_blueprints(created_at DESC);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_landing_page_blueprints_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_landing_page_blueprints_updated_at ON landing_page_blueprints;
CREATE TRIGGER trigger_landing_page_blueprints_updated_at
    BEFORE UPDATE ON landing_page_blueprints
    FOR EACH ROW
    EXECUTE FUNCTION update_landing_page_blueprints_updated_at();

-- RLS
ALTER TABLE landing_page_blueprints ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow authenticated users to read landing_page_blueprints"
    ON landing_page_blueprints FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Allow authenticated users to insert landing_page_blueprints"
    ON landing_page_blueprints FOR INSERT
    TO authenticated
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users to update landing_page_blueprints"
    ON landing_page_blueprints FOR UPDATE
    TO authenticated
    USING (true);

COMMENT ON TABLE landing_page_blueprints IS 'Reconstruction blueprints mapping competitor analysis to brand-specific creative briefs';
COMMENT ON COLUMN landing_page_blueprints.analysis_id IS 'FK to the source landing page analysis (Skills 1-4 results)';
COMMENT ON COLUMN landing_page_blueprints.offer_variant_id IS 'FK to product_offer_variants for mechanism/hooks context (optional, uses default if null)';
COMMENT ON COLUMN landing_page_blueprints.blueprint IS 'Skill 5 output: section-by-section reconstruction brief with element mappings';
COMMENT ON COLUMN landing_page_blueprints.brand_profile_snapshot IS 'Snapshot of brand profile used at generation time for audit trail';
COMMENT ON COLUMN landing_page_blueprints.content_gaps IS 'List of content gaps detected: fields where brand data was missing';
