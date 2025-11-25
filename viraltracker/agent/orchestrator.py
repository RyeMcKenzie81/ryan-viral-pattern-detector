"""
Orchestrator Agent - Routes requests to specialized agents

This is the main entry point for all agent requests. It analyzes the user's
query and routes it to the appropriate specialized agent:
- Twitter Agent: Twitter/X data operations
- TikTok Agent: TikTok data operations
- YouTube Agent: YouTube data operations
- Facebook Agent: Facebook Ad Library operations
- Analysis Agent: Statistical analysis and AI-powered insights
"""

import logging
from pydantic_ai import Agent, RunContext
from .dependencies import AgentDependencies

# Import all specialized agents
from .agents import (
    twitter_agent,
    tiktok_agent,
    youtube_agent,
    facebook_agent,
    analysis_agent,
    ad_creation_agent
)

logger = logging.getLogger(__name__)

# Create orchestrator agent
orchestrator = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Orchestrator Agent for the ViralTracker system.

Your role is to analyze user requests and route them to the appropriate specialized agent.

**Available Specialized Agents:**

1. **Twitter Agent** - For Twitter/X operations:
   - Searching and scraping tweets by keyword
   - Getting top tweets by engagement
   - Finding comment opportunities
   - Analyzing search terms
   - Generating content from viral hooks
   - Exporting tweet data

2. **TikTok Agent** - For TikTok operations:
   - Searching TikTok by keyword or hashtag
   - Scraping user accounts
   - Analyzing individual or batch videos

3. **YouTube Agent** - For YouTube operations:
   - Searching YouTube for viral videos and Shorts

4. **Facebook Agent** - For Facebook Ad Library operations:
   - Searching ads by URL
   - Scraping ads from specific pages

5. **Analysis Agent** - For advanced analytics:
   - Finding viral outliers using statistical methods
   - Analyzing tweet hooks with AI
   - Exporting comprehensive analysis reports

**Your Responsibilities:**
- Understand the user's intent
- Route to the most appropriate specialized agent
- Pass relevant context and parameters
- Coordinate multi-step workflows if needed

**Important:**
- ALWAYS route to a specialized agent - do not try to handle requests directly
- Use the routing tools to delegate work
- Provide clear summaries of results from specialized agents
"""
)

# Routing tools
@orchestrator.tool
async def route_to_twitter_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Twitter Agent for Twitter/X operations."""
    logger.info(f"Routing to Twitter Agent: {query}")
    result = await twitter_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_tiktok_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to TikTok Agent for TikTok operations."""
    logger.info(f"Routing to TikTok Agent: {query}")
    result = await tiktok_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_youtube_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to YouTube Agent for YouTube operations."""
    logger.info(f"Routing to YouTube Agent: {query}")
    result = await youtube_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_facebook_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Facebook Agent for Facebook Ad Library operations."""
    logger.info(f"Routing to Facebook Agent: {query}")
    result = await facebook_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_analysis_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Analysis Agent for statistical and AI analysis."""
    logger.info(f"Routing to Analysis Agent: {query}")
    result = await analysis_agent.run(query, deps=ctx.deps)
    return result.output

logger.info("Orchestrator Agent initialized with 5 routing tools")
