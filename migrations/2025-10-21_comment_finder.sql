-- Comment Finder V1 Database Schema
-- Creates tables for comment opportunity detection and generation

-- Enable pgvector extension (for future semantic dedup in V1.1)
CREATE EXTENSION IF NOT EXISTS vector;

-- 1) Generated Comments Table
-- Handoff between generate-comments and export-comments commands
-- Stores AI-generated comment suggestions with scoring and lifecycle status

CREATE TABLE IF NOT EXISTS public.generated_comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  tweet_id text NOT NULL,
  suggestion_type text CHECK (suggestion_type IN ('add_value','ask_question','mirror_reframe')),
  comment_text text NOT NULL,
  score_total double precision NOT NULL,
  label text CHECK (label IN ('green','yellow','red')) NOT NULL,
  topic text,  -- best-match taxonomy label
  why text,    -- short rationale for CSV export
  rank int,    -- 1-3 for suggestion ordering
  review_status text CHECK (review_status IN ('pending','approved','rejected')) DEFAULT 'pending',
  review_notes text,  -- optional moderator notes for future UI
  created_at timestamptz NOT NULL DEFAULT now(),
  status text CHECK (status IN ('pending','exported','posted','skipped')) NOT NULL DEFAULT 'pending',
  UNIQUE (project_id, tweet_id, suggestion_type)
);

CREATE INDEX IF NOT EXISTS idx_generated_comments_project_status
  ON public.generated_comments(project_id, status);

CREATE INDEX IF NOT EXISTS idx_generated_comments_created
  ON public.generated_comments(created_at DESC);

COMMENT ON TABLE public.generated_comments IS 'AI-generated comment suggestions for Twitter opportunities';
COMMENT ON COLUMN public.generated_comments.topic IS 'Best-match taxonomy label (e.g., "facebook ads")';
COMMENT ON COLUMN public.generated_comments.why IS 'Short rationale: "High velocity + taxonomy facebook ads (0.84)"';
COMMENT ON COLUMN public.generated_comments.rank IS 'Suggestion ranking (1-3) within type';
COMMENT ON COLUMN public.generated_comments.review_status IS 'For future HTMX UI review workflow';


-- 2) Tweet Snapshot Table
-- Historical snapshot of tweets for metrics and author signal calculation
-- Populated during comment generation runs

CREATE TABLE IF NOT EXISTS public.tweet_snapshot (
  tweet_id text PRIMARY KEY,
  project_id uuid NOT NULL,
  author_handle text,
  author_followers integer,
  lang text,
  text_body text,
  tweeted_at timestamptz NOT NULL,
  likes integer DEFAULT 0,
  replies integer DEFAULT 0,
  rts integer DEFAULT 0,
  collected_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tweet_snapshot_project_time
  ON public.tweet_snapshot(project_id, tweeted_at DESC);

CREATE INDEX IF NOT EXISTS idx_tweet_snapshot_author
  ON public.tweet_snapshot(author_handle);

COMMENT ON TABLE public.tweet_snapshot IS 'Historical tweet data for velocity and author analysis';


-- 3) Author Stats Table
-- Aggregated author engagement metrics for openness scoring
-- Optional for V1, can be populated incrementally

CREATE TABLE IF NOT EXISTS public.author_stats (
  handle text PRIMARY KEY,
  last_24h_replies integer DEFAULT 0,
  last_24h_author_replied_ratio double precision DEFAULT 0.0,
  total_tweets_seen integer DEFAULT 0,
  avg_openness_score double precision,  -- optional: track typical author openness
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_author_stats_updated
  ON public.author_stats(updated_at DESC);

COMMENT ON TABLE public.author_stats IS 'Author engagement patterns for openness scoring (V1.1)';
COMMENT ON COLUMN public.author_stats.last_24h_author_replied_ratio IS 'Ratio of tweets where author replied to others';


-- 4) Acceptance Log Table
-- Tracks processed tweets to prevent duplicates and enable 7-day lookback
-- Will store embeddings in V1.1 for semantic deduplication

CREATE TABLE IF NOT EXISTS public.acceptance_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  source text NOT NULL,      -- 'twitter', 'reddit', etc
  foreign_id text NOT NULL,  -- tweet_id, post_id, etc
  embedding vector(768),     -- optional: Gemini text-embedding-004 for semantic dedup (V1.1)
  accepted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, source, foreign_id)
);

CREATE INDEX IF NOT EXISTS idx_acceptance_log_7d
  ON public.acceptance_log(project_id, accepted_at DESC);

CREATE INDEX IF NOT EXISTS idx_acceptance_log_source
  ON public.acceptance_log(project_id, source, foreign_id);

COMMENT ON TABLE public.acceptance_log IS 'Tracks processed tweets for 7-day duplicate detection';
COMMENT ON COLUMN public.acceptance_log.embedding IS 'For semantic dedup in V1.1 (pgvector cosine similarity)';


-- Grant permissions (adjust as needed for your Supabase setup)
-- GRANT ALL ON public.generated_comments TO authenticated;
-- GRANT ALL ON public.tweet_snapshot TO authenticated;
-- GRANT ALL ON public.author_stats TO authenticated;
-- GRANT ALL ON public.acceptance_log TO authenticated;
