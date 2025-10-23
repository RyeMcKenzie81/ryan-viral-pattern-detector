-- Comment Finder V1.1 - Feature 1.1: Tweet Metadata in CSV Export
-- Adds FK constraint between generated_comments and posts for tweet metadata access
-- Date: 2025-10-22

-- ============================================================================
-- PART 1: Data Integrity Checks
-- ============================================================================

-- Check 1: Verify post_id is unique in posts table (required for FK)
DO $$
DECLARE
    duplicate_count INTEGER;
BEGIN
    SELECT COUNT(*) - COUNT(DISTINCT post_id)
    INTO duplicate_count
    FROM public.posts;

    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'Found % duplicate post_id values in posts table. Cannot create unique constraint.', duplicate_count;
    ELSE
        RAISE NOTICE 'Check 1 passed: All post_id values in posts table are unique';
    END IF;
END $$;

-- Check 2: Verify all tweet_ids in generated_comments exist in posts
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(DISTINCT gc.tweet_id)
    INTO orphan_count
    FROM public.generated_comments gc
    LEFT JOIN public.posts p ON gc.tweet_id = p.post_id
    WHERE p.post_id IS NULL;

    IF orphan_count > 0 THEN
        RAISE WARNING 'Found % orphaned tweet_ids in generated_comments that do not exist in posts table', orphan_count;
        RAISE WARNING 'Run this query to see them: SELECT DISTINCT tweet_id FROM generated_comments gc LEFT JOIN posts p ON gc.tweet_id = p.post_id WHERE p.post_id IS NULL';
    ELSE
        RAISE NOTICE 'Check 2 passed: All tweet_ids in generated_comments exist in posts table';
    END IF;
END $$;


-- ============================================================================
-- PART 2: Add Unique Constraint on posts.post_id
-- ============================================================================

-- Add unique constraint to posts.post_id (required for FK reference)
-- post_id should be unique anyway since it stores the platform's unique ID
ALTER TABLE public.posts
ADD CONSTRAINT uq_posts_post_id UNIQUE (post_id);

COMMENT ON CONSTRAINT uq_posts_post_id ON public.posts
IS 'Ensures post_id (platform ID) is unique, enabling FK references';


-- ============================================================================
-- PART 3: Add Foreign Key Constraint
-- ============================================================================

-- Add FK constraint from generated_comments.tweet_id to posts.post_id
-- Note: posts.post_id is a text field containing the Twitter tweet ID
-- This allows the export query to JOIN and retrieve tweet metadata

ALTER TABLE public.generated_comments
ADD CONSTRAINT fk_generated_comments_tweet_id
FOREIGN KEY (tweet_id)
REFERENCES public.posts(post_id)
ON DELETE CASCADE;  -- If tweet is deleted, delete associated comment suggestions

COMMENT ON CONSTRAINT fk_generated_comments_tweet_id ON public.generated_comments
IS 'Links comment suggestions to tweet data in posts table for metadata access';


-- ============================================================================
-- PART 4: Add Performance Index
-- ============================================================================

-- Add index on tweet_id for faster JOINs during export
-- This improves performance when querying generated_comments with posts
CREATE INDEX IF NOT EXISTS idx_generated_comments_tweet_id
ON public.generated_comments(tweet_id);


-- ============================================================================
-- PART 5: VERIFICATION QUERIES
-- ============================================================================

-- Verify unique constraint was added
SELECT
    conname AS constraint_name,
    conrelid::regclass AS table_name,
    contype AS constraint_type
FROM pg_constraint
WHERE conname = 'uq_posts_post_id';

-- Verify FK constraint was added
SELECT
    conname AS constraint_name,
    conrelid::regclass AS table_name,
    confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE conname = 'fk_generated_comments_tweet_id';

-- Verify index was created
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE indexname = 'idx_generated_comments_tweet_id';

-- Test JOIN (should return data if comments exist)
SELECT
    gc.id,
    gc.tweet_id,
    p.caption AS tweet_text,
    p.posted_at,
    a.platform_username AS author,
    a.follower_count AS author_followers
FROM public.generated_comments gc
JOIN public.posts p ON gc.tweet_id = p.post_id
LEFT JOIN public.accounts a ON p.account_id = a.id
LIMIT 5;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration complete: Constraints and index added successfully';
    RAISE NOTICE '   - Unique constraint: posts.post_id (uq_posts_post_id)';
    RAISE NOTICE '   - FK constraint: generated_comments.tweet_id → posts.post_id';
    RAISE NOTICE '   - Index: idx_generated_comments_tweet_id';
    RAISE NOTICE '   - Next step: Update export query in viraltracker/cli/twitter.py';
END $$;
