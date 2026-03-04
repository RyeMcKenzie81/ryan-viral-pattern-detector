# Ad Creator V2 — Phase 5 Implementation Plan
# Polish + Promotion

**Date:** 2026-02-14
**Branch:** `feat/ad-creator-v2-phase0`
**Parent plan:** `docs/plans/ad-creator-v2/PLAN.md` (Phase 5 at line 1295)
**Predecessor:** `CHECKPOINT_009.md` (Phase 4 complete, 200 tests)

---

## Decisions Log

| # | Question | Decision |
|---|----------|----------|
| 1 | Results dashboard approach | Enhanced current page (not new page). Group by template, status/date/brand/product/ad_run_id filters, summary stats, bulk actions, sortable. |
| 2 | Prompt versioning strategy | Both: `prompt_version` TEXT on `generated_ads` AND `generation_config` JSONB on `ad_runs`. Full reproducibility snapshot. |
| 3 | Batch size guardrails | Hard cap 50 backend. UI tiered: 1-10 none, 11-30 estimate, 31-50 confirm, >50 block + auto-split. Configurable pricing constants. |
| 4 | Scoring validation approach | Both CI tests (synthetic diversity invariants) + one-time analysis script (real DB data >= 5 brands). |
| 5 | RetryRejected defect scan | Yes — retried ads get defect scan via `DefectScanService.scan_ad()` before `review_ad_staged()`. Consistent with main flow. |

---

## Chunk Overview

| Chunk | Scope | Est. Tests | Dependencies |
|-------|-------|-----------|--------------|
| P5-C1 | RetryRejectedNode refactor (V1 → staged review) | ~15 | None |
| P5-C2 | Prompt versioning + generation_config migration | ~10 | None |
| P5-C3 | Batch size guardrails + cost estimation | ~12 | None |
| P5-C4 | Scoring preset validation (CI + analysis script) | ~15 | None |
| P5-C5 | Results dashboard enhancement | ~8 | P5-C2 (prompt_version column) |
| P5-C6 | QA + E2E testing (Railway browser test) | 0 (manual) | P5-C1..C5 |

---

## P5-C1: RetryRejectedNode Refactor

**Problem:** `RetryRejectedNode` (line 168-262 of `retry_rejected.py`) uses V1 dual review (`review_ad_claude` + `review_ad_gemini` + `apply_dual_review_logic`), not the Phase 4 staged review (`review_ad_staged` with 15-check rubric).

**Goal:** Align retry review with the main flow: defect scan → staged review → save with structured scores.

### Changes

#### 1. `retry_rejected.py` — Refactor review section

**Current flow** (lines 168-198):
```
generate → upload → review_ad_claude → review_ad_gemini → apply_dual_review_logic → save
```

**New flow:**
```
generate → upload → defect_scan_service.scan_ad() → if passed: review_ad_staged() → save
```

**Specific changes:**
- Import `DefectScanService` and `load_quality_config`
- Load `quality_config` once before the retry loop (same pattern as ReviewAdsNode line 65-68)
- For each retried ad:
  1. After `execute_generation` + `upload_generated_ad`, get image bytes
  2. Call `defect_scan_service.scan_ad(image_data)`
  3. If defect scan fails (defects found): save with `final_status='rejected'`, `defect_scan_result`, skip review
  4. If defect scan passes: call `review_ad_staged(image_data, product_name, hook_text, ad_analysis, config=quality_config)`
  5. Save with `review_check_scores`, `defect_scan_result`, `congruence_score` from state lookup
- Remove `review_ad_claude`, `review_ad_gemini`, `apply_dual_review_logic` calls
- Remove `make_failed_review` import
- Update metadata classvar to reflect new services
- Update reviewed_ads append to include `review_check_scores`, `weighted_score`, `congruence_score` (match ReviewAdsNode dict shape)

#### 2. DefectScanService interface (VERIFIED)

`DefectScanService.scan_for_defects(image_base64: str, product_name: str, media_type: str)` takes base64-encoded image string. After `execute_generation()`, `generated_ad['image_base64']` is available. Use that directly — no need to re-download from storage.

```python
from ..services.defect_scan_service import DefectScanService

defect_service = DefectScanService()
defect_result = await defect_service.scan_for_defects(
    image_base64=generated_ad['image_base64'],
    product_name=ctx.state.product_dict.get('name', ''),
)
```

For `review_ad_staged()`, it needs raw bytes (`image_data: bytes`), so decode:
```python
import base64
image_data = base64.b64decode(generated_ad['image_base64'])
```

#### 3. Update metadata ClassVar

```python
metadata: ClassVar[NodeMetadata] = NodeMetadata(
    inputs=["reviewed_ads", "auto_retry_rejected", "max_retry_attempts",
            "product_dict", "ad_analysis", "ad_run_id", "congruence_results"],
    outputs=["reviewed_ads"],
    services=["generation_service.generate_prompt", "generation_service.execute_generation",
               "defect_scan_service.scan_for_defects",
               "review_service.review_ad_staged",
               "ad_creation.upload_generated_ad", "ad_creation.save_generated_ad"],
    llm="Gemini Image Gen + Claude Vision + Gemini Vision (staged)",
    llm_purpose="Retry rejected ads with fresh generation, defect scan, and staged review",
)
```

### Tests — `tests/pipelines/ad_creation_v2/test_retry_rejected.py` (NEW)

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_skip_when_disabled` | auto_retry_rejected=False → pass through |
| 2 | `test_skip_when_no_rejected` | No rejected ads → pass through |
| 3 | `test_retry_generates_and_reviews` | Full flow: generate → defect scan → staged review → save |
| 4 | `test_retry_defect_rejected` | Defect scan finds defects → saved as rejected with defect_scan_result |
| 5 | `test_retry_review_approved` | Staged review approves → saved with review_check_scores |
| 6 | `test_retry_review_rejected` | Staged review rejects → final_status=rejected |
| 7 | `test_retry_review_flagged` | Borderline → Stage 3 triggered |
| 8 | `test_retry_generation_failure` | execute_generation raises → logged, skipped |
| 9 | `test_retry_review_failure` | review_ad_staged raises → final_status=review_failed |
| 10 | `test_retry_congruence_lookup` | congruence_score looked up from state.congruence_results |
| 11 | `test_retry_appends_to_reviewed_ads` | New dict shape matches ReviewAdsNode output |
| 12 | `test_retry_saves_prompt_version` | prompt_version passed through to save |
| 13 | `test_retry_increments_index` | next_index increments correctly |
| 14 | `test_retry_max_attempts` | Respects max_retry_attempts (1 per rejected ad) |
| 15 | `test_retry_hook_passthrough` | Hook data preserved from original rejected ad |

---

## P5-C2: Prompt Versioning + Generation Config

**Problem:** `prompt_version` exists in state (`v2.1.0`) but is not persisted to DB. No way to reproduce a run's exact configuration.

### Migration — `migrations/2026-02-14_ad_creator_v2_phase5_versioning.sql`

```sql
-- Migration: Add prompt versioning and generation config
-- Date: 2026-02-14
-- Purpose: Enable reproducibility by tracking prompt version per ad
--          and full generation config per ad_run.

-- 1. Add prompt_version to generated_ads
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS prompt_version TEXT;

COMMENT ON COLUMN generated_ads.prompt_version
IS 'Pydantic prompt schema version used to generate this ad (e.g. v2.1.0)';

-- 2. Add generation_config JSONB to ad_runs
ALTER TABLE ad_runs
ADD COLUMN IF NOT EXISTS generation_config JSONB;

COMMENT ON COLUMN ad_runs.generation_config
IS 'Full reproducibility snapshot: prompt_version, scorer_weights, quality_config, image_resolution, content_source, pipeline_version';
```

### Service Changes

#### `ad_creation_service.py` — `save_generated_ad()`

Add parameter:
```python
prompt_version: Optional[str] = None,
```

Add to data dict:
```python
if prompt_version is not None:
    data["prompt_version"] = prompt_version
```

#### `ad_creation_service.py` — `create_ad_run()`

The `parameters` JSONB already exists and is passed through. We add `generation_config` as a separate column for structured querying:

Add parameter:
```python
generation_config: Optional[Dict] = None,
```

Add to data dict:
```python
if generation_config:
    data["generation_config"] = generation_config
```

### Pipeline Changes

#### `InitializeNode` — Build `generation_config` snapshot

After building `run_parameters`, build `generation_config`:

```python
generation_config = {
    "prompt_version": ctx.state.prompt_version,
    "pipeline_version": ctx.state.pipeline_version,
    "image_resolution": ctx.state.image_resolution,
    "content_source": ctx.state.content_source,
    "canvas_sizes": ctx.state.canvas_sizes,
    "color_modes": ctx.state.color_modes,
    "match_template_structure": ctx.state.match_template_structure,
    "auto_retry_rejected": ctx.state.auto_retry_rejected,
    "max_retry_attempts": ctx.state.max_retry_attempts,
    "template_id": ctx.state.template_id,
}
```

Pass to `create_ad_run(generation_config=generation_config)`.

#### `ReviewAdsNode` + `RetryRejectedNode` — Pass `prompt_version`

Both already call `save_generated_ad()`. Add `prompt_version=ctx.state.prompt_version` to each call.

#### `GenerateAdsNode` — Pass `prompt_version`

Same: add `prompt_version=ctx.state.prompt_version` to `save_generated_ad()` calls.

#### `DefectScanNode` — Pass `prompt_version`

Same for defect-rejected ads saved in DefectScanNode.

### Tests — `tests/pipelines/ad_creation_v2/test_versioning.py` (NEW)

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_generation_config_built` | InitializeNode builds correct generation_config dict |
| 2 | `test_generation_config_passed_to_create_ad_run` | create_ad_run receives generation_config kwarg |
| 3 | `test_prompt_version_saved_on_generated_ad` | save_generated_ad receives prompt_version kwarg |
| 4 | `test_prompt_version_default` | Default is "v2.1.0" from state |
| 5 | `test_generation_config_snapshot_fields` | All expected fields present in snapshot |
| 6 | `test_prompt_version_in_review_node_save` | ReviewAdsNode passes prompt_version |
| 7 | `test_prompt_version_in_retry_node_save` | RetryRejectedNode passes prompt_version |
| 8 | `test_prompt_version_in_defect_scan_save` | DefectScanNode passes prompt_version for defect-rejected |
| 9 | `test_generation_config_none_when_not_provided` | Backward compat: None doesn't crash |
| 10 | `test_prompt_version_none_when_not_provided` | Backward compat: None doesn't crash |

---

## P5-C3: Batch Size Guardrails + Cost Estimation

### Backend — Hard cap

#### `orchestrator.py` — `run_ad_creation_v2()`

Change validation:
```python
if num_variations < 1 or num_variations > 50:
    raise ValueError(f"num_variations must be between 1 and 50, got {num_variations}")
```

### Cost Estimation Service

#### `viraltracker/pipelines/ad_creation_v2/services/cost_estimation.py` (NEW)

```python
"""Cost estimation for V2 ad creation runs."""

# Configurable pricing constants (USD per unit)
PRICING_DEFAULTS = {
    "gemini_image_gen_per_ad": 0.04,        # Gemini image generation
    "claude_vision_review_per_ad": 0.02,    # Stage 2 Claude Vision review
    "gemini_vision_review_per_ad": 0.01,    # Stage 3 Gemini Vision (conditional ~40% of ads)
    "defect_scan_per_ad": 0.01,             # Stage 1 defect scan
    "congruence_check_per_hook": 0.015,     # HeadlineCongruenceNode LLM call
    "template_analysis_per_run": 0.03,      # AnalyzeTemplateNode (once per run)
    "stage3_trigger_rate": 0.4,             # Estimated % of ads that trigger Stage 3
    "retry_rate": 0.3,                      # Estimated % of ads that get retried (when enabled)
}

def estimate_run_cost(
    num_variations: int,
    num_canvas_sizes: int = 1,
    num_color_modes: int = 1,
    auto_retry: bool = False,
    pricing: dict | None = None,
) -> dict:
    """Estimate cost for a V2 run.

    Returns dict with per_ad_cost, total_cost, breakdown.
    """
```

This is a pure function, no DB calls, no services needed. Just arithmetic with configurable constants.

### UI — Tiered guardrails

#### `21b_🎨_Ad_Creator_V2.py` — In the submission section

1. Import `estimate_run_cost` and `PRICING_DEFAULTS`
2. When user sets `num_variations`:
   - **1-10:** No warning. Show estimate in caption.
   - **11-30:** Show yellow info box with cost estimate.
   - **31-50:** Show orange warning + require checkbox confirmation ("I understand this will cost ~$X").
   - **>50:** Show error, block submission. Offer "Auto-split into {ceil(n/50)} sequential jobs of {n//ceil(n/50)} each".
3. Auto-split: create multiple scheduled jobs with `num_variations = ceil(original / num_jobs)` each.

### Tests — `tests/pipelines/ad_creation_v2/test_cost_estimation.py` (NEW)

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_basic_estimate` | 5 variations → correct total |
| 2 | `test_multi_size_multiplier` | 5 vars × 2 sizes → doubled |
| 3 | `test_multi_color_multiplier` | 5 vars × 3 colors → tripled |
| 4 | `test_retry_adds_cost` | auto_retry=True increases estimate by retry_rate |
| 5 | `test_custom_pricing` | Override pricing constants |
| 6 | `test_breakdown_keys` | Result has per_ad_cost, total_cost, breakdown |
| 7 | `test_zero_variations` | Edge case: 0 → $0 |
| 8 | `test_one_variation` | Edge case: 1 → base cost |
| 9 | `test_stage3_conditional_cost` | Stage 3 cost = stage3_trigger_rate × gemini_review |
| 10 | `test_hard_cap_enforced` | orchestrator raises ValueError for >50 |
| 11 | `test_backend_cap_50` | run_ad_creation_v2(num_variations=51) → ValueError |
| 12 | `test_backend_allows_50` | run_ad_creation_v2(num_variations=50) → no error |

---

## P5-C4: Scoring Preset Validation

### CI Tests — `tests/services/test_scoring_diversity.py` (NEW)

Test that ROLL_THE_DICE_WEIGHTS and SMART_SELECT_WEIGHTS produce diverse template selections with synthetic data.

**Setup:** Create synthetic candidate pools (20-50 templates across 5+ categories with varying asset matches, recency, belief clarity scores).

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_roll_dice_no_template_dominance` | No single template > 30% of 100 selections |
| 2 | `test_roll_dice_category_coverage` | >= 3 categories represented in 20 selections |
| 3 | `test_roll_dice_unused_bonus_effect` | Previously-used templates appear less often |
| 4 | `test_smart_select_asset_match_priority` | Higher asset_match templates selected more often |
| 5 | `test_smart_select_category_coverage` | >= 3 categories in 20 selections |
| 6 | `test_smart_select_belief_clarity_effect` | Higher belief_clarity increases selection probability |
| 7 | `test_both_presets_deterministic_with_seed` | Same seed → same selection (numpy RNG) |
| 8 | `test_roll_dice_uniform_when_all_equal` | Equal scores → roughly uniform distribution |
| 9 | `test_smart_select_no_template_dominance` | No single template > 40% of 100 selections |
| 10 | `test_fallback_on_empty_pool` | Empty pool → graceful fallback |
| 11 | `test_single_candidate_always_selected` | Pool of 1 → always selected |
| 12 | `test_diversity_across_5_brands` | Parameterized: 5 brand configs → all meet diversity thresholds |

### Analysis Script — `scripts/validate_scoring_presets.py` (NEW)

One-time script that:
1. Connects to Supabase (staging/prod)
2. Fetches real template candidates for >= 5 brands
3. Runs 100 selections per brand per preset (Roll/Smart)
4. Produces a report:
   - Per-brand template repeat rate
   - Category distribution
   - Top-5 most-selected templates per preset
   - Diversity score (Shannon entropy)
5. Outputs to stdout + optional JSON file

Not part of CI — manual execution.

### Tests for analysis script

| # | Test | What it validates |
|---|------|-------------------|
| 13 | `test_diversity_score_calculation` | Shannon entropy function correct |
| 14 | `test_report_format` | Report dict has expected keys |
| 15 | `test_repeat_rate_calculation` | Repeat rate = selections / unique_templates |

---

## P5-C5: Results Dashboard Enhancement

### UI Changes — `21b_🎨_Ad_Creator_V2.py`

Enhance `render_results()` (currently lines 956-1062):

#### 1. Summary Stats Bar (top of results view)

```
| Total Ads | Approved | Rejected | Flagged | Override Rate |
|    147    |    98    |    31    |    12   |    8.5%       |
```

Query across all visible runs, not just per-job.

#### 2. Filter Controls

Add a filter bar below summary stats:

- **Status filter:** Multiselect `[Approved, Rejected, Flagged, Review Failed, Gen Failed, Override Approved, Override Rejected, Confirmed]`
- **Date range:** date_input pair (start/end), default last 7 days
- **Brand/Product:** Use existing `render_brand_selector()` — already at top of page
- **Ad Run ID:** text_input for specific run lookup
- **Sort by:** selectbox `[Newest First, Oldest First, Approval Rate (High), Approval Rate (Low)]`

#### 3. Group by Template

Instead of grouping by scheduled_job → job_run, group by template:

```
Template: "Social Proof Testimonial" (template_id: abc-123)
├── Run 2026-02-14 10:30 | 1080x1080 original | 5 ads (3 approved, 2 rejected)
│   ├── Ad #1: Approved [image] [scores] [override]
│   ├── Ad #2: Rejected [image] [scores] [override]
│   └── ...
├── Run 2026-02-13 15:00 | 1080x1350 brand | 3 ads (2 approved, 1 flagged)
│   └── ...
```

This requires a new query that joins `generated_ads` with `ad_runs` and groups by `template_id`/`template_name`.

#### 4. Bulk Actions

At the top of each template group:
- "Approve All Pending" → calls `create_override` for each flagged/rejected ad with action=override_approve
- "Reject All Pending" → same with action=override_reject
- "Retry Rejected" → create new scheduled job with same config targeting rejected ad hooks

#### 5. Pagination

- Default 20 ads per page
- "Load More" button or Streamlit pagination

### Service Support

#### `ad_review_override_service.py` — New methods

```python
def get_ads_filtered(
    self,
    org_id: str,
    *,
    status_filter: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    brand_id: str | None = None,
    product_id: str | None = None,
    ad_run_id: str | None = None,
    template_id: str | None = None,
    sort_by: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Fetch generated ads with filters for dashboard."""

def get_summary_stats(
    self,
    org_id: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    brand_id: str | None = None,
    product_id: str | None = None,
) -> dict:
    """Get aggregate stats: total, approved, rejected, flagged, override_rate."""

def bulk_override(
    self,
    generated_ad_ids: list[str],
    org_id: str,
    user_id: str,
    action: str,
    reason: str | None = None,
) -> dict:
    """Apply override to multiple ads at once. Returns {success: int, failed: int}."""
```

### Tests — `tests/services/test_ad_review_override_service.py` (EXTEND)

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_get_ads_filtered_status` | Status filter works |
| 2 | `test_get_ads_filtered_date_range` | Date range filter works |
| 3 | `test_get_ads_filtered_sort_newest` | Sort by newest first |
| 4 | `test_get_summary_stats` | Returns correct aggregate counts |
| 5 | `test_bulk_override_approve` | Multiple ads overridden at once |
| 6 | `test_bulk_override_empty_list` | Empty list → no-op |
| 7 | `test_get_ads_filtered_pagination` | Limit + offset work correctly |
| 8 | `test_get_ads_filtered_by_template` | Template grouping works |

---

## P5-C6: QA + E2E Testing

**Manual testing checklist** (no automated tests):

### Phase 4 UI Browser Tests (deferred from P4-C6)

- [ ] Override Approve button → status updates, badge changes
- [ ] Override Reject button → status updates, badge changes
- [ ] Confirm button → status updates
- [ ] Override with reason → reason saved
- [ ] Structured review scores display → colored indicators correct
- [ ] Defect scan result display → PASSED/FAILED with defect list
- [ ] Congruence score display → colored value
- [ ] Override rate summary → correct 30d stats

### Phase 5 Feature Tests

- [ ] Cost estimate shows correct values for 5/15/35 variations
- [ ] 31+ variations → confirmation checkbox required
- [ ] 51+ variations → blocked, auto-split offered
- [ ] Results dashboard summary stats → correct counts
- [ ] Status filter → filters correctly
- [ ] Date range filter → filters correctly
- [ ] Group by template → templates grouped with nested runs
- [ ] Bulk approve → all selected ads overridden
- [ ] Prompt version visible in ad details
- [ ] Generation config visible in run details

### Full E2E Flow

- [ ] Create V2 job → submitted to scheduler
- [ ] Job runs on worker → generates ads
- [ ] Defect scan catches bad images
- [ ] Staged review scores all ads
- [ ] Retried ads use staged review (not V1)
- [ ] Results dashboard shows all data
- [ ] Override an ad → status persists
- [ ] Cost estimation matches actual API calls (within 20%)

---

## Files Changed Summary (Estimated)

| File | Change |
|------|--------|
| `migrations/2026-02-14_ad_creator_v2_phase5_versioning.sql` | NEW: prompt_version + generation_config |
| `viraltracker/services/ad_creation_service.py` | +prompt_version param, +generation_config param |
| `viraltracker/services/ad_review_override_service.py` | +get_ads_filtered, +get_summary_stats, +bulk_override |
| `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` | REWRITE: V1 dual review → defect scan + staged review |
| `viraltracker/pipelines/ad_creation_v2/nodes/initialize.py` | +generation_config snapshot |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | +prompt_version passthrough |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | +prompt_version passthrough |
| `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` | +prompt_version passthrough (if save happens here) |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | Hard cap 50 |
| `viraltracker/pipelines/ad_creation_v2/services/cost_estimation.py` | NEW: cost estimation |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | Enhanced dashboard + guardrails |
| `scripts/validate_scoring_presets.py` | NEW: one-time analysis script |
| `tests/pipelines/ad_creation_v2/test_retry_rejected.py` | NEW: ~15 tests |
| `tests/pipelines/ad_creation_v2/test_versioning.py` | NEW: ~10 tests |
| `tests/pipelines/ad_creation_v2/test_cost_estimation.py` | NEW: ~12 tests |
| `tests/services/test_scoring_diversity.py` | NEW: ~15 tests |
| `tests/services/test_ad_review_override_service.py` | +8 tests |

**Total estimated new tests:** ~60
**Running total after Phase 5:** ~260 tests

---

## Execution Order

```
P5-C1 (RetryRejected refactor) ─┐
P5-C2 (Prompt versioning)       ├─ Independent, can run in parallel
P5-C3 (Batch guardrails)        │
P5-C4 (Scoring validation)      ┘
                                 │
P5-C5 (Dashboard enhancement) ──┘ depends on C2 for prompt_version display
                                 │
P5-C6 (QA + E2E) ───────────────┘ depends on all above
```

Recommended serial order: C1 → C2 → C3 → C4 → C5 → C6
(C1-C4 are independent but serial is safer for checkpoint discipline.)
