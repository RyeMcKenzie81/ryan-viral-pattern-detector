# Pydantic AI Alignment Refactor Plan

**Branch:** `refactor/pydantic-ai-alignment`
**Date:** 2025-01-24
**Objective:** Align ViralTracker's tool registration pattern with Pydantic AI best practices and standards

## Background

Currently, ViralTracker uses a custom `@tool_registry.register()` decorator that:
- Stores tool metadata separately from Pydantic AI
- Requires explicit `name` and `description` parameters
- Uses a custom ToolMetadata dataclass
- Auto-generates FastAPI endpoints from this registry

According to Pydantic AI documentation:
- **Standard pattern:** `@agent.tool` decorator is the recommended approach
- **Docstrings:** Should be the source of tool descriptions (sent to LLM)
- **Metadata:** Built-in `metadata` parameter for custom data (NOT sent to LLM)
- **Tool naming:** Should use clean function names, not `*_tool` suffix convention

## Goals

1. ✅ **Align with Pydantic AI standards** - Use `@agent.tool` decorator
2. ✅ **Use docstrings for descriptions** - Move descriptions from decorator to docstrings
3. ✅ **Use metadata parameter** - Store API-specific data (rate limits, categories) in metadata
4. ✅ **Maintain FastAPI auto-generation** - Update endpoint generator to read from agent tools
5. ✅ **Improve Claude Code readiness** - Standard patterns easier for AI to understand and extend

## Current vs. Target Architecture

### Current Pattern (Non-Standard)
```python
@tool_registry.register(
    name="search_twitter_tool",
    description="Search Twitter for tweets",
    category="Ingestion",
    platform="Twitter",
    rate_limit="20/minute"
)
async def search_twitter_tool(
    ctx: RunContext[AgentDependencies],
    query: str
) -> SearchResult:
    pass
```

### Target Pattern (Pydantic AI Standard)
```python
@twitter_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': ['Search for tweets', 'Monitor brand mentions'],
        'examples': ['Find tweets about AI']
    }
)
async def search_twitter(
    ctx: RunContext[AgentDependencies],
    query: str
) -> SearchResult:
    """
    Search Twitter for tweets matching a keyword.

    Args:
        query: Search term or keyword to find tweets

    Returns:
        SearchResult containing matching tweets
    """
    pass
```

## Implementation Phases

### Phase 0: Setup (5 min)
- [x] Create feature branch
- [x] Document refactor plan

### Phase 1: Foundation (30 min)
- [ ] Create `ToolMetadata` TypedDict schema
- [ ] Backup current implementation

### Phase 2: Refactor Tools by Agent (2-3 hours)
- [ ] Twitter agent (8 tools)
- [ ] TikTok agent (5 tools)
- [ ] YouTube agent (1 tool)
- [ ] Facebook agent (2 tools)
- [ ] Analysis agent (3 tools)

### Phase 3: Update Platform Code (1 hour)
- [ ] Update FastAPI endpoint generator
- [ ] Remove old tool_registry.py
- [ ] Update orchestrator routing

### Phase 4: Testing (30 min)
- [ ] Test agent functionality
- [ ] Test FastAPI endpoints
- [ ] Integration test

### Phase 5: Documentation (1 hour)
- [ ] Create CLAUDE_CODE_GUIDE.md
- [ ] Create tool scaffolding CLI
- [ ] Update TOOL_REGISTRY_GUIDE.md

### Phase 6: Validation (30 min)
- [ ] Run full integration tests
- [ ] Create checkpoint document

## Testing Strategy

**Test after each phase:**
1. After each agent refactor → Verify tools registered
2. After endpoint generator update → Verify endpoints exist
3. Before commit → Full integration test

**No workarounds:**
- If something breaks, fix the root cause
- Don't create temporary patches
- Ask for clarification if needed

## Files to Create

1. `viraltracker/agent/tool_metadata.py` - Metadata schema
2. `viraltracker/cli/scaffold.py` - Tool scaffolding
3. `docs/CLAUDE_CODE_GUIDE.md` - AI guide
4. `docs/PHASE_10_PYDANTIC_AI_ALIGNMENT.md` - Checkpoint

## Files to Modify

1. `viraltracker/agent/agents/twitter_agent.py`
2. `viraltracker/agent/agents/tiktok_agent.py`
3. `viraltracker/agent/agents/youtube_agent.py`
4. `viraltracker/agent/agents/facebook_agent.py`
5. `viraltracker/agent/agents/analysis_agent.py`
6. `viraltracker/api/endpoint_generator.py`
7. `viraltracker/agent/orchestrator.py`
8. `docs/TOOL_REGISTRY_GUIDE.md`

## Files to Remove

1. `viraltracker/agent/tool_registry.py` (backup first)
2. `viraltracker/agent/tools_registered.py` (moved to agent files)

## Rollback Plan

```bash
git checkout main
git branch -D refactor/pydantic-ai-alignment
# Restore from *.backup files if needed
```

## Time Estimate

- Total: 5-6 hours
- Can be completed in single session with breaks

## Success Criteria

- ✅ All 19 tools use `@agent.tool` decorator
- ✅ All tools have proper docstrings (Google format)
- ✅ All tools have metadata dictionaries
- ✅ FastAPI endpoints auto-generate from agent tools
- ✅ All tests passing
- ✅ Documentation updated
- ✅ Claude Code guide created

## Notes

- Context window will compact automatically - work autonomously
- Fix issues properly, don't create workarounds
- Test thoroughly at each step
- Ask for clarification when needed
