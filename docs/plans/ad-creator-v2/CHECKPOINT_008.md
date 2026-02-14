# CHECKPOINT 008 — Phase 3: Asset-Aware Prompts + Scoring Expansion

**Date:** 2026-02-14
**Branch:** `feat/ad-creator-v2-phase0`
**Phase:** Phase 3: Asset-Aware Prompts + Scoring Expansion
**Chunks:** P3-C1, P3-C2, P3-C3
**Token estimate:** ~70K total across 3 chunks

---

## Scope Completed

### P3-C1: Phase 2 Deferred Unit Tests (48 tests)
- [x] `tests/pipelines/ad_creation_v2/test_state.py` — canvas_size/color_mode compat properties, empty list fallback, to_dict/from_dict round-trip (13 tests)
- [x] `tests/pipelines/ad_creation_v2/test_orchestrator_normalization.py` — scalar→list normalization, defaults, num_variations validation (11 tests)
- [x] `tests/pipelines/ad_creation_v2/test_generate_ads_node.py` — triple loop variant count, per-ad metadata, variant_counter, failure resilience (6 tests)
- [x] `tests/worker/test_scheduler_v2_validation.py` — canvas size/color mode validation+dedupe, cap math (V×S×C), clamping, fallback to defaults (18 tests)

### P3-C2: Scoring Pipeline Expansion (35 tests)
- [x] `AwarenessAlignScorer` — template awareness_level vs persona awareness_stage, distance-based scoring, None→0.5 neutral
- [x] `AudienceMatchScorer` — template target_sex vs context target_sex, exact→1.0, unisex/None→0.7, mismatch→0.2
- [x] `target_sex` added to `SelectionContext`
- [x] `PHASE_3_SCORERS` list (5 scorers), weight presets updated (5 keys each)
- [x] Default scorers changed from `PHASE_1_SCORERS` to `PHASE_3_SCORERS`
- [x] Tier-3 fallback preserves `target_sex` in cloned context
- [x] `fetch_brand_min_asset_score(brand_id)` helper
- [x] Persona target_sex wired into UI and worker
- [x] Score display updated to 6 columns
- [x] `tests/services/test_template_scoring_service.py` (35 tests)

### P3-C3: Asset-Aware Prompts (15 tests)
- [x] State: `template_elements`, `asset_match_result`, `brand_asset_info`
- [x] Prompt: `TextAreaSpec`, expanded `AssetContext` (12 fields)
- [x] FetchContextNode: template elements fetch with `element_detection_version` branching, brand assets fetch
- [x] SelectImagesNode: `asset_tags` query, enrichment, template requirement passthrough
- [x] ContentService: asset tag matching bonus (required × 0.3, optional × 0.1)
- [x] GenerationService: `_build_asset_context()`, 3 new Optional params
- [x] InitializeNode: `canvas_sizes`/`color_modes` in run_parameters
- [x] GenerateAdsNode + RetryRejectedNode: selected_image_tags passthrough
- [x] `tests/pipelines/ad_creation_v2/test_asset_context.py` (15 tests)

---

## Files Changed

| File | Change |
|------|--------|
| `tests/pipelines/__init__.py` | NEW: package init |
| `tests/pipelines/ad_creation_v2/__init__.py` | NEW: package init |
| `tests/pipelines/ad_creation_v2/test_state.py` | NEW: 13 tests |
| `tests/pipelines/ad_creation_v2/test_orchestrator_normalization.py` | NEW: 11 tests |
| `tests/pipelines/ad_creation_v2/test_generate_ads_node.py` | NEW: 6 tests |
| `tests/pipelines/ad_creation_v2/test_asset_context.py` | NEW: 15 tests |
| `tests/worker/__init__.py` | NEW: package init |
| `tests/worker/test_scheduler_v2_validation.py` | NEW: 18 tests |
| `tests/services/test_template_scoring_service.py` | NEW: 35 tests |
| `viraltracker/services/template_scoring_service.py` | +2 scorers, +target_sex, +weight presets, +brand gate helper |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +3 Phase 3 fields |
| `viraltracker/pipelines/ad_creation_v2/models/prompt.py` | +TextAreaSpec, expanded AssetContext |
| `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` | +template elements fetch, +brand assets fetch |
| `viraltracker/pipelines/ad_creation_v2/nodes/select_images.py` | +asset_tags query, +enrichment |
| `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py` | +canvas_sizes/color_modes in run_parameters |
| `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` | +selected_image_tags, +asset state passthrough |
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | +selected_image_tags, +asset state passthrough |
| `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` | +_build_asset_context(), +3 new params |
| `viraltracker/pipelines/ad_creation_v2/services/content_service.py` | +asset tag matching bonus |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | +persona target_sex, +brand gate, +6-col scores |
| `viraltracker/worker/scheduler_worker.py` | +persona target_sex, +brand gate, +5-dim logging |
| `docs/plans/ad-creator-v2/PLAN.md` | Updated Phase 3 status, added known risks |

---

## Test Results

- **98/98 Phase 3 tests pass** (48 + 35 + 15)
- All changed files pass `python3 -m py_compile`
- 1 pre-existing integration test failure (Supabase FK constraint, fails on main too)

## Post-Plan Review

- **Verdict: PASS**
- Graph Invariants: PASS (all G1-G6, P1-P8)
- Test/Evals Gatekeeper: PASS with WARNs (node-level test gaps — pre-existing)

---

## Known Risks

1. **Regenerate flow lacks asset context** — `ad_creation_service.py:1965` gets `asset_context=None`
2. **`element_detection_version` dependency** — FetchContextNode branching relies on this column
3. **Selected-image coverage divergence** — Visual quality can override asset tag bonus
4. **Node-level test gap** — FetchContextNode/SelectImagesNode Phase 3 additions untested at node level
5. **`brand_assets` schema assumption** — Logo/badge detection relies on naming convention

---

## Deferred to Post-Phase 4

- Browser-test Phase 2 UI controls (multiselect renders, batch estimate)
- Browser-test Phase 3 UI changes (6-column score display, persona-aware scoring)
- End-to-end deployed environment testing

---

## Next Phase

**Phase 4: Congruence + Review Overhaul** — CongruenceService, HeadlineCongruenceNode, 3-stage review pipeline, structured review scores, human override buttons, BeliefClarityScorer.
