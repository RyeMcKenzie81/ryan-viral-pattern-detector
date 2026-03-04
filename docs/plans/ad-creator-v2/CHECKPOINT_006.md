# CHECKPOINT 006 — Phase 1 Foundation Complete

**Date:** 2026-02-13
**Branch:** `feat/ad-creator-v2-phase0`
**Phase:** Phase 1: Foundation (Worker + Pydantic Prompts + Scoring Pipeline)

---

## What Was Built

### P1-C1: V2 Pipeline Directory + Pydantic Prompt Models (20 files)

Created `viraltracker/pipelines/ad_creation_v2/` mirroring V1 structure:

- **state.py** — V2 state with 4 new fields: `template_id`, `pipeline_version`, `canvas_size`, `prompt_version`
- **orchestrator.py** — `ad_creation_v2_graph` + `run_ad_creation_v2()` entry point
- **models/prompt.py** — 20+ Pydantic models replacing V1's 280-line dict literal:
  - `AdGenerationPrompt` (top-level), `TaskConfig`, `ProductContext`, `ContentConfig`
  - `ColorConfig`, `FontConfig`, `StyleConfig`, `ImageConfig`, `TemplateAnalysis`
  - `AssetContext` (Phase 1 stub), `GenerationRules`, `AdBriefConfig`
  - `PerformanceContext` (Phase 6+ stub)
- **services/generation_service.py** — Rewritten to construct `AdGenerationPrompt` model
- **nodes/generate_ads.py** — Passes `canvas_size`, tracks `prompt_version`
- **nodes/compile_results.py** — Includes `pipeline_version` and `prompt_version` in output
- **7 unchanged node copies** (initialize, fetch_context, analyze_template, select_content, select_images, review_ads, retry_rejected)
- **3 unchanged service copies** (review_service, analysis_service, content_service)

### P1-C2: Template Scoring Service (1 file)

`viraltracker/services/template_scoring_service.py`:

- `TemplateScorer` ABC with `score(template, context) -> float`
- `SelectionContext` dataclass with prefetched `product_asset_tags`
- `SelectionResult` structured return type
- 3 Phase 1 scorers: `AssetMatchScorer`, `UnusedBonusScorer`, `CategoryMatchScorer`
- `select_templates()` — Weighted-random selection with asset gate
- `fetch_template_candidates()` — Two Supabase queries merged in Python
- `prefetch_product_asset_tags()` — Single query, N+1 prevention
- `select_templates_with_fallback()` — 3-tier fallback
- Weight presets: `ROLL_THE_DICE_WEIGHTS`, `SMART_SELECT_WEIGHTS`

### P1-C3: Worker Integration (1 modified file)

Replaced V2 stub in `scheduler_worker.py` with full `execute_ad_creation_v2_job()`:

- 3 template selection modes: manual, roll_the_dice, smart_select
- Calls `run_ad_creation_v2()` (not V1)
- Cap metric: `ads_attempted` counts attempts, not approvals
- Progress metadata updated during template loop
- Scoring results logged with per-scorer breakdown

### P1-C4: V2 UI Page (1 file)

`viraltracker/ui/pages/21b_Ad_Creator_V2.py`:

- Product selector via `render_brand_selector()`
- Template selection with 3 modes (manual grid, roll_the_dice, smart_select)
- Preview Selection button runs scoring and shows results
- Generation config (content source, color mode, variations, resolution, persona)
- Batch estimate with cost projection
- Submits `job_type='ad_creation_v2'` to `scheduled_jobs`
- Results view with run metadata, approval rates, and logs

### P1-C5: Comparison Script (1 file)

`scripts/v1_v2_comparison.py`:

- `--dry-run` mode: compile checks, V1 untouched check, scoring test, import check
- `--live` mode: runs V1 and V2 on same templates, compares approval rates
- Pass criteria from plan: V2 within 5% of V1 (N >= 30), 95% completion (N >= 20)
- Template scoring structure validation

---

## File Summary

| Category | New Files | Modified Files |
|----------|-----------|----------------|
| V2 Pipeline | 20 | 0 |
| Template Scoring | 1 | 0 |
| Worker | 0 | 1 |
| UI | 1 | 0 |
| Scripts | 1 | 0 |
| Docs | 1 | 0 |
| **Total** | **24** | **1** |

**V1 files touched: 0** (critical invariant verified)

---

## Verification

- [x] All 24 files compile clean (`py_compile`)
- [x] V1 directory untouched (`git diff viraltracker/pipelines/ad_creation/` = empty)
- [x] Template scoring service has 3 scorer dimensions + composite
- [x] Worker handles 3 template selection modes
- [x] V2 pipeline includes `pipeline_version` and `prompt_version` in output
- [x] Pydantic prompt models use `model_dump(exclude_none=True)` for serialization
- [x] Post-plan review fixes applied (see below)

---

## Post-Plan Review Fixes Applied

1. **CRITICAL**: Fixed `get_supabase_client` import in `template_scoring_service.py` — was importing from `viraltracker.ui.auth` (doesn't export it), changed to `viraltracker.core.database`
2. **BUG**: Fixed `retry_rejected.py` — added `canvas_size` and `prompt_version` params to `generate_prompt()` call, added `image_resolution` to `execute_generation()` call
3. **CLEANUP**: Removed unused `Union` import from 8 node files, unused `End` import from 7 node files (kept in `compile_results.py`), unused `json` import from `review_ads.py`
4. **CLEANUP**: Removed dead validation code in `select_content.py:170-173` (unreachable after else branch raises ValueError)

---

## Known Limitations

1. **Import test**: `python -c "from ... import run_ad_creation_v2"` fails locally because `pydantic_graph` is not installed. `py_compile` passes on all files.
2. **Live comparison**: Not yet run (requires deployed environment with LLM access).
3. **Asset tags**: Product images may not have `asset_tags` populated yet — `AssetMatchScorer` returns 1.0 (no requirements) in that case.

---

## Tech Debt

- TD-32: ~~Template scoring service uses `get_supabase_client()` from UI auth module~~ — **FIXED**: now imports from `viraltracker.core.database`
- TD-33: V2 UI page uses `asyncio.new_event_loop()` for scoring preview — consider Streamlit async integration
- TD-34: Comparison script `--live` mode needs deployed testing environment
