# CHECKPOINT 009 — Phase 4 Complete

**Date:** 2026-02-14
**Branch:** `feat/ad-creator-v2-phase0`
**Phase:** Phase 4: Congruence + Review Overhaul (ALL CHUNKS COMPLETE)
**Total tests:** 200 passing (93 existing + 107 new)

---

## Phase 4 Chunk Status

| Chunk | Scope | Tests | Status |
|-------|-------|-------|--------|
| P4-C1 | Migrations + BeliefClarityScorer | 18 new (48 total scoring) | DONE |
| P4-C2 | CongruenceService + HeadlineCongruenceNode | 29 new | DONE |
| P4-C3 | DefectScanService + DefectScanNode (Stage 1) | 16 new | DONE |
| P4-C4 | Review Overhaul (Stages 2-3) | 35 new (+4 load_quality_config) | DONE |
| P4-C5 | Human Override UI + Override Service | 15 new | DONE |
| P4-C6 | Deferred UI Testing + Success Gate | N/A (validation) | DONE |

---

## P4-C1: Migrations + BeliefClarityScorer

- [x] Migration SQL: final_status CHECK fix, generated_ads columns, ad_review_overrides table, quality_scoring_config table with COALESCE indexes + seed row
- [x] `BeliefClarityScorer`: D6=false->0.0, no eval->0.5, else sum(D1-D5)/15.0
- [x] `fetch_template_candidates()` extended with Query 3: template_evaluations prefetch
- [x] `PHASE_4_SCORERS` list (6 scorers), weight presets updated, default changed from PHASE_3 to PHASE_4
- [x] 18 new tests, all 48 scoring tests pass

## P4-C2: CongruenceService + HeadlineCongruenceNode

- [x] `CongruenceService` with `check_congruence()` and `check_congruence_batch()` (single LLM call for batch)
- [x] `CongruenceResult` dataclass (offer_alignment, hero_alignment, belief_alignment, overall, adapted_headline)
- [x] `HeadlineCongruenceNode` inserted between SelectContentNode and SelectImagesNode
- [x] Pass-through when no offer_variant_id (all hooks score 1.0)
- [x] Replaces hook_text with adapted_headline when below CONGRUENCE_THRESHOLD (0.6)
- [x] `FetchContextNode` extended to fetch LP hero data from brand_landing_pages
- [x] State extended: `lp_hero_data`, `congruence_results`
- [x] Orchestrator updated: 11 nodes
- [x] 29 new tests pass

## P4-C3: DefectScanService + DefectScanNode (Stage 1)

- [x] `DefectScanService` with 5 defect types (TEXT_GARBLED, ANATOMY_ERROR, PHYSICS_VIOLATION, PACKAGING_TEXT_ERROR, PRODUCT_DISTORTION)
- [x] `DefectScanResult` and `Defect` dataclasses with to_dict()
- [x] `DefectScanNode` between GenerateAdsNode and ReviewAdsNode
- [x] Defect-rejected: saved to DB immediately with final_status='rejected' + defect_scan_result, appended to reviewed_ads
- [x] Clean ads: appended to defect_passed_ads for Stage 2-3 review
- [x] Generation-failed: passed through (not scanned)
- [x] `save_generated_ad()` extended with 3 new params (defect_scan_result, review_check_scores, congruence_score)
- [x] State extended: `defect_passed_ads`, `defect_scan_results`
- [x] 16 new tests pass

## P4-C4: Review Overhaul (Stages 2-3)

- [x] `RUBRIC_CHECKS` constant (15 checks: V1-V9, C1-C4, G1-G2)
- [x] `DEFAULT_QUALITY_CONFIG` dict with weights, borderline_range, auto_reject_checks, pass_threshold
- [x] `review_ad_staged()`: Stage 2 (Claude Vision rubric) + conditional Stage 3 (Gemini Vision if borderline)
- [x] Auto-reject logic: V9 < 3.0 -> immediate reject
- [x] Borderline detection: any check in [5.0, 7.0] -> trigger Stage 3
- [x] OR logic: use better weighted score between Stage 2 and Stage 3
- [x] Helper functions: `_build_rubric_prompt()`, `_parse_rubric_scores()`, `compute_weighted_score()`, `apply_staged_review_logic()`, `load_quality_config()`
- [x] `ReviewAdsNode` reads from `defect_passed_ads`, calls `review_ad_staged()`, appends to existing `reviewed_ads`, passes `defect_scan_result`, `review_check_scores`, `congruence_score`
- [x] `ReviewAdsNode` loads `quality_config` from DB via `load_quality_config()`
- [x] 35 new tests pass (rubric constants, parsing, weighted scoring, staged logic, auto-reject, borderline/Stage 3, error handling, OR logic, load_quality_config)

## P4-C5: Human Override UI + Override Service

- [x] `apply_ad_override()` Postgres RPC function (atomic 3-step: insert override, update generated_ads, supersede previous)
- [x] `AdReviewOverrideService` with `create_override()`, `get_latest_override()`, `get_override_stats()`, `get_ads_for_run()`
- [x] Enhanced V2 UI results dashboard:
  - Per-ad cards with image, status badge, hook text
  - Structured review scores (V1-V9, C1-C4, G1-G2 as colored indicators)
  - Defect scan result display
  - Congruence score display
  - Override buttons (Override Approve / Override Reject / Confirm) with optional reason
  - Override rate summary at top (30d stats)
- [x] 15 new tests pass (validation, RPC delegation, latest-override, stats, ads-for-run)

## P4-C6: Success Gate Validation

| Metric | Implementation | Status |
|--------|---------------|--------|
| Defect catch rate | `DefectScanNode` rejects defected ads before Stage 2-3 | Code complete, measurable in prod |
| `defect_scan_result` coverage | Every generated ad (excl. generation_failed) gets scanned | Guaranteed by DefectScanNode flow |
| `review_check_scores` coverage | Every Stage-2-reviewed ad gets structured scores | Guaranteed by `review_ad_staged()` |
| Override tracking | `get_override_stats()` returns counts | Service + RPC complete |

Browser testing deferred to deployment — requires Railway staging environment.

---

## Files Changed (Full Phase 4)

| File | Change |
|------|--------|
| `migrations/2026-02-14_ad_creator_v2_phase4.sql` | NEW: 3 migrations (CHECK fix, columns, tables) |
| `migrations/2026-02-14_ad_creator_v2_phase4_rpc.sql` | NEW: `apply_ad_override()` RPC function |
| `viraltracker/services/template_scoring_service.py` | +BeliefClarityScorer, +PHASE_4_SCORERS, +weight presets, +eval prefetch |
| `viraltracker/services/ad_creation_service.py` | +3 params to save_generated_ad() |
| `viraltracker/services/ad_review_override_service.py` | NEW: Override service |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +lp_hero_data, congruence_results, defect_passed_ads, defect_scan_results |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | +HeadlineCongruenceNode, +DefectScanNode (11 nodes) |
| `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` | +LP hero fetch |
| `viraltracker/pipelines/ad_creation_v2/nodes/select_content.py` | Returns HeadlineCongruenceNode |
| `viraltracker/pipelines/ad_creation_v2/nodes/headline_congruence.py` | NEW: Congruence check + headline adaptation |
| `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` | Returns DefectScanNode |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | NEW: Stage 1 defect scan |
| `viraltracker/pipelines/ad_creation_v2/utils.py` | NEW: shared `stringify_uuids` helper |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | Reads defect_passed_ads, calls review_ad_staged(), extends reviewed_ads |
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | Import stringify_uuids from utils |
| `viraltracker/pipelines/ad_creation_v2/services/congruence_service.py` | NEW: Congruence scoring |
| `viraltracker/pipelines/ad_creation_v2/services/defect_scan_service.py` | NEW: Defect scan |
| `viraltracker/pipelines/ad_creation_v2/services/review_service.py` | +staged review (15-check rubric, Stage 2-3) |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | +override buttons, +structured scores, +defect/congruence display |
| `tests/services/test_template_scoring_service.py` | +18 tests |
| `tests/services/test_ad_review_override_service.py` | NEW: 15 tests |
| `tests/pipelines/ad_creation_v2/test_congruence.py` | NEW: 29 tests |
| `tests/pipelines/ad_creation_v2/test_defect_scan.py` | NEW: 16 tests |
| `tests/pipelines/ad_creation_v2/test_review_service.py` | NEW: 35 tests (+4 load_quality_config) |
| `tests/pipelines/ad_creation_v2/test_review_node.py` | NEW: 12 tests (ReviewAdsNode integration) |
| `docs/plans/ad-creator-v2/PHASE_4_PLAN.md` | NEW: Full plan |
| `docs/plans/ad-creator-v2/CHECKPOINT_009.md` | Updated |

---

## Test Results

```
200 passed in 2.25s

Pipeline tests (tests/pipelines/ad_creation_v2/):
- test_asset_context.py: 15 passed
- test_congruence.py: 29 passed (NEW)
- test_defect_scan.py: 16 passed (NEW)
- test_generate_ads_node.py: 6 passed
- test_orchestrator_normalization.py: 9 passed
- test_review_node.py: 12 passed (NEW — post-review fix)
- test_review_service.py: 35 passed (NEW, +4 load_quality_config)
- test_state.py: 13 passed

Service tests:
- test_ad_review_override_service.py: 15 passed (NEW)
- test_template_scoring_service.py: 48 passed (18 new)
```

---

## Pipeline Graph (Phase 4 Final)

```
InitializeNode
  -> FetchContextNode          (MODIFIED: +LP hero fetch)
  -> AnalyzeTemplateNode
  -> SelectContentNode         (MODIFIED: returns HeadlineCongruenceNode)
  -> HeadlineCongruenceNode    (NEW — Phase 4)
  -> SelectImagesNode
  -> GenerateAdsNode           (MODIFIED: returns DefectScanNode)
  -> DefectScanNode            (NEW — Phase 4, Stage 1)
  -> ReviewAdsNode             (MODIFIED: Stages 2-3, structured rubric)
  -> RetryRejectedNode
  -> CompileResultsNode
```

---

## Known Limitations / Deferred

1. **Browser testing** deferred to Railway deployment (P4-C6 scope)
2. **RetryRejectedNode** still uses V1 dual review, not Stage 2-3 (Phase 5 scope)
3. **Regenerate flow** lacks Phase 4 checks (separate overhaul needed)
4. **Defect catch rate target** (>= 30%) needs 50+ ads in production to validate
5. **CongruenceService** hero_alignment will be null for brands without `brand_landing_pages` data

---

## Post-Plan Review

Initial review identified G4 (CRITICAL): ReviewAdsNode was not calling `review_ad_staged()`.
Fixed by rewriting review_ads.py and adding 16 new tests (12 node + 4 config).
Re-review: **PASS** — all G1-G6, P1-P8, T1-T4, A1-A5 checks green.

Post-review cleanup:
- Extracted `_stringify_uuids` to shared `utils.py` (was duplicated in 3 node files)
- Added logging to silent `except Exception: pass` in UI override stats display

## Next Step

Commit Phase 4 implementation.
