-- ============================================================================
-- Account Metadata Enhancement Migration
-- ============================================================================
-- Purpose: Add account metadata fields (follower count, bio, profile info)
--          to provide better context for viral content analysis
--
-- Why: We're already scraping accounts via Apify - might as well capture
--      account metadata for segmentation and analysis
--
-- Run this in your Supabase SQL Editor
-- ============================================================================

-- Add account metadata columns
DO $$
BEGIN
  -- Follower/Following counts
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'follower_count'
  ) THEN
    ALTER TABLE accounts ADD COLUMN follower_count integer;
    CREATE INDEX idx_accounts_follower_count ON accounts(follower_count);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'following_count'
  ) THEN
    ALTER TABLE accounts ADD COLUMN following_count integer;
  END IF;

  -- Profile information
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'bio'
  ) THEN
    ALTER TABLE accounts ADD COLUMN bio text;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'display_name'
  ) THEN
    ALTER TABLE accounts ADD COLUMN display_name text;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'profile_pic_url'
  ) THEN
    ALTER TABLE accounts ADD COLUMN profile_pic_url text;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'is_verified'
  ) THEN
    ALTER TABLE accounts ADD COLUMN is_verified boolean DEFAULT false;
    CREATE INDEX idx_accounts_is_verified ON accounts(is_verified);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'account_type'
  ) THEN
    ALTER TABLE accounts ADD COLUMN account_type text;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'external_url'
  ) THEN
    ALTER TABLE accounts ADD COLUMN external_url text;
  END IF;

  -- Metadata update timestamp
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'metadata_updated_at'
  ) THEN
    ALTER TABLE accounts ADD COLUMN metadata_updated_at timestamptz;
    CREATE INDEX idx_accounts_metadata_updated_at ON accounts(metadata_updated_at);
  END IF;

END $$;

-- Add comments for documentation
COMMENT ON COLUMN accounts.follower_count IS 'Number of followers at last metadata update';
COMMENT ON COLUMN accounts.following_count IS 'Number of accounts following at last metadata update';
COMMENT ON COLUMN accounts.bio IS 'Account bio/description from profile';
COMMENT ON COLUMN accounts.display_name IS 'Display name (different from username)';
COMMENT ON COLUMN accounts.profile_pic_url IS 'Profile picture URL';
COMMENT ON COLUMN accounts.is_verified IS 'Whether account has verified badge';
COMMENT ON COLUMN accounts.account_type IS 'Account type: personal, business, creator';
COMMENT ON COLUMN accounts.external_url IS 'External URL from profile (website, link tree, etc.)';
COMMENT ON COLUMN accounts.metadata_updated_at IS 'When account metadata (follower count, bio, etc.) was last updated - separate from last_scraped_at for posts';

-- Note: last_scraped_at tracks when we last scraped POSTS
-- Note: metadata_updated_at tracks when we last updated ACCOUNT metadata

/*
ROLLBACK INSTRUCTIONS:
If you need to rollback this migration, run:

ALTER TABLE accounts DROP COLUMN IF EXISTS follower_count;
ALTER TABLE accounts DROP COLUMN IF EXISTS following_count;
ALTER TABLE accounts DROP COLUMN IF EXISTS bio;
ALTER TABLE accounts DROP COLUMN IF EXISTS display_name;
ALTER TABLE accounts DROP COLUMN IF EXISTS profile_pic_url;
ALTER TABLE accounts DROP COLUMN IF EXISTS is_verified;
ALTER TABLE accounts DROP COLUMN IF EXISTS account_type;
ALTER TABLE accounts DROP COLUMN IF EXISTS external_url;
ALTER TABLE accounts DROP COLUMN IF EXISTS metadata_updated_at;

DROP INDEX IF EXISTS idx_accounts_follower_count;
DROP INDEX IF EXISTS idx_accounts_is_verified;
DROP INDEX IF EXISTS idx_accounts_metadata_updated_at;
*/
