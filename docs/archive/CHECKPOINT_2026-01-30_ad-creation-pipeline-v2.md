# Checkpoint: Ad Creation Pipeline V2

**Date:** 2026-01-30
**Branch:** `feat/veo-avatar-tool`
**Status:** COMPLETE (all 3 phases)

## Summary

Rewrote the ad creation workflow from a monolithic 4,327-line agent file with 22 tools into a structured pydantic-graph pipeline with 8 nodes and 4 services. The agent file was reduced to 948 lines with 9 tools.

---

## What Changed

### Before

- **`ad_creation_agent.py`**: 4,327 lines, 22 `@agent.tool()` functions
- The `complete_ad_workflow` tool contained ~665 lines of inline orchestration
- 13 tools were internal pipeline steps always called in sequence (never standalone)
- Business logic lived in tool functions instead of services
- The scheduler and UI constructed fake `RunContext` objects to call tool functions:
  ```python
  # Old pattern (scheduler_worker.py, Ad Creator, Ad History)
  from pydantic_ai import RunContext
  from pydantic_ai.usage import RunUsage
  ctx = RunContext(deps=deps, model=None, usage=RunUsage())
  result = await complete_ad_workflow(ctx=ctx, product_id=..., ...)
  ```

### After

- **`ad_creation_agent.py`**: 948 lines, 9 tools
- `complete_ad_workflow` is a thin wrapper calling `run_ad_creation()`
- All callers import and call `run_ad_creation()` directly — no fake `RunContext`
- Business logic extracted into 4 services, orchestrated by 8 graph nodes
- Pipeline registered in `GRAPH_REGISTRY` for visualization

---

## Architecture

### Pipeline Structure

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
│   ├── retry_rejected.py        # Step 7b: Auto-retry rejected ads (optional)
│   └── compile_results.py       # Step 8: Compile results → End
└── services/
    ├── __init__.py
    ├── analysis_service.py      # Vision AI analysis, template angle extraction
    ├── content_service.py       # Hook selection, benefit variations, belief adapt
    ├── generation_service.py    # Prompt construction, Gemini image gen
    └── review_service.py        # Claude review, Gemini review, OR logic
```

### Pipeline Flow

```
InitializeNode          → Create ad_run row, upload reference ad to storage
    ↓
FetchContextNode        → Load product, persona, hooks, brief, fonts, brand data
    ↓
AnalyzeTemplateNode     → Vision AI analysis of reference ad (with cache check)
    ↓
SelectContentNode       → Branch by content_source:
                           hooks → select top hooks by relevance
                           recreate_template → extract template angle + benefit variations
                           belief_first → adapt belief to template structure
    ↓
SelectImagesNode        → Select product images (auto scoring or manual)
    ↓
GenerateAdsNode         → Loop: build prompt → Gemini image gen → upload (resilient per-ad)
    ↓
ReviewAdsNode           → Loop: Claude Vision + Gemini Vision review, OR logic
    ↓
RetryRejectedNode       → If auto_retry_rejected: regenerate rejected ads, re-review (optional)
    ↓
CompileResultsNode      → Compile results, update ad_run status → End
```

### Entry Point

```python
from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation

result = await run_ad_creation(
    product_id="uuid-string",
    reference_ad_base64="base64...",
    num_variations=5,
    content_source="hooks",        # hooks | recreate_template | belief_first | plan | angles
    color_mode="original",         # original | complementary | brand
    image_selection_mode="auto",   # auto | manual
    auto_retry_rejected=False,     # Auto-retry rejected ads
    deps=deps,                     # Optional[AgentDependencies]
    # ... other optional params
)

# Returns:
{
    "ad_run_id": "uuid",
    "product": {...},
    "ad_analysis": {...},
    "generated_ads": [...],
    "approved_count": 3,
    "rejected_count": 1,
    "flagged_count": 1,
    "summary": "Generated 5 ads: 3 approved, 1 rejected, 1 flagged"
}
```

### Node → Service Mapping

| Node | Service Method(s) | Former Tool |
|------|-------------------|-------------|
| `InitializeNode` | `AdCreationService.create_ad_run()`, `.upload_reference_ad()` | `create_ad_run`, `upload_reference_ad` |
| `FetchContextNode` | `AdCreationService.get_product()`, `.get_hooks()`, `.get_ad_brief_template()` | `get_product_with_images`, `get_hooks_for_product` |
| `AnalyzeTemplateNode` | `AnalysisService.analyze_reference_ad()` + cache check | `analyze_reference_ad` |
| `SelectContentNode` | `ContentService.select_hooks()`, `.extract_template_angle()`, `.generate_benefit_variations()`, `.adapt_belief_to_template()` | `select_hooks`, `extract_template_angle`, `generate_benefit_variations`, `adapt_belief_to_template` |
| `SelectImagesNode` | `ContentService.select_product_images()` | `select_product_images` |
| `GenerateAdsNode` | `GenerationService.generate_prompt()`, `.execute_generation()` | `generate_nano_banana_prompt`, `execute_nano_banana` |
| `ReviewAdsNode` | `ReviewService.review_ad_claude()`, `.review_ad_gemini()`, `.apply_dual_review_logic()` | `review_ad_claude`, `review_ad_gemini`, `save_generated_ad` |
| `RetryRejectedNode` | `GenerationService.generate_prompt()`, `.execute_generation()`, `ReviewService.*`, `AdCreationService.save_generated_ad()` | *New — auto-retry rejected ads* |
| `CompileResultsNode` | `AdCreationService.update_ad_run()` | End of `complete_ad_workflow` |

---

## Agent Tool Inventory (9 remaining)

| # | Tool | Category | Why Kept |
|---|------|----------|----------|
| 1 | `get_product_with_images` | Data retrieval | Used standalone by LLM |
| 2 | `get_hooks_for_product` | Data retrieval | Used standalone by LLM |
| 3 | `get_persona_for_copy` | Data retrieval | Used standalone by LLM |
| 4 | `list_product_personas` | Data retrieval | Used standalone by LLM |
| 5 | `analyze_product_image` | Analysis | Used by Brand Manager (not ad creation) |
| 6 | `complete_ad_workflow` | Pipeline entry | Thin wrapper → `run_ad_creation()` |
| 7 | `send_ads_email` | Export | Standalone export action |
| 8 | `send_ads_slack` | Export | Standalone export action |
| 9 | `generate_size_variant` | Post-processing | Standalone resize action |

### Tools Removed (13)

| Tool | Now In |
|------|--------|
| `analyze_reference_ad` | `AnalyzeTemplateNode` → `AnalysisService` |
| `select_hooks` | `SelectContentNode` → `ContentService` |
| `select_product_images` | `SelectImagesNode` → `ContentService` |
| `generate_nano_banana_prompt` | `GenerateAdsNode` → `GenerationService` |
| `execute_nano_banana` | `GenerateAdsNode` → `GenerationService` |
| `save_generated_ad` | `ReviewAdsNode` |
| `review_ad_claude` | `ReviewAdsNode` → `ReviewService` |
| `review_ad_gemini` | `ReviewAdsNode` → `ReviewService` |
| `create_ad_run` | `InitializeNode` |
| `upload_reference_ad` | `InitializeNode` |
| `extract_template_angle` | `SelectContentNode` → `AnalysisService` |
| `generate_benefit_variations` | `SelectContentNode` → `ContentService` |
| `adapt_belief_to_template` | `SelectContentNode` → `ContentService` |

---

## Callers

All three callers now use the same pattern — import and call `run_ad_creation()` directly:

### 1. Agent Tool (`ad_creation_agent.py`)

```python
@ad_creation_agent.tool(...)
async def complete_ad_workflow(ctx: RunContext[AgentDependencies], ...):
    from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
    return await run_ad_creation(..., deps=ctx.deps)
```

### 2. Scheduler Worker (`scheduler_worker.py`)

```python
from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation

# Belief-first mode (content_source in ['plan', 'angles']):
#   Loops angles × templates, passes angle context in additional_instructions
result = await run_ad_creation(product_id=..., ..., deps=deps)

# Traditional mode (hooks, recreate_template):
#   Loops templates only
result = await run_ad_creation(product_id=..., ..., deps=deps)
```

### 3. Ad Creator UI (`21_🎨_Ad_Creator.py`)

```python
from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
deps = AgentDependencies.create(user_id=..., organization_id=...)
result = await run_ad_creation(..., deps=deps)
```

### 4. Ad History UI (`22_📊_Ad_History.py`)

```python
from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
deps = AgentDependencies.create(project_name="default")
result = await run_ad_creation(..., deps=deps)  # Retry with stored params
```

---

## Scheduler Impact

**The scheduler behavior is unchanged.** The refactoring was a pure internal restructuring:

- **Same function signature**: `run_ad_creation()` accepts the same parameters the old `complete_ad_workflow` tool did
- **Same return format**: Returns the same dict with `ad_run_id`, `approved_count`, `rejected_count`, etc.
- **Same execution flow**: Both belief-first and traditional modes work identically
- **Simplified code**: The scheduler no longer needs to construct fake `RunContext` objects — it calls `run_ad_creation()` directly with a `deps` parameter
- **No configuration changes**: No scheduler settings, job parameters, or database schemas changed

The only difference is the import path changed from:
```python
from viraltracker.agent.agents.ad_creation_agent import complete_ad_workflow
```
to:
```python
from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
```

---

## Bugs Found and Fixed During Testing

| # | Bug | File | Root Cause | Fix |
|---|-----|------|------------|-----|
| 1 | `UUID object has no attribute 'replace'` | `fetch_context.py:161` | Supabase returns UUID objects, wrapping in `UUID()` again failed | `isinstance` check before conversion |
| 2 | `Object of type UUID is not JSON serializable` | `content_service.py:137` | Hook data from DB contains UUID fields | Added `_json_dumps` helper with UUID default handler |
| 3 | Same as #2 | `generation_service.py:261` | Prompt construction included hook UUIDs | Same `_json_dumps` fix |
| 4 | `Object of type UUID is not JSON serializable` | `review_ads.py:128` | `prompt_spec` dict passed to DB insert had UUIDs | Added `_stringify_uuids` recursive helper |
| 5 | `unhashable type: 'dict'` | `content_service.py:387` | `{{}}` inside nested f-strings evaluated as dict literal, not escaped braces | Pre-extracted `offer_variant` data before f-string |

---

## Test Results

- Import chain: All 8 nodes, 4 services, state, orchestrator, GRAPH_REGISTRY imported correctly
- Async test script: Full pipeline ran end-to-end (1 variation, hooks mode)
- Manual UI test #1: 5 variations generated and reviewed (found bug #5, fixed)
- Manual UI test #2: 5 variations generated and reviewed successfully
- Phase 3 cleanup: Import check passed, UI test passed with 9-tool agent

---

## Files Changed

| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation/` | **NEW** - Complete pipeline package (15 files) |
| `viraltracker/pipelines/__init__.py` | **MODIFIED** - Added `ad_creation` to GRAPH_REGISTRY |
| `viraltracker/agent/agents/ad_creation_agent.py` | **MODIFIED** - 4,327 → 948 lines, 22 → 9 tools |
| `viraltracker/worker/scheduler_worker.py` | **MODIFIED** - Direct pipeline calls, removed RunContext |
| `viraltracker/ui/pages/21_🎨_Ad_Creator.py` | **MODIFIED** - Direct pipeline call |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | **MODIFIED** - Direct pipeline call for retries |

---

## Phase History

| Phase | Description | Risk | Status |
|-------|-------------|------|--------|
| Phase 1 | Build pipeline alongside existing code | Zero | Complete |
| Phase 2 | Wire callers through pipeline | Medium | Complete |
| Phase 3 | Remove 13 demoted tools from agent | Low | Complete |
