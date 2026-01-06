-- Migration: Client Onboarding Sessions
-- Date: 2026-01-07
-- Purpose: Track client onboarding progress with section-level data storage
-- Part of: Client Onboarding Pipeline

-- ============================================
-- Table: client_onboarding_sessions
-- Stores all data collected during client onboarding process
-- ============================================
CREATE TABLE IF NOT EXISTS client_onboarding_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Session identification
    session_name TEXT NOT NULL,
    client_name TEXT,

    -- Link to brand if created during import
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,

    -- Session status
    status TEXT DEFAULT 'in_progress' CHECK (status IN (
        'in_progress',      -- Actively being filled
        'awaiting_info',    -- Waiting for client response
        'ready_for_import', -- All required data collected
        'imported',         -- Imported to production tables
        'archived'          -- No longer active
    )),

    -- Section-level data (JSONB for flexibility)
    -- Schema: {"name": str, "website_url": str, "logo_storage_path": str, "brand_voice": str, "scraped_website_data": {...}}
    brand_basics JSONB DEFAULT '{}',

    -- Schema: {"page_url": str, "ad_library_url": str, "ad_account_id": str, "page_id": str, "scraped_ads_count": int, "scraped_at": timestamp}
    facebook_meta JSONB DEFAULT '{}',

    -- Schema: {"products": [{"url": str, "asin": str, "domain": str, "scraped_reviews_count": int, "scraped_at": timestamp}]}
    amazon_data JSONB DEFAULT '{}',

    -- Schema: {"images": [{"storage_path": str, "has_transparent_bg": bool, "notes": str}], "dimensions": {"width": str, "height": str, "depth": str, "unit": str}, "weight": {"value": float, "unit": str}}
    product_assets JSONB DEFAULT '{}',

    -- Schema: [{"name": str, "website_url": str, "amazon_url": str, "facebook_page_url": str, "ad_library_url": str, "scraped": bool}]
    competitors JSONB DEFAULT '[]',

    -- Schema: {"demographics": {"age_range": str, "gender": str, "location": str, "income_level": str}, "pain_points": [str], "desires_goals": [str], "notes": str}
    target_audience JSONB DEFAULT '{}',

    -- Completeness tracking
    completeness_score DECIMAL(5,2) DEFAULT 0,
    missing_fields JSONB DEFAULT '[]',

    -- Interview questions (AI-generated)
    interview_questions JSONB DEFAULT '[]',
    interview_questions_generated_at TIMESTAMPTZ,

    -- Scraping status tracking
    -- Schema: {"website": {"status": "pending|running|complete|failed", "started_at": ts, "error": str}, "facebook_ads": {...}, "amazon_reviews": {...}, "competitors": {...}}
    scrape_jobs JSONB DEFAULT '{}',

    -- Notes and context
    notes TEXT,
    call_transcript TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_client_onboarding_sessions_status
    ON client_onboarding_sessions(status);

CREATE INDEX IF NOT EXISTS idx_client_onboarding_sessions_brand_id
    ON client_onboarding_sessions(brand_id);

CREATE INDEX IF NOT EXISTS idx_client_onboarding_sessions_created_at
    ON client_onboarding_sessions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_client_onboarding_sessions_updated_at
    ON client_onboarding_sessions(updated_at DESC);

-- ============================================
-- Trigger: Auto-update updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_client_onboarding_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_client_onboarding_updated_at ON client_onboarding_sessions;
CREATE TRIGGER trigger_client_onboarding_updated_at
    BEFORE UPDATE ON client_onboarding_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_client_onboarding_updated_at();

-- ============================================
-- Comments
-- ============================================
COMMENT ON TABLE client_onboarding_sessions IS 'Tracks client onboarding progress with section-level data storage for the Client Onboarding Pipeline';
COMMENT ON COLUMN client_onboarding_sessions.brand_basics IS 'Brand name, website, logo, voice - JSON schema: {name, website_url, logo_storage_path, brand_voice, scraped_website_data}';
COMMENT ON COLUMN client_onboarding_sessions.facebook_meta IS 'Facebook page and ad library info - JSON schema: {page_url, ad_library_url, ad_account_id, page_id, scraped_ads_count, scraped_at}';
COMMENT ON COLUMN client_onboarding_sessions.amazon_data IS 'Amazon product URLs and ASINs - JSON schema: {products: [{url, asin, domain, scraped_reviews_count, scraped_at}]}';
COMMENT ON COLUMN client_onboarding_sessions.product_assets IS 'Product images and dimensions - JSON schema: {images: [], dimensions: {width, height, depth, unit}, weight: {value, unit}}';
COMMENT ON COLUMN client_onboarding_sessions.competitors IS 'Competitor information array - JSON schema: [{name, website_url, amazon_url, facebook_page_url, ad_library_url, scraped}]';
COMMENT ON COLUMN client_onboarding_sessions.target_audience IS 'Target audience info - JSON schema: {demographics: {age_range, gender, location, income_level}, pain_points: [], desires_goals: [], notes}';
COMMENT ON COLUMN client_onboarding_sessions.completeness_score IS 'Percentage of required and nice-to-have fields filled (0-100)';
COMMENT ON COLUMN client_onboarding_sessions.interview_questions IS 'AI-generated questions to ask client for missing info - JSON array of strings';
COMMENT ON COLUMN client_onboarding_sessions.scrape_jobs IS 'Tracks status of scraping operations - JSON schema: {type: {status, started_at, error}}';
