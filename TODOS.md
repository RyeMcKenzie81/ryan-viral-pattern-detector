# TODOS

## Event Retention Automation
**What:** Set up pg_cron to auto-delete activity_events older than 90 days.
**Status:** Migration added with one-time cleanup + cron SQL comment. Need to enable pg_cron on Supabase and schedule: `SELECT cron.schedule('activity-event-retention', '0 3 * * *', $$DELETE FROM activity_events WHERE created_at < now() - interval '90 days'$$);`
**Added:** 2026-03-30 from /plan-eng-review of Activity Feed feature.
**Updated:** 2026-03-31 — migration created, one-time cleanup included, pg_cron SQL documented.

## Opportunity Scoring Weight Tuning (Phase 2 prerequisite)
**What:** After Phase 1 has 4+ weeks of rank_delta data, analyze which scoring weights best predict actual rank improvement. Compare predicted opportunity_score against actual rank_delta_28d outcomes.
**Why:** Starting weights (impression_trend 30%, position_proximity 30%, keyword_volume 20%, cluster_gap 20%) are educated guesses. Real data will reveal which components actually predict rank movement.
**Context:** Phase 1 tracks rank_delta_7d/14d/28d for actioned opportunities in `seo_opportunities` table. After sufficient data accumulates (~50+ actioned opportunities with 28d deltas), run correlation analysis: which scoring components correlate with negative rank_delta (improvement)? Results inform Phase 2 auto-execution confidence thresholds and may justify reweighting the formula.
**Depends on:** Phase 1 running for 4+ weeks across multiple brands with GSC connected.
**Added:** 2026-04-03 from /plan-eng-review of SEO Feedback Loop.
