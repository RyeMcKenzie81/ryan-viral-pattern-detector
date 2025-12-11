-- Migration: Amazon Review Scraping System
-- Date: 2025-12-08
-- Purpose: Add tables for storing Amazon product URLs, reviews, and analysis
-- Part of Sprint 3.5: Amazon Review Scraping

-- ============================================================================
-- Table: amazon_product_urls
-- Links products to their Amazon listings for review scraping
-- ============================================================================
CREATE TABLE IF NOT EXISTS amazon_product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    amazon_url TEXT NOT NULL,
    asin TEXT NOT NULL,
    domain_code TEXT NOT NULL DEFAULT 'com',

    -- Scrape tracking
    last_scraped_at TIMESTAMPTZ,
    total_reviews_scraped INTEGER DEFAULT 0,
    scrape_cost_estimate DECIMAL(10,4),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Each product can only have one entry per ASIN
    UNIQUE(product_id, asin)
);

COMMENT ON TABLE amazon_product_urls IS 'Links products to Amazon listings for review scraping';
COMMENT ON COLUMN amazon_product_urls.asin IS 'Amazon Standard Identification Number (10 chars)';
COMMENT ON COLUMN amazon_product_urls.domain_code IS 'Amazon domain: com, ca, co.uk, de, etc.';
COMMENT ON COLUMN amazon_product_urls.scrape_cost_estimate IS 'Estimated Apify cost for scraping';

-- Indexes for amazon_product_urls
CREATE INDEX IF NOT EXISTS idx_amazon_product_urls_product ON amazon_product_urls(product_id);
CREATE INDEX IF NOT EXISTS idx_amazon_product_urls_brand ON amazon_product_urls(brand_id);
CREATE INDEX IF NOT EXISTS idx_amazon_product_urls_asin ON amazon_product_urls(asin);


-- ============================================================================
-- Table: amazon_reviews
-- Individual reviews scraped from Amazon
-- ============================================================================
CREATE TABLE IF NOT EXISTS amazon_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    amazon_product_url_id UUID NOT NULL REFERENCES amazon_product_urls(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Amazon review data
    review_id TEXT NOT NULL,
    asin TEXT NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    title TEXT,
    body TEXT,
    author TEXT,
    review_date DATE,
    verified_purchase BOOLEAN DEFAULT FALSE,
    helpful_votes INTEGER DEFAULT 0,

    -- Scrape metadata (for debugging/analysis)
    scrape_source TEXT,
    scrape_filter TEXT,

    scraped_at TIMESTAMPTZ DEFAULT NOW(),

    -- Dedupe constraint: one review per ASIN
    UNIQUE(review_id, asin)
);

COMMENT ON TABLE amazon_reviews IS 'Individual Amazon reviews scraped via Apify';
COMMENT ON COLUMN amazon_reviews.review_id IS 'Amazon internal review ID for deduplication';
COMMENT ON COLUMN amazon_reviews.scrape_source IS 'How review was found: star_filter, keyword_filter, helpful_sort';
COMMENT ON COLUMN amazon_reviews.scrape_filter IS 'Specific filter used: five_star, great, etc.';

-- Indexes for amazon_reviews
CREATE INDEX IF NOT EXISTS idx_amazon_reviews_product ON amazon_reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_amazon_reviews_brand ON amazon_reviews(brand_id);
CREATE INDEX IF NOT EXISTS idx_amazon_reviews_rating ON amazon_reviews(rating);
CREATE INDEX IF NOT EXISTS idx_amazon_reviews_asin ON amazon_reviews(asin);
CREATE INDEX IF NOT EXISTS idx_amazon_reviews_amazon_url ON amazon_reviews(amazon_product_url_id);


-- ============================================================================
-- Table: amazon_review_analysis
-- Aggregated AI analysis of reviews per product
-- ============================================================================
CREATE TABLE IF NOT EXISTS amazon_review_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Analysis metadata
    total_reviews_analyzed INTEGER,
    sentiment_distribution JSONB,

    -- Extracted persona signals (the gold!)
    pain_points JSONB,
    desires JSONB,
    language_patterns JSONB,
    objections JSONB,
    purchase_triggers JSONB,

    -- Verbatim quotes for ad copy
    top_positive_quotes TEXT[],
    top_negative_quotes TEXT[],
    transformation_quotes TEXT[],

    -- Meta
    model_used TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),

    -- One analysis per product
    UNIQUE(product_id)
);

COMMENT ON TABLE amazon_review_analysis IS 'AI-extracted persona signals from Amazon reviews';
COMMENT ON COLUMN amazon_review_analysis.pain_points IS 'Categorized pain points: {emotional: [], functional: [], social: []}';
COMMENT ON COLUMN amazon_review_analysis.desires IS 'Categorized desires: {emotional: [], functional: [], social: []}';
COMMENT ON COLUMN amazon_review_analysis.language_patterns IS 'Customer language: {positive_phrases: [], negative_phrases: [], descriptive_words: []}';
COMMENT ON COLUMN amazon_review_analysis.top_positive_quotes IS 'Best verbatim quotes for ad copy';
COMMENT ON COLUMN amazon_review_analysis.transformation_quotes IS 'Before/after transformation language';

-- Indexes for amazon_review_analysis
CREATE INDEX IF NOT EXISTS idx_amazon_review_analysis_product ON amazon_review_analysis(product_id);
CREATE INDEX IF NOT EXISTS idx_amazon_review_analysis_brand ON amazon_review_analysis(brand_id);
