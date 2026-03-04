# Ad Creator V2 — CHECKPOINT 010 (Phase 5)

**Date:** 2026-02-14
**Branch:** `feat/ad-creator-v2-phase0`
**Phase:** Phase 5 — Polish + Promotion
**Status:** GATE_PENDING

> Phase 5 code is complete and all 276 tests pass. Status is GATE_PENDING because
> the Phase 5 success gate (PLAN.md) requires manual acceptance checks that have
> not yet been performed (2-week stability, V2 vs V1 approval-rate comparison,
> CTR non-inferiority for Meta-connected brands, browser-based UI tests).

---

## Phase 5 Chunks — All Code Complete

| Chunk | Scope | Tests | Status |
|-------|-------|-------|--------|
| P5-C1 | RetryRejectedNode refactor (V1 dual review -> staged review) | 15 | Done |
| P5-C2 | Prompt versioning + generation_config migration | 7 | Done |
| P5-C3 | Batch size guardrails + cost estimation | 14 | Done |
| P5-C4 | Scoring preset validation (CI tests + analysis script) | 25 (21 `def test_` + 1 parameterized x5) | Done |
| P5-C5 | Results dashboard enhancement (filters, stats, bulk actions) | 15 | Done |
| P5-C6 | QA (syntax verification, full test suite pass) | 0 (manual) | Done |

**Total new tests:** 76
**Running total:** 276 (V2 pipeline + scoring + override service)

---

## Per-Chunk Checkpoint Details

### Chunk P5-C1: RetryRejectedNode Refactor

**Date**: 2026-02-14
**Token estimate**: ~15K / 50K

#### Scope Completed
- [x] Replace V1 dual review (review_ad_claude + review_ad_gemini + apply_dual_review_logic)
- [x] New flow: generate -> upload -> DefectScanService.scan_for_defects() -> review_ad_staged() -> save
- [x] Defect-rejected retries saved with defect_scan_result, skip review
- [x] Staged review retries saved with review_check_scores, weighted_score, congruence_score
- [x] Both paths pass prompt_version to save_generated_ad()

#### Files Changed
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | REWRITE — replaced V1 dual review with staged review (defect scan + full rubric) |
| `tests/pipelines/ad_creation_v2/test_retry_rejected.py` | NEW — 15 tests covering staged review in retry path |

#### Migrations Run
- None (P5-C1 is code-only)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | PASS |
| `pytest tests/pipelines/ad_creation_v2/test_retry_rejected.py` (15 tests) | PASS |

#### Success Gate Status
- [x] RetryRejectedNode uses staged review (not V1 dual review)
- [x] Defect-rejected retries skip full review
- [x] Staged review retries store structured review data

#### Risks / Open Issues
- Unused `Any` import in retry_rejected.py (cosmetic)
- No golden eval fixtures for retry node (mocks only)

#### Next Chunk Plan
- P5-C2: Prompt versioning + generation_config migration

---

### Chunk P5-C2: Prompt Versioning + Generation Config

**Date**: 2026-02-14
**Token estimate**: ~10K / 50K

#### Scope Completed
- [x] Migration adds `generated_ads.prompt_version TEXT` and `ad_runs.generation_config JSONB`
- [x] `ad_creation_service.py` accepts prompt_version and generation_config params in save methods
- [x] InitializeNode builds generation_config snapshot from pipeline inputs
- [x] ReviewAdsNode, RetryRejectedNode, DefectScanNode all pass prompt_version to save

#### Files Changed
| File | Change |
|------|--------|
| `migrations/2026-02-14_ad_creator_v2_phase5_versioning.sql` | NEW — adds prompt_version and generation_config columns |
| `viraltracker/services/ad_creation_service.py` | MODIFIED — prompt_version + generation_config params |
| `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py` | MODIFIED — builds generation_config snapshot |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | MODIFIED — passes prompt_version |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | MODIFIED — passes prompt_version |
| `tests/pipelines/ad_creation_v2/test_versioning.py` | NEW — 7 tests |

#### Migrations Run
- `migrations/2026-02-14_ad_creator_v2_phase5_versioning.sql` — **not yet applied** (pending staging deployment)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile` on all 4 modified files | PASS |
| `pytest tests/pipelines/ad_creation_v2/test_versioning.py` (7 tests) | PASS |

#### Success Gate Status
- [x] prompt_version persisted on generated_ads
- [x] generation_config snapshot persisted on ad_runs
- [ ] Migration applied to staging/prod (pending deployment)

#### Risks / Open Issues
- Migration not yet applied to any environment

#### Next Chunk Plan
- P5-C3: Batch size guardrails + cost estimation

---

### Chunk P5-C3: Batch Size Guardrails + Cost Estimation

**Date**: 2026-02-14
**Token estimate**: ~12K / 50K

#### Scope Completed
- [x] `CostEstimationService` with configurable `PRICING_DEFAULTS`, `MAX_VARIATIONS_PER_RUN = 50`
- [x] `estimate_run_cost()` with breakdown, retry multiplier
- [x] Orchestrator hard cap changed from 100 to 50
- [x] UI tiered guardrails (1-10 none, 11-30 estimate, 31-50 confirm, >50 block)

#### Files Changed
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/services/cost_estimation.py` | NEW — cost estimation service |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | MODIFIED — hard cap 100→50 |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | MODIFIED — tiered guardrail UI |
| `tests/pipelines/ad_creation_v2/test_cost_estimation.py` | NEW — 14 tests |
| `tests/pipelines/ad_creation_v2/test_orchestrator_normalization.py` | MODIFIED — updated cap tests (+11) |

#### Migrations Run
- None (P5-C3 is code-only)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile` on cost_estimation.py, orchestrator.py | PASS |
| `pytest tests/pipelines/ad_creation_v2/test_cost_estimation.py` (14 tests) | PASS |
| `pytest tests/pipelines/ad_creation_v2/test_orchestrator_normalization.py` (11 tests) | PASS |

#### Success Gate Status
- [x] Cost estimation returns correct estimates for various configurations
- [x] Hard cap enforced at 50 in orchestrator
- [ ] UI guardrails verified in browser (pending deployment)

#### Risks / Open Issues
- UI guardrail behavior untested in browser

#### Next Chunk Plan
- P5-C4: Scoring preset validation

---

### Chunk P5-C4: Scoring Preset Validation

**Date**: 2026-02-14
**Token estimate**: ~15K / 50K

#### Scope Completed
- [x] 25 diversity invariant tests across Roll the Dice and Smart Select presets
- [x] Analysis script for production validation (`scripts/validate_scoring_presets.py`)

#### Files Changed
| File | Change |
|------|--------|
| `tests/services/test_scoring_diversity.py` | NEW — 25 test cases |
| `scripts/validate_scoring_presets.py` | NEW — production validation script |

#### Test Count Reconciliation

`test_scoring_diversity.py` contains **21 `def test_` functions**. The file reports **25 test cases** because `test_diversity_across_5_brands` is decorated with `@pytest.mark.parametrize("brand_config", [...])` containing 5 brand configurations, producing 5 test cases from 1 function definition. Breakdown:

| Category | `def test_` count | Runtime test cases |
|----------|:-----------------:|:-----------------:|
| Roll the Dice (TestRollTheDiceDiversity) | 4 | 4 |
| Smart Select (TestSmartSelectDiversity) | 4 | 4 |
| Cross-Preset (TestCrossPresetInvariants) | 4 | 4 |
| Parameterized (TestParameterizedBrandDiversity) | 1 | 5 (x5 brand_config) |
| Helpers (TestDiversityHelpers) | 8 | 8 |
| **Total** | **21** | **25** |

Verified: `pytest tests/services/test_scoring_diversity.py --tb=no -v` reports 25 PASSED.

#### Migrations Run
- None (P5-C4 is test-only)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `pytest tests/services/test_scoring_diversity.py` (25 test cases) | PASS |

#### Success Gate Status
- [x] No template dominance (>30% for Roll the Dice, >40% for Smart Select)
- [x] Category coverage maintained
- [x] Unused bonus has measurable effect
- [x] Deterministic with seed
- [x] Graceful fallback on empty pool
- [ ] Production validation with `validate_scoring_presets.py` (pending deployment)

#### Risks / Open Issues
- `print()` used in analysis script instead of `logger.info()` (acceptable for CLI tool)
- Production validation not yet run

#### Next Chunk Plan
- P5-C5: Results dashboard enhancement

---

### Chunk P5-C5: Results Dashboard Enhancement

**Date**: 2026-02-14
**Token estimate**: ~18K / 50K

#### Scope Completed
- [x] `get_ads_filtered()` — filtered query with status, date range, product, ad_run_id, sort, pagination
- [x] `get_summary_stats()` — aggregate counts + override_rate
- [x] `bulk_override()` — apply override to multiple ads at once
- [x] UI: summary stats bar, filter controls, template grouping, bulk actions, pagination

#### Files Changed
| File | Change |
|------|--------|
| `viraltracker/services/ad_review_override_service.py` | MODIFIED — 3 new methods (get_ads_filtered, get_summary_stats, bulk_override) |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | MODIFIED — enhanced render_results() with stats/filters/grouping/pagination |
| `tests/services/test_ad_review_override_service.py` | MODIFIED — 15 new tests (30 total) |

#### Migrations Run
- None (P5-C5 is code-only; uses existing tables)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile viraltracker/services/ad_review_override_service.py` | PASS |
| `pytest tests/services/test_ad_review_override_service.py` (30 tests) | PASS |

#### Success Gate Status
- [x] Filtered queries return correct results with all filter combinations
- [x] Summary stats compute correctly
- [x] Bulk override applies to multiple ads
- [ ] UI dashboard verified in browser (pending deployment)

#### Risks / Open Issues
- `ad_runs!inner` join dependency — ads without `organization_id` on ad_runs silently excluded
- No automated Streamlit UI tests

#### Next Chunk Plan
- P5-C6: QA pass

---

### Chunk P5-C6: QA (Syntax Verification + Full Test Suite)

**Date**: 2026-02-14
**Token estimate**: ~5K / 50K

#### Scope Completed
- [x] `python3 -m py_compile` on all 8 changed production Python files
- [x] Full test suite run (276 tests)
- [x] Post-plan review run (PASS verdict)

#### Files Changed
| File | Change |
|------|--------|
| `docs/plans/ad-creator-v2/PHASE_5_PLAN.md` | NEW — Phase 5 implementation plan |
| `docs/plans/ad-creator-v2/CHECKPOINT_010.md` | NEW — this checkpoint |

#### Migrations Run
- None (QA-only chunk)

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile` (8 production files) | ALL PASS |
| `pytest` full V2 suite (276 tests) | ALL PASS |
| Post-plan review (graph invariants + test gatekeeper) | PASS |

#### Success Gate Status
- [x] All production files compile clean
- [x] 276 tests pass
- [x] Post-plan review PASS

#### Risks / Open Issues
- None for this chunk

#### Next Chunk Plan
- No more Phase 5 chunks. Phase 5 code is complete. Awaiting manual acceptance gates.

---

## Test Evidence

### Full Suite Run (276 tests)

Command:
```
venv/bin/python -m pytest tests/pipelines/ad_creation_v2/ tests/services/test_scoring_diversity.py tests/services/test_ad_review_override_service.py tests/services/test_template_scoring_service.py --tb=no -q
```

Output:
```
276 passed, 16 warnings in 2.49s
```

Run date: 2026-02-14, branch `feat/ad-creator-v2-phase0`.
`test_orchestrator_allows_50` calls the real `run_ad_creation_v2(num_variations=50)`
with `deps=MagicMock()` and `ad_creation_v2_graph.run` patched to raise a sentinel
exception. The test asserts the sentinel is reached (proving validation passed)
and no `ValueError` is raised. This catches validation drift without triggering
heavyweight dependency initialization.

### Syntax Verification (8 production files)

```
PASS: retry_rejected.py
PASS: initialize.py
PASS: review_ads.py
PASS: defect_scan.py
PASS: orchestrator.py
PASS: ad_creation_service.py
PASS: ad_review_override_service.py
PASS: cost_estimation.py
```

### Test Count Breakdown (276 total)

| Test File | Count | Scope |
|-----------|-------|-------|
| test_retry_rejected.py | 15 | P5-C1: staged review in retry |
| test_versioning.py | 7 | P5-C2: prompt_version + generation_config |
| test_cost_estimation.py | 14 | P5-C3: cost estimation + cap |
| test_orchestrator_normalization.py | 11 | P5-C3: updated cap tests |
| test_scoring_diversity.py | 25 | P5-C4: diversity invariants (21 def test_ + 1 parameterized x5) |
| test_ad_review_override_service.py | 30 | P5-C5: filtered + bulk |
| test_template_scoring_service.py | 48 | Existing scoring tests |
| Other V2 pipeline tests | 126 | Phases 1-4 |
| **Total** | **276** | |

---

## Post-Plan Review Evidence

**Verdict: PASS**

Review performed on 2026-02-14 against all files changed in Phase 5 (17 files listed in Files Changed section below).

### Graph Invariants Checker (G1-G6 + P1-P8): ALL PASS
- G1 (syntax): All changed Python files compile clean (`python3 -m py_compile` on 8 production files — see evidence above)
- G2 (debug artifacts): No print/breakpoint/TODO left in production code (note: `print()` in `scripts/validate_scoring_presets.py` is a CLI script, not production code)
- G3 (secrets): No hardcoded secrets or credentials
- G4 (critical logic): All service methods properly delegated, no logic in thin wrappers
- G5 (error handling): No bare `except: pass`
- G6 (imports): All imports resolve (one unused `Any` in retry_rejected.py — cosmetic, non-fatal)
- P1-P8 (pipeline checks): Node transitions correct, state mutations valid, End nodes produce correct output

### Test/Evals Gatekeeper (T1-T4 + A1-A5): ALL PASS
- T1 (test existence): All new service methods have tests
- T2 (test quality): Tests cover happy path, edge cases, error cases
- T3 (no skipped tests): No `@pytest.mark.skip` or `xfail`
- T4 (test isolation): All tests use mocks, no real DB/API calls
- A1-A5 (pipeline test checks): Node tests mock deps correctly, state transitions tested

### Known Risks (documented in PLAN.md Phase 5 section)
1. No automated Streamlit UI tests
2. `ad_runs!inner` join dependency in filtered queries
3. No golden eval fixtures for retry node
4. Unused `Any` import in retry_rejected.py
5. `print()` in analysis script

---

## Phase 5 Success Gate (from PLAN.md)

> Full V2 pipeline stable over >= 2 weeks of daily use. V2 approval rate >= V1
> (N >= 100 ads per pipeline, same brand/template distribution). Promotion to
> primary requires additionally: V2 ads deployed to Meta show non-inferior CTR
> vs V1 ads (one-sided 90% CI lower bound >= 0.9x V1 mean CTR, measured over
> >= 50 V2 ads with >= 7 days matured data each). For brands without Meta
> connection, promotion requires V2 approval rate >= V1 only.

### Gate Evidence

| Gate Criterion | Status | Evidence |
|---------------|--------|----------|
| **2-week stability** (daily use without failures) | PENDING | Not yet measured — requires 14 days of production use after staging deployment. Clock starts when V2 is deployed to Railway staging and used daily. |
| **V2 vs V1 approval-rate comparison** (N>=100 each, same distribution) | PENDING | Not yet measured — requires >= 100 V2 ads and >= 100 V1 ads generated with matched brand/template distribution. Currently no V2 production ads exist. |
| **CTR non-inferiority** (Meta-connected brands, 90% CI lower bound >= 0.9x V1, N>=50 ads, >=7d matured) | PENDING | Not yet measured — requires >= 50 V2 ads deployed to Meta with >= 7 days of matured performance data per ad. |
| **Non-Meta brands: approval-rate gate** | PENDING | Not yet measured — same as approval-rate comparison above but for brands without `brand_ad_accounts`. |
| **All tests pass** | PASS | 276 tests passing (see Test Evidence section) |
| **Post-plan review PASS** | PASS | Graph invariants G1-G6 + P1-P8 PASS, Test gatekeeper T1-T4 + A1-A5 PASS (see Post-Plan Review Evidence section) |
| **All production files compile** | PASS | 8 files verified with `python3 -m py_compile` (see Syntax Verification section) |

**Overall Gate Verdict: FAIL (PENDING manual acceptance checks)**

The code implementation is complete and verified. The outstanding gate criteria require production deployment and time-based measurement that cannot be satisfied by code review alone. Next steps to clear the gate:

1. Deploy to Railway staging (run migration, deploy branch)
2. Generate >= 100 V2 ads across >= 3 brands over 2 weeks
3. Generate >= 100 V1 ads in parallel (same brands/templates) for comparison
4. For Meta-connected brands: deploy >= 50 V2 ads to Meta, wait 7+ days for maturation
5. Compute approval-rate comparison and CTR non-inferiority statistics
6. Run manual browser tests (see Pending UI Tests in PLAN.md)
7. Run `scripts/validate_scoring_presets.py` against production data

---

## Files Changed (Phase 5)

| File | Change Type |
|------|-------------|
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | REWRITE |
| `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py` | MODIFIED |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | MODIFIED |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | MODIFIED |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | MODIFIED |
| `viraltracker/services/ad_creation_service.py` | MODIFIED |
| `viraltracker/services/ad_review_override_service.py` | MODIFIED |
| `viraltracker/pipelines/ad_creation_v2/services/cost_estimation.py` | NEW |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | MODIFIED |
| `migrations/2026-02-14_ad_creator_v2_phase5_versioning.sql` | NEW |
| `scripts/validate_scoring_presets.py` | NEW |
| `tests/pipelines/ad_creation_v2/test_retry_rejected.py` | NEW |
| `tests/pipelines/ad_creation_v2/test_versioning.py` | NEW |
| `tests/pipelines/ad_creation_v2/test_cost_estimation.py` | NEW |
| `tests/pipelines/ad_creation_v2/test_orchestrator_normalization.py` | MODIFIED |
| `tests/services/test_scoring_diversity.py` | NEW |
| `tests/services/test_ad_review_override_service.py` | MODIFIED |
| `docs/plans/ad-creator-v2/PHASE_5_PLAN.md` | NEW |

---

## Manual Testing Checklist (P5-C6)

### Phase 4 UI Browser Tests (deferred from P4)
- [ ] Override Approve/Reject/Confirm buttons update status
- [ ] Structured review scores display with colored indicators
- [ ] Defect scan results display PASSED/FAILED
- [ ] Congruence score color-coded

### Phase 5 Feature Tests
- [ ] Cost estimate shows correct values
- [ ] 31+ variations requires confirmation checkbox
- [ ] >50 variations blocked
- [ ] Summary stats bar shows correct counts
- [ ] Status/date filters work
- [ ] Template grouping correct
- [ ] Bulk approve/reject works
- [ ] Pagination navigates correctly

### Full E2E
- [ ] V2 job creation -> submission -> worker execution -> results display
- [ ] Retry uses staged review (not V1)

---

## Next Steps

Phase 5 code is complete. The pipeline is feature-complete with:
- 11-node pydantic-graph pipeline
- 3-stage review (defect scan, Claude Vision rubric, conditional Gemini Vision)
- Headline congruence checks
- Human override system with bulk actions
- Cost estimation and batch guardrails
- Prompt versioning and reproducibility
- Dashboard with filters, grouping, pagination
- Validated scoring presets for template diversity
- 276 tests passing, post-plan review PASS

**To clear the Phase 5 success gate:**
1. Run migration on staging/prod Supabase
2. Browser-test the UI on Railway staging (see PLAN.md "Pending UI Tests" section)
3. Run `scripts/validate_scoring_presets.py` against prod data
4. Accumulate 2 weeks of daily V2 usage for stability evidence
5. Collect N>=100 V2 ads + N>=100 V1 ads for approval-rate comparison
6. For Meta-connected brands: collect N>=50 V2 ads with 7+ days matured CTR data
7. Compute gate statistics and update this checkpoint with PASS/FAIL
8. Deploy to production
