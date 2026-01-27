# Checkpoint: PydanticAI Agent Usage Tracking

**Date:** 2026-01-27
**Branch:** feat/veo-avatar-tool

## Summary

Implemented usage tracking for all 9 PydanticAI agent-using services, integrated tracking into UI pages and graph pipelines, fixed organization filtering across all pages, and fixed asyncio event loop conflicts.

---

## Phase 1: Tracking Wrapper (COMPLETE)

### `viraltracker/services/agent_tracking.py` (NEW)
Centralized wrapper functions for tracking PydanticAI agent usage:
- `run_agent_with_tracking()` - async wrapper for `agent.run()`
- `run_agent_sync_with_tracking()` - sync wrapper for `agent.run_sync()`
- `_track_agent_usage()` - extracts usage from RunResult and calls UsageTracker
- `_get_provider_from_model()` - determines provider (anthropic/openai/google) from model name

### Services Updated (9 total)

| Service | File | Agent Calls | Operations Tracked |
|---------|------|-------------|-------------------|
| ScriptService | `content_pipeline/services/script_service.py` | 3 | generate_script, review_script, revise_script |
| ComicService | `content_pipeline/services/comic_service.py` | 3 | condense_to_comic, evaluate_comic_script, revise_comic |
| CompetitorService | `competitor_service.py` | 3 | analyze_landing_page, extract_belief_signals, analyze_reviews |
| BeliefAnalysisService | `belief_analysis_service.py` | 1 | draft_canvas |
| RedditSentimentService | `reddit_sentiment_service.py` | 5 | score_relevance, filter_signal, score_intent, extract_quotes, extract_belief_signals |
| PlanningService | `planning_service.py` | 3 | suggest_offers, suggest_jtbd, suggest_angles |
| PersonaService | `persona_service.py` | 2 | generate_persona_from_product, synthesize_competitor_persona |
| AmazonReviewService | `amazon_review_service.py` | 2 | analyze_reviews, analyze_reviews_for_product |
| CopyScaffoldService | `copy_scaffold_service.py` | 1 | generate_copy |

### Pattern Used

```python
# In service __init__
self._tracker: Optional[UsageTracker] = None
self._user_id: Optional[str] = None
self._org_id: Optional[str] = None

def set_tracking_context(self, tracker, user_id, org_id):
    self._tracker = tracker
    self._user_id = user_id
    self._org_id = org_id

# In methods with agent calls
result = await run_agent_with_tracking(
    agent, prompt,
    tracker=self._tracker,
    user_id=self._user_id,
    organization_id=self._org_id,
    tool_name="service_name",
    operation="method_name"
)
```

---

## Phase 2: UI Integration (COMPLETE)

### New Utility Added

**File:** `viraltracker/ui/utils.py`

Added `setup_tracking_context(service)` function that:
- Checks if service has `set_tracking_context` method
- Gets current user_id from `get_current_user_id()`
- Gets current org_id from `get_current_organization_id()`
- Creates UsageTracker and configures service

### UI Pages Updated (14 total)

| Page | Service(s) | Update Type |
|------|------------|-------------|
| 41_Content_Pipeline | ScriptService, ComicService | Getter functions |
| 13_Competitive_Analysis | CompetitorService | Getter function |
| 03_Personas | PersonaService | Getter function |
| 25_Ad_Planning | PlanningService, CopyScaffoldService | Getter + inline |
| 32_Research_Insights | PlanningService | Getter function |
| 04_URL_Mapping | CompetitorService | Getter function |
| 12_Competitor_Research | CompetitorService, PersonaService | Getter + inline |
| 05_Brand_Research | PersonaService, AmazonReviewService | Getter functions |
| 06_Client_Onboarding | AmazonReviewService | Getter function |
| 26_Plan_List | PlanningService | Getter function |
| 11_Competitors | CompetitorService | Getter function |
| 21_Ad_Creator | PlanningService | Inline |
| 24_Ad_Scheduler | PlanningService | Getter function |

---

## Phase 3: Pipeline Tracking (COMPLETE)

Pipelines create their own `AgentDependencies` internally, so the UI can't pass tracking context. Fixed by calling `setup_tracking_context()` after dependency creation.

### Pipelines Fixed

| Pipeline | File | Services Tracked |
|----------|------|-----------------|
| Belief Reverse Engineer | `pipelines/belief_reverse_engineer.py` | belief_analysis, reddit_sentiment |
| Reddit Sentiment | `pipelines/reddit_sentiment.py` | reddit_sentiment (both entry points) |

---

## Phase 4: Organization Filtering (COMPLETE)

### Critical Fix: Cross-Org Data Leakage

Many pages had local `get_brands()` functions that fetched ALL brands without organization filtering, allowing users to see data from other workspaces.

### Pages with direct query fixes (5 pages)

| Page | Fix |
|------|-----|
| 22_Ad_History | Rewrote queries with org_id filtering on ad_runs |
| 23_Ad_Gallery | Added org filtering to product and ad queries |
| 15_Reddit_Research | Added org selector, replaced local get_brands() |
| 24_Ad_Scheduler | Added org selector, replaced local get_brands() |
| 26_Plan_List | Added org filtering to belief_plans query, added missing require_auth() |

### Pages with local get_brands() replaced (10 pages)

All replaced to delegate to shared `get_brands()` from `viraltracker/ui/utils`:

- 02_Brand_Manager, 03_Personas, 04_URL_Mapping, 05_Brand_Research
- 11_Competitors, 12_Competitor_Research, 13_Competitive_Analysis
- 27_Plan_Executor, 31_Belief_Canvas, 41_Content_Pipeline

---

## Phase 5: Asyncio Fix (COMPLETE)

### Problem

Streamlit runs its own event loop, so `asyncio.run()` fails with "This event loop is already running". This crashed the Reddit Research pipeline after scraping.

### Fix

Added `nest_asyncio.apply()` to all 13 pages that use `asyncio.run()`:

- 15_Reddit_Research, 22_Ad_History, 23_Ad_Gallery, 25_Ad_Planning
- 27_Plan_Executor, 28_Template_Queue, 29_Template_Recommendations
- 30_Ad_Performance, 31_Belief_Canvas, 42_Comic_Video
- 43_Comic_JSON_Generator, 44_Editor_Handoff, 45_Audio_Production, 99_Sora_MVP

---

## Bug Fixes

### synthesize_messaging() argument error
- **File:** `12_Competitor_Research.py` line 676
- **Issue:** Extra `[group]` argument passed to `synthesize_messaging()` which only accepts 1 arg
- **Fix:** Removed extra argument
- **Pre-existing bug** from offer variant discovery commit

### RunResult import error
- **File:** `services/agent_tracking.py`
- **Issue:** `RunResult` renamed to `AgentRunResult` and moved in pydantic-ai 1.x
- **Fix:** Removed import, used `from __future__ import annotations`

---

## Verification

### Tracking Verified (4/9 services)

| Service | Status | Verified Via |
|---------|--------|-------------|
| ScriptService + ComicService | ✅ Verified | Content Pipeline |
| CompetitorService | ✅ Verified | Competitor Research |
| BeliefAnalysisService | ✅ Verified | Belief Canvas (1,486 in + 3,525 out tokens) |
| RedditSentimentService | ✅ Verified | Reddit Research |
| PlanningService | ⏳ Pending | Ad Planning |
| PersonaService | ⏳ Pending | Personas |
| AmazonReviewService | ⏳ Pending | Brand Research / Client Onboarding |
| CopyScaffoldService | ⏳ Pending | Ad Planning (generate copy) |

### SQL to verify

```sql
SELECT tool_name, operation, input_tokens, output_tokens, created_at
FROM token_usage
WHERE created_at > now() - interval '30 minutes'
ORDER BY created_at DESC;
```

---

## Database Table

Usage tracked to `token_usage` table:
- `provider`: anthropic, openai, google, or unknown
- `model`: Full model name from agent
- `tool_name`: Service name (e.g., "script_service")
- `operation`: Method name (e.g., "generate_script")
- `input_tokens`: From PydanticAI usage.request_tokens
- `output_tokens`: From PydanticAI usage.response_tokens

---

## Remaining Work

- Test PlanningService (Ad Planning page)
- Test PersonaService (Personas page)
- Test AmazonReviewService (Brand Research / Client Onboarding)
- Test CopyScaffoldService (Ad Planning - generate copy step)
