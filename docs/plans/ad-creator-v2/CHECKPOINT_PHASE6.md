# Phase 6: Creative Genome — Implementation Checkpoint

**Date:** 2026-02-15
**Branch:** `feat/ad-creator-v2-phase0`
**Status:** Post-plan review PASS — pending UI validation + migration

## What Was Implemented

Phase 6 closes the ad creation learning loop: track which creative elements correlate with ad performance, use Thompson Sampling to shift future generation toward better-performing options, and inject advisory performance context into prompts.

### New Files (4)

| File | Purpose |
|------|---------|
| `migrations/2026-02-15_creative_genome.sql` | Schema: `element_tags`/`pre_gen_score` columns on `generated_ads`, new tables `creative_element_scores`, `creative_element_rewards`, `system_alerts` |
| `viraltracker/services/creative_genome_service.py` | Core service: reward computation (composite CTR/Conv/ROAS), Thompson Sampling (Beta distributions), pre-gen scoring, cold-start priors (cross-brand shrinkage), performance context builder, monitoring/validation with threshold alerts |
| `tests/services/test_creative_genome_service.py` | 33 unit tests covering all pure functions and async methods |
| `tests/pipelines/ad_creation_v2/test_element_tagging.py` | 7 tests for element tag building and pipeline integration |

### Modified Files (12)

| File | Changes |
|------|---------|
| `viraltracker/services/ad_creation_service.py` | `save_generated_ad()` +2 params: `element_tags: Optional[Dict]`, `pre_gen_score: Optional[float]` |
| `viraltracker/services/template_scoring_service.py` | +`PerformanceScorer` class (looks up posterior mean from `creative_element_scores`), +`PHASE_6_SCORERS` list, +`performance` key in `ROLL_THE_DICE_WEIGHTS` (0.0) and `SMART_SELECT_WEIGHTS` (0.3) |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +`performance_context: Optional[Dict[str, Any]] = None` field |
| `viraltracker/pipelines/ad_creation_v2/models/prompt.py` | Expanded `PerformanceContext` model: +`cold_start_level`, `total_matured_ads`, `top_performing_elements`, `exploration_rate` fields |
| `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` | Builds `element_tags` dict per ad, computes `pre_gen_score` (non-fatal), passes `performance_context` to `generate_prompt()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` | Fetches genome performance context via `CreativeGenomeService.get_performance_context()` (non-fatal) |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | Passes `element_tags` + `pre_gen_score` to `save_generated_ad()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | Passes `element_tags` + `pre_gen_score` to `save_generated_ad()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | Builds `retry_element_tags`, passes `performance_context` to `generate_prompt()`, passes `element_tags` to both `save_generated_ad()` calls |
| `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` | Accepts `performance_context` param, builds `PerformanceContext` model, wires into `AdGenerationPrompt` |
| `viraltracker/worker/scheduler_worker.py` | +`execute_creative_genome_update_job()` (compute rewards + update scores), +`execute_genome_validation_job()` (health metrics + alerts), routing in `execute_job()` |
| `tests/services/test_template_scoring_service.py` | Updated weight preset assertions to include `performance` key |

### Test Results

- **40 new tests** (33 genome service + 7 element tagging) — all passing
- **639 total tests passing**
- **8 pre-existing failures** in integration tests (confirmed same on baseline commit)
- **0 regressions** from Phase 6 changes

### Key Design Decisions

1. **Element tags built in GenerateAdsNode**, passed through pipeline dicts to save calls in DefectScanNode/ReviewAdsNode/RetryRejectedNode
2. **Pre-gen score** only computed when `performance_context` is present (non-fatal, catches all exceptions)
3. **Genome context fetch** in FetchContextNode is non-fatal (try/except with warning log)
4. **PerformanceScorer** uses posterior mean (α/(α+β)) not sampling, for deterministic template scoring
5. **Thompson Sampling** uses sampling (np.random.beta) for exploration in `sample_element_scores()`
6. **Cold-start priors** aggregate cross-brand with 0.3x shrinkage toward uniform
7. **Reward weights** stratified by campaign objective (CONVERSIONS, SALES, TRAFFIC, AWARENESS, ENGAGEMENT, DEFAULT)
8. **Monitoring thresholds** for approval_rate, generation_success_rate, data_freshness, winner_rate

### Post-Plan Review Fixes

3 issues found and fixed during post-plan review:

1. **CRITICAL:** `scheduler_worker.py` — `reschedule_job(job)` was undefined (NameError at runtime). Fixed to use `calculate_next_run()` for success + `_reschedule_after_failure()` for failure.
2. **CRITICAL:** `scheduler_worker.py` — `update_job_run()` called with wrong signature (positional strings vs dict). Fixed to dict format.
3. **LOW:** `retry_rejected.py` — `pre_gen_score` missing from `save_generated_ad()` calls. Added for consistency.
4. **LOW:** `template_scoring_service.py` — `PerformanceScorer` silent `except`. Added `logger.warning()`.

### UI Validation Tests (TODO before merge)

| # | Test | Where | Priority | Pass? |
|---|------|-------|----------|-------|
| 1 | Run migration `2026-02-15_creative_genome.sql` | Supabase SQL editor | **MUST** (before any V2 runs) | |
| 2 | V2 ad creation (any template, hooks mode) — verify ad saves with `element_tags` populated | Ad Creator UI | **HIGH** | |
| 3 | V2 scheduled run with `smart_select` mode — verify templates selected normally | Ad Scheduler UI | MEDIUM | |
| 4 | Check scheduler worker logs on next genome cron cycle — verify no NameError | Railway logs | LOW | |

### Plan Source

`docs/plans/ad-creator-v2/PLAN.md` Section 10
