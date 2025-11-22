# Orchestrator Refactor Plan - Multi-Agent Architecture

**Status:** Planning Phase
**Created:** 2025-01-21
**Goal:** Migrate from monolithic agent (15+ tools) to orchestrator pattern with 5 specialized agents

## Overview

### Current Architecture
- **1 monolithic agent** with 15+ tools across all platforms
- All tools in single agent context
- Difficult to maintain and extend

### Proposed Architecture
- **1 Orchestrator Agent** - Routes queries to specialized agents
- **5 Specialized Agents** - Platform and analysis experts (3-5 tools each)
- **Shared State** via ResultCache for inter-agent communication
- **Backwards Compatible** - Existing code continues working

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                        │
│  - Routes queries to specialized agents                      │
│  - Manages inter-agent communication                         │
│  - Coordinates multi-platform tasks                          │
│  Tools: call_twitter_agent, call_tiktok_agent, etc.         │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┬──────────────┐
        ▼                   ▼                   ▼              ▼
┌───────────────┐   ┌───────────────┐   ┌──────────────┐   ┌─────────────┐
│ Twitter Agent │   │ TikTok Agent  │   │ YouTube Agent│   │Facebook Agent│
│ 5 tools       │   │ 5 tools       │   │ 1 tool       │   │ 2 tools      │
└───────────────┘   └───────────────┘   └──────────────┘   └─────────────┘
        │                   │                   │                  │
        └───────────────────┴───────────────────┴──────────────────┘
                                    │
                            ┌───────────────┐
                            │Analysis Agent │
                            │ 3 tools       │
                            └───────────────┘
                                    │
                            ┌───────────────┐
                            │ ResultCache   │
                            │ (Shared State)│
                            └───────────────┘
```

## Benefits

✅ **Better tool selection accuracy** - Agents specialize in specific platforms
✅ **Reduced context window usage** - Smaller, focused system prompts
✅ **Parallel agent execution** - Multi-platform queries run concurrently
✅ **Easier maintenance** - Changes isolated to specific agents
✅ **Easier testing** - Test agents independently
✅ **Zero breaking changes** - Orchestrator exports as `agent`

---

## Phase 1: Update Dependencies with ResultCache

### File: `viraltracker/agent/dependencies.py`

Add ResultCache for inter-agent data passing:

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class ResultCache(BaseModel):
    """Shared result cache for inter-agent data passing"""
    last_twitter_query: Optional[List[Any]] = None
    last_tiktok_query: Optional[List[Any]] = None
    last_youtube_query: Optional[List[Any]] = None
    last_facebook_query: Optional[List[Any]] = None
    last_analysis: Optional[Any] = None
    custom: Dict[str, Any] = {}

    def clear(self) -> None:
        """Clear all cached results"""
        self.last_twitter_query = None
        self.last_tiktok_query = None
        self.last_youtube_query = None
        self.last_facebook_query = None
        self.last_analysis = None
        self.custom = {}

class AgentDependencies(BaseModel):
    """Shared dependencies across all agents"""
    # Services
    twitter: TwitterService
    tiktok: TikTokService
    youtube: YouTubeService
    facebook: FacebookService
    gemini: GeminiService
    stats: StatsService

    # Configuration
    project_name: str

    # Shared state for inter-agent communication
    result_cache: ResultCache = ResultCache()
```

---

## Phase 2: Create Specialized Agents

### Directory Structure

```
viraltracker/agent/agents/
├── __init__.py
├── twitter_agent.py
├── tiktok_agent.py
├── youtube_agent.py
├── facebook_agent.py
└── analysis_agent.py
```

### File: `viraltracker/agent/agents/__init__.py`

```python
"""Specialized agents for platform-specific operations"""
from .twitter_agent import twitter_agent
from .tiktok_agent import tiktok_agent
from .youtube_agent import youtube_agent
from .facebook_agent import facebook_agent
from .analysis_agent import analysis_agent

__all__ = [
    'twitter_agent',
    'tiktok_agent',
    'youtube_agent',
    'facebook_agent',
    'analysis_agent'
]
```

### File: `viraltracker/agent/agents/twitter_agent.py`

```python
"""Twitter/X Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import Twitter-specific tools
from ..tools_registered import (
    search_twitter_tool,
    scrape_twitter_user_tool,
    get_top_tweets_tool,
    analyze_tweet_tool,
    export_tweets_tool
)

logger = logging.getLogger(__name__)

# Create Twitter specialist agent
twitter_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the Twitter/X platform specialist agent.

Your ONLY responsibility is Twitter/X data operations:
- Searching and scraping tweets by keyword
- Scraping specific user timelines
- Querying database for top tweets
- Analyzing individual tweets
- Exporting tweet results to CSV/JSON/Markdown files

**Important:**
- When you retrieve tweets, ALWAYS save them to result_cache.last_twitter_query
- When exporting, use the same parameters that were used in the query
- Support multi-keyword OR logic with comma-separated keywords (e.g., "btc,bitcoin")
- Always provide clear summaries of results

**Available Services:**
- TwitterService: For API scraping
- StatsService: For database queries
- GeminiService: For AI analysis

**Result Format:**
- Provide clear, structured responses with metrics
- Show top results with engagement stats
- Include URLs for all content
- Save files to ~/Downloads/ for exports
"""
)

# Register tools
twitter_agent.tool(search_twitter_tool)
twitter_agent.tool(scrape_twitter_user_tool)
twitter_agent.tool(get_top_tweets_tool)
twitter_agent.tool(analyze_tweet_tool)
twitter_agent.tool(export_tweets_tool)

logger.info("Twitter Agent initialized with 5 tools")
```

### File: `viraltracker/agent/agents/tiktok_agent.py`

```python
"""TikTok Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import TikTok-specific tools
from ..tools_phase16 import (
    search_tiktok_tool,
    search_tiktok_hashtag_tool,
    scrape_tiktok_user_tool,
    analyze_tiktok_video_tool,
    analyze_tiktok_batch_tool
)

logger = logging.getLogger(__name__)

tiktok_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the TikTok platform specialist agent.

Your ONLY responsibility is TikTok data operations:
- Searching TikTok by keyword or hashtag
- Scraping user profiles and videos
- Analyzing single or batch videos
- Tracking viral TikTok trends

**Important:**
- Save all results to result_cache.last_tiktok_query
- Focus on viral content (100K+ views by default)
- Target micro-influencers (50K followers or less)
- Provide engagement metrics (likes, comments, shares)

**Available Services:**
- TikTokService: For API scraping
- StatsService: For database queries
- GeminiService: For content analysis
"""
)

# Register tools
tiktok_agent.tool(search_tiktok_tool)
tiktok_agent.tool(search_tiktok_hashtag_tool)
tiktok_agent.tool(scrape_tiktok_user_tool)
tiktok_agent.tool(analyze_tiktok_video_tool)
tiktok_agent.tool(analyze_tiktok_batch_tool)

logger.info("TikTok Agent initialized with 5 tools")
```

### File: `viraltracker/agent/agents/youtube_agent.py`

```python
"""YouTube Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies
from ..tools_phase17 import search_youtube_tool

logger = logging.getLogger(__name__)

youtube_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the YouTube platform specialist agent.

Your ONLY responsibility is YouTube data operations:
- Searching YouTube by keyword
- Finding viral YouTube Shorts
- Analyzing video performance
- Tracking YouTube trends

**Important:**
- Save results to result_cache.last_youtube_query
- Focus on Shorts (default: 100 Shorts, 0 regular videos)
- Target viral content (100K+ views)
- Target micro-influencers (50K subscribers or less)

**Available Services:**
- YouTubeService: For API scraping
- StatsService: For database queries
"""
)

youtube_agent.tool(search_youtube_tool)

logger.info("YouTube Agent initialized with 1 tool")
```

### File: `viraltracker/agent/agents/facebook_agent.py`

```python
"""Facebook Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies
from ..tools_phase17 import (
    search_facebook_ads_tool,
    scrape_facebook_page_ads_tool
)

logger = logging.getLogger(__name__)

facebook_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the Facebook platform specialist agent.

Your ONLY responsibility is Facebook advertising data operations:
- Searching Facebook Ad Library by keyword
- Scraping ads from Facebook pages
- Analyzing ad performance and spend
- Tracking competitor advertising strategies

**Important:**
- Save results to result_cache.last_facebook_query
- Provide ad spend and reach statistics
- Track active vs inactive campaigns
- Focus on engagement metrics

**Available Services:**
- FacebookService: For Ad Library scraping
- StatsService: For database queries
"""
)

facebook_agent.tool(search_facebook_ads_tool)
facebook_agent.tool(scrape_facebook_page_ads_tool)

logger.info("Facebook Agent initialized with 2 tools")
```

### File: `viraltracker/agent/agents/analysis_agent.py`

```python
"""Analysis Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies
from ..tools import (
    analyze_viral_content_tool,
    compare_platforms_tool,
    generate_insights_tool
)

logger = logging.getLogger(__name__)

analysis_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the Analysis specialist agent.

Your ONLY responsibility is cross-platform analysis and insights:
- Analyzing viral content patterns
- Comparing performance across platforms
- Generating strategic insights and recommendations
- Identifying trends and opportunities

**Important:**
- Access cached results from other agents via result_cache
- Provide actionable insights and recommendations
- Compare metrics across platforms
- Save analysis to result_cache.last_analysis

**Available Services:**
- GeminiService: For AI-powered analysis
- StatsService: For aggregate metrics
- All platform services: For cross-platform queries
"""
)

analysis_agent.tool(analyze_viral_content_tool)
analysis_agent.tool(compare_platforms_tool)
analysis_agent.tool(generate_insights_tool)

logger.info("Analysis Agent initialized with 3 tools")
```

---

## Phase 3: Create Orchestrator Agent

### File: `viraltracker/agent/orchestrator.py`

```python
"""Orchestrator Agent - Routes queries to specialized agents"""
import logging
from pydantic_ai import Agent, RunContext
from .dependencies import AgentDependencies

# Import specialized agents
from .agents import (
    twitter_agent,
    tiktok_agent,
    youtube_agent,
    facebook_agent,
    analysis_agent
)

logger = logging.getLogger(__name__)

# Create orchestrator
orchestrator = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the Orchestrator Agent that coordinates specialized platform agents.

Your responsibility is to route user queries to the appropriate specialized agents:
- **Twitter Agent**: Twitter/X search, scraping, queries, exports
- **TikTok Agent**: TikTok search, hashtags, user scraping, video analysis
- **YouTube Agent**: YouTube search, Shorts discovery
- **Facebook Agent**: Facebook Ad Library search, page ad scraping
- **Analysis Agent**: Cross-platform analysis, insights, comparisons

**Routing Guidelines:**
1. Identify which platform(s) the query targets
2. Call the appropriate platform agent(s)
3. For multi-platform queries, call agents in parallel or sequence
4. For analysis/insights, call Analysis Agent with cached results
5. Always provide clear, structured responses to the user

**Important:**
- Use call_twitter_agent for Twitter/X queries
- Use call_tiktok_agent for TikTok queries
- Use call_youtube_agent for YouTube queries
- Use call_facebook_agent for Facebook queries
- Use call_analysis_agent for cross-platform insights
- Agents share data via result_cache in dependencies

**Examples:**
- "Find viral Bitcoin tweets" → call_twitter_agent
- "What's trending on TikTok about #productivity" → call_tiktok_agent
- "Compare Twitter vs TikTok engagement" → call_analysis_agent (after platform agents)
- "Export top tweets" → call_twitter_agent
"""
)

# ============================================================================
# Routing Tools
# ============================================================================

@orchestrator.tool
async def call_twitter_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route query to Twitter Agent for Twitter/X operations.

    Use this for:
    - Searching tweets by keyword
    - Scraping Twitter users
    - Querying top tweets from database
    - Analyzing tweets
    - Exporting tweet data

    Args:
        ctx: Run context with shared dependencies
        query: User query for Twitter Agent

    Returns:
        Twitter Agent's response
    """
    logger.info(f"Routing to Twitter Agent: {query}")
    result = await twitter_agent.run(query, deps=ctx.deps)
    return result.data


@orchestrator.tool
async def call_tiktok_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route query to TikTok Agent for TikTok operations.

    Use this for:
    - Searching TikTok by keyword
    - Searching hashtags
    - Scraping TikTok users
    - Analyzing videos

    Args:
        ctx: Run context with shared dependencies
        query: User query for TikTok Agent

    Returns:
        TikTok Agent's response
    """
    logger.info(f"Routing to TikTok Agent: {query}")
    result = await tiktok_agent.run(query, deps=ctx.deps)
    return result.data


@orchestrator.tool
async def call_youtube_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route query to YouTube Agent for YouTube operations.

    Use this for:
    - Searching YouTube by keyword
    - Finding viral Shorts

    Args:
        ctx: Run context with shared dependencies
        query: User query for YouTube Agent

    Returns:
        YouTube Agent's response
    """
    logger.info(f"Routing to YouTube Agent: {query}")
    result = await youtube_agent.run(query, deps=ctx.deps)
    return result.data


@orchestrator.tool
async def call_facebook_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route query to Facebook Agent for Facebook Ad Library operations.

    Use this for:
    - Searching Facebook Ad Library
    - Scraping page ads

    Args:
        ctx: Run context with shared dependencies
        query: User query for Facebook Agent

    Returns:
        Facebook Agent's response
    """
    logger.info(f"Routing to Facebook Agent: {query}")
    result = await facebook_agent.run(query, deps=ctx.deps)
    return result.data


@orchestrator.tool
async def call_analysis_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route query to Analysis Agent for cross-platform insights.

    Use this for:
    - Analyzing viral content patterns
    - Comparing platforms
    - Generating strategic insights
    - Making recommendations

    Args:
        ctx: Run context with shared dependencies
        query: User query for Analysis Agent

    Returns:
        Analysis Agent's response
    """
    logger.info(f"Routing to Analysis Agent: {query}")
    result = await analysis_agent.run(query, deps=ctx.deps)
    return result.data


logger.info("Orchestrator initialized with 5 routing tools")
```

---

## Phase 4: Update Main Agent Export

### File: `viraltracker/agent/agent.py`

Update to export orchestrator (backwards compatible):

```python
"""Main Agent Entry Point - Exports Orchestrator"""
import logging
from .orchestrator import orchestrator
from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# Export orchestrator as 'agent' for backwards compatibility
agent = orchestrator

# Also export for explicit use
__all__ = ['agent', 'orchestrator', 'AgentDependencies']

logger.info("Main agent module initialized (orchestrator pattern)")
```

**Why this works:**
- Existing code imports: `from viraltracker.agent.agent import agent`
- This still works because `agent = orchestrator`
- FastAPI, CLI, and Streamlit continue working unchanged

---

## Phase 5: Migration Checklist

### Pre-Migration

- [ ] **Backup current code** (create git branch `pre-orchestrator-refactor`)
- [ ] **Document current agent behavior** (save sample queries/responses)
- [ ] **Test existing integrations** (FastAPI, CLI, Streamlit)
- [ ] **Review all current tools** (ensure all are migrated to new agents)

### Migration Steps

1. [ ] **Phase 1**: Update `dependencies.py` with ResultCache
2. [ ] **Phase 2**: Create `agents/` directory
3. [ ] **Phase 2**: Create all 5 specialized agents
4. [ ] **Phase 3**: Create `orchestrator.py`
5. [ ] **Phase 4**: Update `agent.py` to export orchestrator
6. [ ] **Phase 5**: Run tests
7. [ ] **Phase 6**: Test FastAPI endpoints
8. [ ] **Phase 7**: Test CLI commands
9. [ ] **Phase 8**: Test Streamlit UI
10. [ ] **Phase 9**: Monitor logs for routing behavior

### Post-Migration Validation

- [ ] **Test FastAPI endpoints** (verify same responses)
- [ ] **Test CLI commands** (verify same behavior)
- [ ] **Test Streamlit UI** (verify agent interactions)
- [ ] **Run integration tests** (multi-platform queries)
- [ ] **Monitor performance** (compare response times)
- [ ] **Check logs** (verify routing working correctly)

---

## Phase 6: Testing Strategy

### Test Files to Create

1. **`tests/agent/test_orchestrator.py`**
2. **`tests/agent/test_twitter_agent.py`**
3. **`tests/agent/test_tiktok_agent.py`**
4. **`tests/agent/test_youtube_agent.py`**
5. **`tests/agent/test_facebook_agent.py`**
6. **`tests/agent/test_analysis_agent.py`**

### Example Test: `tests/agent/test_orchestrator.py`

```python
"""Tests for Orchestrator Agent"""
import pytest
from viraltracker.agent.orchestrator import orchestrator
from viraltracker.agent.dependencies import AgentDependencies

@pytest.mark.asyncio
async def test_orchestrator_routes_twitter_query(mock_dependencies):
    """Test orchestrator correctly routes Twitter query"""
    query = "Find viral tweets about Bitcoin"

    result = await orchestrator.run(query, deps=mock_dependencies)

    assert result.data
    assert "tweets" in result.data.lower() or "twitter" in result.data.lower()

@pytest.mark.asyncio
async def test_orchestrator_routes_tiktok_query(mock_dependencies):
    """Test orchestrator correctly routes TikTok query"""
    query = "Search TikTok for #productivity videos"

    result = await orchestrator.run(query, deps=mock_dependencies)

    assert result.data
    assert "tiktok" in result.data.lower()

@pytest.mark.asyncio
async def test_multi_platform_query(mock_dependencies):
    """Test orchestrator handles multi-platform queries"""
    query = "Compare Bitcoin mentions on Twitter and TikTok"

    result = await orchestrator.run(query, deps=mock_dependencies)

    assert result.data
    # Should involve both platform agents and analysis agent
```

---

## Phase 7: Deployment Plan

### Development Environment

```bash
# 1. Create feature branch
git checkout -b feature/orchestrator-refactor

# 2. Implement phases 1-4
# ... (make changes)

# 3. Test locally
source venv/bin/activate
pytest tests/agent/

# 4. Test API
uvicorn viraltracker.api.app:app --reload

# 5. Test Streamlit
streamlit run viraltracker/ui/app.py

# 6. Commit
git add .
git commit -m "feat: Implement orchestrator pattern with specialized agents

- Add ResultCache for inter-agent communication
- Create 5 specialized agents (Twitter, TikTok, YouTube, Facebook, Analysis)
- Create orchestrator with routing tools
- Maintain backwards compatibility

Closes #XXX"

# 7. Push and create PR
git push origin feature/orchestrator-refactor
```

### Production Deployment

1. **Merge to main** after PR approval
2. **Deploy API** (restart FastAPI service)
3. **Deploy Streamlit** (restart Streamlit service)
4. **Monitor logs** for routing behavior
5. **Monitor metrics** (response times, error rates)

---

## Phase 8: Future Enhancements

### Post-Launch Improvements

1. **Agent Performance Metrics**
   - Track which agents are called most frequently
   - Monitor average response times per agent
   - Log tool usage statistics

2. **Advanced Routing**
   - Implement parallel agent calls for multi-platform queries
   - Add agent result caching (avoid redundant calls)
   - Smart routing based on query context

3. **Agent Observability**
   - Add detailed logging for agent decisions
   - Create agent performance dashboard in Streamlit
   - Track tool success/failure rates

4. **Additional Specialized Agents**
   - **Reddit Agent**: Reddit scraping and analysis
   - **Instagram Agent**: Instagram Reels analysis
   - **Trend Detection Agent**: Cross-platform trend identification
   - **Content Generation Agent**: AI-powered content creation

---

## Inter-Agent Communication Patterns

### Pattern 1: Sequential Chaining
Agent A → Agent B (B uses A's results)

```python
# Twitter agent finds tweets
result_a = await twitter_agent.run("Find Bitcoin tweets", deps=deps)
deps.result_cache.last_twitter_query = tweets

# Analysis agent analyzes cached tweets
result_b = await analysis_agent.run("Analyze these tweets", deps=deps)
```

### Pattern 2: Structured Data Returns
Agents return Pydantic models

```python
class TweetQueryResult(BaseModel):
    tweets: List[Tweet]
    total_views: int
    avg_engagement: float
```

### Pattern 3: Shared State (Recommended)
Via ResultCache in AgentDependencies

```python
# Agent A saves to cache
ctx.deps.result_cache.last_twitter_query = tweets

# Agent B reads from cache
tweets = ctx.deps.result_cache.last_twitter_query
```

### Pattern 4: Message History
Pass conversation context between agents

### Pattern 5: Hybrid (RECOMMENDED)
Combine Structured Returns + Shared State

---

## Validation Questions & Answers

### Q: Does this plan follow Pydantic AI best practices?
**A: Yes, fully compliant.**

✅ **Agent Pattern**: Uses `Agent()` class with proper model, deps_type, and system_prompt
✅ **RunContext**: All tools use `RunContext[AgentDependencies]`
✅ **Tool Decorators**: Uses `@agent.tool` decorator pattern
✅ **Structured Dependencies**: Uses Pydantic BaseModel
✅ **Orchestrator Pattern**: Follows Pydantic AI's recommended multi-agent orchestration
✅ **Shared State**: Uses dependencies object for inter-agent communication
✅ **Async/Await**: All tools properly async
✅ **Type Safety**: Full type hints with Pydantic models

### Q: Will this create an agent catalog?
**A: Not in current plan, but easy to add.**

See the main plan document for details on creating an agent registry similar to the tool registry.

### Q: Will this negatively impact FastAPI endpoints or CLI?
**A: No breaking changes - fully backwards compatible.**

✅ **Same Import Path**: `from viraltracker.agent.agent import agent` continues working
✅ **Same Interface**: `await agent.run(prompt, deps=deps)` unchanged
✅ **Same Response Format**: Returns `RunResult` with `.data` attribute
✅ **Same Dependencies**: `AgentDependencies` maintains same structure

---

## Summary

**Total Implementation Time**: 2-3 days for full implementation and testing

**Impact**:
- No breaking changes to FastAPI, CLI, or Streamlit
- Better tool selection and faster responses
- Easier to maintain and extend with new platforms
- Clear separation of concerns
- Improved testability

**Next Steps**:
1. Review and approve this plan
2. Create feature branch
3. Implement Phase 1 (dependencies)
4. Implement Phase 2 (specialized agents)
5. Implement Phase 3 (orchestrator)
6. Test thoroughly
7. Deploy

---

**Document Version**: 1.0
**Last Updated**: 2025-01-21
**Status**: Planning Phase - Awaiting Approval
