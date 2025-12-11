-- Migration: Add Amazon URL support to competitors
-- Date: 2025-12-10
-- Purpose: Allow competitors to have Amazon product URLs for review scraping

-- Add amazon_url column to competitors table
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS amazon_url text;

COMMENT ON COLUMN competitors.amazon_url IS 'Amazon product URL for review scraping';

-- Create competitor_amazon_urls table (mirrors amazon_product_urls structure)
CREATE TABLE IF NOT EXISTS competitor_amazon_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    amazon_url TEXT NOT NULL,
    asin TEXT NOT NULL,
    domain_code TEXT NOT NULL DEFAULT 'com',
    last_scraped_at TIMESTAMPTZ,
    total_reviews_scraped INTEGER DEFAULT 0,
    scrape_cost_estimate FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competitor_id, asin)
);

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_urls_competitor ON competitor_amazon_urls(competitor_id);

COMMENT ON TABLE competitor_amazon_urls IS 'Amazon product URLs for competitor review scraping';

-- Create competitor_amazon_reviews table (mirrors amazon_reviews structure)
CREATE TABLE IF NOT EXISTS competitor_amazon_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_amazon_url_id UUID NOT NULL REFERENCES competitor_amazon_urls(id) ON DELETE CASCADE,
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    review_id TEXT NOT NULL,
    asin TEXT NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    title TEXT,
    body TEXT,
    author TEXT,
    review_date DATE,
    verified_purchase BOOLEAN DEFAULT false,
    helpful_votes INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(review_id, asin)
);

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_reviews_competitor ON competitor_amazon_reviews(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_amazon_reviews_rating ON competitor_amazon_reviews(rating);

COMMENT ON TABLE competitor_amazon_reviews IS 'Amazon reviews for competitor products';

-- Create competitor_amazon_review_analysis table
CREATE TABLE IF NOT EXISTS competitor_amazon_review_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE UNIQUE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    total_reviews_analyzed INTEGER DEFAULT 0,
    sentiment_distribution JSONB DEFAULT '{}',
    pain_points JSONB DEFAULT '{}',
    desires JSONB DEFAULT '{}',
    language_patterns JSONB DEFAULT '{}',
    objections JSONB DEFAULT '{}',
    purchase_triggers TEXT[],
    transformation JSONB DEFAULT '{}',
    transformation_quotes TEXT[],
    top_positive_quotes TEXT[],
    top_negative_quotes TEXT[],
    model_used TEXT,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_analysis_competitor ON competitor_amazon_review_analysis(competitor_id);

COMMENT ON TABLE competitor_amazon_review_analysis IS 'AI analysis of competitor Amazon reviews';
