# Checkpoint: Blueprint-Aware Ad Creator V2 — Implementation Complete

**Date**: 2026-03-05
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Implementation complete, post-plan review PASS, 227/227 tests passing

---

## What Was Done

Added optional landing page blueprint integration to the V2 ad creation pipeline. When a user selects a completed blueprint during ad creation, the pipeline:

1. **Loads blueprint context** (strategy tone, differentiators, copy directions, emotional hooks) in FetchContextNode
2. **Enriches the generation prompt** with blueprint strategy context via a new `BlueprintContext` Pydantic model
3. **Adds a 4th congruence dimension** (`blueprint_alignment`) scored by Claude alongside existing offer/hero/belief dimensions
4. **Persists `blueprint_id`** on every `generated_ads` row through all 4 save paths
5. **Exposes a blueprint selector** in the V2 Ad Creator UI, filtered by product and auto-clearing on product change

All changes are backward-compatible: when no blueprint is selected, every new field is `None` and behavior is identical to the current pipeline.

---

## Files Changed (16 Python + 1 SQL migration + 3 docs)

### New Files
| File | Purpose |
|------|---------|
| `migrations/2026-03-05_blueprint_id_on_generated_ads.sql` | Nullable FK column + index on `generated_ads` |
| `docs/plans/blueprint-aware-ad-creator-v2/PLAN.md` | Full implementation plan |
| `docs/plans/blueprint-aware-ad-creator-v2/CHECKPOINT_IMPLEMENTATION_COMPLETE.md` | This checkpoint |
| `docs/plans/blueprint-aware-ad-creator-v2/POST_PLAN_REVIEW.md` | Post-plan review report (PASS) |

### Pipeline State & Orchestrator
| File | Changes |
|------|---------|
| `viraltracker/pipelines/ad_creation_v2/state.py` | Added `blueprint_id` (config field) and `blueprint_context` (populated-by-nodes field) |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | Added `blueprint_id` parameter to `run_ad_creation_v2()`, passed to state constructor |

### Pipeline Nodes
| File | Changes |
|------|---------|
| `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` | Non-fatal blueprint loading block after LP hero data fetch. Defensive: handles `sections: null`, missing `reconstruction_blueprint` key, non-completed status. Enriches `lp_hero_data` from blueprint if not already loaded. |
| `viraltracker/pipelines/ad_creation_v2/nodes/headline_congruence.py` | Updated pass-through condition to also run when `blueprint_context` present (not just `offer_variant_id`). Passes `blueprint_context` to batch congruence check. Includes `blueprint_alignment` in result dict. |
| `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` | Passes `blueprint_context` to `generation_service.generate_prompt()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | Passes `blueprint_id` to `save_generated_ad()` |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | Passes `blueprint_id` to `save_generated_ad()` (defect-rejected save path) |
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | Passes `blueprint_id` to both `save_generated_ad()` calls (defect-rejected + review-completed). Passes `blueprint_context` to `generate_prompt()`. |

### Pipeline Services & Models
| File | Changes |
|------|---------|
| `viraltracker/pipelines/ad_creation_v2/models/prompt.py` | New `BlueprintContext` Pydantic model. Added `blueprint_context` field to `AdGenerationPrompt`. |
| `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` | Added `blueprint_context` param to `generate_prompt()`. Builds `BlueprintContext` model and passes to `AdGenerationPrompt` constructor. |
| `viraltracker/pipelines/ad_creation_v2/services/congruence_service.py` | Added `blueprint_alignment` field to `CongruenceResult`. Threaded `blueprint_context` param through all 6 methods: `check_congruence()`, `check_congruence_batch()`, `_score_with_llm()`, `_score_batch_with_llm()`, `_build_prompt()`, `_parse_batch_result()`. Added LANDING PAGE BLUEPRINT section to congruence prompt with `blueprint_alignment` dimension. |

### Service Layer
| File | Changes |
|------|---------|
| `viraltracker/services/ad_creation_service.py` | Added `blueprint_id: Optional[UUID]` param to `save_generated_ad()`. Writes to data dict when not None. |

### Worker & UI
| File | Changes |
|------|---------|
| `viraltracker/worker/scheduler_worker.py` | Unpacks `blueprint_id` from `params`. Passes to `run_ad_creation_v2()`. |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | Added `v2_blueprint_id` session state. New `get_blueprints_for_product()` helper. New `render_blueprint_selector()` with compact preview (tone, differentiators). Blueprint clears on product change. `blueprint_id` included in submit parameters. |

---

## Data Flow Summary

```
UI: user selects blueprint → st.session_state.v2_blueprint_id
  → _handle_submit() → parameters['blueprint_id']
    → scheduled_jobs.parameters JSONB
      → Worker: params.get('blueprint_id')
        → run_ad_creation_v2(blueprint_id=...)
          → AdCreationPipelineState.blueprint_id
            → FetchContextNode: loads blueprint → state.blueprint_context
              → HeadlineCongruenceNode: blueprint_context as 4th congruence dim
              → GenerateAdsNode: blueprint_context in prompt JSON
              → ReviewAdsNode/DefectScanNode/RetryRejectedNode: blueprint_id on generated_ads row
```

---

## Edge Cases & Defensive Checks

| Scenario | Handling |
|----------|----------|
| No blueprint selected | All fields None, zero behavior change |
| Blueprint not completed / not found | FetchContextNode checks `status == "completed"`, logs warning |
| Blueprint `sections` is null | `rb.get("sections") or []` handles both missing and null |
| Blueprint JSON has no `reconstruction_blueprint` key | `bp_json.get("reconstruction_blueprint", bp_json)` falls back to root |
| LP hero data already exists | Blueprint does NOT overwrite — only fills in if `lp_hero_data` is None |
| Blueprint deleted after job submitted | FK `ON DELETE SET NULL` — column becomes NULL, FetchContextNode skips gracefully |
| Product change clears blueprint | Session state guard in `render_blueprint_selector()` + product-change reset block |
| Old jobs without blueprint_id | `params.get('blueprint_id')` returns None — zero impact |
| Congruence LLM fails | Existing non-fatal fallback to 1.0 score preserved |
| 4th congruence dimension | Simple average (existing pattern); 0.25 weight per dim instead of 0.33 |

---

## Verification Checklist

- [x] All 14 Python files pass `python3 -m py_compile`
- [x] All 4 `save_generated_ad()` call sites include `blueprint_id`
- [x] Congruence `blueprint_alignment` threaded through all 6 methods
- [x] `blueprint_context` passed to generation prompt in both GenerateAdsNode and RetryRejectedNode
- [x] HeadlineCongruenceNode runs when blueprint_context present (even without offer_variant_id)
- [x] UI clears blueprint on product change (session state guard)
- [x] Blueprint selector only shows completed blueprints
- [x] Plan saved to `docs/plans/blueprint-aware-ad-creator-v2/PLAN.md`

---

## Test Results

- **227/227 tests pass** (213 existing + 14 new), zero regressions
- 14 new tests across `test_state.py` (4) and `test_congruence.py` (10):
  - State: blueprint field defaults, round-trip serialization, to_dict presence
  - Congruence: `blueprint_alignment` field, blueprint-only scoring (single + batch), prompt building with/without blueprint, batch parsing with blueprint_alignment, HeadlineCongruenceNode blueprint-only trigger and no-offer-no-blueprint pass-through

## Post-Plan Review

- **Verdict: PASS** — See `POST_PLAN_REVIEW.md` for full report
- Graph Invariants Checker: PASS (0 blocking issues)
- Test/Evals Gatekeeper: PASS (0 blocking issues)
- Plan completeness: 15/15 items DONE

## Remaining Steps

- [ ] Run migration on Supabase: `migrations/2026-03-05_blueprint_id_on_generated_ads.sql`
- [ ] Manual testing: submit V2 job with and without blueprint
