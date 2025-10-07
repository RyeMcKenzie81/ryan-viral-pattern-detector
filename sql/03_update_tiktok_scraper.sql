-- ============================================================================
-- Update TikTok Platform Scraper Configuration
-- ============================================================================
-- Purpose: Configure TikTok platform to use ScrapTik API (Apify)
--
-- ScrapTik Details:
-- - Actor: scraptik~tiktok-api
-- - Pricing: $0.002 per request (flat rate)
-- - Features: Search, hashtags, user posts, video downloads, comments
-- ============================================================================

UPDATE platforms
SET
  scraper_type = 'apify',
  scraper_config = jsonb_build_object(
    'actor_id', 'scraptik~tiktok-api',
    'default_post_type', 'videos',
    'cost_per_request', 0.002,
    'endpoints', jsonb_build_object(
      'search_posts', 'searchPosts',
      'hashtag_posts', 'challengePosts',
      'user_posts', 'userPosts',
      'get_post', 'get-post',
      'video_download', 'video-without-watermark',
      'list_comments', 'list-comments'
    )
  ),
  max_video_length_sec = 600,
  typical_video_length_sec = 30,
  aspect_ratio = '9:16',
  updated_at = now()
WHERE slug = 'tiktok';

-- Verify the update
SELECT
  name,
  slug,
  scraper_type,
  scraper_config,
  max_video_length_sec,
  aspect_ratio
FROM platforms
WHERE slug = 'tiktok';
