-- Migration: Asset pipeline hardening + expanded Meta metrics
-- Date: 2026-02-11
-- Purpose: Store object_type, track download failure reasons,
--          add e-commerce and video engagement metric columns.

-- Part A: Asset pipeline hardening
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS object_type TEXT;

ALTER TABLE meta_ad_assets
    ADD COLUMN IF NOT EXISTS not_downloadable_reason TEXT;

COMMENT ON COLUMN meta_ads_performance.object_type IS
    'AdCreative object_type from Meta API (e.g. VIDEO, SHARE, PHOTO)';
COMMENT ON COLUMN meta_ad_assets.not_downloadable_reason IS
    'Why the asset could not be downloaded (no_source_url, no_url_from_api, http_403, download_error, etc.)';

-- Part B: Expanded metrics
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS initiate_checkouts INTEGER;
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS landing_page_views INTEGER;
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS content_views INTEGER;
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS cost_per_initiate_checkout NUMERIC(10,4);
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS video_p95_watched INTEGER;
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS video_thruplay INTEGER;
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS hold_rate NUMERIC(10,4);
ALTER TABLE meta_ads_performance
    ADD COLUMN IF NOT EXISTS hook_rate NUMERIC(10,4);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_meta_ads_perf_brand_is_video
    ON meta_ads_performance(brand_id, is_video);
CREATE INDEX IF NOT EXISTS idx_meta_ad_assets_brand_status
    ON meta_ad_assets(brand_id, status);

-- Comments
COMMENT ON COLUMN meta_ads_performance.initiate_checkouts IS 'Initiate checkout actions from Meta actions array';
COMMENT ON COLUMN meta_ads_performance.landing_page_views IS 'Landing page view actions from Meta actions array';
COMMENT ON COLUMN meta_ads_performance.content_views IS 'View content actions (fb_pixel_view_content) from Meta actions array';
COMMENT ON COLUMN meta_ads_performance.cost_per_initiate_checkout IS 'Cost per initiate checkout from Meta cost_per_action_type';
COMMENT ON COLUMN meta_ads_performance.video_p95_watched IS '95% video completion views';
COMMENT ON COLUMN meta_ads_performance.video_thruplay IS 'ThruPlay views (15s or full completion)';
COMMENT ON COLUMN meta_ads_performance.hold_rate IS 'ThruPlay / 3-sec video views (0-1). Measures ability to retain viewer past the hook.';
COMMENT ON COLUMN meta_ads_performance.hook_rate IS '3-sec video views / impressions (0-1). Measures ability to stop the scroll.';
