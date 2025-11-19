-- Add shares column to posts table for platforms that track shares/retweets
-- Twitter: retweets
-- TikTok: shareCount
-- Instagram: shares (if available)
-- YouTube: N/A (no native share count)

ALTER TABLE posts ADD COLUMN IF NOT EXISTS shares bigint;

COMMENT ON COLUMN posts.shares IS 'Share/retweet count - platform-specific (Twitter retweets, TikTok shares, etc.)';
