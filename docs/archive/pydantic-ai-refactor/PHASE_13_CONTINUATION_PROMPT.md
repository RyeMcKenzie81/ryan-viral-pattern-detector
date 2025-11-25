# Phase 13 Continuation Prompt

**Copy and paste this entire prompt into your next Claude Code session to continue the tool migration.**

---

## Context

You are continuing Phase 13 of the Pydantic AI alignment refactor for the ViralTracker project. The planning phase is complete, and you need to execute the migration of 19 tools from `@tool_registry.register()` to `@agent.tool(metadata={...})` pattern.

## Current Status

- **Branch**: `refactor/pydantic-ai-alignment`
- **Latest Commit**: `03cac67` - "docs: Add Phase 12 checkpoint - Multi-agent endpoint generator complete"
- **System Status**: Fully functional with all 24 endpoints operational
- **Phase 12**: ✅ COMPLETE
- **Phase 13**: ⏸️ PAUSED at planning stage

## What You Need to Do

Migrate 19 tools across 5 specialist agents from the old `@tool_registry.register()` pattern to the new Pydantic AI `@agent.tool(metadata={...})` pattern.

### Migration Order (Do in this exact order)

1. ✅ Analysis Agent (3 tools) - START HERE
2. Facebook Agent (2 tools)
3. YouTube Agent (1 tool)
4. TikTok Agent (5 tools)
5. Twitter Agent (8 tools)

### For Each Agent

**Step 1**: Read `docs/PHASE_13_CHECKPOINT.md` to understand the full context

**Step 2**: Read the tools for that agent from `viraltracker/agent/tools_registered.py`

**Step 3**: Read the agent file to understand current structure

**Step 4**: Transform each tool:
- Change `@tool_registry.register(name="x_tool", ...)` to `@agent.tool(metadata={...})`
- Remove `_tool` suffix from function name
- Keep all metadata (category, platform, rate_limit, use_cases, examples)
- Keep function signature and implementation IDENTICAL
- Ensure docstring has Google-style Args/Returns sections

**Step 5**: Add tools directly in the agent file:
- Remove import from `tools_registered`
- Remove old `agent.tool(function)` registration calls
- Tools auto-register via decorator

**Step 6**: Test after EACH agent:
```bash
# Check import works
source venv/bin/activate
python -c "from viraltracker.agent.agents.analysis_agent import analysis_agent; print(f'Tools: {len(analysis_agent._function_tools)}')"

# Restart FastAPI (if running) and check logs
# Should see correct tool count

# Test endpoint
curl -s http://localhost:8000/api/v1/analysis/tools/ | jq .
```

**Step 7**: Create checkpoint if tokens drop below 40k remaining

## Pattern Example

**BEFORE** (in `tools_registered.py`):
```python
@tool_registry.register(
    name="find_outliers_tool",
    description="Find viral outlier tweets",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=["Find top content", "Identify viral tweets"],
    examples=["Show me viral tweets from today"]
)
async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore"
) -> OutlierResult:
    """Find viral outlier tweets using statistical analysis."""
    # implementation...
```

**AFTER** (in `analysis_agent.py`):
```python
@analysis_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': ['Find top content', 'Identify viral tweets'],
        'examples': ['Show me viral tweets from today']
    }
)
async def find_outliers(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore"
) -> OutlierResult:
    """
    Find viral outlier tweets using statistical analysis.

    Uses Z-score or percentile method to identify tweets with
    exceptionally high engagement relative to the dataset.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Statistical threshold (default: 2.0)
        method: 'zscore' or 'percentile' (default: 'zscore')

    Returns:
        OutlierResult model with structured data
    """
    # implementation... (KEEP IDENTICAL)
```

## Critical Rules

### DO:
- ✅ Keep function implementations IDENTICAL
- ✅ Keep all metadata (category, platform, rate_limit, use_cases, examples)
- ✅ Test after EACH agent migration
- ✅ Create checkpoints if tokens running low
- ✅ Commit after each successful agent migration
- ✅ Remove `_tool` suffix from function names

### DON'T:
- ❌ Modify function logic or implementation
- ❌ Change function signatures (parameters, types, defaults)
- ❌ Change return types
- ❌ Skip testing
- ❌ Wait until the end to test everything at once
- ❌ Modify orchestrator.py (it's already correct)

## Tool Inventory

### Analysis Agent (3 tools)
- `find_outliers_tool` → `find_outliers`
- `analyze_hooks_tool` → `analyze_hooks`
- `export_results_tool` → `export_results`

### Facebook Agent (2 tools)
- `search_facebook_ads_tool` → `search_facebook_ads`
- `scrape_facebook_page_ads_tool` → `scrape_facebook_page_ads`

### YouTube Agent (1 tool)
- `search_youtube_tool` → `search_youtube`

### TikTok Agent (5 tools)
- `search_tiktok_tool` → `search_tiktok`
- `search_tiktok_hashtag_tool` → `search_tiktok_hashtag`
- `scrape_tiktok_user_tool` → `scrape_tiktok_user`
- `analyze_tiktok_video_tool` → `analyze_tiktok_video`
- `analyze_tiktok_batch_tool` → `analyze_tiktok_batch`

### Twitter Agent (8 tools)
- `search_twitter_tool` → `search_twitter`
- `get_top_tweets_tool` → `get_top_tweets`
- `export_tweets_tool` → `export_tweets`
- `find_comment_opportunities_tool` → `find_comment_opportunities`
- `export_comments_tool` → `export_comments`
- `analyze_search_term_tool` → `analyze_search_term`
- `generate_content_tool` → `generate_content`
- `verify_scrape_tool` → `verify_scrape`

## Key Files

### Read These First
- `docs/PHASE_13_CHECKPOINT.md` - Complete context and plan
- `docs/REFACTOR_PLAN_PYDANTIC_AI_ALIGNMENT.md` - Original refactor plan
- `viraltracker/agent/tool_metadata.py` - ToolMetadata schema

### Source Files
- `viraltracker/agent/tools_registered.py` - Contains all 19 tools (source)

### Target Files (Add tools here)
- `viraltracker/agent/agents/analysis_agent.py`
- `viraltracker/agent/agents/facebook_agent.py`
- `viraltracker/agent/agents/youtube_agent.py`
- `viraltracker/agent/agents/tiktok_agent.py`
- `viraltracker/agent/agents/twitter_agent.py`

### Remove After Migration Complete
- `viraltracker/agent/tools_registered.py` (backup to `.backup` first)
- `viraltracker/agent/tool_registry.py` (backup to `.backup` first)

## Testing Commands

### After Each Agent
```bash
# Verify import
source venv/bin/activate
python -c "from viraltracker.agent.agents.AGENT_NAME import AGENT_NAME; print(len(AGENT_NAME._function_tools))"

# If FastAPI running, check logs for tool count

# Test endpoint exists
curl -s http://localhost:8000/api/v1/AGENT_NAME/tools/ | jq .
```

### Final Integration Test
```bash
# Test orchestrator can route to agents
curl -X POST "http://localhost:8000/agent/run" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find viral tweets from last 24 hours", "project_name": "test"}'
```

## Success Criteria

- ✅ All 19 tools migrated to `@agent.tool(metadata={...})` pattern
- ✅ All tools co-located in their respective agent files
- ✅ No imports from `tools_registered.py` in agent files
- ✅ All 24 FastAPI endpoints still functional
- ✅ `tools_registered.py` and `tool_registry.py` removed (backed up)
- ✅ All tests passing
- ✅ Documentation updated

## Token Budget

Estimated: 100-120k tokens total
- Analysis: ~15k
- Facebook: ~10k
- YouTube: ~5k
- TikTok: ~20k
- Twitter: ~30k
- Testing: ~10k
- Docs: ~5k
- Buffer: ~15k

## Your First Steps

1. Read `docs/PHASE_13_CHECKPOINT.md`
2. Read Analysis agent tools from `tools_registered.py` (lines 45-431)
3. Read `viraltracker/agent/agents/analysis_agent.py`
4. Begin migration of 3 Analysis tools
5. Test thoroughly
6. Move to next agent

## Important Reminders

- **Test after each agent** - Don't skip this
- **Keep implementations identical** - Only change decorator and name
- **Checkpoint frequently** - If tokens drop below 40k
- **Commit incrementally** - After each agent passes tests
- **Ask questions** - If anything is unclear

---

**Ready to Begin!** Start with Analysis Agent (3 tools) - it's the smallest and will validate your pattern before tackling larger agents.

Good luck! The planning is complete, now it's time to execute systematically.
