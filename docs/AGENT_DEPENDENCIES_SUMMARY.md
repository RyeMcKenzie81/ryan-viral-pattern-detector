# Agent Dependencies Summary - Task 1.5

**Status:** ✅ Complete
**Date:** 2025-11-17
**Branch:** `feature/pydantic-ai-agent`

## Overview

The `AgentDependencies` class provides typed dependency injection for the Pydantic AI agent. It encapsulates all services (TwitterService, GeminiService, StatsService) and configuration needed by agent tools, following the dependency injection pattern for clean separation of concerns.

## Architecture

```
viraltracker/agent/
├── __init__.py           # Module exports
└── dependencies.py       # AgentDependencies class with factory method
```

## AgentDependencies Class

**File:** `viraltracker/agent/dependencies.py` (110 lines)

### Purpose

Provides typed access to all services and configuration needed by Pydantic AI agent tools. Uses a factory method pattern for easy initialization with sensible defaults.

### Class Definition

```python
@dataclass
class AgentDependencies:
    """Typed dependencies for Pydantic AI agent."""

    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    project_name: str = "yakety-pack-instagram"
```

### Factory Method

```python
@classmethod
def create(
    cls,
    project_name: str = "yakety-pack-instagram",
    gemini_api_key: Optional[str] = None,
    gemini_model: str = "gemini-2.0-flash-exp",
    rate_limit_rpm: int = 9,
) -> "AgentDependencies":
    """Factory method to create AgentDependencies with initialized services."""
```

**Parameters:**
- `project_name`: Name of project to analyze (default: "yakety-pack-instagram")
- `gemini_api_key`: Optional Gemini API key (default: uses environment variable)
- `gemini_model`: Gemini model to use (default: "gemini-2.0-flash-exp")
- `rate_limit_rpm`: Rate limit for Gemini API in requests per minute (default: 9)

**Returns:** `AgentDependencies` instance with all services initialized

**Raises:** `ValueError` if required credentials (Supabase, Gemini) are missing

### Key Features

1. **Typed Dependency Injection**: All services are type-hinted for IDE support
2. **Factory Pattern**: Easy initialization with `AgentDependencies.create()`
3. **Sensible Defaults**: Works out-of-box for yakety-pack-instagram project
4. **Configurable**: Can customize project, model, and rate limits
5. **Environment-aware**: Uses environment variables for credentials

## Usage Examples

### Example 1: Basic Usage (Default Configuration)

```python
from viraltracker.agent.dependencies import AgentDependencies

# Create with defaults
deps = AgentDependencies.create()

# Access services
tweets = await deps.twitter.get_tweets(
    project=deps.project_name,
    hours_back=24
)

analysis = await deps.gemini.analyze_hook(
    tweet_text=tweets[0].text,
    tweet_id=tweets[0].id
)

outliers = deps.stats.calculate_zscore_outliers(
    values=[t.engagement_score for t in tweets],
    threshold=2.0
)
```

### Example 2: Custom Project and Rate Limiting

```python
# Create for different project with lower rate limit
deps = AgentDependencies.create(
    project_name="my-tiktok-project",
    rate_limit_rpm=6  # 6 requests per minute
)

print(deps.project_name)  # "my-tiktok-project"
print(deps.gemini._requests_per_minute)  # 6
```

### Example 3: Custom API Key

```python
# Use custom Gemini API key
deps = AgentDependencies.create(
    gemini_api_key="your-api-key-here"
)
```

### Example 4: In Pydantic AI Agent Tool

```python
from pydantic_ai import RunContext
from viraltracker.agent.dependencies import AgentDependencies

async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24
) -> str:
    """Find viral outlier tweets."""

    # Access services via context
    tweets = await ctx.deps.twitter.get_tweets(
        project=ctx.deps.project_name,
        hours_back=hours_back
    )

    scores = [t.engagement_score for t in tweets]
    outliers = ctx.deps.stats.calculate_zscore_outliers(scores)

    return f"Found {len(outliers)} outliers from {len(tweets)} tweets"
```

## Testing

**Test File:** `test_agent_dependencies.py` (150 lines)

### Test Suites

1. **Import Test** - Verifies AgentDependencies can be imported
2. **Factory Method Test** - Tests default and custom parameters
3. **Service Initialization Test** - Verifies all services are properly initialized
4. **String Representation Test** - Tests `__str__` and `__repr__` methods

### Run Tests

```bash
cd /Users/ryemckenzie/projects/viraltracker
python test_agent_dependencies.py
```

**Expected Output:**
```
============================================================
AGENT DEPENDENCIES TEST SUITE
Phase 1, Task 1.5
============================================================
✅ PASS - Import
✅ PASS - Factory Method
✅ PASS - Service Initialization
✅ PASS - String Representation

🎉 All tests passed! Agent dependencies ready.
```

## Integration with Pydantic AI

The `AgentDependencies` class is designed to work seamlessly with Pydantic AI's dependency injection system:

```python
from pydantic_ai import Agent
from viraltracker.agent.dependencies import AgentDependencies

# Create agent with typed dependencies
agent = Agent(
    'openai:gpt-4o',
    deps_type=AgentDependencies,
    retries=2
)

# Create dependencies instance
deps = AgentDependencies.create(project_name="yakety-pack-instagram")

# Run agent with dependencies
result = await agent.run(
    "Find viral tweets from the last 24 hours",
    deps=deps
)
```

## Design Patterns

### Dependency Injection

The `AgentDependencies` class follows the dependency injection pattern:
- **Decouples** agent tools from service initialization
- **Testable** - Easy to mock services in tests
- **Configurable** - Services can be customized at creation time

### Factory Method

The `create()` class method provides:
- **Sensible defaults** for common use cases
- **Flexibility** to customize when needed
- **Centralized initialization** logic

### Dataclass Pattern

Using `@dataclass` provides:
- **Type safety** with type hints
- **Automatic** `__init__`, `__repr__`, `__eq__` methods
- **IDE support** with autocomplete

## Service Details

### TwitterService
- **Purpose:** Database operations via Supabase
- **Methods:** `get_tweets()`, `get_tweets_by_ids()`, `save_hook_analysis()`
- **Credentials:** Uses `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` environment variables

### GeminiService
- **Purpose:** AI-powered hook analysis
- **Methods:** `analyze_hook()`, `set_rate_limit()`
- **Features:** Rate limiting (9 req/min default), exponential backoff on 429 errors
- **Credentials:** Uses `GEMINI_API_KEY` environment variable

### StatsService
- **Purpose:** Statistical calculations
- **Methods:** `calculate_zscore_outliers()`, `calculate_percentile()`, `calculate_summary_stats()`
- **Type:** Static methods, no initialization needed

## Dependencies

**Required Packages:**
- `pydantic-ai>=1.18.0` - Pydantic AI framework
- Services layer dependencies (see `docs/SERVICES_LAYER_SUMMARY.md`)

## Environment Variables

Required environment variables (loaded from `.env`):
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_KEY` - Supabase service key
- `GEMINI_API_KEY` - Google Gemini API key

## Next Steps

**Task 1.6: Agent Tools**

Now that dependencies are complete, proceed to create agent tools:
1. `find_outliers_tool()` - Find viral outlier tweets
2. `analyze_hooks_tool()` - Analyze tweet hooks with AI
3. `export_results_tool()` - Format and export analysis results

See: `docs/PYDANTIC_AI_MIGRATION_PLAN.md` (lines 519-650)

## Files Created

1. `viraltracker/agent/__init__.py` - Module exports
2. `viraltracker/agent/dependencies.py` - AgentDependencies class (110 lines)
3. `test_agent_dependencies.py` - Test suite (150 lines)
4. `docs/AGENT_DEPENDENCIES_SUMMARY.md` - This document

## Summary

✅ **Status:** Complete and tested
✅ **Tests:** All passing (4 test suites)
✅ **Documentation:** Complete
✅ **Ready for:** Task 1.6 (Agent Tools)

The AgentDependencies class provides a clean, typed, and testable way to inject services into Pydantic AI agent tools, following best practices for dependency injection and factory patterns.
