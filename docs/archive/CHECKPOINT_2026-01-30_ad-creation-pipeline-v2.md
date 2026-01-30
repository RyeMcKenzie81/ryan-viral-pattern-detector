# Checkpoint: Ad Creation Pipeline V2

**Date:** 2026-01-30
**Branch:** `feat/veo-avatar-tool`
**Commits:** `5203003`, `1ed58f0`

## What Was Done

Rewrote the ad creation workflow from a monolithic 4,327-line agent file with 22 tools into a structured pydantic-graph pipeline with 8 nodes and 4 services.

### Phase 1: Build Pipeline (Complete)

Created `viraltracker/pipelines/ad_creation/` with:

```
viraltracker/pipelines/ad_creation/
├── __init__.py
├── state.py                     # AdCreationPipelineState (34 fields)
├── orchestrator.py              # Graph definition + run_ad_creation()
├── nodes/
│   ├── __init__.py
│   ├── initialize.py            # Step 1: Create ad_run, upload reference
│   ├── fetch_context.py         # Step 2: Product, persona, hooks, brief, fonts
│   ├── analyze_template.py      # Step 3: Vision AI analysis (+ cache)
│   ├── select_content.py        # Step 4: Branch by content_source
│   ├── select_images.py         # Step 5: Auto/manual image selection
│   ├── generate_ads.py          # Step 6: Loop N variations (resilient)
│   ├── review_ads.py            # Step 7: Dual AI review (Claude + Gemini)
│   └── compile_results.py       # Step 8: Compile results → End
└── services/
    ├── __init__.py
    ├── analysis_service.py      # Vision AI analysis, template angle extraction
    ├── content_service.py       # Hook selection, benefit variations, belief adapt
    ├── generation_service.py    # Prompt construction, Gemini image gen
    └── review_service.py        # Claude review, Gemini review, OR logic
```

Registered pipeline in `GRAPH_REGISTRY` in `pipelines/__init__.py`.

### Phase 2: Wire Through Pipeline (Complete)

- `ad_creation_agent.py`: `complete_ad_workflow` tool → thin wrapper calling `run_ad_creation()`
  - Removed ~665 lines of inline orchestration code
- `scheduler_worker.py`: Replaced fake `RunContext` construction with direct `run_ad_creation()` calls
  - Removed `from pydantic_ai import RunContext` and `RunUsage` imports
- `21_🎨_Ad_Creator.py`: Direct `run_ad_creation()` call, renamed to "Ad Creator V2"
- `22_📊_Ad_History.py`: Direct `run_ad_creation()` call for re-runs

### Bugs Found and Fixed During Testing

1. **UUID object vs string** (`fetch_context.py`): `brand_id` from Supabase was already a UUID object. Fixed with `isinstance` check.
2. **UUID serialization** (`content_service.py`, `generation_service.py`): Hooks data from DB contains UUID fields that `json.dumps` can't serialize. Added `_json_dumps` helper.
3. **UUID in DB insert** (`review_ads.py`): `prompt_spec` dict contained UUIDs from hook data. Added `_stringify_uuids` recursive helper.
4. **Nested f-string escaping** (`content_service.py`): `{{}}` inside nested f-strings evaluated as dict literal, not escaped braces. Pre-extracted offer_variant data before f-string.

### Test Results

- Import chain: All 8 nodes, 4 services, state, orchestrator, GRAPH_REGISTRY ✅
- Async test script: Full pipeline ran end-to-end (1 variation, hooks mode) ✅
- Manual UI test: 5 variations generated and reviewed successfully from Ad Creator V2 ✅

## Phase 3 Status: IN PROGRESS

Phase 3 line removal is DONE. The agent file is now 948 lines (down from 3,660). The following cleanup was completed:
- Removed 13 tool functions and 3 helper functions
- Updated docstring, section headers, tool count logger (now says 9 tools)
- Removed unused `Any` import
- `py_compile` passed

**STILL NEEDED:**
1. Run full import check: `python3 -c "from viraltracker.agent import agent"` (was interrupted)
2. Commit and push
3. User testing: run Ad Creator V2 from UI to confirm nothing broke

### Phase 3 Details: Clean Up Agent File

Removed 13 demoted tools from `ad_creation_agent.py`. These are internal pipeline steps that are now handled by pipeline nodes/services. The agent keeps 9 tools with standalone utility:

| # | Tool (KEEP) | Why |
|---|------------|-----|
| 1 | `get_product_with_images` | Data retrieval - used standalone |
| 2 | `get_hooks_for_product` | Data retrieval - used standalone |
| 3 | `get_persona_for_copy` | Data retrieval - used standalone |
| 4 | `list_product_personas` | Data retrieval - used standalone |
| 5 | `analyze_product_image` | Standalone analysis (Brand Manager) |
| 6 | `complete_ad_workflow` | Thin wrapper → pipeline |
| 7 | `send_ads_email` | Export |
| 8 | `send_ads_slack` | Export |
| 9 | `generate_size_variant` | Post-processing |

Tools to REMOVE (13):
- `analyze_reference_ad` - now in AnalyzeTemplateNode → AnalysisService
- `select_hooks` - now in SelectContentNode → ContentService
- `select_product_images` - now in SelectImagesNode → ContentService
- `generate_nano_banana_prompt` - now in GenerateAdsNode → GenerationService
- `execute_nano_banana` - now in GenerateAdsNode → GenerationService
- `save_generated_ad` - now in ReviewAdsNode
- `review_ad_claude` - now in ReviewAdsNode → ReviewService
- `review_ad_gemini` - now in ReviewAdsNode → ReviewService
- `create_ad_run` - now in InitializeNode
- `upload_reference_ad` - now in InitializeNode
- `extract_template_angle` - now in SelectContentNode → AnalysisService
- `generate_benefit_variations` - now in SelectContentNode → ContentService
- `adapt_belief_to_template` - now in SelectContentNode → ContentService

Expected file size reduction: ~4,327 → ~800-1,000 lines.

## Key Files

| File | Status |
|------|--------|
| `viraltracker/pipelines/ad_creation/` | NEW - complete pipeline package |
| `viraltracker/agent/agents/ad_creation_agent.py` | MODIFIED - tool wired as wrapper |
| `viraltracker/pipelines/__init__.py` | MODIFIED - registry entry added |
| `viraltracker/worker/scheduler_worker.py` | MODIFIED - direct pipeline calls |
| `viraltracker/ui/pages/21_🎨_Ad_Creator.py` | MODIFIED - direct pipeline call, V2 title |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | MODIFIED - direct pipeline call |
