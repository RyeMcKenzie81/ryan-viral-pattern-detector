-- Add Twitter platform
-- Date: 2025-10-16
-- Purpose: Add Twitter as a supported platform for viral content analysis

-- Insert Twitter platform
INSERT INTO platforms (name, slug, scraper_config, max_video_length_sec, typical_video_length_sec)
VALUES (
    'Twitter',
    'twitter',
    '{
        "actor_id": "apidojo/tweet-scraper",
        "default_post_type": "tweet",
        "supports_search": true,
        "supports_account_scraping": true
    }'::jsonb,
    NULL,  -- No video length limits (text posts supported)
    NULL   -- Varied content types
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    scraper_config = EXCLUDED.scraper_config,
    max_video_length_sec = EXCLUDED.max_video_length_sec,
    typical_video_length_sec = EXCLUDED.typical_video_length_sec;

-- Verification query
SELECT id, name, slug, scraper_config
FROM platforms
WHERE slug = 'twitter';
