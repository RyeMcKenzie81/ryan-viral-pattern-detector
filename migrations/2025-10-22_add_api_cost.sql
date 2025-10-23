-- V1.2 Feature 4.1: Cost Tracking
-- Add api_cost_usd column to generated_comments table

-- Add column for API cost tracking
ALTER TABLE public.generated_comments
ADD COLUMN IF NOT EXISTS api_cost_usd numeric(10, 8) DEFAULT 0.0;

-- Add comment explaining the column
COMMENT ON COLUMN public.generated_comments.api_cost_usd IS 'Gemini API cost in USD for this suggestion (input + output tokens). Typical: $0.00008 per tweet.';

-- Add index for cost queries (aggregation by project and time)
CREATE INDEX IF NOT EXISTS idx_generated_comments_cost
  ON public.generated_comments(project_id, created_at DESC, api_cost_usd);

-- Example query: Total cost by project in last 7 days
-- SELECT
--     project_id,
--     COUNT(DISTINCT tweet_id) as tweets_processed,
--     COUNT(*) as suggestions_generated,
--     SUM(api_cost_usd) as total_cost_usd,
--     AVG(api_cost_usd) as avg_cost_per_suggestion
-- FROM generated_comments
-- WHERE created_at >= NOW() - INTERVAL '7 days'
-- GROUP BY project_id
-- ORDER BY total_cost_usd DESC;
