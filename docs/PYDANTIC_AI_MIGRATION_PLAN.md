# Pydantic AI Migration Plan - Viraltracker Agent

**Project:** Viraltracker CLI → Agentic Platform
**Framework:** Pydantic AI + Streamlit + FastAPI
**Deployment:** Railway
**Timeline:** 9-14 days (3 phases)
**Branch:** `feature/pydantic-ai-agent`

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Current State Analysis](#current-state-analysis)
3. [Target Architecture](#target-architecture)
4. [Migration Strategy](#migration-strategy)
5. [Phase 1: MVP - Core Tools (4-5 days)](#phase-1-mvp---core-tools-4-5-days)
6. [Phase 1.5: Complete Tool Coverage (2-3 days)](#phase-15-complete-tool-coverage-2-3-days)
7. [Phase 2: Polish (3-4 days)](#phase-2-polish-3-4-days)
8. [Phase 3: Automation (2-3 days)](#phase-3-automation-2-3-days)
9. [Railway Deployment](#railway-deployment)
10. [Testing Strategy](#testing-strategy)
11. [Success Criteria](#success-criteria)
12. [Rollback Plan](#rollback-plan)

---

## Project Overview

### Goals

Transform Viraltracker from a CLI-only tool into a multi-access platform:

1. **Keep CLI working** - Existing scripts and workflows continue to function
2. **Add Agent Interface** - Conversational access via Pydantic AI
3. **Add Web UI** - Streamlit interface for non-technical users
4. **Add API** - Webhook/automation support for n8n, Zapier, etc.
5. **Production Ready** - Deploy to Railway with proper architecture

### Why Pydantic AI?

- **Type-safe tools** - Pydantic models prevent bugs
- **Automatic tool calling** - LLM decides which tools to use
- **Streaming support** - Real-time feedback
- **Result validation** - Ensure quality before returning to user
- **Multi-model support** - Works with OpenAI, Anthropic, Gemini

### Access Methods

```
┌─────────────────────────────────────────────┐
│           SERVICE LAYER (Core)              │
│  - TwitterService (DB access)               │
│  - GeminiService (AI analysis)              │
│  - StatsService (calculations)              │
└──────────────┬──────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┐
   │           │           │              │
   ▼           ▼           ▼              ▼
┌──────┐  ┌───────┐  ┌─────────┐  ┌────────────┐
│ CLI  │  │ Agent │  │Streamlit│  │ FastAPI    │
│      │  │(Chat) │  │  (UI)   │  │ (Webhooks) │
└──────┘  └───────┘  └─────────┘  └────────────┘
```

---

## Current State Analysis

### Existing CLI Commands

```bash
# Twitter commands
viraltracker twitter scrape --keyword "parenting" --hours 24
viraltracker twitter find-outliers --project yakety-pack --days-back 7
viraltracker twitter analyze-hooks --input-json outliers.json
viraltracker twitter generate-comments --project yakety-pack --hours-back 48

# Export commands
viraltracker twitter export-tweets --project yakety-pack --format csv
viraltracker twitter export-comments --project yakety-pack --format json
```

### Tool Migration Roadmap

| CLI Command | Phase | Agent Tool | Priority |
|-------------|-------|------------|----------|
| `find-outliers` | **Phase 1** | `find_outliers_tool` | ⭐⭐⭐ High |
| `analyze-hooks` | **Phase 1** | `analyze_hooks_tool` | ⭐⭐⭐ High |
| `export-*` | **Phase 1** | `export_results_tool` | ⭐⭐⭐ High |
| `scrape` | **Phase 1.5** | `scrape_tweets_tool` | ⭐⭐ Medium |
| `generate-comments` | **Phase 1.5** | `find_comment_opportunities_tool` | ⭐⭐ Medium |

**Strategy:**
- **Phase 1** - Prove concept with core analysis tools (find-outliers, analyze-hooks, export)
- **Phase 1.5** - Add remaining tools once MVP is validated (scrape, generate-comments)
- **Phase 2+** - Polish all tools with streaming, validation, multi-format output

### Current Architecture

```
viraltracker/
├── cli/
│   └── twitter.py        # Click commands (monolithic)
├── scraping/
│   └── twitter.py        # Scraping logic
├── analysis/
│   └── outlier_detector.py
├── generation/
│   ├── hook_analyzer.py  # Gemini hook analysis
│   └── comment_finder.py
└── database/
    └── db.py             # SQLite access
```

**Issues:**
- Business logic mixed with CLI code
- Hard to reuse from other interfaces
- No type safety
- No structured outputs

---

## Target Architecture

### New Structure (Pydantic AI Best Practices)

```
viraltracker/
├── services/              # NEW: Data access layer
│   ├── __init__.py
│   ├── twitter_service.py   # DB operations
│   ├── gemini_service.py    # AI API calls
│   ├── stats_service.py     # Calculations
│   └── models.py            # Pydantic models
│
├── agent/                 # NEW: Pydantic AI layer
│   ├── __init__.py
│   ├── tools.py            # @agent.tool functions
│   ├── agent.py            # Agent configuration
│   └── dependencies.py     # Typed dependencies
│
├── api/                   # NEW: FastAPI (Phase 3)
│   ├── __init__.py
│   ├── main.py
│   ├── routes/
│   └── auth.py
│
├── ui/                    # NEW: Streamlit (Phase 1)
│   ├── app.py             # Main chat interface
│   └── pages/             # Multi-page (Phase 2)
│
├── cli/                   # REFACTORED: Thin wrapper
│   └── twitter.py         # Now calls services
│
├── scraping/              # UNCHANGED
│   └── twitter.py
│
├── analysis/              # REFACTORED
│   └── outlier_detector.py  # Now a service
│
├── generation/            # REFACTORED
│   ├── hook_analyzer.py     # Now a service
│   └── comment_finder.py    # Now a service
│
└── database/              # UNCHANGED
    └── db.py
```

---

## Migration Strategy

### Principles

1. **Non-breaking** - CLI continues to work during migration
2. **Incremental** - Build new alongside old, then switch
3. **Backwards compatible** - Old code can call new services
4. **Test continuously** - Verify each step works

### Approach

```
Old CLI → Extract → Services → Wire to Agent + CLI
         (Phase 1)  (Phase 1)  (Phase 1)

Services → Add UI → Polish UX
(Phase 1)  (Phase 2) (Phase 2)

UI → Add API → Deploy to Railway
(Phase 2)  (Phase 3)  (Phase 3)
```

---

## Phase 1: MVP (4-5 days)

**Goal:** Working agent + Streamlit UI + Keep CLI functional

### Day 1-2: Services Layer

#### Task 1.1: Create Service Models

**File:** `viraltracker/services/models.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional

class Tweet(BaseModel):
    """Tweet data model"""
    id: str
    text: str
    view_count: int
    like_count: int
    reply_count: int
    retweet_count: int
    created_at: datetime
    author_username: str
    author_followers: int
    url: str

class HookAnalysis(BaseModel):
    """Hook analysis result"""
    tweet_id: str
    tweet_text: str
    hook_type: str
    hook_type_confidence: float
    emotional_trigger: str
    emotional_trigger_confidence: float
    hook_explanation: str
    adaptation_notes: str
    analyzed_at: datetime = Field(default_factory=datetime.now)

class OutlierTweet(BaseModel):
    """Viral outlier tweet"""
    tweet: Tweet
    zscore: float
    percentile: float

class CommentCandidate(BaseModel):
    """Comment opportunity"""
    tweet: Tweet
    green_flag_score: float
    engagement_score: float
    reasoning: str
```

**Time:** 2 hours

---

#### Task 1.2: Create TwitterService

**File:** `viraltracker/services/twitter_service.py`

```python
from typing import List, Optional
from datetime import datetime, timedelta
import sqlite3
from .models import Tweet, HookAnalysis, OutlierTweet

class TwitterService:
    """
    Data access service for Twitter data.
    Pure data access - no business logic.
    """

    def __init__(self, db_path: str = "viraltracker.db"):
        self.db_path = db_path

    async def get_tweets(
        self,
        project: str,
        hours_back: int,
        min_views: int = 0,
        text_only: bool = False
    ) -> List[Tweet]:
        """Fetch tweets from database"""
        # Implementation
        pass

    async def get_tweets_by_ids(
        self,
        tweet_ids: List[str]
    ) -> List[Tweet]:
        """Fetch specific tweets by ID"""
        pass

    async def save_hook_analysis(
        self,
        analysis: HookAnalysis
    ) -> None:
        """Save hook analysis to database"""
        pass

    async def get_hook_analyses(
        self,
        project: str,
        hours_back: Optional[int] = None,
        hook_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[HookAnalysis]:
        """Fetch hook analyses with filters"""
        pass

    async def mark_as_outlier(
        self,
        tweet_id: str,
        zscore: float,
        threshold: float
    ) -> None:
        """Mark tweet as viral outlier"""
        pass
```

**Time:** 4 hours

---

#### Task 1.3: Create GeminiService

**File:** `viraltracker/services/gemini_service.py`

```python
import google.generativeai as genai
import json
import asyncio
from typing import Optional
from .models import HookAnalysis

class GeminiService:
    """
    Service for Gemini AI API calls.
    Handles rate limiting and retries.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp"):
        self.api_key = api_key
        self.model_name = model
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        self._last_call_time = 0
        self._min_delay = 6.7  # For 9 req/min

    async def analyze_hook(
        self,
        tweet_text: str,
        tweet_id: Optional[str] = None
    ) -> HookAnalysis:
        """
        Analyze a single tweet's hook.
        Includes rate limiting.
        """
        # Wait for rate limit
        await self._rate_limit()

        # Build prompt
        prompt = self._build_hook_prompt(tweet_text)

        # Call API
        response = await self.model.generate_content(prompt)

        # Parse response
        result = json.loads(response.text)

        # Return structured result
        return HookAnalysis(
            tweet_id=tweet_id or "",
            tweet_text=tweet_text,
            hook_type=result['hook_type'],
            hook_type_confidence=result['hook_type_confidence'],
            emotional_trigger=result['emotional_trigger'],
            emotional_trigger_confidence=result['emotional_trigger_confidence'],
            hook_explanation=result['explanation'],
            adaptation_notes=result['adaptation_notes']
        )

    async def _rate_limit(self) -> None:
        """Enforce rate limiting"""
        import time
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_delay:
            await asyncio.sleep(self._min_delay - elapsed)
        self._last_call_time = time.time()

    def _build_hook_prompt(self, tweet_text: str) -> str:
        """Build hook analysis prompt"""
        # Use existing prompt from hook_analyzer.py
        pass
```

**Time:** 3 hours

---

#### Task 1.4: Create StatsService

**File:** `viraltracker/services/stats_service.py`

```python
import statistics
from typing import List, Tuple

class StatsService:
    """Statistical calculations service"""

    @staticmethod
    def calculate_zscore_outliers(
        values: List[float],
        threshold: float = 2.0
    ) -> List[Tuple[int, float]]:
        """
        Calculate Z-score outliers.

        Returns:
            List of (index, zscore) tuples for outliers
        """
        if len(values) < 2:
            return []

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)

        if stdev == 0:
            return []

        outliers = []
        for i, value in enumerate(values):
            zscore = (value - mean) / stdev
            if zscore > threshold:
                outliers.append((i, zscore))

        return outliers

    @staticmethod
    def calculate_percentile(value: float, values: List[float]) -> float:
        """Calculate percentile rank of a value"""
        sorted_values = sorted(values)
        rank = sum(1 for v in sorted_values if v <= value)
        return (rank / len(values)) * 100
```

**Time:** 1 hour

---

### Day 3: Pydantic AI Agent

#### Task 1.5: Setup Dependencies

**File:** `viraltracker/agent/dependencies.py`

```python
from dataclasses import dataclass
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
import os

@dataclass
class AgentDependencies:
    """Typed dependencies for Pydantic AI agent"""

    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    project_name: str = "yakety-pack-instagram"

    @classmethod
    def create(
        cls,
        db_path: str = "viraltracker.db",
        gemini_api_key: Optional[str] = None,
        project_name: str = "yakety-pack-instagram"
    ) -> 'AgentDependencies':
        """Factory method to create dependencies"""

        api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")

        return cls(
            twitter=TwitterService(db_path),
            gemini=GeminiService(api_key),
            stats=StatsService(),
            project_name=project_name
        )
```

**Time:** 1 hour

---

#### Task 1.6: Create Agent Tools

**File:** `viraltracker/agent/tools.py`

```python
from pydantic_ai import RunContext
from typing import Optional, List
from .dependencies import AgentDependencies
from viraltracker.services.models import OutlierTweet, HookAnalysis
import asyncio

async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    zscore_threshold: float = 2.0,
    min_views: int = 100,
    text_only: bool = True
) -> str:
    """
    Find viral outlier tweets using Z-score analysis.

    Args:
        hours_back: Hours of data to analyze (default: 24)
        zscore_threshold: Z-score threshold for outliers (default: 2.0)
        min_views: Minimum view count to consider (default: 100)
        text_only: Only include text tweets, no media (default: True)

    Returns:
        Summary of viral tweets found
    """
    # Fetch tweets
    tweets = await ctx.deps.twitter.get_tweets(
        project=ctx.deps.project_name,
        hours_back=hours_back,
        min_views=min_views,
        text_only=text_only
    )

    if not tweets:
        return f"No tweets found for {ctx.deps.project_name} in last {hours_back} hours"

    # Calculate outliers
    view_counts = [t.view_count for t in tweets]
    outlier_results = ctx.deps.stats.calculate_zscore_outliers(
        view_counts,
        zscore_threshold
    )

    if not outlier_results:
        return f"No outliers found with threshold {zscore_threshold}. Try lowering threshold."

    # Build outlier list
    outliers = []
    for idx, zscore in outlier_results:
        tweet = tweets[idx]
        percentile = ctx.deps.stats.calculate_percentile(
            tweet.view_count,
            view_counts
        )

        outliers.append(OutlierTweet(
            tweet=tweet,
            zscore=zscore,
            percentile=percentile
        ))

        # Mark in database
        await ctx.deps.twitter.mark_as_outlier(
            tweet_id=tweet.id,
            zscore=zscore,
            threshold=zscore_threshold
        )

    # Sort by views
    outliers.sort(key=lambda o: o.tweet.view_count, reverse=True)

    # Format response
    response = f"✅ Found {len(outliers)} viral tweets out of {len(tweets)} total\n\n"
    response += f"**Top 5 Viral Tweets:**\n"

    for i, outlier in enumerate(outliers[:5], 1):
        t = outlier.tweet
        response += f"\n{i}. @{t.author_username} - {t.view_count:,} views (Z-score: {outlier.zscore:.2f})\n"
        response += f"   {t.text[:100]}...\n"
        response += f"   {t.url}\n"

    return response


async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    rate_limit: int = 9
) -> str:
    """
    Analyze viral tweet hooks using AI.

    Args:
        tweet_ids: Specific tweet IDs to analyze (if None, uses recent outliers)
        hours_back: Hours of data if tweet_ids not provided (default: 24)
        rate_limit: Max Gemini API requests per minute (default: 9)

    Returns:
        Summary of hook analysis with top patterns
    """
    # Get tweets to analyze
    if tweet_ids:
        tweets = await ctx.deps.twitter.get_tweets_by_ids(tweet_ids)
    else:
        # Get recent tweets and find outliers
        all_tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=100,
            text_only=True
        )

        if not all_tweets:
            return f"No tweets found to analyze"

        # Find outliers
        view_counts = [t.view_count for t in all_tweets]
        outlier_results = ctx.deps.stats.calculate_zscore_outliers(view_counts, 2.0)

        tweets = [all_tweets[idx] for idx, _ in outlier_results]

    if not tweets:
        return "No tweets to analyze. Try different parameters."

    # Analyze hooks with progress
    analyses = []

    for i, tweet in enumerate(tweets, 1):
        try:
            analysis = await ctx.deps.gemini.analyze_hook(
                tweet_text=tweet.text,
                tweet_id=tweet.id
            )

            # Save to database
            await ctx.deps.twitter.save_hook_analysis(analysis)
            analyses.append(analysis)

        except Exception as e:
            # Log error but continue
            print(f"Error analyzing tweet {tweet.id}: {e}")
            continue

    if not analyses:
        return "Failed to analyze any tweets. Check API quota."

    # Calculate statistics
    from collections import Counter
    hook_types = Counter(a.hook_type for a in analyses)
    triggers = Counter(a.emotional_trigger for a in analyses)
    avg_conf = sum(a.hook_type_confidence for a in analyses) / len(analyses)

    # Format response
    response = f"✅ Analyzed {len(analyses)} viral hooks\n\n"
    response += f"**Hook Types:**\n"
    for hook_type, count in hook_types.most_common(3):
        pct = (count / len(analyses)) * 100
        response += f"- {hook_type}: {count} ({pct:.0f}%)\n"

    response += f"\n**Emotional Triggers:**\n"
    for trigger, count in triggers.most_common(3):
        pct = (count / len(analyses)) * 100
        response += f"- {trigger}: {count} ({pct:.0f}%)\n"

    response += f"\n**Average Confidence:** {avg_conf:.1%}\n"

    return response


async def export_results_tool(
    ctx: RunContext[AgentDependencies],
    data_type: str,
    hours_back: int = 24,
    format: str = "json"
) -> str:
    """
    Export data to downloadable format.

    Args:
        data_type: Type of data - "outliers", "hooks", or "tweets"
        hours_back: Hours of data to export (default: 24)
        format: Output format - "json", "csv", or "markdown" (default: json)

    Returns:
        File path to exported data
    """
    # Implementation will return data for download
    pass
```

**Time:** 4 hours

---

#### Task 1.7: Create Agent

**File:** `viraltracker/agent/agent.py`

```python
from pydantic_ai import Agent, RunContext
from .dependencies import AgentDependencies
from .tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)

# Create agent
agent = Agent(
    'openai:gpt-4o',  # or 'anthropic:claude-3-5-sonnet-20241022'
    deps_type=AgentDependencies,
    retries=2,
)

# Register tools
agent.tool(find_outliers_tool)
agent.tool(analyze_hooks_tool)
agent.tool(export_results_tool)

# Dynamic system prompt
@agent.system_prompt
async def system_prompt(ctx: RunContext[AgentDependencies]) -> str:
    return f"""
You are a viral content analysis assistant for the {ctx.deps.project_name} project.

You help analyze Twitter content to find viral patterns and generate insights.

**Available Tools:**

1. **find_outliers_tool**: Find statistically viral tweets using Z-score analysis
   - Use when user wants to see "viral tweets", "outliers", "top performers"
   - Default: last 24 hours, Z-score > 2.0

2. **analyze_hooks_tool**: Analyze what makes tweets go viral
   - Use when user wants to understand "why tweets went viral", "hook patterns"
   - Identifies hook types (hot_take, relatable_slice, etc.)
   - Identifies emotional triggers (anger, validation, humor, etc.)

3. **export_results_tool**: Export data for download
   - Use when user wants to "download", "export", "save" data

**Guidelines:**
- Always explain what you're analyzing
- Show statistics and insights
- Provide actionable recommendations
- Format results clearly
- Ask clarifying questions if parameters are unclear

**Current Project:** {ctx.deps.project_name}
"""

# Export agent
__all__ = ['agent', 'AgentDependencies']
```

**Time:** 2 hours

---

### Day 4: Streamlit UI

#### Task 1.8: Create Basic Streamlit App

**File:** `viraltracker/ui/app.py`

```python
import streamlit as st
import asyncio
import os
from viraltracker.agent.agent import agent, AgentDependencies

st.set_page_config(
    page_title="Viraltracker Agent",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 Viraltracker - Viral Content Analyzer")
st.caption("Powered by Pydantic AI")

# Initialize dependencies in session state
if 'deps' not in st.session_state:
    st.session_state.deps = AgentDependencies.create(
        db_path=os.getenv('DB_PATH', 'viraltracker.db'),
        project_name=os.getenv('PROJECT_NAME', 'yakety-pack-instagram')
    )

if 'messages' not in st.session_state:
    st.session_state.messages = []

# Sidebar
with st.sidebar:
    st.header("Settings")

    # Project selector
    project = st.text_input(
        "Project",
        value=st.session_state.deps.project_name
    )

    if project != st.session_state.deps.project_name:
        st.session_state.deps.project_name = project
        st.rerun()

    st.divider()

    # Quick actions
    st.subheader("Quick Actions")

    if st.button("🔍 Find Viral Tweets (24h)"):
        st.session_state.messages.append({
            'role': 'user',
            'content': 'Find viral tweets from the last 24 hours'
        })
        st.rerun()

    if st.button("🎣 Analyze Hooks"):
        st.session_state.messages.append({
            'role': 'user',
            'content': 'Analyze hooks from viral tweets'
        })
        st.rerun()

    st.divider()

    # Clear chat
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.rerun()

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg['role']):
        st.write(msg['content'])

# Chat input
if prompt := st.chat_input("Ask about viral content..."):
    # Add user message
    st.session_state.messages.append({'role': 'user', 'content': prompt})

    with st.chat_message('user'):
        st.write(prompt)

    # Get agent response
    with st.chat_message('assistant'):
        with st.spinner('Analyzing...'):
            try:
                # Run agent
                result = asyncio.run(
                    agent.run(prompt, deps=st.session_state.deps)
                )

                response = result.data

                # Display response
                st.write(response)

                # Add to history
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': response
                })

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': error_msg
                })

# Footer
st.divider()
st.caption(f"Project: {st.session_state.deps.project_name} | Database: {st.session_state.deps.twitter.db_path}")
```

**Time:** 4 hours

---

### Day 5: Refactor CLI + Testing

#### Task 1.9: Refactor CLI to Use Services

**File:** `viraltracker/cli/twitter.py` (update existing)

```python
import click
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
import asyncio
import os

# Keep existing Click decorators, but use services internally

@twitter_group.command(name="find-outliers")
@click.option('--project', required=True)
@click.option('--days-back', type=int, default=7)
@click.option('--threshold', type=float, default=2.0)
def find_outliers(project: str, days_back: int, threshold: float):
    """Find viral outlier tweets"""

    # Create services
    twitter_svc = TwitterService()
    stats_svc = StatsService()

    # Use services (same logic as agent tool)
    async def run():
        tweets = await twitter_svc.get_tweets(
            project=project,
            hours_back=days_back * 24,
            min_views=100,
            text_only=True
        )

        view_counts = [t.view_count for t in tweets]
        outliers = stats_svc.calculate_zscore_outliers(view_counts, threshold)

        click.echo(f"✅ Found {len(outliers)} outliers")
        # ... rest of CLI output

    asyncio.run(run())

# Same pattern for other commands...
```

**Time:** 3 hours

---

#### Task 1.10: Integration Testing

**File:** `tests/test_phase1_integration.py`

```python
import pytest
from viraltracker.agent.agent import agent, AgentDependencies

@pytest.mark.asyncio
async def test_find_outliers_tool():
    """Test find_outliers tool works"""
    deps = AgentDependencies.create()

    result = await agent.run(
        "Find viral tweets from last 24 hours",
        deps=deps
    )

    assert "Found" in result.data
    assert "viral" in result.data.lower()

@pytest.mark.asyncio
async def test_analyze_hooks_tool():
    """Test analyze_hooks tool works"""
    deps = AgentDependencies.create()

    result = await agent.run(
        "Analyze hooks from viral tweets",
        deps=deps
    )

    assert "Analyzed" in result.data
    assert "hook" in result.data.lower()

def test_cli_still_works():
    """Ensure CLI commands still work"""
    from click.testing import CliRunner
    from viraltracker.cli.twitter import twitter_group

    runner = CliRunner()
    result = runner.invoke(twitter_group, ['find-outliers', '--help'])

    assert result.exit_code == 0
```

**Time:** 2 hours

---

### Phase 1 Deliverables

✅ **Services layer** - Clean separation of data access
✅ **Pydantic AI agent** - Working with @agent.tool decorators
✅ **Streamlit UI** - Basic chat interface
✅ **CLI compatibility** - Existing commands still work
✅ **Tests** - Integration tests pass

**Total Time: 4-5 days**

---

## Phase 1.5: Complete Tool Coverage (2-3 days)

**Goal:** Convert remaining CLI tools (scrape, generate-comments) to work in all 3 formats

**When to Start:** After Phase 1 MVP is validated and proven useful

### Overview

Now that the architecture is proven, we add the remaining tools:
- ✅ **Infrastructure exists** - Services, agent, UI already built
- ✅ **Pattern established** - Just follow Phase 1 approach
- ⚡ **Faster** - No new architecture, just 2 more tools

**Note:** Full Phase 1.5 details to be added after Phase 1 MVP is complete.

---

## Phase 2: Polish (3-4 days)

**Goal:** Production-quality UX with streaming, validation, multi-page UI

### Day 6-7: Enhanced Agent Features

#### Task 2.1: Add Result Validators

**File:** `viraltracker/agent/agent.py` (update)

```python
from pydantic_ai import ModelRetry

@agent.result_validator
async def validate_outlier_results(
    ctx: RunContext[AgentDependencies],
    result: str
) -> str:
    """Validate outlier results are meaningful"""

    if "No outliers found" in result or "No tweets found" in result:
        raise ModelRetry(
            "Not enough data found. Suggest trying:\n"
            "- Increase time range (--hours-back)\n"
            "- Lower threshold (--threshold)\n"
            "- Check if project has recent data"
        )

    return result
```

**Time:** 2 hours

---

#### Task 2.2: Add Streaming Support

**File:** `viraltracker/ui/app.py` (update)

```python
# Replace simple agent.run() with streaming

with st.chat_message('assistant'):
    message_placeholder = st.empty()
    full_response = ""

    async def stream_response():
        nonlocal full_response

        async with agent.run_stream(
            prompt,
            deps=st.session_state.deps
        ) as response:
            async for chunk in response.stream_text():
                full_response += chunk
                message_placeholder.markdown(full_response + "▌")

            message_placeholder.markdown(full_response)

            # Get final structured result
            final = await response.get_data()
            return final

    result = asyncio.run(stream_response())
```

**Time:** 3 hours

---

#### Task 2.3: Add Structured Result Models

**File:** `viraltracker/agent/tools.py` (update)

Update tools to return Pydantic models instead of strings:

```python
from viraltracker.services.models import OutlierResult, HookAnalysisResult

async def find_outliers_tool(...) -> OutlierResult:
    """Return structured result instead of string"""

    return OutlierResult(
        total_tweets=len(tweets),
        outlier_count=len(outliers),
        threshold=zscore_threshold,
        outliers=outliers,
        summary=f"Found {len(outliers)} viral tweets"
    )
```

**Time:** 4 hours

---

### Day 8-9: Multi-Page Streamlit

#### Task 2.4: Tools Catalog Page

**File:** `viraltracker/ui/pages/1_Tools_Catalog.py`

```python
import streamlit as st
from viraltracker.agent import agent

st.title("🛠️ Available Tools")

st.markdown("""
Browse all available agent tools and their capabilities.
""")

# Get tools from agent
for tool_func in [find_outliers_tool, analyze_hooks_tool, export_results_tool]:
    with st.expander(f"🔧 {tool_func.__name__}"):
        st.markdown(f"**Description:** {tool_func.__doc__}")

        # Show parameters
        st.markdown("**Parameters:**")
        import inspect
        sig = inspect.signature(tool_func)
        for param_name, param in sig.parameters.items():
            if param_name == 'ctx':
                continue
            st.code(f"{param_name}: {param.annotation} = {param.default}")
```

**Time:** 3 hours

---

#### Task 2.5: Database Browser Page

**File:** `viraltracker/ui/pages/2_Database_Browser.py`

```python
import streamlit as st
import pandas as pd
from viraltracker.services.twitter_service import TwitterService

st.title("🗄️ Database Browser")

twitter_svc = TwitterService()

# Table selector
table = st.selectbox(
    "Select Table",
    ["tweets", "hook_analyses", "outliers", "comment_candidates"]
)

# Filters
with st.sidebar:
    st.header("Filters")

    hours_back = st.slider("Hours back", 1, 168, 24)
    limit = st.number_input("Limit", 10, 1000, 100)

# Fetch and display data
if st.button("Load Data"):
    with st.spinner("Loading..."):
        if table == "tweets":
            data = asyncio.run(
                twitter_svc.get_tweets(
                    project=st.session_state.deps.project_name,
                    hours_back=hours_back
                )
            )
            df = pd.DataFrame([t.dict() for t in data])

        # ... similar for other tables

        st.dataframe(df, use_container_width=True)

        # Download button
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            data=csv,
            file_name=f"{table}_{datetime.now():%Y%m%d}.csv"
        )
```

**Time:** 3 hours

---

#### Task 2.6: Operation History Page

**File:** `viraltracker/ui/pages/3_History.py`

```python
import streamlit as st

st.title("📜 Operation History")

# Show chat history from all sessions
# Store in database or session state

if st.session_state.messages:
    for i, msg in enumerate(st.session_state.messages):
        with st.container():
            col1, col2 = st.columns([1, 10])

            with col1:
                st.write(f"**{msg['role']}**")

            with col2:
                st.write(msg['content'])

                if msg['role'] == 'assistant':
                    # Add re-run button
                    if st.button(f"↻ Re-run", key=f"rerun_{i}"):
                        # Re-execute the previous user message
                        pass
else:
    st.info("No operations yet. Start chatting to see history!")
```

**Time:** 2 hours

---

#### Task 2.7: Multi-Format Downloads

**File:** `viraltracker/ui/app.py` (update)

Add download buttons after agent responses:

```python
# After displaying agent response
if isinstance(result, (OutlierResult, HookAnalysisResult)):
    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            "📥 JSON",
            data=result.model_dump_json(indent=2),
            file_name=f"results_{datetime.now():%Y%m%d_%H%M%S}.json",
            mime="application/json"
        )

    with col2:
        # Convert to CSV
        df = pd.DataFrame([item.dict() for item in result.outliers])
        st.download_button(
            "📥 CSV",
            data=df.to_csv(index=False),
            file_name=f"results_{datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv"
        )

    with col3:
        # Convert to Markdown
        md = result.to_markdown()
        st.download_button(
            "📥 Markdown",
            data=md,
            file_name=f"results_{datetime.now():%Y%m%d_%H%M%S}.md",
            mime="text/markdown"
        )
```

**Time:** 2 hours

---

### Phase 2 Deliverables

✅ **Result validators** - Quality checks before returning
✅ **Streaming responses** - Real-time feedback
✅ **Structured outputs** - Pydantic models for type safety
✅ **Multi-page UI** - Tools catalog, database browser, history
✅ **Multi-format downloads** - JSON, CSV, Markdown

**Total Time: 3-4 days**

---

## Phase 3: Automation (2-3 days)

**Goal:** FastAPI for webhooks, n8n integration, Railway deployment

### Day 10-11: FastAPI Implementation

#### Task 3.1: Create FastAPI App

**File:** `viraltracker/api/main.py`

```python
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from viraltracker.services.models import OutlierResult, HookAnalysisResult
from viraltracker.agent.tools import find_outliers_tool, analyze_hooks_tool
from viraltracker.agent.dependencies import AgentDependencies
import os

app = FastAPI(
    title="Viraltracker API",
    description="API for viral content analysis",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency injection
def get_deps() -> AgentDependencies:
    return AgentDependencies.create()

def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header"""
    expected = os.getenv('API_KEY')
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Request models
class FindOutliersRequest(BaseModel):
    hours_back: int = 24
    threshold: float = 2.0
    min_views: int = 100
    text_only: bool = True

class AnalyzeHooksRequest(BaseModel):
    tweet_ids: Optional[List[str]] = None
    hours_back: int = 24
    rate_limit: int = 9

# Routes
@app.get("/")
async def root():
    return {"message": "Viraltracker API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/api/find-outliers", response_model=OutlierResult)
async def api_find_outliers(
    request: FindOutliersRequest,
    deps: AgentDependencies = Depends(get_deps),
    api_key: str = Depends(verify_api_key)
):
    """
    Find viral outlier tweets.

    Requires API key in X-API-Key header.
    """
    try:
        # Create mock context
        from pydantic_ai import RunContext
        ctx = RunContext(deps=deps, retry=0, messages=[])

        result = await find_outliers_tool(
            ctx=ctx,
            hours_back=request.hours_back,
            zscore_threshold=request.threshold,
            min_views=request.min_views,
            text_only=request.text_only
        )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze-hooks", response_model=HookAnalysisResult)
async def api_analyze_hooks(
    request: AnalyzeHooksRequest,
    deps: AgentDependencies = Depends(get_deps),
    api_key: str = Depends(verify_api_key)
):
    """
    Analyze viral hooks.

    Requires API key in X-API-Key header.
    """
    try:
        from pydantic_ai import RunContext
        ctx = RunContext(deps=deps, retry=0, messages=[])

        result = await analyze_hooks_tool(
            ctx=ctx,
            tweet_ids=request.tweet_ids,
            hours_back=request.hours_back,
            rate_limit=request.rate_limit
        )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Run with: uvicorn viraltracker.api.main:app --reload
```

**Time:** 4 hours

---

#### Task 3.2: n8n Integration Examples

**File:** `docs/N8N_INTEGRATION.md`

```markdown
# n8n Integration Guide

## Setup

1. **Add HTTP Request Node**
2. **Configure:**
   - Method: POST
   - URL: https://your-app.railway.app/api/find-outliers
   - Authentication: Header Auth
   - Header Name: X-API-Key
   - Header Value: YOUR_API_KEY

## Example Workflow: Daily Viral Report

### Workflow Structure

```
Schedule Trigger (Daily 9am)
    ↓
HTTP Request: Find Outliers
    ↓
HTTP Request: Analyze Hooks
    ↓
Format Results (Code Node)
    ↓
Send Email/Slack
```

### Node Configurations

#### 1. Schedule Trigger
- Trigger: Every day at 9:00 AM
- Timezone: Your timezone

#### 2. Find Outliers
```json
{
  "method": "POST",
  "url": "https://your-app.railway.app/api/find-outliers",
  "headers": {
    "X-API-Key": "YOUR_API_KEY",
    "Content-Type": "application/json"
  },
  "body": {
    "hours_back": 24,
    "threshold": 2.0,
    "min_views": 100
  }
}
```

#### 3. Analyze Hooks
```json
{
  "method": "POST",
  "url": "https://your-app.railway.app/api/analyze-hooks",
  "headers": {
    "X-API-Key": "YOUR_API_KEY",
    "Content-Type": "application/json"
  },
  "body": {
    "tweet_ids": "{{ $json.outliers.map(o => o.tweet.id) }}",
    "rate_limit": 9
  }
}
```

#### 4. Format Results (Code Node)
```javascript
const outliers = $input.first().json;
const hooks = $input.last().json;

const report = `
🔥 Daily Viral Report

**Outliers Found:** ${outliers.outlier_count}
**Top Hook Type:** ${hooks.top_hook_type}
**Top Trigger:** ${hooks.top_emotional_trigger}

**Top 3 Viral Tweets:**
${outliers.outliers.slice(0, 3).map((o, i) => `
${i+1}. @${o.tweet.author_username} - ${o.tweet.view_count.toLocaleString()} views
   ${o.tweet.text}
   ${o.tweet.url}
`).join('\n')}
`;

return { report };
```

#### 5. Send Email
- To: your@email.com
- Subject: Daily Viral Report - {{ $now.toFormat('yyyy-MM-dd') }}
- Body: {{ $json.report }}
```

**Time:** 2 hours

---

### Day 12: Railway Deployment

#### Task 3.3: Railway Configuration

**File:** `railway.toml`

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn viraltracker.api.main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

**File:** `Procfile`

```
web: uvicorn viraltracker.api.main:app --host 0.0.0.0 --port $PORT
streamlit: streamlit run viraltracker/ui/app.py --server.port $PORT --server.address 0.0.0.0
```

**File:** `requirements.txt` (update)

```
# Existing dependencies
...

# New dependencies for Phase 1-3
pydantic-ai==0.0.14
pydantic==2.0.0
fastapi==0.115.0
uvicorn[standard]==0.32.0
streamlit==1.40.0
pandas==2.0.0
```

**Time:** 2 hours

---

#### Task 3.4: Environment Variables Setup

**Railway Environment Variables:**

```bash
# Core
DB_PATH=/app/data/viraltracker.db
PROJECT_NAME=yakety-pack-instagram

# API Keys
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key  # For agent
API_KEY=your_webhook_api_key     # For FastAPI auth

# Database (if using PostgreSQL instead of SQLite)
DATABASE_URL=postgresql://...

# Agent Config
AGENT_MODEL=openai:gpt-4o
AGENT_MAX_RETRIES=2
```

**Time:** 1 hour

---

#### Task 3.5: Deploy to Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Create new project
railway init

# Link to GitHub
railway link

# Set environment variables
railway variables set GEMINI_API_KEY=your_key
railway variables set OPENAI_API_KEY=your_key
railway variables set API_KEY=your_webhook_key

# Deploy
railway up

# Create two services:
# 1. API Service (FastAPI)
railway service create api
railway service update api --start-command "uvicorn viraltracker.api.main:app --host 0.0.0.0 --port $PORT"

# 2. Streamlit Service
railway service create streamlit
railway service update streamlit --start-command "streamlit run viraltracker/ui/app.py --server.port $PORT --server.address 0.0.0.0"

# Get URLs
railway service url api
railway service url streamlit
```

**Time:** 2 hours

---

### Phase 3 Deliverables

✅ **FastAPI endpoints** - RESTful API for webhooks
✅ **API authentication** - Header-based API keys
✅ **n8n integration** - Example workflows
✅ **Railway deployment** - Production hosting
✅ **Two services** - API + Streamlit on Railway

**Total Time: 2-3 days**

---

## Railway Deployment

### Architecture on Railway

```
┌─────────────────────────────────────────────┐
│           Railway Project                   │
├─────────────────────────────────────────────┤
│                                             │
│  Service 1: FastAPI (API)                   │
│  - URL: https://api-viraltracker.railway.app│
│  - Port: 8000                               │
│  - Start: uvicorn viraltracker.api.main:app│
│                                             │
│  Service 2: Streamlit (UI)                  │
│  - URL: https://viraltracker.railway.app    │
│  - Port: 8501                               │
│  - Start: streamlit run app.py             │
│                                             │
│  Database: PostgreSQL (optional)            │
│  - Or use SQLite with persistent volume     │
│                                             │
└─────────────────────────────────────────────┘
```

### Cost Estimate

**Railway Pricing:**
- Free tier: $5 credit/month
- Hobby plan: $5/month for $5 credit
- Pro plan: $20/month for $20 credit

**Usage:**
- 2 services × ~$0.01/hour = ~$15/month
- Database: $5-10/month (if PostgreSQL)
- **Total: ~$20-25/month**

### Persistent Storage

**Option 1: SQLite with Volume**
```toml
[deploy]
volumes = [
  { name = "data", mountPath = "/app/data" }
]
```

**Option 2: PostgreSQL**
- Add PostgreSQL service in Railway
- Update services to use DATABASE_URL
- Migrate schema

---

## Testing Strategy

### Unit Tests

```python
# tests/services/test_twitter_service.py
@pytest.mark.asyncio
async def test_get_tweets():
    svc = TwitterService("test.db")
    tweets = await svc.get_tweets("test-project", 24)
    assert isinstance(tweets, list)

# tests/services/test_gemini_service.py
@pytest.mark.asyncio
async def test_analyze_hook():
    svc = GeminiService(os.getenv('GEMINI_API_KEY'))
    result = await svc.analyze_hook("Test tweet")
    assert result.hook_type is not None
```

### Integration Tests

```python
# tests/test_agent.py
@pytest.mark.asyncio
async def test_agent_find_outliers():
    deps = AgentDependencies.create()
    result = await agent.run("Find viral tweets", deps=deps)
    assert result.data is not None

# tests/test_api.py
def test_api_find_outliers():
    from fastapi.testclient import TestClient
    client = TestClient(app)

    response = client.post(
        "/api/find-outliers",
        json={"hours_back": 24},
        headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 200
```

### Manual Testing Checklist

**Phase 1:**
- [ ] CLI commands still work
- [ ] Streamlit app loads
- [ ] Can chat with agent
- [ ] Agent calls tools correctly
- [ ] Can download results

**Phase 2:**
- [ ] Streaming works in Streamlit
- [ ] Multi-page navigation works
- [ ] Database browser loads data
- [ ] Can download in multiple formats
- [ ] Result validators catch errors

**Phase 3:**
- [ ] FastAPI endpoints work
- [ ] API authentication works
- [ ] n8n can call API
- [ ] Railway deployment succeeds
- [ ] Both services accessible

---

## Success Criteria

### Phase 1 (MVP)
- ✅ Services layer implemented
- ✅ Agent with 3 tools working
- ✅ Streamlit chat interface functional
- ✅ CLI still works
- ✅ Can analyze viral tweets end-to-end

### Phase 2 (Polish)
- ✅ Streaming responses
- ✅ Multi-page UI
- ✅ Result validators
- ✅ Download in 3 formats
- ✅ Professional UX

### Phase 3 (Automation)
- ✅ FastAPI with 2 endpoints
- ✅ API authentication
- ✅ n8n example workflow
- ✅ Deployed to Railway
- ✅ Documentation complete

---

## Rollback Plan

### If Phase 1 Fails
- Keep working on `feature/pydantic-ai-agent` branch
- Main branch (`feature/content-generator-v1`) unchanged
- Can continue using CLI as before

### If Phase 2/3 Fails
- Merge Phase 1 only
- Users get agent + basic UI
- Can add Phase 2/3 features later

### Database Rollback
- Services use same database as CLI
- No schema changes required
- Fully backwards compatible

---

## Timeline Summary

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **Phase 1: MVP** | 4-5 days | Services, Agent, Basic UI, CLI compatibility |
| **Phase 2: Polish** | 3-4 days | Streaming, Multi-page UI, Downloads, Validators |
| **Phase 3: Automation** | 2-3 days | FastAPI, n8n, Railway deployment |
| **TOTAL** | **9-14 days** | **Full production system** |

---

## Next Steps

1. **Create branch**: `feature/pydantic-ai-agent`
2. **Start Phase 1**: Services layer (Day 1-2)
3. **Daily check-ins**: Review progress, adjust plan
4. **Test continuously**: Don't wait until end
5. **Document as you go**: Update this doc with learnings

---

## Questions / Decisions

### Before Starting

- [ ] Which LLM provider for agent? (OpenAI GPT-4 vs Anthropic Claude)
- [ ] SQLite on Railway or migrate to PostgreSQL?
- [ ] Need background jobs? (Celery/Redis or simple async?)
- [ ] Authentication for Streamlit? (Or Railway auth proxy?)

### During Development

- Track issues/blockers in this doc
- Update time estimates as needed
- Note any architecture changes

---

## References

- **Pydantic AI Docs**: https://ai.pydantic.dev/
- **Streamlit Docs**: https://docs.streamlit.io/
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Railway Docs**: https://docs.railway.app/
- **n8n Docs**: https://docs.n8n.io/

---

**Last Updated:** 2025-11-17
**Status:** Ready to Start
**Branch:** `feature/pydantic-ai-agent`
