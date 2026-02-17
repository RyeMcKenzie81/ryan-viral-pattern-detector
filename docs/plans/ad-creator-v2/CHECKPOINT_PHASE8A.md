# Phase 8A: Core Autonomous Intelligence — Implementation Checkpoint

**Date:** 2026-02-16
**Branch:** `feat/ad-creator-v2-phase0`
**Status:** Code complete — post-plan review PASS

## What Was Implemented

Phase 8A adds 5 self-improving intelligence features to the Ad Creator V2 pipeline: few-shot exemplar library, adaptive threshold calibration, visual embedding space, pairwise interaction detection, and predictive fatigue scoring.

### New Files (11)

| File | Purpose |
|------|---------|
| `migrations/2026-02-16_ad_creator_v2_phase8a.sql` | 5 tables (exemplar_library, visual_embeddings, element_interactions, element_combo_usage, calibration_proposals) + pgvector extension + quality_calibration job seed |
| `viraltracker/pipelines/ad_creation_v2/services/exemplar_service.py` | Exemplar CRUD, auto-seed from overrides (superseded_by IS NULL), diversity selection, embedding-based similarity search, review prompt context builder |
| `viraltracker/pipelines/ad_creation_v2/services/visual_descriptor_service.py` | Gemini Flash visual descriptor extraction, OpenAI text-embedding-3-small embedding, pgvector storage and similarity search |
| `viraltracker/services/quality_calibration_service.py` | Override analysis (FP/FN rates), proposal generation with safety rails (min 30 samples, max ±1.0 delta), explicit validation of all 15 rubric checks, activate/dismiss workflow |
| `viraltracker/services/interaction_detector_service.py` | Pairwise element effect detection from creative_element_rewards + element_tags, bootstrap 95% CI, top-15 ranking, canonical ordering, advisory context formatting |
| `tests/services/test_exemplar_service.py` | 11 tests: caps, diversity, auto-seed, build_exemplar_context |
| `tests/services/test_visual_descriptor_service.py` | 12+ tests: parsing, text conversion, defaults, Gemini/OpenAI mocking, CRUD methods |
| `tests/services/test_quality_calibration_service.py` | 16+ tests: validation (6 conditions), safety rails, proposal rows, activate/dismiss/pending/history |
| `tests/services/test_interaction_detector_service.py` | 14+ tests: bootstrap CI, norm_cdf, advisory formatting, canonical ordering, top-15 limit, get_top_interactions |
| `tests/services/test_fatigue_scorer.py` | 17 tests: decay curves, bounds, scorer lists, weight presets, combo key format |

### Modified Files (8)

| File | Changes |
|------|---------|
| `viraltracker/services/template_scoring_service.py` | +`FatigueScorer` class (hybrid template decay + combo modifier), +`PHASE_8_SCORERS` (8 scorers), +"fatigue" in ROLL_THE_DICE_WEIGHTS (0.2) and SMART_SELECT_WEIGHTS (0.4) |
| `viraltracker/pipelines/ad_creation_v2/services/review_service.py` | +`exemplar_context` param to `review_ad_staged()`, `_run_rubric_review_claude()`, `_run_rubric_review_gemini()`, `_build_rubric_prompt()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | +Exemplar lookup before review (embedding extraction on-the-fly), +visual embedding storage post-review, all wrapped in try/except |
| `viraltracker/pipelines/ad_creation_v2/nodes/compile_results.py` | +`_record_combo_usage()` idempotent upsert with last_ad_run_id dedup |
| `viraltracker/worker/scheduler_worker.py` | +`execute_quality_calibration_job()` handler, +interaction detection piggyback on genome_validation |
| `viraltracker/services/creative_genome_service.py` | +Interaction advisory context in `get_performance_context()` |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | +"Mark as Exemplar" button in results dashboard |
| `viraltracker/ui/pages/64_⚙️_Platform_Settings.py` | +Calibration Proposals, Interaction Effects, Exemplar Library tabs |

### Test Results

- **135+ tests** — all passing (87 Phase 8A core + 48 existing scoring)
- **0 regressions** (weight preset tests updated for "fatigue" key)

### Key Design Decisions

1. **FatigueScorer** follows `TemplateScorer` ABC: stateless `score(template, context) -> float [0.2, 1.0]`
2. **Hybrid fatigue**: template-level `e^(-0.05 * days)` base × element-combo `e^(-0.03 * days)` modifier
3. **Combo dedup**: `ON CONFLICT ... DO UPDATE` with `IS DISTINCT FROM last_ad_run_id` prevents retry double-counting
4. **Combo unique index**: `CREATE UNIQUE INDEX` with `COALESCE(product_id, ...)` because Postgres rejects functional expressions in table-level UNIQUE constraints
5. **Exemplar auto-seed**: filters `superseded_by IS NULL` to use only latest override per ad
6. **Exemplar caps**: 30 total (10 gold_approve + 10 gold_reject + 10 edge_case)
7. **Diversity selection**: greedy on (template_category, canvas_size, color_mode) combo uniqueness
8. **Interaction detection**: observed vs independence expectation `E[A] × E[B] / E[global]`, bootstrap 95% CI
9. **Canonical ordering**: `(element_a_name, element_a_value) <= (element_b_name, element_b_value)` alphabetically
10. **Calibration safety rails**: min 30 overrides, max ±1.0 threshold delta, max ±0.5 weight delta, full validation before storage
11. **Failed validation → persisted**: proposals always stored for auditability, invalid ones get `status="insufficient_evidence"`
12. **Non-fatal Phase 8A additions**: all new code in pipeline nodes wrapped in try/except with warning logs
13. **SQL injection fix**: all values in `_record_combo_usage()` use `_sql_val()` escaping helper

### Post-Plan Review Findings (Fixed)

| # | Issue | Fix |
|---|-------|-----|
| 1 | SQL injection in `_record_combo_usage()`: brand_id, product_id, combo_key, now, ad_run_id directly interpolated | Changed to use `_sql_val()` for proper escaping |
| 2 | Weight preset test regression: expected 7 keys but Phase 8A added "fatigue" (8th) | Updated both expected_keys sets |

### Pre-existing Gaps (Not Phase 8A-specific)

- No eval baselines exist for `ReviewAdsNode` (no `tests/evals/` directory). Phase 8A modified the review prompt by adding optional `exemplar_context` injection, but the baseline gap predates Phase 8A. Tracked as tech debt.

### Full Risk Register

See `PHASE8_PLAN.md` > "Risks & Mitigations" for the complete risk register (9 implementation risks, 3 operational risks, 2 pre-existing gaps).

### Data Flow

```
Generation complete → extract_and_store() → visual_embeddings table
                   → record combo usage (idempotent) → element_combo_usage table

Review time → get ad embedding → find_similar_exemplars() → build_exemplar_context()
           → inject into _build_rubric_prompt() → Stage 2/3 review

Weekly genome_validation → detect_interactions() → element_interactions table
                        → enhance advisory context

Weekly quality_calibration → analyze_overrides(superseded_by IS NULL) → propose_calibration()
                          → calibration_proposals (pending)
                          → Operator activates in Settings → new quality_scoring_config

Template selection → FatigueScorer.score() → reads product_template_usage + element_combo_usage
                  → hybrid decay score [0.2, 1.0]
```

### UI Validation Tests (TODO before merge)

| # | Test | Where | Priority | Pass? |
|---|------|-------|----------|-------|
| 1 | Run migration `2026-02-16_ad_creator_v2_phase8a.sql` | Supabase SQL editor | **MUST** | |
| 2 | "Mark as Exemplar" button appears on approved ads in V2 results | Ad Creator V2 page | HIGH | |
| 3 | Platform Settings shows Calibration, Interactions, Exemplar Library tabs | Platform Settings page | HIGH | |
| 4 | Auto-seed exemplars works for brand with existing overrides | Platform Settings > Exemplar Library | HIGH | |
| 5 | FatigueScorer active in template selection (8 scorers) | Run ad generation, check logs | MEDIUM | |
| 6 | Visual embeddings stored after review | Run ad generation, check visual_embeddings table | MEDIUM | |
| 7 | Quality calibration job runs on schedule | Check scheduled_jobs table, trigger manual run | MEDIUM | |
| 8 | Interaction detection piggybacks on genome_validation | Trigger genome validation, check element_interactions | MEDIUM | |
