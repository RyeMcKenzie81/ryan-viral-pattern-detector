-- Migration: Extract valuable fields from facebook_ads snapshot to dedicated columns
-- Date: 2025-12-04
-- Purpose: Enable easy querying of landing pages, CTAs, and ad copy for research

-- ============================================================================
-- STEP 1: Add new columns
-- ============================================================================

-- Landing page URL (for competitor/funnel research)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS link_url TEXT;
COMMENT ON COLUMN facebook_ads.link_url IS 'Landing page URL the ad points to';

-- CTA fields (for CTA pattern analysis)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS cta_text TEXT;
COMMENT ON COLUMN facebook_ads.cta_text IS 'Call-to-action button text (Learn more, Shop now, etc.)';

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS cta_type TEXT;
COMMENT ON COLUMN facebook_ads.cta_type IS 'CTA type enum (LEARN_MORE, SHOP_NOW, SIGN_UP, etc.)';

-- Ad copy fields (for copy analysis)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS ad_title TEXT;
COMMENT ON COLUMN facebook_ads.ad_title IS 'Ad headline/title';

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS ad_body TEXT;
COMMENT ON COLUMN facebook_ads.ad_body IS 'Primary ad text/body copy';

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS caption TEXT;
COMMENT ON COLUMN facebook_ads.caption IS 'Link caption (often shows domain + offer)';

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS link_description TEXT;
COMMENT ON COLUMN facebook_ads.link_description IS 'Link preview description text';

-- Page metrics (for authority/reach analysis)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_like_count INTEGER;
COMMENT ON COLUMN facebook_ads.page_like_count IS 'Number of page likes at time of scrape';

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_profile_uri TEXT;
COMMENT ON COLUMN facebook_ads.page_profile_uri IS 'Facebook page URL';

-- Ad format (for creative type analysis)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS display_format TEXT;
COMMENT ON COLUMN facebook_ads.display_format IS 'Ad display format (DCO, VIDEO, IMAGE, CAROUSEL, etc.)';

-- ============================================================================
-- STEP 2: Backfill from existing snapshot data
-- ============================================================================

-- Extract link_url
UPDATE facebook_ads
SET link_url = snapshot->>'link_url'
WHERE link_url IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'link_url' IS NOT NULL;

-- Extract cta_text
UPDATE facebook_ads
SET cta_text = snapshot->>'cta_text'
WHERE cta_text IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'cta_text' IS NOT NULL;

-- Extract cta_type
UPDATE facebook_ads
SET cta_type = snapshot->>'cta_type'
WHERE cta_type IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'cta_type' IS NOT NULL;

-- Extract title
UPDATE facebook_ads
SET ad_title = snapshot->>'title'
WHERE ad_title IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'title' IS NOT NULL;

-- Extract body text (nested in body.text)
UPDATE facebook_ads
SET ad_body = snapshot->'body'->>'text'
WHERE ad_body IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->'body'->>'text' IS NOT NULL;

-- Extract caption
UPDATE facebook_ads
SET caption = snapshot->>'caption'
WHERE caption IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'caption' IS NOT NULL;

-- Extract link_description
UPDATE facebook_ads
SET link_description = snapshot->>'link_description'
WHERE link_description IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'link_description' IS NOT NULL;

-- Extract page_like_count
UPDATE facebook_ads
SET page_like_count = (snapshot->>'page_like_count')::INTEGER
WHERE page_like_count IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'page_like_count' IS NOT NULL;

-- Extract page_profile_uri
UPDATE facebook_ads
SET page_profile_uri = snapshot->>'page_profile_uri'
WHERE page_profile_uri IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'page_profile_uri' IS NOT NULL;

-- Extract display_format
UPDATE facebook_ads
SET display_format = snapshot->>'display_format'
WHERE display_format IS NULL
  AND snapshot IS NOT NULL
  AND snapshot->>'display_format' IS NOT NULL;

-- ============================================================================
-- STEP 3: Create indexes for common queries
-- ============================================================================

-- Index on link_url for landing page analysis (domain extraction)
CREATE INDEX IF NOT EXISTS idx_facebook_ads_link_url ON facebook_ads(link_url);

-- Index on cta_type for CTA pattern analysis
CREATE INDEX IF NOT EXISTS idx_facebook_ads_cta_type ON facebook_ads(cta_type);

-- Index on display_format for ad type analysis
CREATE INDEX IF NOT EXISTS idx_facebook_ads_display_format ON facebook_ads(display_format);

-- ============================================================================
-- VERIFICATION: Check backfill results
-- ============================================================================

-- Run this query to verify the backfill worked:
-- SELECT
--     COUNT(*) as total_ads,
--     COUNT(link_url) as has_link_url,
--     COUNT(cta_text) as has_cta_text,
--     COUNT(caption) as has_caption,
--     COUNT(page_like_count) as has_page_likes
-- FROM facebook_ads;
