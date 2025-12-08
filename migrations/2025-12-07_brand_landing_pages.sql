-- Migration: Add brand_landing_pages table for landing page scraping
-- Date: 2025-12-07
-- Purpose: Store scraped landing pages from ad link_urls for brand research

-- Create brand_landing_pages table
CREATE TABLE IF NOT EXISTS brand_landing_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,

    -- Source info
    url TEXT NOT NULL,
    source_ad_id UUID REFERENCES facebook_ads(id) ON DELETE SET NULL,

    -- Scraped content
    page_title TEXT,
    meta_description TEXT,
    raw_markdown TEXT,

    -- AI-extracted structured data
    extracted_data JSONB DEFAULT '{}',

    -- Individual extracted fields for querying
    product_name TEXT,
    pricing JSONB DEFAULT '{}',
    benefits TEXT[] DEFAULT '{}',
    features TEXT[] DEFAULT '{}',
    testimonials JSONB DEFAULT '[]',
    social_proof TEXT[] DEFAULT '{}',
    call_to_action TEXT,
    objection_handling JSONB DEFAULT '[]',
    guarantee TEXT,
    urgency_elements TEXT[] DEFAULT '{}',

    -- AI analysis
    analysis_raw JSONB DEFAULT '{}',
    copy_patterns JSONB DEFAULT '{}',
    persona_signals JSONB DEFAULT '{}',

    -- Metadata
    scrape_status TEXT DEFAULT 'pending' CHECK (scrape_status IN ('pending', 'scraped', 'analyzed', 'failed')),
    scrape_error TEXT,
    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    model_used TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_brand_landing_pages_brand_id ON brand_landing_pages(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_landing_pages_url ON brand_landing_pages(url);
CREATE INDEX IF NOT EXISTS idx_brand_landing_pages_status ON brand_landing_pages(scrape_status);

-- Unique constraint to prevent duplicate URLs per brand
CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_landing_pages_brand_url
ON brand_landing_pages(brand_id, url);

-- Comments
COMMENT ON TABLE brand_landing_pages IS 'Scraped landing pages from ad link_urls for brand research persona synthesis';
COMMENT ON COLUMN brand_landing_pages.raw_markdown IS 'Full page content as markdown from FireCrawl';
COMMENT ON COLUMN brand_landing_pages.extracted_data IS 'Structured data extracted by FireCrawl LLM';
COMMENT ON COLUMN brand_landing_pages.analysis_raw IS 'Full AI analysis response for persona signals';
COMMENT ON COLUMN brand_landing_pages.copy_patterns IS 'Identified copywriting patterns for ad generation';
COMMENT ON COLUMN brand_landing_pages.persona_signals IS 'Extracted persona signals for synthesis';

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_brand_landing_pages_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_brand_landing_pages_updated_at ON brand_landing_pages;
CREATE TRIGGER trigger_brand_landing_pages_updated_at
    BEFORE UPDATE ON brand_landing_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_brand_landing_pages_updated_at();
