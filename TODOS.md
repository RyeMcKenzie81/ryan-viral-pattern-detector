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
