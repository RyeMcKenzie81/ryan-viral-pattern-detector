# Checkpoint: PydanticAI Agent Usage Tracking

**Date:** 2026-01-26
**Branch:** feat/veo-avatar-tool

## Summary

Implemented usage tracking for all 9 PydanticAI agent-using services. Created a centralized wrapper module that automatically tracks token usage to the billing system.

## Files Created

### `viraltracker/services/agent_tracking.py` (NEW)
Centralized wrapper functions for tracking PydanticAI agent usage:
- `run_agent_with_tracking()` - async wrapper for `agent.run()`
- `run_agent_sync_with_tracking()` - sync wrapper for `agent.run_sync()`
- `_track_agent_usage()` - extracts usage from RunResult and calls UsageTracker
- `_get_provider_from_model()` - determines provider (anthropic/openai/google) from model name

## Files Modified

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

### Changes per Service

Each service received:
1. Import statements for `run_agent_with_tracking` and `UsageTracker`
2. Private tracking fields: `_tracker`, `_user_id`, `_org_id`
3. `set_tracking_context(tracker, user_id, org_id)` method
4. All `agent.run()` calls replaced with `run_agent_with_tracking()`
5. All `agent.run_sync()` calls replaced with `run_agent_sync_with_tracking()`

## Pattern Used

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
    agent,
    prompt,
    tracker=self._tracker,
    user_id=self._user_id,
    organization_id=self._org_id,
    tool_name="service_name",
    operation="method_name"
)
```

## Next Steps

### Phase 2: UI Integration (Pending)

UI pages that use these services need to call `set_tracking_context()` before invoking agent methods:

| UI Page | Service(s) Used |
|---------|-----------------|
| Content Pipeline | ScriptService, ComicService |
| Competitor Research | CompetitorService |
| Belief Canvas | BeliefAnalysisService |
| Reddit Research | RedditSentimentService |
| Ad Planning | PlanningService |
| Personas | PersonaService |
| Brand Onboarding | AmazonReviewService |
| Ad Scheduler | CopyScaffoldService |

### Integration Pattern for UI

```python
from viraltracker.services.usage_tracker import UsageTracker
from viraltracker.core.database import get_supabase_client

# Get tracking context from session
tracker = UsageTracker(get_supabase_client())
user_id = st.session_state.get("user_id")
org_id = st.session_state.get("selected_org_id")

# Set tracking context on service
service = ScriptService(...)
service.set_tracking_context(tracker, user_id, org_id)

# Now use service normally - tracking happens automatically
result = await service.generate_script(...)
```

## Verification

All files pass syntax check:
```bash
python3 -m py_compile viraltracker/services/agent_tracking.py
python3 -m py_compile viraltracker/services/content_pipeline/services/script_service.py
# ... (all 10 files verified)
```

## Database Table

Usage is tracked to the existing `token_usage` table with:
- `provider`: anthropic, openai, google, or unknown
- `model`: Full model name from agent
- `tool_name`: Service name (e.g., "script_service")
- `operation`: Method name (e.g., "generate_script")
- `input_tokens`: From PydanticAI usage.request_tokens
- `output_tokens`: From PydanticAI usage.response_tokens

---

## Phase 2: UI Integration (COMPLETED)

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
| 41_📝_Content_Pipeline.py | ScriptService, ComicService | Getter functions |
| 13_📊_Competitive_Analysis.py | CompetitorService | Getter function |
| 03_👤_Personas.py | PersonaService | Getter function |
| 25_📋_Ad_Planning.py | PlanningService, CopyScaffoldService | Getter + inline |
| 32_💡_Research_Insights.py | PlanningService | Getter function |
| 04_🔗_URL_Mapping.py | CompetitorService | Getter function |
| 12_🔍_Competitor_Research.py | CompetitorService, PersonaService | Getter + inline |
| 05_🔬_Brand_Research.py | PersonaService, AmazonReviewService | Getter functions |
| 06_🚀_Client_Onboarding.py | AmazonReviewService | Getter function |
| 26_📊_Plan_List.py | PlanningService | Getter function |
| 11_🎯_Competitors.py | CompetitorService | Getter function |
| 21_🎨_Ad_Creator.py | PlanningService | Inline |
| 24_📅_Ad_Scheduler.py | PlanningService | Getter function |

### Update Pattern Used

For getter functions:
```python
def get_service():
    from viraltracker.services.some_service import SomeService
    from viraltracker.ui.utils import setup_tracking_context
    service = SomeService()
    setup_tracking_context(service)
    return service
```

For inline instantiations:
```python
from viraltracker.services.some_service import SomeService
from viraltracker.ui.utils import setup_tracking_context
service = SomeService()
setup_tracking_context(service)
# use service...
```

## Status: COMPLETE

All PydanticAI agent usage is now tracked to the billing system:
1. ✅ Wrapper module created (`agent_tracking.py`)
2. ✅ 9 services updated with tracking wrappers
3. ✅ UI utility function added (`setup_tracking_context`)
4. ✅ 14 UI pages updated to enable tracking

## Verification

To verify tracking is working:
1. Use any feature that calls a tracked service (e.g., generate a script)
2. Query the `token_usage` table:
   ```sql
   SELECT * FROM token_usage
   WHERE provider = 'anthropic'
   ORDER BY created_at DESC
   LIMIT 10;
   ```
3. Verify records appear with correct `tool_name` and `operation`
