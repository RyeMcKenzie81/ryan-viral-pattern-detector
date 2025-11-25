# Phase 12 Checkpoint: FastAPI Endpoint Generator Multi-Agent Update

**Date**: November 24, 2025
**Branch**: `refactor/pydantic-ai-alignment`
**Status**: In Progress - Updating Endpoint Generator for All Agents

---

## Executive Summary

Discovered critical architectural issue: FastAPI endpoint generator only creates endpoints for orchestrator's 5 routing tools, NOT for the 19 actual platform-specific tools in specialized agents. Updating system to generate endpoints for ALL agents.

**Key Discovery**: Current `app.py` only passes `orchestrator` to endpoint generator, missing endpoints for `twitter_agent`, `tiktok_agent`, `youtube_agent`, `facebook_agent`, and `analysis_agent`.

---

## Problem Identified

### Current Behavior (Incorrect)

```python
# viraltracker/api/app.py:345
from ..agent.agent import agent  # This is actually orchestrator
tools_router = generate_tool_endpoints(agent, limiter, verify_api_key)
```

**Result**: Only 5 endpoints generated (routing tools):
- `POST /tools/route-to-twitter-agent`
- `POST /tools/route-to-tiktok-agent`
- `POST /tools/route-to-youtube-agent`
- `POST /tools/route-to-facebook-agent`
- `POST /tools/route-to-analysis-agent`

### Expected Behavior (Correct)

Should generate endpoints for ALL 19 tools across 6 agents:

**Orchestrator (5 routing tools)**:
- `route_to_twitter_agent`
- `route_to_tiktok_agent`
- `route_to_youtube_agent`
- `route_to_facebook_agent`
- `route_to_analysis_agent`

**Twitter Agent (8 tools)**:
- `search_twitter_tool`
- `get_top_tweets_tool`
- `export_tweets_tool`
- `find_comment_opportunities_tool`
- `export_comments_tool`
- `analyze_search_term_tool`
- `generate_content_tool`
- `verify_scrape_tool`

**TikTok Agent (5 tools)**:
- `search_tiktok_tool`
- `get_top_tiktoks_tool`
- `export_tiktoks_tool`
- `find_tiktok_outliers_tool`
- `analyze_tiktok_hooks_tool`

**YouTube Agent (1 tool)**:
- `search_youtube_tool`

**Facebook Agent (2 tools)**:
- `search_facebook_tool`
- `export_facebook_tool`

**Analysis Agent (3 tools)**:
- `find_outliers_tool`
- `analyze_hooks_tool`
- `generate_twitter_content_tool`

**Total**: 24 endpoints (5 routing + 19 platform tools)

---

## Root Cause Analysis

### Backwards Compatibility Layer

```python
# viraltracker/agent/agent.py:42
agent = orchestrator  # Re-export for backwards compatibility
```

This was designed to maintain compatibility with existing code that imported `agent`, but it means:
1. `app.py` imports `agent` thinking it gets all tools
2. Actually gets only the orchestrator with 5 routing tools
3. Specialized agents (twitter, tiktok, etc.) are never passed to endpoint generator

### Why This Wasn't Noticed Earlier

The system still works because:
1. Users interact through `POST /agent/run` endpoint
2. Orchestrator routes requests to specialized agents correctly
3. Tool execution happens internally via agent delegation
4. Direct tool endpoints (`POST /tools/{tool-name}`) were never tested

However, this means:
- Cannot call tools directly via API (e.g., `POST /tools/search-twitter`)
- FastAPI auto-docs only show 5 routing endpoints
- Streamlit UI cannot use direct tool endpoints
- External integrations must go through orchestrator

---

## Solution Design

### Option 1: Multiple Router Registrations (Recommended)

Generate separate routers for each agent, then include all in main app:

```python
# viraltracker/api/app.py
from ..agent.orchestrator import orchestrator
from ..agent.agents.twitter_agent import twitter_agent
from ..agent.agents.tiktok_agent import tiktok_agent
from ..agent.agents.youtube_agent import youtube_agent
from ..agent.agents.facebook_agent import facebook_agent
from ..agent.agents.analysis_agent import analysis_agent

# Generate routers for each agent
orchestrator_router = generate_tool_endpoints(orchestrator, limiter, verify_api_key, prefix="orchestrator")
twitter_router = generate_tool_endpoints(twitter_agent, limiter, verify_api_key, prefix="twitter")
tiktok_router = generate_tool_endpoints(tiktok_agent, limiter, verify_api_key, prefix="tiktok")
youtube_router = generate_tool_endpoints(youtube_agent, limiter, verify_api_key, prefix="youtube")
facebook_router = generate_tool_endpoints(facebook_agent, limiter, verify_api_key, prefix="facebook")
analysis_router = generate_tool_endpoints(analysis_agent, limiter, verify_api_key, prefix="analysis")

# Include all routers
app.include_router(orchestrator_router, prefix="/api/v1/orchestrator", tags=["Orchestrator"])
app.include_router(twitter_router, prefix="/api/v1/twitter", tags=["Twitter"])
app.include_router(tiktok_router, prefix="/api/v1/tiktok", tags=["TikTok"])
app.include_router(youtube_router, prefix="/api/v1/youtube", tags=["YouTube"])
app.include_router(facebook_router, prefix="/api/v1/facebook", tags=["Facebook"])
app.include_router(analysis_router, prefix="/api/v1/analysis", tags=["Analysis"])
```

**Advantages**:
- Clean separation by agent
- Easy to add/remove agents
- Clear API structure in docs
- Minimal changes to `endpoint_generator.py`

**Disadvantages**:
- More code in `app.py`
- URL structure changes (breaking change for existing API users)

### Option 2: Multi-Agent Generator

Update `generate_tool_endpoints()` to accept multiple agents:

```python
# viraltracker/api/endpoint_generator.py
def generate_tool_endpoints(
    agents: list[Agent],  # Changed from single agent
    limiter: Limiter,
    auth_dependency: Callable,
    rate_limit: str = "20/minute"
) -> APIRouter:
    router = APIRouter()

    for agent in agents:
        for tool_name, tool in agent._function_toolset.tools.items():
            # Generate endpoint for each tool
            ...

    return router
```

**Advantages**:
- Single router with all tools
- Maintains current URL structure
- Simpler app.py

**Disadvantages**:
- Tool name collisions possible (e.g., if two agents have `search_tool`)
- Less clear organization in API docs
- Harder to control per-agent settings

### Chosen Approach: Option 1 (Multiple Routers)

Rationale:
1. Better API organization
2. Clear separation of concerns
3. No tool name collisions
4. Easier to apply per-agent rate limits
5. Better documentation structure

---

## Implementation Plan

### Step 1: Update app.py Imports

```python
# Change from:
from ..agent.agent import agent

# To:
from ..agent.orchestrator import orchestrator
from ..agent.agents.twitter_agent import twitter_agent
from ..agent.agents.tiktok_agent import tiktok_agent
from ..agent.agents.youtube_agent import youtube_agent
from ..agent.agents.facebook_agent import facebook_agent
from ..agent.agents.analysis_agent import analysis_agent
```

### Step 2: Generate Multiple Routers

```python
# Generate a router for each agent
orchestrator_router = generate_tool_endpoints(orchestrator, limiter, verify_api_key)
twitter_router = generate_tool_endpoints(twitter_agent, limiter, verify_api_key)
tiktok_router = generate_tool_endpoints(tiktok_agent, limiter, verify_api_key)
youtube_router = generate_tool_endpoints(youtube_agent, limiter, verify_api_key)
facebook_router = generate_tool_endpoints(facebook_agent, limiter, verify_api_key)
analysis_router = generate_tool_endpoints(analysis_agent, limiter, verify_api_key)
```

### Step 3: Include All Routers

```python
# Include all routers with proper prefixes and tags
app.include_router(orchestrator_router, prefix="/api/v1/orchestrator", tags=["Orchestrator"])
app.include_router(twitter_router, prefix="/api/v1/twitter", tags=["Twitter"])
app.include_router(tiktok_router, prefix="/api/v1/tiktok", tags=["TikTok"])
app.include_router(youtube_router, prefix="/api/v1/youtube", tags=["YouTube"])
app.include_router(facebook_router, prefix="/api/v1/facebook", tags=["Facebook"])
app.include_router(analysis_router, prefix="/api/v1/analysis", tags=["Analysis"])
```

### Step 4: Maintain Backwards Compatibility (Optional)

Keep existing `/tools/*` endpoints pointing to orchestrator:

```python
# Legacy endpoint for backwards compatibility
app.include_router(orchestrator_router, prefix="/tools", tags=["Tools (Legacy)"])
```

---

## Expected API Structure (After Update)

### Orchestrator Endpoints
- `POST /api/v1/orchestrator/tools/route-to-twitter-agent`
- `POST /api/v1/orchestrator/tools/route-to-tiktok-agent`
- `POST /api/v1/orchestrator/tools/route-to-youtube-agent`
- `POST /api/v1/orchestrator/tools/route-to-facebook-agent`
- `POST /api/v1/orchestrator/tools/route-to-analysis-agent`

### Twitter Endpoints
- `POST /api/v1/twitter/tools/search-twitter-tool`
- `POST /api/v1/twitter/tools/get-top-tweets-tool`
- `POST /api/v1/twitter/tools/export-tweets-tool`
- `POST /api/v1/twitter/tools/find-comment-opportunities-tool`
- `POST /api/v1/twitter/tools/export-comments-tool`
- `POST /api/v1/twitter/tools/analyze-search-term-tool`
- `POST /api/v1/twitter/tools/generate-content-tool`
- `POST /api/v1/twitter/tools/verify-scrape-tool`

### TikTok Endpoints
- `POST /api/v1/tiktok/tools/search-tiktok-tool`
- `POST /api/v1/tiktok/tools/get-top-tiktoks-tool`
- `POST /api/v1/tiktok/tools/export-tiktoks-tool`
- `POST /api/v1/tiktok/tools/find-tiktok-outliers-tool`
- `POST /api/v1/tiktok/tools/analyze-tiktok-hooks-tool`

### YouTube Endpoints
- `POST /api/v1/youtube/tools/search-youtube-tool`

### Facebook Endpoints
- `POST /api/v1/facebook/tools/search-facebook-tool`
- `POST /api/v1/facebook/tools/export-facebook-tool`

### Analysis Endpoints
- `POST /api/v1/analysis/tools/find-outliers-tool`
- `POST /api/v1/analysis/tools/analyze-hooks-tool`
- `POST /api/v1/analysis/tools/generate-twitter-content-tool`

### Legacy Endpoints (Backwards Compatibility)
- `POST /tools/*` → Routes to orchestrator tools only

---

## Testing Plan

### 1. Verify Endpoint Generation

```bash
# Start server
uvicorn viraltracker.api.app:app --reload --port 8000

# Check docs
curl http://localhost:8000/docs
```

**Expected**: Should see 6 endpoint groups (Orchestrator, Twitter, TikTok, YouTube, Facebook, Analysis)

### 2. Test Direct Tool Calls

```bash
# Test Twitter search
curl -X POST "http://localhost:8000/api/v1/twitter/tools/search-twitter-tool" \
  -H "Content-Type: application/json" \
  -d '{"ctx": {...}, "keyword": "AI", "max_results": 10}'

# Test TikTok search
curl -X POST "http://localhost:8000/api/v1/tiktok/tools/search-tiktok-tool" \
  -H "Content-Type: application/json" \
  -d '{"ctx": {...}, "keyword": "viral", "max_results": 10}'
```

### 3. Verify Backwards Compatibility

```bash
# Test legacy orchestrator endpoint
curl -X POST "http://localhost:8000/tools/route-to-twitter-agent" \
  -H "Content-Type: application/json" \
  -d '{"ctx": {...}, "query": "Find AI tweets"}'
```

### 4. Check Tool Count

```python
# Verify all tools registered
from viraltracker.api.app import app

# Count routes
routes = [r for r in app.routes if r.path.startswith("/api/v1/")]
print(f"Total API endpoints: {len(routes)}")
# Expected: 24+ (24 tool endpoints + health/status endpoints)
```

---

## Migration Impact

### Breaking Changes

**URL Structure Change**:
- Old: `POST /tools/search-twitter-tool`
- New: `POST /api/v1/twitter/tools/search-twitter-tool`

**Impact**: External API clients need to update URLs

**Mitigation**:
1. Keep legacy `/tools/*` prefix for orchestrator
2. Add deprecation warnings to legacy endpoints
3. Provide migration guide in API docs
4. Maintain both for 2-3 releases

### Non-Breaking Changes

- `POST /agent/run` endpoint unchanged
- Orchestrator delegation unchanged
- Internal tool calls unchanged
- Database queries unchanged

---

## Benefits

### 1. Complete API Coverage

All 19 platform-specific tools now accessible via direct API calls

### 2. Better API Organization

Clear separation by platform makes API easier to understand and use

### 3. Improved Documentation

FastAPI auto-docs now show all tools grouped by platform

### 4. Enables Direct Tool Access

External systems can call tools directly without going through orchestrator

### 5. Streamlit UI Enhancement

UI can now use direct tool endpoints for faster responses (no orchestrator overhead)

### 6. Better Rate Limiting

Can apply different rate limits per platform/agent

---

## Current Status

- ✅ Problem identified
- ✅ Solution designed
- ✅ Implementation plan created
- 🔄 Checkpoint document created
- ⏭️ app.py update pending
- ⏭️ Testing pending
- ⏭️ Validation pending

---

## Next Steps

1. **Update app.py** (15 minutes)
   - Import all agents
   - Generate routers for each
   - Include all routers with proper prefixes

2. **Test endpoint generation** (10 minutes)
   - Start server
   - Check `/docs` page
   - Verify all 24 endpoints present

3. **Test direct tool calls** (15 minutes)
   - Test one tool per agent
   - Verify responses
   - Check error handling

4. **Update documentation** (10 minutes)
   - Update API docs with new URL structure
   - Add migration guide
   - Update CLAUDE_CODE_GUIDE.md with endpoint examples

5. **Create final checkpoint** (5 minutes)
   - Document completion
   - Update phase status

**Total Estimated Time**: 55 minutes

---

## Files to Modify

### Primary
- `viraltracker/api/app.py` - Add multi-agent router generation

### Secondary (Optional)
- `docs/API_MIGRATION_GUIDE.md` - Document URL changes
- `docs/CLAUDE_CODE_GUIDE.md` - Add endpoint examples
- `viraltracker/ui/app.py` - Update to use direct endpoints

### Testing
- Manual testing via curl
- Check FastAPI docs page
- Verify all endpoints respond

---

## Success Criteria

- ✅ All 6 agents have routers generated
- ✅ 24 total tool endpoints accessible
- ✅ FastAPI docs show all endpoints grouped by agent
- ✅ Direct tool calls work without orchestrator
- ✅ Backwards compatibility maintained for `/tools/*`
- ✅ All existing functionality preserved

---

## Lessons Learned

### What We Discovered

1. **Backwards compatibility layer can hide issues**: The `agent = orchestrator` export in `agent.py` made it non-obvious that only orchestrator tools had endpoints

2. **Endpoint generator already correct**: The `endpoint_generator.py` code was already using Pydantic AI standard (`agent._function_toolset.tools`) - we just weren't passing all agents

3. **Testing gap**: Direct tool endpoints were never tested, only the `/agent/run` endpoint

### Best Practices Reinforced

1. **Always verify generated endpoints**: Check FastAPI docs page after adding tools
2. **Test direct tool access**: Don't rely only on orchestrator delegation
3. **Document API structure**: Clear documentation prevents confusion
4. **Plan for breaking changes**: URL structure changes need migration guides

---

## Related Documentation

- `docs/PHASE_11_CLAUDE_CODE_DOCUMENTATION_COMPLETE.md` - Previous checkpoint
- `docs/PHASE_10_PYDANTIC_AI_CHECKPOINT.md` - Foundation phase
- `docs/REFACTOR_PLAN_PYDANTIC_AI_ALIGNMENT.md` - Overall plan
- `docs/CLAUDE_CODE_GUIDE.md` - AI developer guide
- `viraltracker/api/endpoint_generator.py` - Endpoint generation logic

---

**Branch**: `refactor/pydantic-ai-alignment`
**Status**: Checkpoint created - Ready to update app.py
**Next Action**: Modify `viraltracker/api/app.py` to import and register all agent routers

---
