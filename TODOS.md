# TODOS

## Ad History — Sort by angle
**What:** In `viraltracker/ui/pages/22_📊_Ad_History.py`, add an "Angle" column / grouping option to the ad-run listing so the user can sort or filter to see all runs (and thus all generated ads) for a specific belief angle. Should pull `belief_angles.name` joined via `ad_runs.angle_id` (column added in `migrations/2026-05-26_ad_runs_angle_id.sql`).
**Why:** With angle-driven generation as the primary flow, the natural unit of comparison is "how did all my ads testing angle X perform vs angle Y." Right now the page shows ads in flat chronological order with no way to roll up by strategic angle.
**Context:** Schema is ready — `ad_runs.angle_id` (PR #196) + `generated_ads.angle_id` (already-existing column populated by PR #196's stamping path). Implementation is UI-only: add a filter selectbox at the top of Ad History showing all angles that have at least one ad_run, plus column showing angle name on each run row.
**Depends on:** Nothing — schema and data are live in production.
**Added:** 2026-05-26 from session post-Step-5c review.

## Ad History — Date range filter
**What:** Add a date range picker at the top of `viraltracker/ui/pages/22_📊_Ad_History.py` so the user can scope the run listing to a specific window (e.g. "last 7 days", "last 30 days", custom range). Should filter `ad_runs.created_at` server-side via Supabase query (not in-memory) so pagination still works correctly with large result sets.
**Why:** Ad History grows unbounded over time. Today the only way to find recent runs is to manually paginate through the most-recent-first listing. A simple date filter would surface the relevant window immediately.
**Context:** Streamlit has `st.date_input()` with range support — minimal UI work. Existing query in `get_ad_runs()` (around line 89) takes brand_id/org_id filters; add an optional `(start_date, end_date)` tuple that gets translated to `.gte("created_at", ...).lte("created_at", ...)` calls. Default to "last 30 days" to keep first load snappy.
**Depends on:** Nothing — pure UI + query addition.
**Added:** 2026-05-26 from session post-Step-5c review.

## PR 4b — Full in-batch hook-diversity-rejection refactor for angle-driven flow
**What:** Refactor hook generation in `viraltracker/pipelines/ad_creation_v2/services/content_service.py` (`select_hooks()` and `generate_benefit_variations()`) from one-shot batch LLM calls to per-hook iteration that lets `HookDiversityChecker.generate_with_diversity()` actually intercept each hook with retry-and-best-of-N rejection. Then thread `hook_embedding` from the diversity check directly to `save_generated_ad()` so we skip the inline embedding pass (currently in PR 4a).
**Why:** PR 4a (Step 4a, merged) populated `generated_ads.hook_embedding` + `ad_creation_run_id` so the falsifiability metric works end-to-end, but the actual in-batch diversity GUARDRAIL (the "wired but tired at 3am" rejection-and-retry behavior) is NOT yet active. Hooks generate in batches and the diversity check only stores embeddings after the fact.
**Context:** Decision in `/plan-eng-review` (2026-05-25) was C "full refactor"; surfaced during Step 4 implementation that hooks are generated as a batch (one LLM call returns N hooks) inside content_service, not one-at-a-time at the scheduler. PR 4a was the falsifiability-only minimal slice. PR 4b is the rejection-loop work. Two paths considered: (a) call LLM N times (1 per hook, expensive but exact match to checker's contract), (b) call LLM for 2-3x what we need, post-process via diversity check. Pick (b) for cost; (a) for purity. Multi-file refactor on hot ad-generation paths — real refactor risk.
**Depends on:** PR 4a merged. Real production data from V1 (need to see if the falsifiability metric flags collapse before doing the bigger refactor — could turn out P4 was right to defer entirely).
**Added:** 2026-05-25 from Step 4 implementation discovery.

## Fix winners-extraction script's generated_ads ↔ Meta ad_name join
**What:** `scripts/extract_winning_angle_baselines.py --extract-angles` matches Meta `ad_name` to `generated_ads.storage_path` basename and currently fails for older Martin Clinic-style ad names like `Ryan Upload - insomnia _M5-4dc8486a-MC-XX-ST.png_Feb/14/2026` (matched 0/10 winners). The embedded 8-char hex fragments (e.g. `4dc8486a`) look like `generated_ads.id` UUID prefixes; PostgREST `like` on UUID columns fails without explicit `::text` cast. Fix by either (a) pulling recent `generated_ads.id` set into Python and doing prefix-match locally, or (b) adding a derived `ad_name_basename TEXT` column on `generated_ads` populated at insert time for direct join.
**Why:** Without the join, `--extract-angles` produces empty inferred angles for any ad whose storage_path basename doesn't match Meta's naming convention — defeats the whole "reverse-engineer winning angles as a quality bar" use case.
**Context:** Discovered 2026-05-25 when running Step 1b for Martin Clinic. Calibration finding (0.65 threshold) was the actually-useful Step 1 output; the winners-extraction angle inference was nice-to-have and gracefully degraded to "Cannot infer — no ad copy provided" for unmatched ads. Not a V1 blocker; nice-to-have for future calibration runs against other brands.
**Depends on:** Nothing — independent fix when someone next needs the script.
**Added:** 2026-05-25 from Step 1 execution against real Martin Clinic data.

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

## Consolidate GSC Stores — seo_article_rankings vs seo_article_analytics
**What:** Migrate the opportunity miner to read `seo_article_analytics` and retire `seo_article_rankings` (or reduce it to a compatibility view). Both tables store GSC position/impressions/clicks today.
**Why:** Two stores for one feed go stale independently — during the 2026-06-09 eng review one was 3 months stale and the other 8 weeks, and the split helped hide a total GSC-feed outage (analytics_sync had never run; the weekly opportunity scan silently produced 0 output for months).
**Pros:** One feed to monitor, one freshness gate, simpler miner; kills the "which table is right" class of bugs.
**Cons:** Miner query rewrite + data migration; `seo_article_rankings` holds ~10k rows including `source='manual'` entries that need a home.
**Context:** Miner reads rankings via the batch fetch in `opportunity_miner_service.py` (~line 164); the Dashboard reads analytics. Increment 0 of the §7 Tier-2 work adds per-source freshness monitoring covering BOTH tables in the meantime, so this is debt, not an outage risk. Start at the miner's batch-fetch query. `seo_article_analytics` is canonical (proper daily grain, `UNIQUE(article_id, date, source)`).
**Depends on:** §7 Tier-2 increment 0 (feed fixes + freshness monitoring) shipped.
**Added:** 2026-06-09 from /plan-eng-review of hardening plan §4 + §7 Tier-2.

## Review Link Impact Card Against Measured Data (DUE ~2026-06-23)
**What:** Validate the Link Impact card (SEO Dashboard) once 2+ weekly scans have written real coverage snapshots. Check: (1) the approximate backfill series roughly agrees with measured snapshots where they overlap (it should UNDERCOUNT — Related-block links churn timestamps; large divergence means the reconstruction is misleading and should be dropped); (2) provenance labels switch from approximate/mixed → measured as history accrues; (3) bucket medians are stable enough to be readable (if gained-links bucket has <5 articles, consider widening the window from 90d); (4) the live-check sample (10/brand) is catching anything — if verified is always 100%, consider dropping the cap to 5 to save Shopify calls.
**Why:** The card shipped against zero measured history by design (built 2026-06-09 instead of waiting 2 weeks; approximate backfill made it useful day one). This review closes the loop on whether the cold-start approximations were honest.
**Context:** Card code in `48_🔍_SEO_Dashboard.py` (Link Impact section); data method `SEOAnalyticsService.get_link_impact`; live-check `InterlinkingService.verify_live_links`. Snapshots accrue every Sunday scan (seo_opportunity_scan, next runs 06-16 and 06-23 — two data points by the due date). Plan: §11 R7/R9.
**Depends on:** Two weekly scans having run (06-16, 06-23).
**Added:** 2026-06-09, per Ryan's "build it now and make a note to review in 1-2 weeks."
