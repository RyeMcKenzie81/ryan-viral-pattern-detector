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
- Ad Intelligence Agent: Ad account analysis and optimization
"""

import logging
import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolReturnPart, ThinkingPart
from .dependencies import AgentDependencies

# Import all specialized agents
from .agents import (
    twitter_agent,
    tiktok_agent,
    youtube_agent,
    facebook_agent,
    analysis_agent,
    ad_creation_agent,
    ad_intelligence_agent,
    klaviyo_agent,
    ops_agent,
    competitor_agent,
)

logger = logging.getLogger(__name__)

from ..core.config import Config


# ---------------------------------------------------------------------------
# History processor: trim old tool results to keep context window manageable
# ---------------------------------------------------------------------------

def trim_long_tool_results(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    """Truncate old tool results and drop old thinking parts.

    Strategy:
    - Last 6 messages: untouched (current turn + recent context)
    - Older messages: truncate ToolReturnPart.content to 500 chars,
      drop ThinkingPart entirely from ModelResponse
    """
    if len(messages) <= 6:
        return messages

    cutoff = len(messages) - 6

    for i, msg in enumerate(messages):
        if i >= cutoff:
            break
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content = str(part.content)
                    if len(content) > 500:
                        part.content = content[:500] + f"... [truncated from {len(content)} chars]"
        elif isinstance(msg, ModelResponse):
            msg.parts = [p for p in msg.parts if not isinstance(p, ThinkingPart)]
            # Keep at least one part to preserve message alternation
            if not msg.parts:
                from pydantic_ai.messages import TextPart
                msg.parts = [TextPart(content="(trimmed)")]

    return messages


# Create orchestrator agent
orchestrator = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    history_processors=[trim_long_tool_results],
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

4. **Facebook Agent** - For Facebook Ad Library and Meta Ads operations:
   - Searching ads by URL
   - Scraping ads from specific pages
   - Checking Meta ad account info for a brand
   - Getting asset download statistics

5. **Analysis Agent** - For advanced analytics, brand research, SEO, and Reddit research:
   - Finding viral outliers using statistical methods
   - Analyzing tweet hooks with AI
   - Exporting comprehensive analysis reports
   - Getting brand research summaries and analysis counts
   - Listing SEO projects and checking project status
   - SEO keyword discovery from seed terms
   - Finding "striking distance" keyword opportunities
   - Checking keyword rankings and ranking history
   - Listing SEO articles by status (published, draft, in_review)
   - GA4 page analytics and traffic source breakdowns
   - Reddit research: searching posts and analyzing sentiment
   - Responds to: "what does Reddit say about X", "Reddit sentiment on X", "search Reddit for X"
   - Also responds to: "find keywords for X", "SEO opportunities", "how are our articles ranking?"
   - Also responds to: "page analytics", "traffic sources", "where is our traffic coming from?"

6. **Ad Creation Agent** - For Facebook ad creative generation, templates, and translation:
   - Creating Facebook ad variations using AI
   - Analyzing reference ads with Claude vision
   - Selecting viral hooks and product images
   - Generating ad creatives with Gemini Nano Banana
   - Dual AI review (Claude + Gemini) with OR logic
   - Sequential generation of 5 ad variations
   - Template queue stats and pending template listing
   - Looking up ads by any ID format (UUID, filename fragment, Meta ad ID)
   - Translating existing ads into other languages (Spanish, Portuguese, etc.)

7. **Klaviyo Agent** - For email marketing operations:
   - Listing and creating email campaigns
   - Creating and managing automation flows (post-purchase, welcome series, etc.)
   - Viewing campaign and flow performance metrics
   - Managing lists and segments

8. **Ad Intelligence Agent** - For ad account analysis and optimization:
   - Full account analysis (classify → baseline → diagnose → recommend)
   - Recommendation management (view, acknowledge, act on, ignore)
   - Fatigue detection (frequency + CTR trend analysis)
   - Coverage gap analysis (awareness level × creative format inventory)
   - Congruence checking (creative-copy-landing page alignment)
   - Ad performance queries (top ads, spend breakdown, campaign comparison)
   - Responds to: /analyze_account, /recommend, /fatigue_check, /coverage_gaps, /congruence_check
   - Also responds to: "what are my top ads?", "how much did I spend?", "which campaigns are best?"
   - Also responds to: "analyze my ad account", "which ads should I kill", "check for fatigued ads"

9. **Competitor Agent** - For competitor research and intelligence:
   - Listing tracked competitors and their products
   - Analyzing competitor landing pages (13-layer belief-first analysis)
   - Amazon review analysis (pain points, objections, language patterns)
   - Intel pack generation (video ad analysis → hooks, angles, personas)
   - Remixing competitor video structures for your brand
   - Generating alternative hooks from competitor concepts
   - Persona synthesis: build 4D personas from competitor data or product data
   - Export personas as copywriting briefs for ad creation
   - Responds to: "analyze my competitors", "what are competitors doing?", "competitor landing pages"
   - Also responds to: "scrape competitor X", "remix their video", "competitor review insights"
   - Also responds to: "build a persona for X", "generate persona from competitor", "persona copy brief"

10. **Ops Agent** - For operational queries and job management:
   - Queue background jobs (meta sync, ad classification, template scrape, etc.)
   - Check job status and progress
   - List recent jobs (filter by brand, status)
   - List brands the user has access to
   - System health summary (job success/failure rates, what ran overnight)
   - Responds to: "queue a meta sync", "run ad classification", "start a template scrape"
   - Also responds to: "check job status", "what's running?", "any failed jobs?", "system health"
   - Also responds to: "list my brands", "what brands do I have?", "what happened overnight?"

**Follow-up Handling:**
When the user says "that", "those", "it", "them", "the same", etc., resolve the
referent from session context (injected via dynamic instructions). Include relevant
entity IDs (brand_id, product_id, competitor_id, etc.) when routing to sub-agents
so they don't have to re-ask the user.

**Routing Priority Rules:**
- For compound queries that combine **performance data** (sales, ROAS, top ads) with
  **translation** (translate, translated, translation status, Spanish, Portuguese):
  1. First route to **Ad Intelligence Agent** to get the ad IDs that match performance criteria
  2. Then route to **Ad Creation Agent** with those ad IDs for translation or translation status checks
- If the request is purely about translating specific ads (by ID), route directly to Ad Creation Agent.
- For multi-step queries, YOU can call multiple agent routing tools sequentially.
  Pass results from one agent to the next.

**Your Responsibilities:**
- Understand the user's intent
- Route to the most appropriate specialized agent
- Pass relevant context and parameters
- Coordinate multi-step workflows by calling multiple agents sequentially when needed

**Important:**
- ALWAYS route to a specialized agent - do not try to handle requests directly
- Use the routing tools to delegate work
- Provide clear summaries of results from specialized agents
"""
)


# ---------------------------------------------------------------------------
# Dynamic instructions: inject session state each turn
# ---------------------------------------------------------------------------

@orchestrator.instructions
def session_instructions(ctx: RunContext[AgentDependencies]) -> str:
    """Inject session state as dynamic instructions.

    Re-evaluated every turn (old instructions dropped from history).
    Gives the orchestrator awareness of active brand, product, competitor, etc.
    so it can resolve follow-up references like "analyze those" or "that brand".
    """
    state = ctx.deps.result_cache.custom.get("session_state")
    if not state:
        return ""

    parts = []
    if state.get("brand_name"):
        parts.append(f"brand={state['brand_name']} ({state.get('brand_id', '?')})")
    if state.get("product_name"):
        parts.append(f"product={state['product_name']} ({state.get('product_id', '?')})")
    # Show all competitors if a list was captured, otherwise single
    if state.get("competitor_ids") and state.get("competitor_names"):
        comp_pairs = [
            f"{n} ({i})" for n, i in
            zip(state["competitor_names"], state["competitor_ids"])
        ]
        parts.append(f"competitors=[{', '.join(comp_pairs)}]")
    elif state.get("competitor_id"):
        parts.append(f"competitor={state.get('competitor_name', '?')} ({state['competitor_id']})")
    if state.get("persona_id"):
        parts.append(f"persona={state.get('persona_name') or state['persona_id']}")
    if state.get("seo_project_id"):
        parts.append(f"seo_project={state.get('seo_project_name') or state['seo_project_id']}")
    if state.get("last_agent"):
        parts.append(f"last_agent={state['last_agent']}")

    if not parts:
        return ""

    return (
        f"[Session: {', '.join(parts)}]\n"
        "When the user says 'that', 'it', 'those', 'the same' — resolve from session context above. "
        "Include relevant entity IDs when routing to sub-agents. "
        "Do NOT re-ask for an ID already in the session."
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
    """Route request to Ad Creation Agent for Facebook ad creative generation and translation.

    This agent generates Facebook ad variations using:
    - Claude vision for reference ad analysis
    - Viral hooks from database
    - Product images from database
    - Gemini for ad generation
    - Dual AI review (Claude + Gemini) with OR logic

    Also handles ad TRANSLATION into other languages (Spanish, Portuguese, etc.):
    - Translating existing ads into other languages
    - Looking up ads by ID/filename to check translation status
    - Checking which ads have or haven't been translated

    Route here when users mention: translate, translation, Spanish, Portuguese,
    language, or ask about translation status of ads.
    """
    logger.info(f"Routing to Ad Creation Agent: {query}")
    result = await ad_creation_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_ad_intelligence_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Ad Intelligence Agent for ad account analysis and optimization.

    This agent analyzes Meta ad account performance using a 4-layer model:
    1. Classification - Classify ads by awareness level and creative format
    2. Baselines - Compute contextual cohort benchmarks (p25/median/p75)
    3. Diagnostics - Rules-based health assessment with 12 diagnostic rules
    4. Recommendations - Actionable suggestions with evidence

    Also supports standalone analyses: fatigue detection, coverage gaps, congruence checking.

    Route here when users ask about:
    - Ad account analysis or optimization
    - Which ads to kill or scale
    - Ad fatigue or frequency issues
    - Coverage gaps or missing awareness levels
    - Creative-copy-landing page alignment
    - Ad recommendations or what to do next
    - Ad performance queries (top ads, spend, ROAS, campaign breakdown)
    - Account summaries or period-over-period comparisons
    - Individual ad performance details
    """
    # Inject cached brand context for follow-up queries
    cached_brand_id = ctx.deps.result_cache.custom.get("ad_intelligence_brand_id")
    cached_brand_name = ctx.deps.result_cache.custom.get("ad_intelligence_brand_name")
    cached_run_id = ctx.deps.result_cache.custom.get("ad_intelligence_run_id")
    if cached_brand_id and cached_brand_name:
        context_prefix = (
            f"[Context: The user is currently working with brand '{cached_brand_name}' "
            f"(brand_id: {cached_brand_id})."
        )
        if cached_run_id:
            context_prefix += f" The latest analysis run_id is {cached_run_id}."
        context_prefix += " Use this brand unless the user specifies a different one.]\n\n"
        query = context_prefix + query

    # Clear stale side-channel result before sub-agent runs
    ctx.deps.result_cache.custom.pop("ad_intelligence_result", None)

    logger.info(f"Routing to Ad Intelligence Agent: {query}")
    handler_factory = ctx.deps.result_cache.custom.get("_make_event_handler")
    handler = handler_factory("Ad Intelligence") if handler_factory else None
    result = await ad_intelligence_agent.run(
        query, deps=ctx.deps, event_stream_handler=handler
    )

    # Return raw ChatRenderer markdown, bypassing sub-agent LLM paraphrase
    cached = ctx.deps.result_cache.custom.get("ad_intelligence_result")
    if cached and "rendered_markdown" in cached:
        return cached["rendered_markdown"]
    return result.output

@orchestrator.tool
async def route_to_klaviyo_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Klaviyo Agent for email marketing operations.

    This agent manages Klaviyo email campaigns, automation flows, and analytics.

    Route here when users ask about:
    - Email campaigns (create, send, schedule, list)
    - Automation flows (post-purchase, welcome series, abandoned cart, win-back)
    - Email marketing metrics and analytics
    - Mailing lists and segments
    - Klaviyo integration management
    """
    logger.info(f"Routing to Klaviyo Agent: {query}")
    result = await klaviyo_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_ops_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Ops Agent for job management and system operations.

    This agent handles operational queries:
    - Queueing background jobs (meta sync, ad classification, template scrape, etc.)
    - Checking job status and progress
    - Listing recent jobs filtered by brand or status
    - Listing brands the user has access to
    - System health overview (success/failure rates, active schedules)

    Route here when users ask about:
    - Running or queueing any background job
    - Checking if a job finished or failed
    - What's currently running or what happened overnight
    - Listing their brands or finding a brand ID
    - System status or health
    """
    if os.getenv("CHAT_OPS_ENABLED", "true").lower() == "false":
        return "Ops tools are currently disabled. Set CHAT_OPS_ENABLED=true to enable."
    logger.info(f"Routing to Ops Agent: {query}")
    result = await ops_agent.run(query, deps=ctx.deps)
    return result.output

@orchestrator.tool
async def route_to_competitor_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """Route request to Competitor Agent for competitor research and intelligence.

    This agent handles competitor analysis:
    - Listing tracked competitors and their products
    - Analyzing competitor landing pages (scraping + 13-layer belief-first analysis)
    - Amazon review analysis (pain points, objections, language patterns)
    - Intel pack generation and retrieval (video ad analysis)
    - Remixing competitor video structures for the user's brand
    - Generating alternative hooks from competitor concepts

    Route here when users ask about:
    - Competitor research, analysis, or strategy
    - Landing page or Amazon review insights
    - "What are my competitors doing?"
    - Intel packs, video analysis, or remixing
    """
    logger.info(f"Routing to Competitor Agent: {query}")
    result = await competitor_agent.run(query, deps=ctx.deps)
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

logger.info("Orchestrator Agent initialized with 11 tools (9 routing + 1 utility)")
