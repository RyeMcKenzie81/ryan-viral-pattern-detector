-- Add video_type field to posts table
-- Date: 2025-10-16
-- Purpose: Track whether a video is a Short, regular video, or stream
--          This is critical for YouTube content as Shorts, videos, and streams
--          perform very differently and must be analyzed separately.

-- Add video_type column to posts table
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'posts' AND column_name = 'video_type'
  ) THEN
    ALTER TABLE posts ADD COLUMN video_type text
      CHECK (video_type IN ('short', 'video', 'stream', 'reel', 'post'));
    CREATE INDEX idx_posts_video_type ON posts(video_type);
  END IF;
END $$;

COMMENT ON COLUMN posts.video_type IS 'Type of video content: short (YT Shorts/TikTok), video (YT long-form), stream (live), reel (IG Reels), post (IG static)';

-- Verification query
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'posts' AND column_name = 'video_type';
