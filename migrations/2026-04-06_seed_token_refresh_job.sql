-- Migration: Seed daily token_refresh scheduled job
-- Date: 2026-04-06
-- Purpose: Auto-extend Meta OAuth tokens before they expire (7-day window)
-- Cron: 6 AM daily PST (cron parser uses Python weekday, times are PST)

INSERT INTO scheduled_jobs (
    job_type, name, schedule_type, cron_expression,
    next_run_at, status, parameters
)
SELECT 'token_refresh', 'Daily Meta Token Refresh', 'recurring',
       '0 6 * * *',                   -- 6 AM daily PST
       NOW() + interval '5 minutes',  -- near-immediate first run to verify handler
       'active', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM scheduled_jobs WHERE job_type = 'token_refresh'
);
