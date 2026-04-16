"""
Competitor Intelligence Agent - Specialized agent for competitor research and analysis.

This agent exposes 8 tools:
- Discovery: list_competitors, get_competitor_summary
- Research: analyze_competitor_landing_pages, get_amazon_review_insights
- Intel packs: get_intel_pack, queue_intel_pack_analysis
- Creative: remix_competitor_video, generate_competitor_hooks
"""

import json
import logging
import re
from typing import Dict, List, Optional

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies
from ...core.config import Config

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


async def _resolve_brand(brand_id: str) -> str:
    """Resolve a brand name or UUID to a valid brand UUID."""
    if _UUID_RE.match(brand_id):
        return brand_id

    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("brands").select("id, name").execute()
    brands = result.data or []

    search = brand_id.lower().strip()

    # Exact match
    for b in brands:
        if b["name"].lower() == search:
            return b["id"]

    # Substring match
    matches = [b for b in brands if search in b["name"].lower() or b["name"].lower() in search]
    if len(matches) == 1:
        return matches[0]["id"]

    # Word overlap
    if not matches:
        search_words = set(search.split())
        matches = [b for b in brands if search_words & set(b["name"].lower().split())]
        if len(matches) == 1:
            return matches[0]["id"]

    if matches:
        names = ", ".join(f"**{m['name']}**" for m in matches)
        raise ValueError(f"Multiple brands match '{brand_id}': {names}. Please be more specific.")
    raise ValueError(f"No brand found matching '{brand_id}'.")

competitor_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Competitor Intelligence specialist agent.

**Your role:** Help users research competitors, analyze their strategies, and extract
actionable insights for ad creation and positioning.

**Primary tools:**
- list_competitors: See all tracked competitors for a brand
- get_competitor_summary: Deep overview of a competitor (products, ads, pages, reviews)
- analyze_competitor_landing_pages: Trigger AI analysis of competitor landing pages
- get_amazon_review_insights: Get structured analysis of competitor Amazon reviews
- get_intel_pack: Retrieve a generated ingredient pack (hooks, angles, pain points)
- queue_intel_pack_analysis: Start background video analysis for a competitor
- remix_competitor_video: Adapt a competitor's video structure for the user's brand
- generate_competitor_hooks: Generate alternative hooks from a competitor video

**Guidelines:**
- When the user mentions a competitor by name, resolve it from the list first
- For long-running operations (landing page scrape, intel pack), explain it's queued
- Present insights in a structured, actionable format
- Connect findings back to opportunities for the user's brand
""",
)


# ============================================================================
# DISCOVERY TOOLS
# ============================================================================


@competitor_agent.tool(
    metadata={
        "category": "Discovery",
        "use_cases": [
            "See tracked competitors",
            "List competitors for a brand",
        ],
    }
)
async def list_competitors(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """List all competitors tracked for a brand.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: UUID or name of the brand (e.g. "Martin Clinic")

    Returns:
        Formatted list of competitors with product counts and ad stats.
    """
    brand_id = await _resolve_brand(brand_id)
    service = ctx.deps.competitor
    competitors = service.get_competitors_for_brand(brand_id)

    if not competitors:
        return "No competitors tracked for this brand yet."

    lines = []
    for c in competitors:
        stats = service.get_competitor_stats(c["id"])
        lines.append(
            f"- **{c['name']}** ({c.get('website', 'no website')})\n"
            f"  Products: {stats.get('products', 0)} · "
            f"Ads: {stats.get('ads', 0)} · "
            f"Landing pages: {stats.get('landing_pages', 0)} · "
            f"Amazon URLs: {stats.get('amazon_urls', 0)}\n"
            f"  ID: `{c['id']}`"
        )

    return f"**Competitors ({len(competitors)}):**\n\n" + "\n\n".join(lines)


@competitor_agent.tool(
    metadata={
        "category": "Discovery",
        "use_cases": [
            "Deep dive on a competitor",
            "Get competitor overview",
        ],
    }
)
async def get_competitor_summary(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
) -> str:
    """Get a detailed summary of a competitor including products, landing page
    analysis stats, and Amazon review analysis stats.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID of the competitor

    Returns:
        Structured summary with products, analysis coverage, and key findings.
    """
    service = ctx.deps.competitor

    competitor = service.get_competitor(competitor_id)
    if not competitor:
        return f"Competitor {competitor_id} not found."

    products = service.get_competitor_products(competitor_id)
    stats = service.get_competitor_stats(competitor_id)
    lp_stats = service.get_landing_page_stats(competitor_id)
    belief_stats = service.get_belief_first_analysis_stats_for_competitor(competitor_id)

    # Build summary
    sections = [
        f"## {competitor['name']}",
        f"Website: {competitor.get('website', 'N/A')}",
        "",
        f"### Stats",
        f"- Ads tracked: {stats.get('ads', 0)}",
        f"- Landing pages: {lp_stats.get('total', 0)} "
        f"(analyzed: {lp_stats.get('analyzed', 0)}, pending: {lp_stats.get('pending', 0)})",
        f"- Belief-first analyses: {belief_stats.get('analyzed', 0)}/{belief_stats.get('total', 0)}",
        f"- Amazon URLs: {stats.get('amazon_urls', 0)}",
    ]

    if products:
        sections.append("")
        sections.append("### Products")
        for p in products:
            variants = service.get_competitor_product_variants(p["id"])
            variant_str = f" ({len(variants)} variants)" if variants else ""
            sections.append(f"- **{p['name']}**{variant_str} · ID: `{p['id']}`")

    # Check for intel packs
    intel_service = ctx.deps.competitor_intel
    packs = intel_service.get_packs_for_competitor(competitor_id)
    if packs:
        sections.append("")
        sections.append("### Intel Packs")
        for pack in packs[:3]:
            coverage = pack.get("field_coverage", {})
            sections.append(
                f"- Pack `{pack['id'][:8]}...` — "
                f"{pack.get('n_videos', '?')} videos analyzed · "
                f"Status: {pack.get('status', '?')} · "
                f"Coverage: {json.dumps(coverage)}"
            )

    return "\n".join(sections)


# ============================================================================
# RESEARCH TOOLS
# ============================================================================


@competitor_agent.tool(
    metadata={
        "category": "Research",
        "use_cases": [
            "Analyze competitor landing pages",
            "Scrape and analyze competitor pages",
        ],
    }
)
async def analyze_competitor_landing_pages(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
    belief_first: bool = True,
) -> str:
    """Scrape and analyze landing pages for a competitor.

    This runs the 13-layer belief-first analysis by default, extracting
    strategic insights about messaging, positioning, and conversion tactics.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID of the competitor
        belief_first: If True, runs deep belief-first analysis (default: True)

    Returns:
        Summary of analysis results or status if already analyzed.
    """
    service = ctx.deps.competitor
    stats = service.get_landing_page_stats(competitor_id)

    if stats.get("total", 0) == 0:
        # Need to scrape first
        try:
            scraped = service.scrape_landing_pages_for_competitor(competitor_id)
            msg = f"Scraped {len(scraped)} landing pages. "
        except Exception as e:
            return f"Failed to scrape landing pages: {e}"
    else:
        msg = f"{stats['total']} landing pages already scraped. "

    if belief_first:
        pending = stats.get("total", 0) - stats.get("analyzed", 0)
        if pending > 0:
            try:
                results = service.analyze_landing_pages_belief_first_for_competitor(
                    competitor_id
                )
                msg += f"Ran belief-first analysis on {len(results)} pages."
            except Exception as e:
                return msg + f"Analysis failed: {e}"
        else:
            msg += "All pages already analyzed."

        # Get aggregate
        try:
            aggregate = service.aggregate_belief_first_analysis_for_competitor(
                competitor_id
            )
            if aggregate:
                msg += f"\n\n**Aggregate Findings:**\n{json.dumps(aggregate, indent=2, default=str)[:2000]}"
        except Exception as e:
            logger.warning(f"Aggregate failed: {e}")

    return msg


@competitor_agent.tool(
    metadata={
        "category": "Research",
        "use_cases": [
            "Get Amazon review analysis",
            "What do customers say about competitor",
        ],
    }
)
async def get_amazon_review_insights(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
    product_id: Optional[str] = None,
) -> str:
    """Get structured insights from competitor Amazon reviews.

    Analyzes reviews to extract pain points, desired features, objections,
    and language patterns. If no analysis exists, triggers one.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID of the competitor
        product_id: Optional competitor product UUID to filter by

    Returns:
        Structured analysis of customer pain points, desires, and objections.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    # Check for existing analysis
    query = db.table("competitor_amazon_review_analysis").select("*").eq(
        "competitor_id", competitor_id
    )
    if product_id:
        query = query.eq("competitor_product_id", product_id)
    query = query.order("analyzed_at", desc=True).limit(1)
    result = query.execute()

    if result.data:
        analysis = result.data[0]
        data = analysis.get("analysis_data", {})
        return (
            f"**Amazon Review Analysis** (analyzed: {analysis.get('analyzed_at', 'N/A')})\n\n"
            f"Reviews analyzed: {analysis.get('review_count', '?')}\n\n"
            f"**Pain Points:**\n{json.dumps(data.get('pain_points', []), indent=2, default=str)[:500]}\n\n"
            f"**Desired Features:**\n{json.dumps(data.get('desired_features', []), indent=2, default=str)[:500]}\n\n"
            f"**Objections:**\n{json.dumps(data.get('objections', []), indent=2, default=str)[:500]}\n\n"
            f"**Language Patterns:**\n{json.dumps(data.get('language_patterns', []), indent=2, default=str)[:500]}"
        )

    # No analysis — trigger one
    service = ctx.deps.competitor
    try:
        analysis_result = service.analyze_amazon_reviews_for_competitor(competitor_id)
        if analysis_result:
            return f"Analysis complete. {json.dumps(analysis_result, indent=2, default=str)[:2000]}"
        return "No Amazon reviews found for this competitor. Add Amazon URLs first."
    except Exception as e:
        return f"Failed to analyze reviews: {e}"


# ============================================================================
# INTEL PACK TOOLS
# ============================================================================


@competitor_agent.tool(
    metadata={
        "category": "Intel",
        "use_cases": [
            "Get competitor intel pack",
            "What did we learn from competitor videos",
        ],
    }
)
async def get_intel_pack(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
    pack_id: Optional[str] = None,
) -> str:
    """Retrieve a competitor intel pack — aggregated insights from video analysis.

    Intel packs contain: hooks, personas, benefits, pain points, JTBDs,
    angles, objections, and emotional triggers extracted from competitor videos.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID of the competitor
        pack_id: Optional specific pack UUID. If not provided, returns the latest.

    Returns:
        Formatted intel pack with key findings.
    """
    intel_service = ctx.deps.competitor_intel

    if pack_id:
        pack = intel_service.get_pack(pack_id)
    else:
        packs = intel_service.get_packs_for_competitor(competitor_id)
        pack = packs[0] if packs else None

    if not pack:
        return (
            "No intel packs found. Use `queue_intel_pack_analysis` to generate one "
            "from competitor video ads."
        )

    pack_data = pack.get("pack_data", {})
    sections = [
        f"## Intel Pack — {pack.get('n_videos', '?')} videos analyzed",
        f"Status: {pack.get('status', '?')} · Created: {pack.get('created_at', 'N/A')[:10]}",
        "",
    ]

    for key in ["hooks", "pain_points", "benefits", "personas", "jtbds", "angles", "objections", "emotional_triggers"]:
        items = pack_data.get(key, [])
        if items:
            label = key.replace("_", " ").title()
            sections.append(f"### {label} ({len(items)})")
            for item in items[:5]:
                if isinstance(item, dict):
                    sections.append(f"- {item.get('text', item.get('name', json.dumps(item, default=str)[:100]))}")
                else:
                    sections.append(f"- {str(item)[:100]}")
            if len(items) > 5:
                sections.append(f"  _{len(items) - 5} more..._")
            sections.append("")

    return "\n".join(sections)


@competitor_agent.tool(
    metadata={
        "category": "Intel",
        "use_cases": [
            "Analyze competitor video ads",
            "Generate intel pack from competitor",
        ],
    }
)
async def queue_intel_pack_analysis(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
    brand_id: str,
    n_videos: int = 10,
) -> str:
    """Queue a background job to analyze competitor video ads and generate an intel pack.

    This scores competitor ads, downloads the top N videos, analyzes each with Gemini,
    and aggregates findings into a unified pack of hooks, pain points, angles, etc.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID of the competitor
        brand_id: UUID or name of the brand (for organization context)
        n_videos: Number of top videos to analyze (default: 10)

    Returns:
        Confirmation with job ID and estimated time.
    """
    brand_id = await _resolve_brand(brand_id)
    from viraltracker.services.pipeline_helpers import queue_one_time_job

    job_id = queue_one_time_job(
        brand_id=brand_id,
        job_type="competitor_intel_analysis",
        parameters={
            "competitor_id": competitor_id,
            "n_videos": n_videos,
        },
        trigger_source="api",
        name=f"Intel pack: {n_videos} videos",
    )

    if not job_id:
        return "Failed to queue intel pack analysis. Check logs."

    return (
        f"Queued competitor intel analysis (ID: {job_id}). "
        f"Analyzing top {n_videos} video ads. "
        "Estimated completion: ~15 minutes. Ask me to check status anytime."
    )


# ============================================================================
# CREATIVE TOOLS
# ============================================================================


@competitor_agent.tool(
    metadata={
        "category": "Creative",
        "use_cases": [
            "Remix competitor video for our brand",
            "Adapt competitor ad structure",
        ],
    }
)
async def remix_competitor_video(
    ctx: RunContext[AgentDependencies],
    pack_id: str,
    video_index: int = 0,
    brand_id: Optional[str] = None,
    product_id: Optional[str] = None,
    creativity_level: int = 3,
) -> str:
    """Remix a competitor's video structure for the user's brand.

    Takes a video from an intel pack and adapts its structure, hooks,
    and flow for the user's product.

    Args:
        ctx: Run context with AgentDependencies
        pack_id: UUID of the intel pack containing the video
        video_index: Index of the video in the pack (default: 0 = top-scored)
        brand_id: Optional brand UUID for brand context
        product_id: Optional product UUID for product-specific remixing
        creativity_level: 1 (faithful) to 5 (wild reimagining), default: 3

    Returns:
        Remixed video concept with adapted hooks, structure, and copy.
    """
    intel_service = ctx.deps.competitor_intel

    pack = intel_service.get_pack(pack_id)
    if not pack:
        return f"Intel pack {pack_id} not found."

    video_analyses = pack.get("video_analyses", [])
    if video_index >= len(video_analyses):
        return f"Video index {video_index} out of range. Pack has {len(video_analyses)} videos."

    try:
        remix = intel_service.remix_video(
            pack_id=pack_id,
            video_index=video_index,
            brand_id=brand_id,
            product_id=product_id,
            creativity_level=creativity_level,
        )
        return f"## Remixed Video Concept\n\n{json.dumps(remix, indent=2, default=str)[:3000]}"
    except Exception as e:
        return f"Remix failed: {e}"


@competitor_agent.tool(
    metadata={
        "category": "Creative",
        "use_cases": [
            "Generate hooks from competitor video",
            "Alternative hooks for competitor concept",
        ],
    }
)
async def generate_competitor_hooks(
    ctx: RunContext[AgentDependencies],
    pack_id: str,
    video_index: int = 0,
) -> str:
    """Generate 5 alternative hooks from a competitor video concept.

    Analyzes the video's core concept and generates alternative hooks
    using different persuasion techniques.

    Args:
        ctx: Run context with AgentDependencies
        pack_id: UUID of the intel pack
        video_index: Index of the video (default: 0 = top-scored)

    Returns:
        5 alternative hooks with technique labels.
    """
    intel_service = ctx.deps.competitor_intel

    pack = intel_service.get_pack(pack_id)
    if not pack:
        return f"Intel pack {pack_id} not found."

    try:
        hooks = intel_service.generate_hooks(
            pack_id=pack_id,
            video_index=video_index,
        )
        return f"## Alternative Hooks\n\n{json.dumps(hooks, indent=2, default=str)[:2000]}"
    except Exception as e:
        return f"Hook generation failed: {e}"
