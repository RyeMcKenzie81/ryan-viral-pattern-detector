# Phase 13 Checkpoint: Tool Migration Planning Complete

**Date**: November 24, 2025, 4:45 PM
**Branch**: `refactor/pydantic-ai-alignment`
**Status**: ⏸️ PAUSED - Ready for migration in next session
**Token Usage**: 125k/200k (62.5% used in planning phase)

---

## Summary

Phase 13 planning is complete. We analyzed the current tool registration patterns, created a detailed migration plan, and determined that migrating all 19 tools from `@tool_registry.register()` to `@agent.tool(metadata={...})` is feasible but requires a fresh context window to execute efficiently.

## What Was Accomplished

### ✅ Analysis Complete
- **Identified tool registration patterns**:
  - Orchestrator: 5 routing tools using `@orchestrator.tool` (CORRECT - no migration needed)
  - Specialist agents: 19 tools using `@tool_registry.register()` (NEEDS MIGRATION)
- **Verified ToolMetadata schema exists** at `viraltracker/agent/tool_metadata.py`
- **Confirmed Phase 12 success**: All 24 endpoints functional via FastAPI

### ✅ Migration Plan Created
**Migration order** (smallest to largest for incremental validation):
1. Analysis Agent (3 tools: find_outliers, analyze_hooks, export_results)
2. Facebook Agent (2 tools: search_ads, scrape_page_ads)
3. YouTube Agent (1 tool: search_youtube)
4. TikTok Agent (5 tools: search, search_hashtag, scrape_user, analyze_video, analyze_batch)
5. Twitter Agent (8 tools: search, get_top_tweets, export_tweets, find_opportunities, export_comments, analyze_term, generate_content, verify_scrape)

**Total scope**: 19 tools across ~1,760 lines of code

### ✅ Pattern Documented

**OLD PATTERN** (in `tools_registered.py`):
```python
@tool_registry.register(
    name="find_outliers_tool",
    description="Find viral outlier tweets using statistical analysis",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[...],
    examples=[...]
)
async def find_outliers_tool(ctx: RunContext[AgentDependencies], ...) -> OutlierResult:
    """Find viral outlier tweets using statistical analysis."""
    ...
```

**NEW PATTERN** (in `analysis_agent.py`):
```python
@analysis_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [...],
        'examples': [...]
    }
)
async def find_outliers(ctx: RunContext[AgentDependencies], ...) -> OutlierResult:
    """
    Find viral outlier tweets using statistical analysis.

    Uses Z-score or percentile method to identify tweets with
    exceptionally high engagement relative to the dataset.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        ...

    Returns:
        OutlierResult model with structured data and markdown export
    """
    ...
```

## Current State

### System Status
- ✅ **Fully functional** - All 24 tool endpoints working
- ✅ **Phase 12 complete** - Multi-agent endpoint generator operational
- ✅ **Branch clean** - All changes committed to `refactor/pydantic-ai-alignment`
- ✅ **Latest commit**: `03cac67` - "docs: Add Phase 12 checkpoint - Multi-agent endpoint generator complete"

### Architecture
**Current (Hybrid)**:
- Orchestrator: 5 tools using `@orchestrator.tool` ✅
- Specialists: 19 tools using `@tool_registry.register()` ❌
- Agents import tools from `tools_registered.py` then register with `.tool()`

**Target (Pydantic AI Standard)**:
- Orchestrator: 5 tools using `@orchestrator.tool` ✅ (already correct)
- Specialists: 19 tools using `@agent.tool(metadata={...})` directly in agent files
- All tools co-located with their agents
- Remove `tools_registered.py` and `tool_registry.py`

## Files to Modify in Next Session

### Agent Files (Add tools directly)
1. `viraltracker/agent/agents/analysis_agent.py` - Add 3 tools
2. `viraltracker/agent/agents/facebook_agent.py` - Add 2 tools
3. `viraltracker/agent/agents/youtube_agent.py` - Add 1 tool
4. `viraltracker/agent/agents/tiktok_agent.py` - Add 5 tools
5. `viraltracker/agent/agents/twitter_agent.py` - Add 8 tools

### Files to Remove (After migration)
1. `viraltracker/agent/tools_registered.py` - Contains all 19 tools
2. `viraltracker/agent/tool_registry.py` - Old registration system

### Testing After Each Agent
- Import agent module to verify no syntax errors
- Check FastAPI endpoint generation
- Verify tool count matches expected
- Run simple agent query to test tool functionality

## Migration Steps for Next Session

### Step-by-Step Process

**For each agent** (in order: Analysis → Facebook → YouTube → TikTok → Twitter):

1. **Read tools** from `tools_registered.py` for that agent
2. **Transform pattern**:
   - Remove `@tool_registry.register()` decorator
   - Add `@agent.tool(metadata={...})` decorator
   - Keep function signature and implementation identical
   - Move to agent file
3. **Update imports** in agent file:
   - Remove imports from `tools_registered`
   - Add any missing imports (Optional, List, etc.)
   - Add import for ToolMetadata schema
4. **Remove old registration**:
   - Remove `agent.tool(old_function)` calls
   - Tools now auto-register via decorator
5. **Test**:
   - Run Python import check
   - Check FastAPI logs for tool count
   - Verify endpoint exists in `/docs`
6. **Checkpoint** if tokens running low

### Example: Analysis Agent Migration

**Before** (current):
```python
# In analysis_agent.py
from ..tools_registered import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)

# Register tools
analysis_agent.tool(find_outliers_tool)
analysis_agent.tool(analyze_hooks_tool)
analysis_agent.tool(export_results_tool)
```

**After** (target):
```python
# In analysis_agent.py
from typing import Optional, List
from pydantic_ai import RunContext
from ..tool_metadata import ToolMetadata
from ..dependencies import AgentDependencies
from ...services.models import OutlierResult, HookAnalysisResult

@analysis_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': ['Find top performing content', ...],
        'examples': ['Show me viral tweets from today', ...]
    }
)
async def find_outliers(ctx: RunContext[AgentDependencies], ...) -> OutlierResult:
    """
    Find viral outlier tweets using statistical analysis.

    Uses Z-score or percentile method to identify tweets with
    exceptionally high engagement relative to the dataset.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Statistical threshold (default: 2.0)
        method: 'zscore' or 'percentile' (default: 'zscore')
        ...

    Returns:
        OutlierResult model with structured data
    """
    # [Implementation stays the same]
    ...

# Repeat for analyze_hooks and export_results
```

## Key Decisions Made

1. **Use Pydantic AI native metadata parameter** - Preserves all metadata (category, platform, rate_limit, use_cases, examples)
2. **Remove `_tool` suffix from function names** - Align with Pydantic AI naming conventions
3. **Keep docstrings verbose** - They're sent to the LLM, so keep detailed
4. **Co-locate tools with agents** - Better organization, easier to find
5. **Migrate incrementally** - Test after each agent to catch issues early

## Testing Strategy

### After Each Agent Migration
```bash
# 1. Check Python can import
source venv/bin/activate
python -c "from viraltracker.agent.agents.analysis_agent import analysis_agent; print(f'Tools: {len(analysis_agent._function_tools)}')"

# 2. Restart FastAPI and check logs
# Should see: "Analysis: 3 tools"

# 3. Check /docs endpoint
curl -s http://localhost:8000/api/v1/analysis/tools/ | jq .
```

### Final Integration Test
```bash
# After all migrations complete
curl -X POST "http://localhost:8000/agent/run" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find viral tweets from last 24 hours", "project_name": "test"}'
```

## Token Budget for Next Session

**Estimated requirements**:
- Analysis agent (3 tools): ~15k tokens
- Facebook agent (2 tools): ~10k tokens
- YouTube agent (1 tool): ~5k tokens
- TikTok agent (5 tools): ~20k tokens
- Twitter agent (8 tools): ~30k tokens
- Testing & validation: ~10k tokens
- Documentation: ~5k tokens
- **Total**: ~95k tokens

**Recommendation**: Budget 100-120k tokens for full migration

## Important Notes

### DO NOT Modify
- Tool function signatures (parameters, types)
- Tool implementation logic
- Return types
- Error handling

### DO Modify
- Decorator (from `@tool_registry.register()` to `@agent.tool(metadata={...})`)
- Function names (remove `_tool` suffix)
- Docstring formatting (add Args/Returns sections if missing)
- File location (move from `tools_registered.py` to agent files)

### Critical Reminders
- **Test after each agent** - Don't wait until end
- **Check FastAPI logs** - Verify tool counts
- **Keep backup** - `tools_registered.py` can be renamed to `.backup` first
- **Commit incrementally** - After each agent migration + test

## Success Criteria

- ✅ All 19 tools migrated to `@agent.tool(metadata={...})` pattern
- ✅ All tools co-located in their respective agent files
- ✅ All FastAPI endpoints still functional (24 total)
- ✅ `tools_registered.py` and `tool_registry.py` removed
- ✅ All tests passing
- ✅ Documentation updated

## Next Steps

1. **Start new Claude Code session**
2. **Use continuation prompt** (see below)
3. **Begin with Analysis agent** (smallest, easiest)
4. **Test thoroughly** after each agent
5. **Create checkpoints** if needed
6. **Complete Phase 13** with final documentation

---

**Phase 13 Status**: ⏸️ PAUSED - Ready to execute in next session
**Overall Refactor**: ~85% complete (functionally 100%, cleanup pending)
**System Status**: Fully operational
