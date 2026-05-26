-- Migration: Add angle_id to ad_runs for angle-driven flow stamping
-- Date: 2026-05-26
-- Plan: docs/plans/angle-driven-ad-creator/PLAN.md (Step 4a follow-up)
--
-- generated_ads.angle_id was added back in sql/migration_generated_ads_belief_metadata.sql
-- (Phase 1-2 belief-plan work) but no code path was actually populating it in
-- the V2 ad creation pipeline. PR #195 fixed the V2 executor to receive the
-- angle, but the save_generated_ad() call sites in the V2 pipeline nodes
-- (review_ads, defect_scan, retry_rejected) don't pass angle_id explicitly.
--
-- Rather than threading angle_id through all those call sites individually
-- (mirror of the threading hell that ad_creation_run_id was solving), we
-- stamp the angle_id on the parent ad_run once at creation time. Then
-- save_generated_ad() reads ad_run.angle_id alongside ad_run.ad_creation_run_id
-- (single SELECT, same query) and stamps it on every generated_ads row.
--
-- One ad_run = one angle in V2's content_source='angles' mode (AC2 = one
-- angle per run, decision from session chat 2026-05-25). NULL for non-angle
-- runs (recreate_template, manual).

BEGIN;

ALTER TABLE ad_runs
    ADD COLUMN IF NOT EXISTS angle_id UUID REFERENCES belief_angles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ad_runs_angle_id
    ON ad_runs(angle_id)
    WHERE angle_id IS NOT NULL;

COMMENT ON COLUMN ad_runs.angle_id IS
    'Belief angle this ad_run is testing. Stamped at ad_run creation by the V2 '
    'InitializeNode when content_source=''angles''. save_generated_ad() reads '
    'this and copies onto every generated_ads.angle_id under this run. NULL for '
    'non-angle runs (recreate_template, manual). FK references belief_angles(id).';

COMMIT;
