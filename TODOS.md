# TODOS

## Review Rule #7 (safest→exploratory ordering) in AngleGeneratorService prompt
**What:** After V1 has produced ~5–10 angle batches, audit whether Rule #7 (the generator orders angles from safest/floor → most exploratory/ceiling) is actually producing a meaningful psychographic gradient or whether the 5 angles cluster regardless. If clustered, drop the ordering rule and let the cross-angle hook similarity metric do the work; if working, keep it and make the gradient explicit in the UI (label them 1 = floor, N = ceiling).
**Why:** Rule #7 is a strong opinion that violates conventional "let the model generate freely, rank after" prompting practice. We kept it because the ordering is what makes the cross-angle similarity gradient interpretable later. But strong opinions deserve a planned review point, not silent persistence.
**Context:** Decision in `/plan-eng-review` (2026-05-25) prompt draft conversation. Calibration item flagged in `docs/plans/angle-driven-ad-creator/PROMPT_DRAFT.md` (notes-for-review section). Review trigger: after ~5–10 batches in production. The audit is a 30-min eyeball test on the generator output ordering vs the cross-angle similarity report — does the ordering correspond to the gradient?
**Depends on:** V1 (angle-driven-ad-creator) shipping + ~5–10 production angle batches.
**Added:** 2026-05-25 from /plan-eng-review of angle-driven ad creator.

## LLM Eval Suite for AngleGeneratorService Prompt
**What:** Automated eval suite grading the angle generator's output on (a) distinctness across the 5 angles in a batch, (b) deliverability against the landing page promise, (c) absence of LLM slop language. Golden examples = Ryan's handwritten 5 angles + best production angles from V1's first month.
**Why:** The prompt is load-bearing. A future tweak that "feels cleaner" could silently regress angle quality and we'd only find out from production CTR data weeks later. An eval suite catches prompt regressions in CI.
**Context:** Decision 3A in `/plan-eng-review` (2026-05-25) explicitly deferred this to fast-follow because golden examples don't exist yet. After V1 has produced ~5–10 batches there will be real reference data. Build the harness + seed golden examples then.
**Depends on:** V1 (angle-driven-ad-creator) shipping + ~2 weeks of production angle data.
**Added:** 2026-05-25 from /plan-eng-review of angle-driven ad creator.

## Angle Performance Dashboard in Research Insights
**What:** New section in `viraltracker/ui/pages/32_💡_Research_Insights.py` showing per-angle metrics: ads-in-market, average CTR, best-performing ad, status (untested/testing/winner/loser). Joins `belief_angles` → `generated_ads.angle_id` → `ad_intelligence` results.
**Why:** V1 captures the data (every ad records `angle_id`); without the UI we're running manual SQL queries to see what's working. Eventually clients will want to see this too — "here are the 5 angles we tested for you, here's which one is winning, here's why."
**Context:** Decision P5 in `/office-hours` and confirmed in `/plan-eng-review` (2026-05-25) deferred the dashboard from V1 scope to keep the build at ~2.5–3 weeks. The data exists from day 1; just no UI. Build once V1 has produced 2–3 weeks of ads so the dashboard has something meaningful to show on day one. Joins through ad_intelligence have edge cases (deleted ads, cross-platform metrics, NULL fields) — budget time for polish.
**Depends on:** V1 (angle-driven-ad-creator) shipping + ~2 weeks of production runs.
**Added:** 2026-05-25 from /plan-eng-review of angle-driven ad creator.

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

## DESIGN.md — Document UI Pattern Library
**What:** Create DESIGN.md documenting ViralTracker's Streamlit UI patterns (component vocabulary, spacing, color usage, empty state patterns, tab structures, selector patterns).
**Why:** 77+ Streamlit pages with no documented design system. Each new page reinvents patterns slightly differently. A DESIGN.md would make pages consistent and speed up development.
**Context:** Best patterns exist across competitor pages (11-13), Research Insights (32), and Brand Manager (02). Codify the patterns from these well-designed pages. Run /design-consultation to generate.
**Depends on:** Nothing. Can be done independently at any time.
**Added:** 2026-04-08 from /plan-design-review of Competitor Ad Intelligence feature.

## Competitor Intel Phase 2 — Belief Cluster Analysis
**What:** After pack generation, run one LLM call over the extracted angles, pain points, and personas to identify 3-5 core positioning strategies the competitor uses. Each cluster defined by the intersection of angle/belief + pain point + persona + awareness level. Display as a "Positioning Map" section in the pack.
**Why:** The raw aggregated data (hooks, angles, benefits) is useful but doesn't answer the strategic question: "What are the 3-5 bets this competitor is making?" Clustering by belief/pain/persona reveals their actual creative strategy.
**Context:** All per-video extraction data already exists in `video_analyses` JSONB. No new video analysis needed — just one Claude call over the existing extractions. Could also power cross-competitor comparison ("Competitor A bets on mechanism, Competitor B bets on social proof").
**Depends on:** Phase 1 tested and stable.
**Added:** 2026-04-08 from Phase 1 testing discussion.

## Ad Translation Capability B — Pipeline Language Threading
**What:** Thread `language` param into `create_ads_v2()` pipeline so new ads can be generated directly in any language. Hooks adapted in target language, copy scaffolding generates in target language. Requires adding `language` param to `run_ad_creation_v2()`, `ContentService.select_hooks()`, `CopyScaffoldService.generate_copy_set()`, and `AdGenerationService.generate_prompt()`.
**Why:** Lets users create fresh Spanish ads from templates, not just translate existing ones. Currently only Capability A (translate existing ads) is implemented.
**Pros:** Complete multi-language story. Users can create AND translate.
**Cons:** Touches 4 deep pipeline files (content_service, copy_scaffold_service, generation_service, orchestrator). Also requires copy guardrail localization (see below).
**Context:** Deferred from ad-translation PR during /plan-eng-review scope reduction. Capability A must be merged and tested first. ~30min CC time.
**Depends on:** Ad Translation Capability A merged. Copy Guardrail Localization (below).
**Added:** 2026-04-22 from /plan-eng-review of Ad Translation feature.

## Copy Guardrail Localization
**What:** The copy validation regexes in `copy_scaffold_service.py` (lines 42-82) are English-only. Patterns like `r'\d+%\s*off'` won't catch Spanish equivalents (`'\d+%\s*de descuento'`). Non-English copy bypasses ALL safety checks.
**Why:** Blocks Capability B (pipeline language threading). Not needed for Capability A since we translate already-approved English copy.
**Pros:** Safety parity across languages. Prevents prohibited claims in non-English ads.
**Cons:** Maintaining regex patterns per language is brittle. Better long-term approach: switch to Claude-based semantic validation instead of regex.
**Context:** Current guardrails check for discounts, medical claims, guarantees, urgency language — all via English regex. Could either (a) add per-language regex sets, or (b) replace with a Claude validation call that works in any language. Option (b) is more robust but adds latency + cost.
**Depends on:** Nothing, but only matters when Capability B is implemented.
**Added:** 2026-04-22 from /plan-eng-review of Ad Translation feature (outside voice finding).
