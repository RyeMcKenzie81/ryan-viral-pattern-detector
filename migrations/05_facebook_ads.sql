-- Facebook Ads Library Integration
-- Stores all ads from Facebook Ad Library with full metadata

-- Create facebook_ads table
CREATE TABLE IF NOT EXISTS facebook_ads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Core identifiers
    ad_id TEXT,
    ad_archive_id TEXT UNIQUE NOT NULL,
    account_id UUID REFERENCES accounts(id),
    platform_id UUID NOT NULL REFERENCES platforms(id),

    -- Ad metadata
    categories JSONB,
    archive_types JSONB,
    entity_type TEXT,
    is_active BOOLEAN DEFAULT false,
    is_profile_page BOOLEAN DEFAULT false,

    -- Creative & content
    snapshot JSONB,
    contains_digital_media BOOLEAN DEFAULT false,

    -- Dates
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,

    -- Financial & reach
    currency TEXT,
    spend TEXT,
    impressions TEXT,
    reach_estimate TEXT,

    -- Political & transparency
    political_countries JSONB,
    state_media_label TEXT,
    is_aaa_eligible BOOLEAN DEFAULT false,
    aaa_info JSONB,

    -- Platform & delivery
    publisher_platform JSONB,
    gated_type TEXT,

    -- Collation & grouping
    collation_id TEXT,
    collation_count INTEGER DEFAULT 0,

    -- Safety & moderation
    has_user_reported BOOLEAN DEFAULT false,
    report_count INTEGER DEFAULT 0,
    hide_data_status TEXT,
    hidden_safety_data JSONB,

    -- Additional data
    advertiser JSONB,
    insights JSONB,
    menu_items JSONB,

    -- Import tracking
    import_source TEXT DEFAULT 'facebook_ads_scrape',
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for facebook_ads
CREATE INDEX IF NOT EXISTS idx_facebook_ads_ad_id ON facebook_ads(ad_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_ad_archive_id ON facebook_ads(ad_archive_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_account_id ON facebook_ads(account_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_platform_id ON facebook_ads(platform_id);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_is_active ON facebook_ads(is_active);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_start_date ON facebook_ads(start_date);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_end_date ON facebook_ads(end_date);
CREATE INDEX IF NOT EXISTS idx_facebook_ads_scraped_at ON facebook_ads(scraped_at);

-- Create project_facebook_ads linking table
CREATE TABLE IF NOT EXISTS project_facebook_ads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ad_id UUID NOT NULL REFERENCES facebook_ads(id) ON DELETE CASCADE,
    import_method TEXT DEFAULT 'facebook_ads_scrape',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(project_id, ad_id)
);

-- Indexes for project_facebook_ads
CREATE INDEX IF NOT EXISTS idx_project_facebook_ads_project_id ON project_facebook_ads(project_id);
CREATE INDEX IF NOT EXISTS idx_project_facebook_ads_ad_id ON project_facebook_ads(ad_id);

-- Create brand_facebook_ads linking table
CREATE TABLE IF NOT EXISTS brand_facebook_ads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    ad_id UUID NOT NULL REFERENCES facebook_ads(id) ON DELETE CASCADE,
    import_method TEXT DEFAULT 'facebook_ads_scrape',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, ad_id)
);

-- Indexes for brand_facebook_ads
CREATE INDEX IF NOT EXISTS idx_brand_facebook_ads_brand_id ON brand_facebook_ads(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_facebook_ads_ad_id ON brand_facebook_ads(ad_id);

-- Add Facebook platform if it doesn't exist
INSERT INTO platforms (name, slug, created_at)
VALUES ('Facebook', 'facebook', NOW())
ON CONFLICT (slug) DO NOTHING;

-- Comments
COMMENT ON TABLE facebook_ads IS 'Facebook ads from Ad Library with full metadata including spend, reach, and political transparency';
COMMENT ON TABLE project_facebook_ads IS 'Links Facebook ads to projects for analysis';
COMMENT ON TABLE brand_facebook_ads IS 'Links Facebook ads to brands for competitor analysis';
