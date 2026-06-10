-- Migration: raise runtime limits for long vision-batch jobs
-- Date: 2026-06-10
-- Purpose: stop the recovery sweep from killing-and-rearming legitimately
-- long jobs (duplicate Gemini spend).
--
-- creative_deep_analysis was capped at 1800s (30min) but a real run processes
-- up to 50 images + 20 videos through Gemini and takes HOURS (2026-06-09's ran
-- 3.4h+). ad_intelligence_analysis was capped at 7200s and also overran.
-- While the recovery owner was starved (pre-#275) the caps were never
-- enforced; now that recovery actually ticks every 60s, the sweep marks these
-- runs failed mid-flight and re-arms next_run_at=now() -> restart loop.
-- Verified live: 7 recovery kills across the two types in the 30h after the
-- recovery thread deployed.
--
-- 14400s = 4h, sized above the longest observed legitimate run with headroom.
-- The proper long-term fix is per-phase checkpoint/heartbeat (durable-jobs
-- contract); this stops the bleeding.

UPDATE job_runtime_limits
SET max_runtime_seconds = 14400,
    updated_at = now(),
    notes = '4h — vision batch over up to 50 images + 20 videos; raised 2026-06-10 (was 30min, recovery was killing live runs)'
WHERE job_type = 'creative_deep_analysis';

UPDATE job_runtime_limits
SET max_runtime_seconds = 14400,
    updated_at = now(),
    notes = '4h — full 4-layer analysis; raised 2026-06-10 (was 2h, recovery killed 2 live runs)'
WHERE job_type = 'ad_intelligence_analysis';
