# Checkpoint: Batch Iterate from Iteration Lab

**Date**: 2026-03-18
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Implemented, QA passed, ready for live testing

---

## What Was Built

### Blockers Fixed

1. **`evolve_winner()` rejects low-CTR ads** — Added `skip_winner_check: bool = False` param to `WinnerEvolutionService.evolve_winner()`. When the opportunity detector's quality filters have already validated an ad, the winner criteria check is skipped. Both the existing single-iterate flow (`action_opportunity`) and the new batch flow pass `skip_winner_check=True`.

2. **`ad_runs.brand_id` NULL for imported ads** — `_create_synthetic_ad_run()` now accepts and stores `brand_id`. `import_meta_winner()` passes it through. `evolve_winner()` has a fallback: if `brand_id` is NULL on `ad_runs`, it looks up via `products.brand_id`.

3. **`WinnerEvolutionService` constructor mismatch** — `action_opportunity()` was calling `WinnerEvolutionService(self.supabase)` and `MetaWinnerImportService(self.supabase)`, but both constructors take no args. Fixed to `WinnerEvolutionService()` and `MetaWinnerImportService()`.

4. **Worker passthrough** — `execute_winner_evolution_job()` now reads `skip_winner_check` from job params and passes it to `evolve_winner()`.

### New Features

5. **Proven Winners detector** — `_detect_proven_winner()` finds ads strong across all metrics (ROAS > p50, CTR > p25, spend > $100, impressions > 5K, 7+ days). Returns `pattern_type="proven_winner"` with `strategy_category="scale"`.

6. **Batch queue method** — `batch_queue_iterations()` on `IterationOpportunityDetector`:
   - Accepts up to 20 opportunity IDs
   - Auto-imports non-generated ads via `MetaWinnerImportService`
   - Creates one `winner_evolution` scheduled_job per opportunity
   - Only queues `status == "detected"` (skips already-actioned)
   - Sets status to `"queued"` (not "actioned" — `evolved_ad_id` unknown until worker completes)
   - Returns `{queued, imported, skipped, errors}`

7. **Awareness enrichment** — `_enrich_opportunities()` now fetches `creative_awareness_level` from classifications, enabling awareness-level filtering in the UI.

### UI Enhancements

8. **Strategy constants** — 5 strategies: Improve Hook, New Layout, Auto-Improve, New Sizes, Fresh Creative. Auto-recommended per pattern type.

9. **Opportunity cards** — Each image-ad card now has:
   - Checkbox (left column) for batch selection
   - Strategy dropdown (right column) pre-set to recommended strategy, all 5 options available

10. **Batch queue bar** — Appears below opportunity list when items are selected:
    - Count of selected
    - Bulk strategy override (or "Keep Individual")
    - "Queue N Iterations" button (requires product selection)

11. **Awareness → Opportunities link** — Awareness tab drilldown has "View opportunities for X ads" button. Sets awareness filter + toast telling user to switch to Tab 1.

12. **Awareness filter** — Applied in Tab 1 with clear button. Cleared on brand/product change.

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/winner_evolution_service.py` | `skip_winner_check` param, brand_id fallback |
| `viraltracker/services/meta_winner_import_service.py` | `brand_id` on `_create_synthetic_ad_run()` |
| `viraltracker/worker/scheduler_worker.py` | Pass `skip_winner_check` from job params |
| `viraltracker/services/iteration_opportunity_detector.py` | `_detect_proven_winner()`, `batch_queue_iterations()`, constructor fixes, awareness enrichment |
| `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` | Checkboxes, strategy picker, batch queue bar, awareness linking |

No new tables. No migrations. No dependency changes.

---

## QA Results

- All 5 files compile clean (`python3 -m py_compile`)
- Existing tests unaffected (pre-existing async test failures from missing `pytest-asyncio`)
- 4-agent code review passed:
  - Lambda closure correctly uses default arg capture
  - Column layout indexing valid for both branches
  - Session state keys consistent across card/bar/queue
  - All `scheduled_jobs` fields validated against CHECK constraints
  - Bool type preserved through JSONB round-trip
  - Worker routing confirmed for `winner_evolution` job type
- 2 minor fixes applied post-review: removed dead `timezone` import and unused `cvr` variable

---

## How to Test

### Quick Smoke Test
1. Go to **Iteration Lab** → **Find Opportunities** tab
2. Select a brand with performance data, select a product
3. Click **Scan for Opportunities**
4. Verify "Proven Winner" pattern appears for strong-performing ads
5. Check that each image-ad card has a checkbox and strategy dropdown

### Batch Queue Test
1. Select 2-3 opportunities via checkboxes
2. Override strategy on one via its dropdown
3. Click **Queue N Iterations**
4. Verify success toast with count
5. Check **Scheduled Tasks** page — new `winner_evolution` jobs should appear
6. Verify job parameters include `skip_winner_check: true`

### Awareness Link Test
1. Go to **Awareness Coverage** tab → click **Analyze Awareness**
2. Expand a level → click **View opportunities for X ads**
3. Switch to **Find Opportunities** tab
4. Verify filter badge shows and opportunities are filtered
5. Click **Clear filter** → verify all opportunities return

### Worker Test
1. Wait ~1 minute for worker to pick up a queued job
2. Verify V2 pipeline runs and generates a new ad
3. Check `ad_lineage` table for parent→child entry
