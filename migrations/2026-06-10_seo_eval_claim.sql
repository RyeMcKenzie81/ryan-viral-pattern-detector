-- Migration: eval claim column to prevent concurrent double-evaluation (B14)
-- Date: 2026-06-10
-- Purpose: the seo_content_eval job calls get_pending_articles (status in
-- qa_passed/optimized, not yet evaluated) and processes the batch. With
-- thread-per-job dispatch two eval runs can execute at once (no per-job-type
-- cap of 1), so two runs fetch the SAME pending list and both auto-fix +
-- evaluate the same articles — duplicate eval rows, double-applied body
-- fixes, wasted LLM spend.
--
-- Fix: an atomic per-article claim. content_eval_service.claim_for_eval does a
-- conditional UPDATE (set eval_claimed_at where status still pending AND no
-- live claim); Postgres row-locks, so exactly one concurrent run wins and the
-- other skips. Re-claimable after the article completes (cleared on the
-- eval_passed/eval_failed write) or after a stale window (crashed mid-eval).
--
-- Degrades gracefully if absent: claim_for_eval catches the missing-column
-- error and returns True (proceed) so evaluation still runs (just without the
-- concurrency guard) until the migration is applied.

ALTER TABLE seo_articles
    ADD COLUMN IF NOT EXISTS eval_claimed_at TIMESTAMPTZ;

COMMENT ON COLUMN seo_articles.eval_claimed_at IS
    'B14 concurrency guard: set atomically when an seo_content_eval run claims this article for evaluation; cleared when it finishes. Prevents two concurrent runs from double-processing the same article.';

-- Partial index: the claim query filters on the small pending set.
CREATE INDEX IF NOT EXISTS idx_seo_articles_eval_pending
    ON seo_articles(status) WHERE status IN ('qa_passed', 'optimized');
