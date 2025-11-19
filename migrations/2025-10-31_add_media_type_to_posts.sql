-- Migration: Add media type tracking to posts table
-- Date: 2025-10-31
-- Purpose: Track media type for better outlier filtering and hook analysis

-- Add media type columns
ALTER TABLE posts
ADD COLUMN has_video BOOLEAN DEFAULT false,
ADD COLUMN has_image BOOLEAN DEFAULT false,
ADD COLUMN has_media BOOLEAN DEFAULT false,
ADD COLUMN media_type VARCHAR(20);

-- Add index for filtering
CREATE INDEX idx_posts_media_type ON posts(media_type);
CREATE INDEX idx_posts_has_video ON posts(has_video);

-- Comment
COMMENT ON COLUMN posts.has_video IS 'True if post contains video content';
COMMENT ON COLUMN posts.has_image IS 'True if post contains image content';
COMMENT ON COLUMN posts.has_media IS 'True if post has any media (video, image, etc.)';
COMMENT ON COLUMN posts.media_type IS 'Primary media type: text, image, video, mixed, poll, quote';

-- Backfill existing posts with media detection based on heuristics
-- Posts with length_sec > 0 are videos (for TikTok/YouTube)
UPDATE posts
SET
    has_video = true,
    has_media = true,
    media_type = 'video'
WHERE length_sec IS NOT NULL AND length_sec > 0;

-- Posts with t.co links likely have media, but we can't determine type without re-scraping
-- For now, mark as unknown/text
UPDATE posts
SET media_type = 'text'
WHERE media_type IS NULL;
