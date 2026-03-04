# Phase 8B: Advanced Intelligence — Implementation Checkpoint

**Date:** 2026-02-16
**Branch:** `feat/ad-creator-v2-phase0`
**Commit:** `f2e6a05`
**Status:** Code complete — 63 new tests, 834 total passing, 0 regressions

## What Was Implemented

Phase 8B is the final intelligence phase, upgrading the scoring system from static weights to autonomously learned weights (Thompson Sampling), adding generation-level A/B testing (Mann-Whitney U), cross-brand knowledge transfer, competitive whitespace identification, visual style clustering (DBSCAN), and a full cold→warm→hot scorer weight transition.

### New Files (10)

| File | Purpose |
|------|---------|
| `migrations/2026-02-16_ad_creator_v2_phase8b.sql` | 7 tables (scorer_weight_posteriors, selection_weight_snapshots, whitespace_candidates, generation_experiments, generation_experiment_runs, visual_style_clusters, visual_style_cluster_members) + brands.cross_brand_sharing column + partial unique index for max-1-active-experiment |
| `viraltracker/services/scorer_weight_learning_service.py` | Thompson Sampling on Beta(α,β) posteriors for all 8 scorer weights. Credit assignment from matured rewards. Cold→warm→hot phase transitions. Safety rails (floor 0.1, ceiling 2.0, max ±0.15 delta). Selection snapshot recording. |
| `viraltracker/services/generation_experiment_service.py` | 2-arm (control/variant) generation A/B testing. SHA-256 deterministic arm assignment. Mann-Whitney U with tie-corrected variance (pure Python, no scipy). Ad-level binary outcome analysis. |
| `viraltracker/services/whitespace_identification_service.py` | Competitive whitespace identification: cross-dimension pairwise combo scoring with novelty bonus (`0.15 * exp(-usage/3)`), synergy from interactions, filters (both scores > 0.5, usage < 5, no conflicts). Top 20 candidates. |
| `viraltracker/pipelines/ad_creation_v2/services/visual_clustering_service.py` | DBSCAN on cosine distance matrices of visual embeddings. Performance correlation (cluster → avg reward). Diversity check (cosine > 0.90 threshold). Pure Python DBSCAN implementation. |
| `tests/services/test_scorer_weight_learning.py` | 16 tests: credit assignment, phase transitions, blending formulas, safety rails, initialization |
| `tests/services/test_whitespace.py` | 10 tests: scoring, novelty bonus, filtering, advisory formatting |
| `tests/services/test_generation_experiments.py` | 14 tests: Mann-Whitney U with tie correction (binary heavy-tie data), deterministic assignment, metric aggregation, analysis workflow |
| `tests/services/test_cross_brand_transfer.py` | 11 tests: org scoping, opt-in enforcement, brand similarity (cosine), interaction transfer |
| `tests/services/test_visual_clustering.py` | 12 tests: DBSCAN output, centroid computation, performance correlation, diversity check |

### Modified Files (9)

| File | Changes |
|------|---------|
| `viraltracker/services/template_scoring_service.py` | Default scorers changed from `PHASE_4_SCORERS` to `PHASE_8_SCORERS` in `select_templates_with_fallback()` (line 834) |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +8 fields: selection transport (`selection_weights_used`, `selection_scorer_breakdown`, `selection_composite_score`, `selection_mode`) + experiment assignment (`experiment_seed`, `generation_experiment_id`, `generation_experiment_arm`, `generation_experiment_config`) |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | +4 params to `run_ad_creation_v2()` for selection transport, +experiment seed generation via `sha256(product_id:template_id:timestamp_minute)`, +arm assignment pre-graph |
| `viraltracker/pipelines/ad_creation_v2/nodes/compile_results.py` | +`_record_selection_snapshot()` via ScorerWeightLearningService, +`_record_experiment_outcome()` via GenerationExperimentService |
| `viraltracker/services/creative_genome_service.py` | +Whitespace advisory + visual cluster advisory in `get_performance_context()`, +org-scoped `get_category_priors(brand_id)` with `_get_sharing_brand_ids()`, `_org_scoped_priors()`, +`compute_brand_similarity()` (cosine of score vectors, cached 1hr) |
| `viraltracker/services/interaction_detector_service.py` | +`get_cross_brand_interactions(brand_id)` fallback from opted-in brands in same org |
| `viraltracker/worker/scheduler_worker.py` | +Learned weights via `ScorerWeightLearningService` (replacing static `SMART_SELECT_WEIGHTS`), +`PHASE_8_SCORERS` explicit pass, +selection data threading into template dicts, +selection params passed to `run_ad_creation_v2()`, +piggyback: weight learning + whitespace + clustering on `execute_genome_validation_job()` |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | +`PHASE_8_SCORERS` import + explicit pass, +learned weights via `ScorerWeightLearningService` |
| `viraltracker/ui/pages/64_⚙️_Platform_Settings.py` | +3 tabs: Scorer Weights (per-scorer DataFrame + phase summary), Generation Experiments (list/activate/analyze/conclude), Visual Clusters (ranked DataFrame) |
| `viraltracker/ui/pages/02_🏢_Brand_Manager.py` | +Cross-brand sharing toggle (`st.toggle`) with save button |
| `tests/services/test_template_scoring_service.py` | Renamed `test_phase4_is_default` → `test_phase8_is_default`, updated assertions for 8 scorer keys |

### Test Results

- **834 tests** — all passing (63 Phase 8B new + 771 existing)
- **0 regressions** (scorer default test updated for PHASE_8 change)
- **3 pre-existing failures** (confirmed failing on clean HEAD `e6182db`, not caused by 8B)

### Key Design Decisions

1. **Thompson Sampling**: Beta(α,β) posteriors per scorer per brand, same pattern as creative genome element scores
2. **Credit assignment**: contribution-weighted `W_i * S_i / Σ(W_j * S_j)`, high-contribution scorers get full α/β update, low get 0.3× soft update
3. **Cold→Warm→Hot transition**: 0-29 obs = static only, 30-99 = linear blend `α=(obs-30)/70`, 100+ = fully learned
4. **Safety rails**: floor 0.1 (no scorer zeroed), ceiling 2.0, max ±0.15 delta per weekly update
5. **Mann-Whitney U**: pure Python with tie-corrected variance `σ² = n_a*n_b/12 * (N+1 - Σ(t_k³-t_k)/(N*(N-1)))`, critical for binary approval data with many ties
6. **Ad-level analysis**: each ad is a binary outcome (approved=1, not=0), avoiding bias from varying run sizes
7. **2-arm model**: control/variant configs on experiment row (matching CHECKPOINT_002.md schema), not multi-arm table
8. **Max 1 active experiment per brand**: partial unique index `WHERE status = 'active'`
9. **SHA-256 deterministic assignment**: `hashlib.sha256()` not Python `hash()` (salt-randomized per process)
10. **Experiment seed**: `sha256(product_id:template_id:timestamp_minute)` for replay stability across retries
11. **Selection transport**: weights/scores passed as explicit params to `run_ad_creation_v2()` → state fields → CompileResultsNode records snapshot with `ad_run_id` (solving the "ad_run_id doesn't exist pre-graph" timing problem)
12. **Cross-brand transfer**: org-scoped, opt-in per brand (`brands.cross_brand_sharing` default FALSE), only statistical aggregates cross boundaries
13. **Brand similarity**: cosine similarity of element score mean vectors, cached in-memory (1hr TTL)
14. **Whitespace scoring**: `predicted_potential = mean(score_a, score_b) + synergy_bonus + novelty_bonus` where novelty = `0.15 * exp(-usage/3.0)`
15. **DBSCAN clustering**: pure Python on cosine distance matrix, eps=0.3, min_samples=3, cluster -1 = noise
16. **Non-fatal integration**: all new code in pipeline nodes and worker wrapped in try/except with warning logs

### P0/P1 Fixes Applied

| # | Issue | Fix |
|---|-------|-----|
| P0-1 | Arm assignment uses ad_run_id before it exists | `experiment_seed` via `sha256(product_id:template_id:timestamp_minute)` pre-graph; record `ad_run_id` linkage in CompileResultsNode |
| P0-2 | Scorer default still PHASE_4_SCORERS | Changed default in `select_templates_with_fallback()` to `PHASE_8_SCORERS`; passed explicitly from scheduler + UI |
| P0-3 | Statistical method drift (Bayesian vs Mann-Whitney U) | Mann-Whitney U as specified in PLAN.md:1063; pure Python, no scipy |
| P0-3b | Multi-arm schema vs parent plan 2-arm | Simplified to control/variant matching CHECKPOINT_002.md schema |
| P0-4 | Style clustering missing from 8B scope | Added VisualClusteringService with DBSCAN as required by PLAN.md:1350 |
| P0-5 | Invalid SQL: UNIQUE WHERE inside CREATE TABLE | Separate `CREATE UNIQUE INDEX ... WHERE status='active'` |
| P0-6 | Python `hash()` salt-randomized per process | `hashlib.sha256().hexdigest()` → int → % 100 |
| P0-7 | Scorer-credit attribution data path unclear | Explicit transport: selection W_i/S_i as params → state → CompileResultsNode records snapshot |
| P1-1 | Human-override metrics counted too early | Override rate computed asynchronously in `run_analysis()` from `ad_review_overrides` |
| P1-2 | Active experiment cardinality undefined | Max 1 active via partial unique index + service validation |
| P1-4 | Statistical unit mismatch (per-run vs per-ad) | Ad-level binary analysis, not per-run summaries |

### Data Flow

```
Template selection → ScorerWeightLearningService.get_learned_weights() → effective weights
                  → select_templates_with_fallback(scorers=PHASE_8_SCORERS) → scores
                  → selection data threaded into run_ad_creation_v2() params → state

Pipeline runs → InitializeNode (ad_run_id created) → ... → CompileResultsNode
             → _record_selection_snapshot() → selection_weight_snapshots table
             → _record_experiment_outcome() → generation_experiment_runs table

Weekly genome_validation job →
  1. Existing: element scores, combo usage, interaction detection
  2. NEW: update_scorer_posteriors() → scorer_weight_posteriors (credit assignment)
  3. NEW: identify_whitespace() → whitespace_candidates (top 20)
  4. NEW: cluster_brand_styles() → visual_style_clusters + members
  5. NEW: correlate_with_performance() → avg_reward per cluster

Generation experiments →
  Orchestrator: sha256 seed → assign_arm() → state.generation_experiment_*
  CompileResultsNode: record_outcome() with ad_run_id
  Analysis: ad-level binary outcomes → Mann-Whitney U → winner/inconclusive
  Settings UI: create/activate/analyze/conclude

Cross-brand transfer →
  Brand requests priors → check cross_brand_sharing in same org
  → aggregate element_scores weighted by observations × similarity
  → apply CROSS_BRAND_SHRINKAGE = 0.3
  → fallback interaction effects from opted-in org peers
```

### UI Validation Tests

#### Completed

| # | Test | Status |
|---|------|--------|
| 1 | Run migration `phase8a.sql` | PASS |
| 2 | Run migration `phase8b.sql` | PASS |
| 3 | Platform Settings — Calibration Proposals tab | PASS |
| 4 | Platform Settings — Interaction Effects tab | PASS |
| 5 | Platform Settings — Exemplar Library tab | PASS |
| 6 | Auto-seed exemplars for brand with overrides | PASS |
| 7 | Platform Settings — Scorer Weights tab | PASS |
| 8 | Platform Settings — Generation Experiments tab | PASS |
| 9 | Platform Settings — Visual Clusters tab | PASS |
| 10 | Mark as Exemplar button works | PASS (after fix `5306a87`) |
| 11 | Remove exemplar from Exemplar Library | PASS (after fix `071361b`) |
| 12 | Full V2 pipeline end-to-end via worker (2 templates) | PASS — all nodes completed, Logfire traces confirm |
| 13 | CompileResultsNode records selection snapshot + experiment data | PASS — node completed in 0.1s, no errors |

#### Previously Remaining — Now Verified

| # | Test | Status | Notes |
|---|------|--------|-------|
| 14 | Visual embeddings stored after review | PASS (after bug fix) | Bug: `visual_descriptor_service.py` called `analyze_image(image_base64=...)` — wrong kwarg name (should be `image_data=`) + spurious `model=` param. Silent `TypeError` caught by `logger.debug()`. Fixed. |
| 15 | Quality calibration job runs on schedule | PASS | `quality_calibration` job exists, `status=active`, cron `0 3 * * 6` (Saturdays 3am) |
| 16 | Interaction detection on genome_validation | CONDITIONAL PASS | genome_validation ran successfully. No interactions found — `creative_element_rewards` table empty (no human overrides yet). Code path executes correctly. |
| 17 | Cross-Brand Sharing toggle | PASS | `brands.cross_brand_sharing` column exists (default FALSE). UI toggle + save button at `Brand_Manager.py:1469-1491` verified. |
| 18 | Selection snapshot in DB | PASS | 2 snapshots in `selection_weight_snapshots` with `composite_score`, `selection_mode=smart_select`. Timestamps match CompileResultsNode trace. |
| 19 | Learned weights when 30+ observations | CONDITIONAL PASS | Posteriors initialized at cold phase (8 scorers, all `alpha=1, beta=1, obs=0`). Needs 30+ observations for warm phase. 16 unit tests cover phase transitions. |
| 20 | Whitespace on genome_validation | CONDITIONAL PASS | genome_validation ran. No whitespace candidates — depends on `element_combo_usage` (empty) and `element_interactions` (empty). Code path executes correctly. |
| 21 | Clustering on genome_validation | CONDITIONAL PASS | genome_validation ran. No clusters — depends on `visual_embeddings` (empty until bug #14 fix deployed). Code path executes correctly. |
| 22 | Experiment create→activate→run→analyze→conclude | PASS (after bug fix) | Full lifecycle tested programmatically. Bug: `_collect_ad_outcomes()` queried `generated_ads.review_status` — column doesn't exist (should be `final_status`). Fixed. Also added Create Experiment form to Platform Settings UI. |

### Bugs Fixed During Testing

| Commit | Bug | Fix |
|--------|-----|-----|
| `5306a87` | Mark as Exemplar: `generated_ads.brand_id` doesn't exist, then `ad_runs.brand_id` doesn't exist | Use `st.session_state.v2_brand_id`, fallback to `ad_runs → products(brand_id)` join |
| `071361b` | Exemplar Library: `generated_ads.weighted_score` doesn't exist | Removed from all queries, compute from `review_check_scores` instead |
| `915e533` | Logfire not initialized on worker server | Added `setup_logfire()` to worker `main()` entry point |
| N/A | Pipeline stuck at "analyzing" after deploy killed worker mid-run | Deploy restart, not a code bug. Manually cleaned up stuck ad_run + scheduled_job_run |
| pending | Visual descriptor service: wrong kwargs to `analyze_image()` | `image_base64=` → `image_data=`, removed spurious `model=` param, pass `model` to `GeminiService()` constructor instead |
| pending | Visual clustering service: wrong column name `descriptors` | Changed to `visual_descriptors` (matches migration schema) |
| pending | Experiment analysis: wrong column `review_status` in `_collect_ad_outcomes()` | Changed to `final_status` (matches `generated_ads` table) |
| pending | Embedding failure logging too quiet (`logger.debug`) | Upgraded to `logger.warning` in `review_ads.py` |
| pending | Missing "Create Experiment" form in Platform Settings UI | Added form with name, hypothesis, type, split ratio, sample size, JSON configs |
| pending | No `genome_validation` scheduled job for Martin Clinic | Created via INSERT, cron `0 4 * * 0` (Sundays 4am) |

### Logfire Observability Status

- **Worker**: Logfire active (`viraltracker-scheduler-worker`), capturing PydanticAI spans + pydantic-graph node spans
- **UI**: Logfire active (`viraltracker`), capturing Pydantic validation spans. Logger output not yet reaching Logfire (known gap — `LogfireLoggingHandler` configured in `app.py` but pipeline logger calls not propagating)
- **Pipeline node traces visible**: InitializeNode → FetchContextNode → AnalyzeTemplateNode → SelectContentNode → HeadlineCongruenceNode → SelectImagesNode → GenerateAdsNode → DefectScanNode → ReviewAdsNode → RetryRejectedNode → CompileResultsNode
- **LLM calls visible**: Gemini 3 Pro Image Preview (generation + review), Claude Opus 4.6 (content selection)

### Dependencies on Phase 8A

Phase 8B builds directly on Phase 8A infrastructure:
- `visual_embeddings` table → DBSCAN clustering input
- `element_interactions` table → whitespace synergy bonus source
- `element_combo_usage` table → whitespace usage count source
- `creative_element_rewards` table → credit assignment reward source
- `FatigueScorer` + `PHASE_8_SCORERS` → now the default (was opt-in in 8A)
- `InteractionDetectorService` → extended with cross-brand transfer
- `CreativeGenomeService.get_performance_context()` → extended with whitespace + cluster advisory
