# Agent Tools Summary - Task 1.6

**Date:** 2025-11-17
**Status:** ✅ COMPLETE
**Files Created:**
- `viraltracker/agent/tools.py` (~500 lines)
- `test_agent_tools.py` (~450 lines)
- `docs/AGENT_TOOLS_SUMMARY.md` (this file)

---

## Overview

This document summarizes the agent tools layer created for the Pydantic AI agent. The tools wrap the services layer (TwitterService, GeminiService, StatsService) to provide agent-callable functions for viral content analysis.

### Architecture

```
┌─────────────────────────────────────────────────┐
│              Pydantic AI Agent                  │
│         (Task 1.7 - to be created)              │
└────────────┬────────────────────────────────────┘
             │
             │ Calls tools via RunContext
             ▼
┌─────────────────────────────────────────────────┐
│           Agent Tools (Task 1.6) ✅             │
│  - find_outliers_tool()                         │
│  - analyze_hooks_tool()                         │
│  - export_results_tool()                        │
└────────────┬────────────────────────────────────┘
             │
             │ Uses services via ctx.deps
             ▼
┌─────────────────────────────────────────────────┐
│         Services Layer (Tasks 1.1-1.4) ✅       │
│  - TwitterService (database)                    │
│  - GeminiService (AI)                           │
│  - StatsService (calculations)                  │
└─────────────────────────────────────────────────┘
             │
             │ Accesses data
             ▼
┌─────────────────────────────────────────────────┐
│           Data Layer                            │
│  - Supabase (PostgreSQL)                        │
│  - Pydantic models                              │
└─────────────────────────────────────────────────┘
```

---

## Tools Created

### 1. find_outliers_tool()

**Purpose:** Find viral outlier tweets using statistical analysis

**Signature:**
```python
async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore",
    min_views: int = 100,
    text_only: bool = True,
    limit: int = 10
) -> str
```

**Parameters:**
- `ctx` - Pydantic AI run context with AgentDependencies
- `hours_back` - Hours to look back (default: 24)
- `threshold` - Statistical threshold (z-score std devs or percentile %) (default: 2.0)
- `method` - 'zscore' or 'percentile' (default: 'zscore')
- `min_views` - Minimum view count filter (default: 100)
- `text_only` - Only text tweets, no media (default: True)
- `limit` - Max outliers to show in summary (default: 10)

**Returns:** Formatted string summary of outliers with statistics

**Example Output:**
```
Found 5 viral outliers from 1,234 tweets (0.4% success rate)

**Analysis Parameters:**
- Method: zscore
- Threshold: 2.0
- Time Range: Last 24 hours
- Min Views: 100

**Dataset Statistics:**
- Mean Engagement: 150.5
- Median Engagement: 85.0
- Std Dev: 220.3

**Top 5 Viral Tweets:**

1. **[Z=3.2, 99th percentile]**
   @parentingtips (45,000 followers)
   Views: 50,000 | Likes: 2,500 | Replies: 150
   "This is a viral tweet about parenting! 🔥..."
   https://twitter.com/parentingtips/status/1234567890

...
```

**Implementation Details:**
- Fetches tweets via `ctx.deps.twitter.get_tweets()`
- Calculates outliers via `ctx.deps.stats.calculate_zscore_outliers()` or `calculate_percentile_outliers()`
- Marks outliers in database via `ctx.deps.twitter.mark_as_outlier()`
- Returns formatted summary with top N outliers
- Handles edge cases: no tweets, no outliers, errors

---

### 2. analyze_hooks_tool()

**Purpose:** Analyze tweet hooks using AI classification

**Signature:**
```python
async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    limit: int = 20,
    min_views: int = 100
) -> str
```

**Parameters:**
- `ctx` - Pydantic AI run context with AgentDependencies
- `tweet_ids` - Optional list of specific tweet IDs to analyze
- `hours_back` - Hours to look back if no tweet_ids (default: 24)
- `limit` - Max tweets to analyze (default: 20)
- `min_views` - Minimum views for auto-selected tweets (default: 100)

**Returns:** Formatted string summary of hook analysis with patterns

**Example Output:**
```
Analyzing 20 viral tweet hooks...

**Analysis Results:**
- Successfully Analyzed: 18/20 (90%)
- Failed: 2
- Average Confidence: 87%

**Top Hook Types:**
- hot_take: 8 (44%)
- relatable_slice: 5 (28%)
- question_curiosity: 3 (17%)
- validation_permission: 2 (11%)

**Top Emotional Triggers:**
- validation: 10 (56%)
- curiosity: 6 (33%)
- humor: 2 (11%)

**Content Patterns:**
- statement: 12 (67%)
- question: 5 (28%)
- story: 1 (5%)

**Example Analyses:**

1. **hot_take** (95% confidence)
   Trigger: validation
   "Hot take: screen time isn't the enemy, boring parenting is"
   Why it works: This controversial opinion challenges conventional wisdom, making parents feel...

...
```

**Implementation Details:**
- If `tweet_ids` provided: fetches specific tweets via `ctx.deps.twitter.get_tweets_by_ids()`
- Otherwise: finds outliers from recent tweets automatically
- Analyzes each tweet via `ctx.deps.gemini.analyze_hook()`
- Saves analyses to database via `ctx.deps.twitter.save_hook_analysis()`
- Respects rate limiting (built into GeminiService)
- Continues on partial failures (graceful degradation)
- Returns summary with pattern statistics and examples

---

### 3. export_results_tool()

**Purpose:** Export comprehensive analysis report in markdown format

**Signature:**
```python
async def export_results_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    include_hooks: bool = True,
    format: str = "markdown"
) -> str
```

**Parameters:**
- `ctx` - Pydantic AI run context with AgentDependencies
- `hours_back` - Hours to look back (default: 24)
- `threshold` - Outlier threshold (default: 2.0)
- `include_hooks` - Include hook analysis (default: True)
- `format` - Output format, currently only 'markdown' (default: 'markdown')

**Returns:** Markdown-formatted comprehensive analysis report

**Example Output:**
```markdown
# Viral Tweet Analysis Report

**Project:** yakety-pack-instagram
**Period:** Last 24 hours
**Generated:** 2025-11-17 10:30:00

---

# Outlier Detection Report

**Generated:** 2025-11-17 10:30:00

## Summary

- **Total Tweets:** 1,234
- **Outliers Found:** 5 (0.4%)
- **Method:** zscore
- **Threshold:** 2.0

## Engagement Statistics

- **Mean:** 150.5
- **Median:** 85.0
- **Std Dev:** 220.3

## Top Outliers

### 1. @parentingtips (Z-score: 3.20)

**Views:** 50,000 | **Likes:** 2,500 | **Percentile:** 99.2%

> This is a viral tweet about parenting! 🔥

[View Tweet](https://twitter.com/parentingtips/status/1234567890)

...

---

# Hook Analysis Report

**Generated:** 2025-11-17 10:30:30

## Summary

- **Total Analyzed:** 10
- **Successful:** 10 (100%)
- **Average Confidence:** 87%

## Top Hook Types

- **hot_take:** 4 (40%)
- **relatable_slice:** 3 (30%)
- **question_curiosity:** 3 (30%)

...
```

**Implementation Details:**
- Runs outlier detection (reuses logic from tool 1)
- Optionally runs hook analysis on top outliers (reuses logic from tool 2)
- Uses `OutlierResult.to_markdown()` and `HookAnalysisResult.to_markdown()` from models
- Combines into comprehensive report
- Currently supports markdown format (extensible for JSON, CSV, etc.)

---

## Testing

### Test Suite

**File:** `test_agent_tools.py` (~450 lines)

**Test Coverage:**

#### Tool 1: find_outliers_tool
- ✅ Basic functionality with normal data
- ✅ No tweets found
- ✅ No outliers detected
- ✅ Edge cases and error handling

#### Tool 2: analyze_hooks_tool
- ✅ Basic functionality with normal data
- ✅ Specific tweet IDs provided
- ✅ Partial failures (some tweets fail analysis)
- ✅ Edge cases and error handling

#### Tool 3: export_results_tool
- ✅ Basic markdown export with hooks
- ✅ Export without hook analysis
- ✅ Formatting validation
- ✅ Error handling

**Run Tests:**
```bash
cd /Users/ryemckenzie/projects/viraltracker
source venv/bin/activate
python test_agent_tools.py
```

**Test Results:**
```
======================================================================
AGENT TOOLS TEST SUITE - Task 1.6
======================================================================

Total Tests: 8
✅ Passed: 8
❌ Failed: 0

🎉 All tests passed! Agent tools are ready.
```

---

## Implementation Patterns

### 1. Tool Signature Pattern

All tools follow this pattern:
```python
async def tool_name(
    ctx: RunContext[AgentDependencies],  # REQUIRED FIRST PARAM
    param1: type = default,
    param2: type = default,
    ...
) -> str:  # Return string for agent consumption
    """
    Tool description that becomes agent documentation.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        param1: Parameter description
        param2: Parameter description

    Returns:
        Description of return value
    """
    # Implementation
```

**Key Requirements:**
- First parameter MUST be `ctx: RunContext[AgentDependencies]`
- Return type should be `str` for simple agent responses
- Docstring becomes tool description for agent
- Access services via `ctx.deps.service_name`
- Access project config via `ctx.deps.project_name`

### 2. Service Access Pattern

```python
# Access TwitterService
tweets = await ctx.deps.twitter.get_tweets(
    project=ctx.deps.project_name,
    hours_back=hours_back
)

# Access GeminiService
analysis = await ctx.deps.gemini.analyze_hook(
    tweet_text=tweet.text,
    tweet_id=tweet.id
)

# Access StatsService
outliers = ctx.deps.stats.calculate_zscore_outliers(
    values=scores,
    threshold=threshold
)
```

### 3. Error Handling Pattern

```python
try:
    # Main tool logic
    result = await some_operation()
    return formatted_result

except Exception as e:
    logger.error(f"Error in tool_name: {e}", exc_info=True)
    return f"Error: {str(e)}"  # User-friendly error message
```

**Key Principles:**
- Catch exceptions at tool level
- Log errors with stack traces
- Return user-friendly error messages
- Don't crash the agent conversation
- Provide suggestions when appropriate

### 4. Output Formatting Pattern

Tools return formatted strings with:
- Clear headers and sections
- Statistics and summaries
- Examples (top N items)
- Markdown formatting for readability
- Action items or suggestions

---

## Dependencies

### Services Layer (Tasks 1.1-1.4)
- `TwitterService` - Database operations via Supabase
- `GeminiService` - AI hook analysis with rate limiting
- `StatsService` - Statistical calculations (z-score, percentile)

### Models (Task 1.1)
- `Tweet` - Tweet data model
- `HookAnalysis` - Hook analysis result model
- `OutlierTweet` - Outlier tweet with statistics
- `OutlierResult` - Aggregated outlier results
- `HookAnalysisResult` - Aggregated hook analysis results

### Agent Dependencies (Task 1.5)
- `AgentDependencies` - Typed dependency injection container

### External Packages
- `pydantic-ai>=1.18.0` - Agent framework
- Python standard library (`logging`, `collections`, `datetime`)

---

## Usage Examples

### Importing Tools

```python
from viraltracker.agent.tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)
from viraltracker.agent.dependencies import AgentDependencies
from pydantic_ai import RunContext
```

### Creating Mock Context for Testing

```python
from unittest.mock import MagicMock, AsyncMock

# Create mock dependencies
mock_deps = MagicMock(spec=AgentDependencies)
mock_deps.project_name = "test-project"
mock_deps.twitter = AsyncMock()
mock_deps.gemini = AsyncMock()
mock_deps.stats = MagicMock()

# Create mock context
mock_ctx = MagicMock(spec=RunContext)
mock_ctx.deps = mock_deps

# Call tool
result = await find_outliers_tool(mock_ctx, hours_back=24)
```

### Registering Tools with Agent (Task 1.7)

```python
from pydantic_ai import Agent
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.agent.tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)

# Create agent
agent = Agent(
    'openai:gpt-4o',
    deps_type=AgentDependencies
)

# Register tools
agent.tool(find_outliers_tool)
agent.tool(analyze_hooks_tool)
agent.tool(export_results_tool)
```

---

## Performance Considerations

### Rate Limiting

- **GeminiService** has built-in rate limiting (9 req/min default)
- `analyze_hooks_tool` respects this automatically
- For large batches, tool will take time (progress not currently shown)
- **Future improvement:** Add streaming progress updates

### Database Queries

- Tools filter at database level (`min_views`, `text_only`, etc.)
- Efficient for large datasets
- Uses indexed columns (created_at, view_count)
- **Future improvement:** Add caching for repeated queries

### Memory Usage

- Tools process tweets in memory
- For very large datasets (>10K tweets), consider pagination
- **Future improvement:** Add pagination support for large datasets

---

## Next Steps

### Task 1.7: Create Agent Configuration

**File to create:** `viraltracker/agent/agent.py`

**Tasks:**
1. Create Pydantic AI Agent instance
2. Register tools
3. Add system prompt
4. Configure retries and error handling
5. Export agent for use in CLI/UI/API

**Example:**
```python
from pydantic_ai import Agent
from .dependencies import AgentDependencies
from .tools import find_outliers_tool, analyze_hooks_tool, export_results_tool

agent = Agent(
    'openai:gpt-4o',
    deps_type=AgentDependencies,
    retries=2
)

agent.tool(find_outliers_tool)
agent.tool(analyze_hooks_tool)
agent.tool(export_results_tool)

@agent.system_prompt
async def system_prompt(ctx):
    return f"""You are a viral content analysis assistant for {ctx.deps.project_name}..."""
```

---

## Change Log

### 2025-11-17 - Initial Implementation (Task 1.6)
- Created 3 agent tools (find_outliers, analyze_hooks, export_results)
- Implemented comprehensive test suite (8 tests, all passing)
- Integrated with services layer (TwitterService, GeminiService, StatsService)
- Added error handling and graceful degradation
- Documented implementation patterns and usage

---

## Success Criteria

- ✅ **3 working tools** - All tools implemented and functional
- ✅ **Service integration** - Tools successfully call all 3 services
- ✅ **Error handling** - Graceful error handling with user-friendly messages
- ✅ **Testing** - 8 tests covering all tools and edge cases
- ✅ **Documentation** - Complete documentation with examples
- ✅ **Ready for Task 1.7** - Agent can now be configured with these tools

**Status: ✅ COMPLETE - Ready to proceed to Task 1.7 (Agent Configuration)**

---

## Questions / Issues

None at this time. All tools working as expected.

---

## References

- **Migration Plan:** `docs/PYDANTIC_AI_MIGRATION_PLAN.md`
- **Handoff Document:** `docs/HANDOFF_PHASE1_TASK16.md`
- **Services Layer:** `docs/SERVICES_LAYER_SUMMARY.md`
- **Agent Dependencies:** `docs/AGENT_DEPENDENCIES_SUMMARY.md`
- **Pydantic AI Docs:** https://ai.pydantic.dev/

---

**Last Updated:** 2025-11-17
**Author:** Claude Code (Pydantic AI Migration)
**Task:** Phase 1, Task 1.6 - Agent Tools
