-- Migration: Add ad_creation_run_id to ad_runs
-- Date: 2026-05-25
-- Plan: docs/plans/angle-driven-ad-creator/PLAN.md (Step 4a — minimal scheduler/AC integration)
--
-- Carries the scheduler-job UUID down through ad_run creation so that
-- save_generated_ad() can stamp generated_ads.ad_creation_run_id without
-- threading the param through 8 separate save_generated_ad call sites.
--
-- generated_ads.ad_creation_run_id was added in 2026-05-25_angle_driven_ads.sql
-- (PR #184). This migration adds the same column to ad_runs as the source-of-truth
-- so a single ad_runs row can stamp every generated_ads row produced under it.

BEGIN;

ALTER TABLE ad_runs
    ADD COLUMN IF NOT EXISTS ad_creation_run_id UUID;

CREATE INDEX IF NOT EXISTS idx_ad_runs_ad_creation_run_id
    ON ad_runs(ad_creation_run_id)
    WHERE ad_creation_run_id IS NOT NULL;

COMMENT ON COLUMN ad_runs.ad_creation_run_id IS
    'Scheduler job UUID that triggered this ad_run. Stamped at ad_run creation by the scheduler; '
    'save_generated_ad() reads it here and copies onto every generated_ads row produced under this run. '
    'Nullable: ad_runs created outside the scheduler (manual, debug, legacy) have NULL.';

COMMIT;
