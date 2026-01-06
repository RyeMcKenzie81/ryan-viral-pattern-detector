"""
Orchestrator Agent - Routes requests to specialized agents

This is the main entry point for all agent requests. It analyzes the user's
query and routes it to the appropriate specialized agent:
- Twitter Agent: Twitter/X data operations
- TikTok Agent: TikTok data operations
- YouTube Agent: YouTube data operations
- Facebook Agent: Facebook Ad Library operations
- Analysis Agent: Statistical analysis and AI-powered insights
- Ad Creation Agent: Facebook ad creative generation
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

from ..core.config import Config

# Create orchestrator agent
orchestrator = Agent(
    model=Config.get_model("orchestrator"),
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

6. **Ad Creation Agent** - For Facebook ad creative generation:
   - Creating Facebook ad variations using AI
   - Analyzing reference ads with Claude vision
   - Selecting viral hooks and product images
   - Generating ad creatives with Gemini Nano Banana
   - Dual AI review (Claude + Gemini) with OR logic
   - Sequential generation of 5 ad variations

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

@orchestrator.tool
async def route_to_ad_creation_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Ad Creation Agent for Facebook ad creative generation.

    This agent generates Facebook ad variations using:
    - Claude vision for reference ad analysis
    - Viral hooks from database
    - Product images from database
    - Gemini Nano Banana for ad generation
    - Dual AI review (Claude + Gemini) with OR logic

    The agent generates 5 ad variations sequentially with automatic quality review.
    """
    logger.info(f"Routing to Ad Creation Agent: {query}")
    result = await ad_creation_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def resolve_product_name(
    ctx: RunContext[AgentDependencies],
    product_name: str
) -> str:
    """Look up product by name in database for natural language queries.

    Use this tool when the user mentions a product by name and you need to find
    the product_id for ad creation or other operations.

    Args:
        product_name: Product name or partial name (e.g., "Wonder Paws", "Collagen 3x")

    Returns:
        JSON string with matching products: {
            "success": true,
            "products": [
                {"id": "uuid", "name": "Product Name", "brand_id": "uuid"},
                ...
            ],
            "count": 2
        }

    Example:
        User: "Create 5 ads for Wonder Paws Collagen 3x"
        → Call resolve_product_name("Wonder Paws Collagen 3x")
        → Get product_id from result
        → Route to ad creation agent with product_id
    """
    import json
    logger.info(f"Resolving product name: {product_name}")

    try:
        products = await ctx.deps.ad_creation.search_products_by_name(product_name)

        if not products:
            return json.dumps({
                "success": False,
                "error": f"No products found matching '{product_name}'",
                "count": 0
            })

        return json.dumps({
            "success": True,
            "products": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "brand_id": str(p.brand_id)
                }
                for p in products
            ],
            "count": len(products)
        })

    except Exception as e:
        logger.error(f"Error resolving product name: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "count": 0
        })

logger.info("Orchestrator Agent initialized with 7 tools (6 routing + 1 utility)")
