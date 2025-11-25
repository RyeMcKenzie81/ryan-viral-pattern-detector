# Claude Code Developer Guide - ViralTracker Tool Development

**Version**: 2.0.0
**Date**: 2025-01-24
**Target**: AI-assisted development with Claude Code
**Status**: Pydantic AI Alignment Complete

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Creating New Tools](#creating-new-tools)
4. [Pydantic AI Best Practices](#pydantic-ai-best-practices)
5. [Tool Development Patterns](#tool-development-patterns)
6. [Testing and Validation](#testing-and-validation)
7. [Common Pitfalls](#common-pitfalls)
8. [Migration Guide](#migration-guide)
9. [File Location Reference](#file-location-reference)

---

## Quick Start

### For Claude Code: How to Create a Tool

When asked to create a new agent tool, follow this checklist:

**Step 1: Understand the requirement**
- [ ] Identify the platform (Twitter, TikTok, YouTube, Facebook, Analysis)
- [ ] Identify the pipeline stage (Routing, Ingestion, Filtration, Discovery, Analysis, Generation, Export)
- [ ] Determine which agent this tool belongs to

**Step 2: Create the tool function**
- [ ] Add to `viraltracker/agent/tools_registered.py`
- [ ] Use `@tool_registry.register()` decorator
- [ ] Include comprehensive docstring (Google format)
- [ ] Add ToolMetadata with proper categorization

**Step 3: Register with agent**
- [ ] Import tool in agent file (e.g., `agents/twitter_agent.py`)
- [ ] Call `agent.tool(your_tool_function)`
- [ ] Verify tool count in agent initialization log

**Step 4: Test**
- [ ] Test via Python: Import and check `agent._function_toolset.tools`
- [ ] Test via API: Check endpoint appears at `/tools/{tool-name}`
- [ ] Test via CLI: Run agent with natural language query

---

## Architecture Overview

### System Structure

```
ViralTracker (Pydantic AI Multi-Agent System)
│
├── Orchestrator Agent (routes to specialists)
│   └── Routing Tools: route_to_{platform}_agent()
│
├── Platform Agents (specialists)
│   ├── Twitter Agent (8 tools)
│   ├── TikTok Agent (5 tools)
│   ├── YouTube Agent (1 tool)
│   ├── Facebook Agent (2 tools)
│   └── Analysis Agent (3 tools)
│
└── Tool Registry (auto-generates API endpoints)
    └── FastAPI Router: POST /tools/{tool-name}
```

### Pipeline Stages (Categories)

1. **Routing** - Orchestrator directing requests
2. **Ingestion** - Data collection from platforms (scraping, API calls)
3. **Filtration** - Data filtering, preprocessing, quality checks
4. **Discovery** - Pattern detection, outlier analysis, statistical methods
5. **Analysis** - Deep analysis (hooks, sentiment, AI-powered insights)
6. **Generation** - Content generation, comment creation
7. **Export** - Data export, reporting, file creation

### Key Insight: Two-Phase Tool Pattern

ViralTracker uses a **hybrid pattern** during Pydantic AI alignment:

**Current (Transition) Pattern**:
```python
# 1. Define in tools_registered.py with custom registry
@tool_registry.register(
    name="my_tool",
    description="...",
    category="Ingestion",
    platform="Twitter"
)
async def my_tool(ctx, param: str):
    """Docstring sent to LLM"""
    pass

# 2. Register with agent in agent file
from ..tools_registered import my_tool
twitter_agent.tool(my_tool)
```

**Target (Pydantic AI Standard) Pattern**:
```python
# Define directly with agent decorator + metadata
@twitter_agent.tool(
    metadata=ToolMetadata(
        category='Ingestion',
        platform='Twitter',
        rate_limit='20/minute',
        use_cases=['Search tweets'],
        examples=['Find tweets about AI']
    )
)
async def search_twitter(ctx, keyword: str):
    """
    Search Twitter for tweets matching a keyword.

    Args:
        keyword: Search term to find tweets

    Returns:
        SearchResult containing matching tweets
    """
    pass
```

**When to use which**:
- **New tools**: Use current pattern until migration complete
- **After migration**: Use target pattern exclusively
- **Check**: Read `docs/PHASE_10_PYDANTIC_AI_CHECKPOINT.md` for current status

---

## Creating New Tools

### Template: Complete Tool Implementation

```python
# File: viraltracker/agent/tools_registered.py

from typing import Optional, List
from pydantic_ai import RunContext
from .dependencies import AgentDependencies
from .tool_registry import tool_registry
from ..services.models import YourResultModel

@tool_registry.register(
    name="your_tool_name_tool",  # Suffix with _tool for now
    description="One-line description of what this tool does",
    category="Ingestion",  # Or: Routing, Filtration, Discovery, Analysis, Generation, Export
    platform="Twitter",    # Or: TikTok, YouTube, Facebook, Instagram, All
    rate_limit="20/minute",  # Adjust based on cost/speed
    use_cases=[
        "Use case 1 - when to use this tool",
        "Use case 2 - another scenario",
        "Use case 3 - specific application"
    ],
    examples=[
        "Example natural language query 1",
        "Example natural language query 2",
        "Example natural language query 3"
    ]
)
async def your_tool_name_tool(
    ctx: RunContext[AgentDependencies],
    required_param: str,
    optional_param: int = 10,
    another_param: bool = True
) -> YourResultModel:
    """
    Detailed description of what this tool does.

    This docstring is sent to the LLM and helps it decide when to use
    this tool. Be clear and specific about:
    - What the tool does
    - When to use it
    - What it returns

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        required_param: Description of this required parameter
        optional_param: Description of optional parameter (default: 10)
        another_param: Boolean flag description (default: True)

    Returns:
        YourResultModel containing the results with structured data

    Raises:
        ValueError: If required_param is invalid
        Exception: Other errors with descriptive messages
    """
    try:
        logger.info(f"Tool starting: param={required_param}")

        # Access services via ctx.deps
        result = await ctx.deps.twitter.some_method(required_param)

        # Process data
        processed = process_data(result)

        # Return structured model
        return YourResultModel(
            data=processed,
            count=len(processed),
            message="Successfully processed"
        )

    except Exception as e:
        logger.error(f"Tool failed: {str(e)}")
        raise Exception(f"Failed to execute tool: {str(e)}")
```

### Step-by-Step: Adding to Agent

```python
# File: viraltracker/agent/agents/twitter_agent.py

# 1. Add import at top
from ..tools_registered import (
    search_twitter_tool,
    # ... existing tools ...
    your_tool_name_tool  # NEW
)

# 2. Register with agent (bottom of file, before logger.info)
twitter_agent.tool(your_tool_name_tool)

# 3. Update tool count in logger message
logger.info("Twitter Agent initialized with 9 tools")  # Was 8, now 9
```

---

## Pydantic AI Best Practices

### Critical Rules for Pydantic AI Alignment

**✅ DO:**
1. **Use docstrings for LLM communication**
   - Docstrings ARE sent to the LLM
   - Be clear about what the tool does
   - Use Google-style docstring format
   - Include Args, Returns, Raises sections

2. **Use metadata for system configuration**
   - Metadata is NOT sent to LLM
   - Store rate limits, categories, API config
   - Use ToolMetadata TypedDict schema

3. **Use `@agent.tool()` decorator**
   - Current: `agent.tool(function_name)` after import
   - Target: `@agent.tool()` decorator on function
   - Both patterns work with Pydantic AI

4. **Access dependencies via `ctx.deps`**
   ```python
   async def my_tool(ctx: RunContext[AgentDependencies], ...):
       # Access services
       result = await ctx.deps.twitter.search(...)
       project = ctx.deps.project_name
       gemini = ctx.deps.gemini
   ```

5. **Return structured Pydantic models**
   ```python
   from ..services.models import SearchResult

   async def search_tool(...) -> SearchResult:
       return SearchResult(
           tweets=[...],
           total_count=42,
           query_metadata={...}
       )
   ```

**❌ DON'T:**
1. **Don't put LLM instructions in metadata**
   - Metadata is for system config only
   - Use docstrings for LLM communication

2. **Don't use `_tool` suffix in target pattern**
   - Current: `search_twitter_tool` (OK during migration)
   - Target: `search_twitter` (clean function name)

3. **Don't duplicate parameter descriptions**
   - Put descriptions in docstring Args section
   - Decorator metadata is for rate limits/categories

4. **Don't skip type hints**
   - Always type hint parameters
   - Always type hint return values
   - Pydantic uses these for validation

5. **Don't create circular imports**
   - Tools in `tools_registered.py`
   - Agents in `agents/*.py`
   - Import tools into agents, not vice versa

### Docstring Format (Google Style)

```python
async def example_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    limit: int = 50,
    include_media: bool = False
) -> SearchResult:
    """
    Search for content matching a keyword.

    This tool searches the platform for posts matching the given keyword
    and returns up to the specified limit. Media can be optionally included.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search term or phrase to find matching content
        limit: Maximum number of results to return (default: 50)
        include_media: Whether to include posts with media (default: False)

    Returns:
        SearchResult containing matching posts with engagement metrics,
        total count, and query metadata

    Raises:
        ValueError: If keyword is empty or limit is invalid
        APIError: If platform API request fails

    Examples:
        # Search for AI content
        result = await example_tool(ctx, keyword="artificial intelligence")

        # Limited search without media
        result = await example_tool(ctx, keyword="python", limit=20)
    """
    pass
```

---

## Tool Development Patterns

### Pattern 1: Ingestion Tool (API Scraping)

```python
@tool_registry.register(
    name="scrape_platform_tool",
    description="Scrape data from external platform API",
    category="Ingestion",
    platform="Twitter",
    rate_limit="10/minute",  # Lower for expensive API calls
    use_cases=[
        "Collect fresh data from platform",
        "Search by keyword or hashtag",
        "Save results to database"
    ]
)
async def scrape_platform_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    max_results: int = 100
) -> ScrapeResult:
    """Scrape platform for keyword and save to database."""
    try:
        # 1. Call external API
        data = await ctx.deps.twitter.search(
            keyword=keyword,
            max_results=max_results,
            project=ctx.deps.project_name
        )

        # 2. Save to database (usually done by service)
        # Data is typically saved by the service method

        # 3. Return results
        return ScrapeResult(
            items_collected=len(data),
            keyword=keyword,
            timestamp=datetime.now()
        )
    except Exception as e:
        logger.error(f"Scrape failed: {str(e)}")
        raise
```

### Pattern 2: Analysis Tool (Database Query + AI)

```python
@tool_registry.register(
    name="analyze_content_tool",
    description="Analyze content using AI and statistical methods",
    category="Analysis",
    platform="Twitter",
    rate_limit="5/minute",  # Lower for AI-powered tools
    use_cases=[
        "Find patterns in viral content",
        "Extract insights from hooks",
        "Generate analysis reports"
    ]
)
async def analyze_content_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    limit: int = 20
) -> AnalysisResult:
    """Analyze recent content for patterns and insights."""
    try:
        # 1. Query database
        content = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back
        )

        # 2. Statistical analysis
        outliers = find_outliers(content, threshold=2.0)

        # 3. AI analysis
        insights = await ctx.deps.gemini.analyze_batch(
            items=outliers[:limit],
            prompt="Analyze viral patterns..."
        )

        # 4. Return structured results
        return AnalysisResult(
            total_analyzed=len(content),
            outliers_found=len(outliers),
            insights=insights
        )
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        raise
```

### Pattern 3: Export Tool (File Generation)

```python
@tool_registry.register(
    name="export_data_tool",
    description="Export data to file formats (CSV, JSON, Markdown)",
    category="Export",
    platform="All",
    rate_limit="30/minute",  # Higher for fast operations
    use_cases=[
        "Export data to CSV for analysis",
        "Generate reports in Markdown",
        "Save results to JSON"
    ]
)
async def export_data_tool(
    ctx: RunContext[AgentDependencies],
    format: str = "csv",
    hours_back: int = 24,
    output_path: Optional[str] = None
) -> ExportResult:
    """Export data to specified format."""
    try:
        # 1. Fetch data
        data = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back
        )

        # 2. Generate file path
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"~/Downloads/export_{timestamp}.{format}"
        output_path = os.path.expanduser(output_path)

        # 3. Export based on format
        if format == "csv":
            df = pd.DataFrame(data)
            df.to_csv(output_path, index=False)
        elif format == "json":
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)

        # 4. Return results
        return ExportResult(
            file_path=output_path,
            records_exported=len(data),
            format=format
        )
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        raise
```

### Pattern 4: Routing Tool (Orchestrator)

```python
# File: viraltracker/agent/orchestrator.py

@orchestrator.tool
async def route_to_twitter_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route request to Twitter Agent for Twitter/X operations.

    Use this when the user wants to:
    - Search or scrape tweets
    - Analyze Twitter data
    - Find comment opportunities
    - Generate Twitter content

    Args:
        ctx: Run context with dependencies
        query: The user's request to route to Twitter Agent

    Returns:
        String result from Twitter Agent execution
    """
    logger.info(f"Routing to Twitter Agent: {query}")
    result = await twitter_agent.run(query, deps=ctx.deps)
    return result.output
```

---

## Testing and Validation

### Test Checklist

**After creating a tool, verify:**

1. **Tool registration**
   ```bash
   source venv/bin/activate
   python -c "
   from viraltracker.agent.agents.twitter_agent import twitter_agent
   tools = twitter_agent._function_toolset.tools
   print(f'Total tools: {len(tools)}')
   print('Tools:', [t.name for t in tools])
   "
   ```

2. **API endpoint generation**
   ```bash
   # Start API
   uvicorn viraltracker.api.app:app --reload --port 8000

   # Check endpoint exists
   curl http://localhost:8000/tools | jq '.tools | keys'

   # Test the tool
   curl -X POST http://localhost:8000/tools/your-tool-name \
     -H "Content-Type: application/json" \
     -d '{"project_name": "test", "param": "value"}'
   ```

3. **Agent integration test**
   ```bash
   # Test via CLI
   source venv/bin/activate
   python -m viraltracker.cli.main chat \
     --project yakety-pack-instagram

   # In chat, try:
   # "Use the your_tool_name to do X"
   ```

4. **Type checking**
   ```bash
   # If mypy is configured
   mypy viraltracker/agent/tools_registered.py
   ```

### Common Test Scenarios

```python
# tests/test_tools.py (example)
import pytest
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.agent.tools_registered import your_tool_name_tool
from pydantic_ai import RunContext

@pytest.mark.asyncio
async def test_your_tool_basic():
    """Test tool with basic parameters."""
    # Setup
    deps = AgentDependencies(
        project_name="test-project",
        twitter=mock_twitter_service,
        gemini=mock_gemini_service
    )
    ctx = RunContext(deps=deps, ...)

    # Execute
    result = await your_tool_name_tool(
        ctx=ctx,
        required_param="test",
        optional_param=20
    )

    # Assert
    assert result.count > 0
    assert result.message == "Successfully processed"

@pytest.mark.asyncio
async def test_your_tool_error_handling():
    """Test tool handles errors gracefully."""
    deps = AgentDependencies(...)
    ctx = RunContext(deps=deps, ...)

    with pytest.raises(ValueError):
        await your_tool_name_tool(ctx=ctx, required_param="")
```

---

## Common Pitfalls

### Pitfall 1: Incorrect Docstring Format

**❌ Wrong:**
```python
async def my_tool(ctx, keyword: str):
    """Does a search"""  # Too brief, no Args/Returns
    pass
```

**✅ Correct:**
```python
async def my_tool(ctx, keyword: str) -> SearchResult:
    """
    Search platform for content matching keyword.

    Args:
        ctx: Run context with AgentDependencies
        keyword: Search term to find matching content

    Returns:
        SearchResult with matching items and metadata
    """
    pass
```

### Pitfall 2: Forgetting to Register with Agent

**❌ Wrong:**
```python
# Created tool in tools_registered.py but didn't add to agent
# Tool won't be available to agent!
```

**✅ Correct:**
```python
# agents/twitter_agent.py
from ..tools_registered import my_new_tool
twitter_agent.tool(my_new_tool)  # Register it!
```

### Pitfall 3: Incorrect Rate Limit

**❌ Wrong:**
```python
@tool_registry.register(
    rate_limit="100/minute"  # Too high for expensive AI call!
)
async def expensive_ai_analysis(...):
    result = await ctx.deps.gemini.analyze(...)  # $$$
```

**✅ Correct:**
```python
@tool_registry.register(
    rate_limit="5/minute"  # Appropriate for costly operation
)
async def expensive_ai_analysis(...):
    result = await ctx.deps.gemini.analyze(...)
```

### Pitfall 4: Not Using Type Hints

**❌ Wrong:**
```python
async def my_tool(ctx, keyword, limit=50):  # No types!
    pass
```

**✅ Correct:**
```python
async def my_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    limit: int = 50
) -> SearchResult:
    pass
```

### Pitfall 5: Circular Imports

**❌ Wrong:**
```python
# agents/twitter_agent.py
from ..tools_registered import my_tool

# tools_registered.py
from .agents.twitter_agent import twitter_agent  # CIRCULAR!
```

**✅ Correct:**
```python
# agents/twitter_agent.py
from ..tools_registered import my_tool  # Import tools

# tools_registered.py
# Don't import agents! Only dependencies and models.
```

---

## Migration Guide

### Current State (Transition Phase)

We are in the middle of Pydantic AI alignment. Current pattern:

```python
# tools_registered.py - Old registry pattern
@tool_registry.register(name="...", description="...")
async def my_tool_tool(ctx, ...):
    pass

# agents/twitter_agent.py - Still register separately
twitter_agent.tool(my_tool_tool)
```

### Target State (Pydantic AI Standard)

After migration completes:

```python
# agents/twitter_agent.py - Tools defined in agent file
@twitter_agent.tool(
    metadata=ToolMetadata(
        category='Ingestion',
        platform='Twitter',
        rate_limit='20/minute'
    )
)
async def search_twitter(ctx, keyword: str):
    """Search Twitter for keyword."""
    pass
```

### When Creating New Tools

**Option A: Follow current pattern** (Recommended until migration complete)
- Add to `tools_registered.py` with `@tool_registry.register()`
- Import and register in agent file
- Easier to migrate later

**Option B: Use target pattern** (Advanced)
- Define directly in agent file with `@agent.tool(metadata=...)`
- Requires updating FastAPI endpoint generator first
- See `docs/REFACTOR_PLAN_PYDANTIC_AI_ALIGNMENT.md`

**Check migration status:**
```bash
cat docs/PHASE_10_PYDANTIC_AI_CHECKPOINT.md
```

---

## File Location Reference

### Where to Find Things

```
viraltracker/
├── agent/
│   ├── orchestrator.py           # Orchestrator agent (routing)
│   ├── dependencies.py           # AgentDependencies definition
│   ├── tool_registry.py          # Custom registry (to be removed)
│   ├── tool_metadata.py          # ToolMetadata TypedDict schema ✅ NEW
│   ├── tools_registered.py       # Current tool definitions
│   │
│   └── agents/                   # Specialized agents
│       ├── twitter_agent.py      # Twitter/X specialist (8 tools)
│       ├── tiktok_agent.py       # TikTok specialist (5 tools)
│       ├── youtube_agent.py      # YouTube specialist (1 tool)
│       ├── facebook_agent.py     # Facebook specialist (2 tools)
│       └── analysis_agent.py     # Analysis specialist (3 tools)
│
├── api/
│   ├── app.py                    # Main FastAPI application
│   └── endpoint_generator.py    # Auto-generates /tools/* endpoints
│
├── services/
│   ├── twitter.py                # TwitterService
│   ├── tiktok.py                 # TikTokService
│   ├── youtube.py                # YouTubeService
│   ├── gemini.py                 # GeminiService (AI)
│   └── models.py                 # Pydantic result models
│
└── cli/
    └── main.py                   # CLI commands and chat interface

docs/
├── CLAUDE_CODE_GUIDE.md          # This file
├── TOOL_REGISTRY_GUIDE.md        # Registry system docs
├── PHASE_10_PYDANTIC_AI_CHECKPOINT.md  # Migration checkpoint
└── REFACTOR_PLAN_PYDANTIC_AI_ALIGNMENT.md  # Full refactor plan
```

### Quick Reference: Import Paths

```python
# Creating a tool
from pydantic_ai import RunContext
from .dependencies import AgentDependencies
from .tool_registry import tool_registry
from ..services.models import YourResultModel

# Accessing services
ctx.deps.twitter      # TwitterService
ctx.deps.tiktok       # TikTokService
ctx.deps.youtube      # YouTubeService
ctx.deps.facebook     # FacebookService
ctx.deps.gemini       # GeminiService
ctx.deps.project_name # Current project name

# Tool metadata (target pattern)
from .tool_metadata import ToolMetadata, create_tool_metadata
```

---

## Examples from Codebase

### Real Tool: find_outliers_tool

```python
@tool_registry.register(
    name="find_outliers_tool",
    description="Find viral outlier tweets using statistical analysis",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Find top performing content",
        "Identify viral tweets",
        "Discover engagement patterns",
        "Track statistical outliers"
    ],
    examples=[
        "Show me viral tweets from today",
        "Find top performers from last 48 hours",
        "What tweets are outliers this week?"
    ]
)
async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore",
    min_views: int = 100,
    text_only: bool = True,
    limit: int = 10
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
        min_views: Minimum view count filter (default: 100)
        text_only: Only include text tweets (default: True)
        limit: Max outliers to return (default: 10)

    Returns:
        OutlierResult model with structured data and markdown export
    """
    try:
        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=text_only
        )

        # Statistical analysis
        if method == "zscore":
            outliers = find_zscore_outliers(tweets, threshold)
        else:
            outliers = find_percentile_outliers(tweets, threshold)

        # Return results
        return OutlierResult(
            outliers=outliers[:limit],
            total_analyzed=len(tweets),
            method=method
        )
    except Exception as e:
        logger.error(f"Outlier detection failed: {str(e)}")
        raise
```

### Real Agent: twitter_agent.py

```python
"""Twitter/X Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import Twitter-specific tools
from ..tools_registered import (
    search_twitter_tool,
    get_top_tweets_tool,
    export_tweets_tool,
    find_comment_opportunities_tool,
    export_comments_tool,
    analyze_search_term_tool,
    generate_content_tool,
    verify_scrape_tool
)

logger = logging.getLogger(__name__)

# Create Twitter specialist agent
twitter_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Twitter/X platform specialist agent.

Your ONLY responsibility is Twitter/X data operations:
- Searching and scraping tweets by keyword
- Querying database for top tweets by engagement
- Finding comment opportunities on viral tweets
- Analyzing search term performance
- Generating content from viral hooks
- Verifying scrape results
- Exporting tweet and comment data to files
"""
)

# Register tools
twitter_agent.tool(search_twitter_tool)
twitter_agent.tool(get_top_tweets_tool)
twitter_agent.tool(export_tweets_tool)
twitter_agent.tool(find_comment_opportunities_tool)
twitter_agent.tool(export_comments_tool)
twitter_agent.tool(analyze_search_term_tool)
twitter_agent.tool(generate_content_tool)
twitter_agent.tool(verify_scrape_tool)

logger.info("Twitter Agent initialized with 8 tools")
```

---

## AI Assistant Instructions

### When Asked to Create a Tool

1. **Gather requirements**:
   - What does the tool do?
   - Which platform? (Twitter, TikTok, YouTube, Facebook, All)
   - Which category? (Ingestion, Analysis, Export, etc.)
   - What parameters are needed?
   - What should it return?

2. **Choose the right pattern**:
   - Check `docs/PHASE_10_PYDANTIC_AI_CHECKPOINT.md` for current state
   - Use current pattern unless instructed otherwise

3. **Write comprehensive code**:
   - Complete docstring (Google format)
   - Proper type hints
   - Error handling
   - Logging
   - Return structured models

4. **Register properly**:
   - Add to `tools_registered.py`
   - Import in appropriate agent file
   - Call `agent.tool(your_tool)`
   - Update tool count in logger

5. **Test immediately**:
   - Verify tool registered
   - Check API endpoint
   - Test with sample query

6. **Document**:
   - Update checkpoint if needed
   - Note any blockers
   - Provide usage examples

### When Something Doesn't Work

1. **Don't create workarounds**
   - Fix the root cause
   - Ask user for clarification if needed

2. **Check common issues**:
   - Circular import?
   - Tool not registered with agent?
   - Incorrect type hints?
   - Missing docstring sections?

3. **Validate against patterns**:
   - Compare with working tools in codebase
   - Check `tools_registered.py` for examples
   - Review agent registration in agent files

---

## Rate Limit Guidelines

Choose rate limits based on operation cost/speed:

| Rate Limit | Use Case | Examples |
|------------|----------|----------|
| `100/minute` | Fast, cheap database queries | `get_top_tweets`, `export_tweets` |
| `20/minute` | Standard operations | `search_twitter`, `find_outliers` |
| `10/minute` | External API calls | `scrape_twitter`, `scrape_tiktok` |
| `5/minute` | AI-powered analysis | `analyze_hooks`, `generate_content` |
| `1/minute` | Very expensive operations | Batch AI processing, large exports |

---

## Success Checklist

Before considering a tool complete:

- [ ] Tool defined in `tools_registered.py` with `@tool_registry.register()`
- [ ] Complete Google-style docstring
- [ ] Proper type hints on all parameters and return
- [ ] Appropriate rate limit set
- [ ] Correct category and platform
- [ ] Use cases and examples provided
- [ ] Imported in agent file
- [ ] Registered with `agent.tool()`
- [ ] Agent tool count updated
- [ ] Tested via Python import
- [ ] Tested via API endpoint
- [ ] Tested via agent natural language query
- [ ] Error handling implemented
- [ ] Logging added
- [ ] Returns structured Pydantic model

---

## Additional Resources

### Documentation
- `docs/TOOL_REGISTRY_GUIDE.md` - Registry system details
- `docs/PHASE_10_PYDANTIC_AI_CHECKPOINT.md` - Current migration status
- `docs/REFACTOR_PLAN_PYDANTIC_AI_ALIGNMENT.md` - Full refactor plan
- `docs/PYDANTIC_AI_ARCHITECTURE_COMPARISON.md` - Architecture analysis

### Code Examples
- `viraltracker/agent/tools_registered.py` - All current tools
- `viraltracker/agent/agents/twitter_agent.py` - Agent with 8 tools
- `viraltracker/agent/orchestrator.py` - Routing tools pattern
- `viraltracker/agent/tool_metadata.py` - Metadata schema

### External Resources
- [Pydantic AI Documentation](https://ai.pydantic.dev/)
- [Pydantic AI Tools Guide](https://ai.pydantic.dev/tools/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

**Last Updated**: 2025-01-24
**Pydantic AI Alignment**: Phase 1 Complete (85%)
**Status**: Ready for autonomous tool development

---

**Pro Tip for Claude Code**: When in doubt, check existing tools in `tools_registered.py` and agent files. They provide working examples of every pattern in this guide.
