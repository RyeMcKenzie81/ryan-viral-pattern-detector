-- Analysis Runs Tracking
-- Tracks search term analysis runs for debugging and historical tracking
-- Links tweets to specific analysis runs via Apify scraper IDs

-- 1) Analysis Runs Table
-- Stores metadata for each search term analysis execution
CREATE TABLE IF NOT EXISTS public.analysis_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,

  -- Analysis parameters
  search_term text NOT NULL,
  tweets_requested integer NOT NULL,  -- --count parameter
  min_likes integer DEFAULT 0,
  days_back integer DEFAULT 7,

  -- Execution tracking
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  status text CHECK (status IN ('running','completed','failed')) DEFAULT 'running',
  error_message text,  -- If status='failed'

  -- External IDs for linking
  apify_run_id text,  -- Apify actor run ID (e.g., '0F3NtiCNhUbTudDjr')
  apify_dataset_id text,  -- Apify dataset ID for this scrape

  -- Results summary
  tweets_analyzed integer,  -- Actual count after scraping
  green_count integer,
  yellow_count integer,
  red_count integer,

  -- Export tracking
  report_file_path text,  -- Path to exported JSON report

  -- Cost tracking
  total_cost_usd numeric(10, 6) DEFAULT 0.0,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_analysis_runs_project
  ON public.analysis_runs(project_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_search_term
  ON public.analysis_runs(project_id, search_term, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_apify
  ON public.analysis_runs(apify_run_id) WHERE apify_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_analysis_runs_status
  ON public.analysis_runs(status, started_at DESC);

-- Table and column comments
COMMENT ON TABLE public.analysis_runs IS 'Tracks search term analysis runs with Apify scraper IDs for full traceability';
COMMENT ON COLUMN public.analysis_runs.apify_run_id IS 'Apify actor run ID (e.g., 0F3NtiCNhUbTudDjr) for linking to external scrape';
COMMENT ON COLUMN public.analysis_runs.apify_dataset_id IS 'Apify dataset ID containing the scraped tweets';
COMMENT ON COLUMN public.analysis_runs.tweets_analyzed IS 'Actual number of tweets analyzed (may be less than tweets_requested)';
COMMENT ON COLUMN public.analysis_runs.report_file_path IS 'Path to exported JSON report file';


-- 2) Link project_posts to analysis_runs
-- Add optional foreign key to track which analysis run imported each tweet
ALTER TABLE public.project_posts
ADD COLUMN IF NOT EXISTS analysis_run_id uuid REFERENCES public.analysis_runs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_project_posts_analysis_run
  ON public.project_posts(analysis_run_id) WHERE analysis_run_id IS NOT NULL;

COMMENT ON COLUMN public.project_posts.analysis_run_id IS 'Optional: Links tweet to the analysis run that imported it';


-- Example queries:

-- Get all analysis runs for a project
-- SELECT
--     id,
--     search_term,
--     started_at,
--     tweets_analyzed,
--     green_count,
--     ROUND((green_count::numeric / tweets_analyzed * 100), 1) as green_pct,
--     total_cost_usd,
--     status
-- FROM analysis_runs
-- WHERE project_id = 'YOUR_PROJECT_ID'
-- ORDER BY started_at DESC;

-- Get all tweets from a specific analysis run
-- SELECT
--     p.post_id,
--     p.caption,
--     p.posted_at,
--     ar.search_term,
--     ar.started_at as analysis_date
-- FROM project_posts pp
-- JOIN posts p ON pp.post_id = p.id
-- JOIN analysis_runs ar ON pp.analysis_run_id = ar.id
-- WHERE ar.id = 'ANALYSIS_RUN_ID';

-- Compare multiple runs of the same search term
-- SELECT
--     started_at::date as date,
--     tweets_analyzed,
--     green_count,
--     ROUND((green_count::numeric / tweets_analyzed * 100), 1) as green_pct,
--     total_cost_usd
-- FROM analysis_runs
-- WHERE project_id = 'YOUR_PROJECT_ID'
--   AND search_term = 'screen time kids'
-- ORDER BY started_at DESC;
