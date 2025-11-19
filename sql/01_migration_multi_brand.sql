-- ============================================================================
-- Multi-Brand, Multi-Platform Migration
-- ============================================================================
-- Purpose: Transform single-brand Instagram tool into multi-brand,
--          multi-platform viral content analysis system
--
-- This migration:
-- 1. Creates new tables for brands, products, platforms, projects
-- 2. Modifies existing tables to support multi-platform
-- 3. Preserves all existing data
-- 4. Maintains backward compatibility
--
-- Run this in your Supabase SQL Editor
-- ============================================================================

-- ============================================================================
-- PART 1: CREATE NEW TABLES
-- ============================================================================

-- Brands table
CREATE TABLE IF NOT EXISTS brands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  slug text UNIQUE NOT NULL,
  description text,
  website text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_brands_slug ON brands(slug);

COMMENT ON TABLE brands IS 'Different brands using the system (e.g., Yakety Pack, Acme Corp)';

-- Products table
CREATE TABLE IF NOT EXISTS products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text NOT NULL,
  description text,
  target_audience text,
  price_range text,
  key_problems_solved jsonb,
  key_benefits jsonb,
  features jsonb,
  context_prompt text,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(brand_id, slug)
);

CREATE INDEX idx_products_brand_id ON products(brand_id);
CREATE INDEX idx_products_slug ON products(slug);
CREATE INDEX idx_products_is_active ON products(is_active);

COMMENT ON TABLE products IS 'Different products per brand with unique adaptation strategies';
COMMENT ON COLUMN products.context_prompt IS 'Full AI context for product adaptations';

-- Platforms table
CREATE TABLE IF NOT EXISTS platforms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  slug text UNIQUE NOT NULL,
  scraper_type text,
  scraper_config jsonb,
  max_video_length_sec int,
  typical_video_length_sec int,
  aspect_ratio text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_platforms_slug ON platforms(slug);

COMMENT ON TABLE platforms IS 'Social media platforms (Instagram, TikTok, YouTube Shorts)';
COMMENT ON COLUMN platforms.scraper_config IS 'Platform-specific scraper configuration (Apify actor IDs, etc.)';

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text UNIQUE NOT NULL,
  description text,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_projects_brand_id ON projects(brand_id);
CREATE INDEX idx_projects_product_id ON projects(product_id);
CREATE INDEX idx_projects_slug ON projects(slug);
CREATE INDEX idx_projects_is_active ON projects(is_active);

COMMENT ON TABLE projects IS 'Content creation projects (brand + product combos)';

-- Project accounts table
CREATE TABLE IF NOT EXISTS project_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  priority int DEFAULT 1,
  notes text,
  added_at timestamptz DEFAULT now(),
  UNIQUE(project_id, account_id)
);

CREATE INDEX idx_project_accounts_project_id ON project_accounts(project_id);
CREATE INDEX idx_project_accounts_account_id ON project_accounts(account_id);
CREATE INDEX idx_project_accounts_priority ON project_accounts(priority);

COMMENT ON TABLE project_accounts IS 'Track which accounts each project monitors (many-to-many)';

-- Project posts table (NEW - for direct URL imports)
CREATE TABLE IF NOT EXISTS project_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  post_id uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  import_method text CHECK (import_method IN ('scrape', 'direct_url', 'csv_batch')),
  is_own_content boolean DEFAULT false,
  notes text,
  added_at timestamptz DEFAULT now(),
  UNIQUE(project_id, post_id)
);

CREATE INDEX idx_project_posts_project_id ON project_posts(project_id);
CREATE INDEX idx_project_posts_post_id ON project_posts(post_id);
CREATE INDEX idx_project_posts_is_own_content ON project_posts(is_own_content);
CREATE INDEX idx_project_posts_import_method ON project_posts(import_method);

COMMENT ON TABLE project_posts IS 'Track posts added to projects (including direct URL imports)';
COMMENT ON COLUMN project_posts.is_own_content IS 'True if this is the brand''s own content vs competitor content';

-- Product adaptations table
CREATE TABLE IF NOT EXISTS product_adaptations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  video_analysis_id uuid REFERENCES video_analysis(id) ON DELETE CASCADE,

  -- Scoring
  hook_relevance_score decimal(3,1) CHECK (hook_relevance_score >= 1 AND hook_relevance_score <= 10),
  audience_match_score decimal(3,1) CHECK (audience_match_score >= 1 AND audience_match_score <= 10),
  transition_ease_score decimal(3,1) CHECK (transition_ease_score >= 1 AND transition_ease_score <= 10),
  viral_replicability_score decimal(3,1) CHECK (viral_replicability_score >= 1 AND viral_replicability_score <= 10),
  overall_score decimal(3,1) CHECK (overall_score >= 1 AND overall_score <= 10),

  -- Adaptation content
  adapted_hook text,
  adapted_script text,
  storyboard jsonb,
  text_overlays jsonb,
  transition_strategy text,
  best_use_case text,
  production_notes text,

  -- Metadata
  ai_model text DEFAULT 'gemini-2.5-flash',
  ai_tokens_used int,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),

  UNIQUE(post_id, product_id)
);

CREATE INDEX idx_product_adaptations_product_id ON product_adaptations(product_id);
CREATE INDEX idx_product_adaptations_post_id ON product_adaptations(post_id);
CREATE INDEX idx_product_adaptations_overall_score ON product_adaptations(overall_score DESC);
CREATE INDEX idx_product_adaptations_video_analysis_id ON product_adaptations(video_analysis_id);

COMMENT ON TABLE product_adaptations IS 'AI-generated content adaptations for different products';
COMMENT ON COLUMN product_adaptations.overall_score IS 'Overall adaptation potential (1-10)';

-- ============================================================================
-- PART 2: MODIFY EXISTING TABLES
-- ============================================================================

-- Add platform support to accounts table
DO $$
BEGIN
  -- Add platform_id column
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'platform_id'
  ) THEN
    ALTER TABLE accounts ADD COLUMN platform_id uuid REFERENCES platforms(id);
    CREATE INDEX idx_accounts_platform_id ON accounts(platform_id);
  END IF;

  -- Add platform_username column
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'accounts' AND column_name = 'platform_username'
  ) THEN
    ALTER TABLE accounts ADD COLUMN platform_username text;
  END IF;

  -- Drop old unique constraint on handle if it exists
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'accounts_handle_key'
  ) THEN
    ALTER TABLE accounts DROP CONSTRAINT accounts_handle_key;
  END IF;

  -- Add new unique constraint on platform_id + platform_username
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'accounts_platform_username_unique'
  ) THEN
    ALTER TABLE accounts ADD CONSTRAINT accounts_platform_username_unique
      UNIQUE(platform_id, platform_username);
  END IF;
END $$;

COMMENT ON COLUMN accounts.platform_id IS 'Which platform this account is on (Instagram, TikTok, etc.)';
COMMENT ON COLUMN accounts.platform_username IS 'Username on the platform (same as handle for now)';

-- Add platform and import tracking to posts table
DO $$
BEGIN
  -- Add platform_id
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'posts' AND column_name = 'platform_id'
  ) THEN
    ALTER TABLE posts ADD COLUMN platform_id uuid REFERENCES platforms(id);
    CREATE INDEX idx_posts_platform_id ON posts(platform_id);
  END IF;

  -- Add import_source
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'posts' AND column_name = 'import_source'
  ) THEN
    ALTER TABLE posts ADD COLUMN import_source text
      CHECK (import_source IN ('scrape', 'direct_url', 'csv_import'));
    CREATE INDEX idx_posts_import_source ON posts(import_source);
  END IF;

  -- Add is_own_content
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'posts' AND column_name = 'is_own_content'
  ) THEN
    ALTER TABLE posts ADD COLUMN is_own_content boolean DEFAULT false;
    CREATE INDEX idx_posts_is_own_content ON posts(is_own_content);
  END IF;

  -- Make account_id nullable (for direct URL imports without account tracking)
  ALTER TABLE posts ALTER COLUMN account_id DROP NOT NULL;
END $$;

COMMENT ON COLUMN posts.platform_id IS 'Which platform this post is from';
COMMENT ON COLUMN posts.import_source IS 'How this post entered the system (scrape, direct_url, csv_import)';
COMMENT ON COLUMN posts.is_own_content IS 'True if this is brand''s own content vs competitor content';

-- Add platform tracking to video_analysis table
DO $$
BEGIN
  -- Add platform_id
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'video_analysis' AND column_name = 'platform_id'
  ) THEN
    ALTER TABLE video_analysis ADD COLUMN platform_id uuid REFERENCES platforms(id);
    CREATE INDEX idx_video_analysis_platform_id ON video_analysis(platform_id);
  END IF;

  -- Add platform_specific_metrics
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'video_analysis' AND column_name = 'platform_specific_metrics'
  ) THEN
    ALTER TABLE video_analysis ADD COLUMN platform_specific_metrics jsonb;
  END IF;
END $$;

COMMENT ON COLUMN video_analysis.platform_id IS 'Which platform this video is from';
COMMENT ON COLUMN video_analysis.platform_specific_metrics IS 'Platform-specific data (TikTok sounds, IG music, etc.)';

-- ============================================================================
-- PART 3: INSERT DEFAULT DATA
-- ============================================================================

-- Insert Instagram platform (we'll use this for existing data)
INSERT INTO platforms (name, slug, scraper_type, scraper_config, max_video_length_sec, typical_video_length_sec, aspect_ratio)
VALUES (
  'Instagram Reels',
  'instagram',
  'apify',
  '{"actor_id": "apify/instagram-scraper", "default_post_type": "reels"}'::jsonb,
  90,
  30,
  '9:16'
)
ON CONFLICT (slug) DO NOTHING;

-- Insert TikTok platform (ready for Phase 4)
INSERT INTO platforms (name, slug, scraper_type, scraper_config, max_video_length_sec, typical_video_length_sec, aspect_ratio)
VALUES (
  'TikTok',
  'tiktok',
  'apify',
  '{"actor_id": "TBD", "default_post_type": "videos"}'::jsonb,
  600,
  30,
  '9:16'
)
ON CONFLICT (slug) DO NOTHING;

-- Insert YouTube Shorts platform (ready for Phase 5)
INSERT INTO platforms (name, slug, scraper_type, scraper_config, max_video_length_sec, typical_video_length_sec, aspect_ratio)
VALUES (
  'YouTube Shorts',
  'youtube_shorts',
  'apify',
  '{"actor_id": "TBD", "default_post_type": "shorts"}'::jsonb,
  60,
  30,
  '9:16'
)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- PART 4: MIGRATE EXISTING DATA
-- ============================================================================

-- This will be done by the Python migration script (migrate_existing_data.py)
-- to ensure data integrity and provide progress tracking

-- The script will:
-- 1. Create "Yakety Pack" brand
-- 2. Create "Core Deck" product with existing context
-- 3. Create default project "Yakety Pack Instagram"
-- 4. Update all existing accounts with Instagram platform_id
-- 5. Update all existing posts with Instagram platform_id and import_source='scrape'
-- 6. Link all accounts to default project
-- 7. Create project_posts entries for all existing posts

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Run these after migration to verify everything worked:

-- Check platform counts
-- SELECT slug, name, COUNT(accounts.id) as account_count
-- FROM platforms
-- LEFT JOIN accounts ON accounts.platform_id = platforms.id
-- GROUP BY platforms.id, platforms.slug, platforms.name;

-- Check brand and product setup
-- SELECT b.name as brand, p.name as product, pr.name as project
-- FROM brands b
-- LEFT JOIN products p ON p.brand_id = b.id
-- LEFT JOIN projects pr ON pr.brand_id = b.id;

-- Check import sources
-- SELECT import_source, COUNT(*) as count
-- FROM posts
-- WHERE import_source IS NOT NULL
-- GROUP BY import_source;

-- Check posts with/without accounts
-- SELECT
--   COUNT(*) FILTER (WHERE account_id IS NOT NULL) as with_account,
--   COUNT(*) FILTER (WHERE account_id IS NULL) as without_account
-- FROM posts;

-- ============================================================================
-- ROLLBACK (USE WITH CAUTION)
-- ============================================================================

-- If you need to rollback this migration, uncomment and run:

/*
DROP TABLE IF EXISTS product_adaptations CASCADE;
DROP TABLE IF EXISTS project_posts CASCADE;
DROP TABLE IF EXISTS project_accounts CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS brands CASCADE;
DROP TABLE IF EXISTS platforms CASCADE;

-- Remove added columns from existing tables
ALTER TABLE accounts DROP COLUMN IF EXISTS platform_id;
ALTER TABLE accounts DROP COLUMN IF EXISTS platform_username;
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_platform_username_unique;
ALTER TABLE accounts ADD CONSTRAINT accounts_handle_key UNIQUE(handle);

ALTER TABLE posts DROP COLUMN IF EXISTS platform_id;
ALTER TABLE posts DROP COLUMN IF EXISTS import_source;
ALTER TABLE posts DROP COLUMN IF EXISTS is_own_content;
ALTER TABLE posts ALTER COLUMN account_id SET NOT NULL;

ALTER TABLE video_analysis DROP COLUMN IF EXISTS platform_id;
ALTER TABLE video_analysis DROP COLUMN IF EXISTS platform_specific_metrics;
*/
