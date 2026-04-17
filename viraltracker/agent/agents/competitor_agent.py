"""
Competitor Intelligence Agent - Specialized agent for competitor research and analysis.

This agent exposes 11 tools:
- Discovery: list_competitors, get_competitor_summary
- Research: analyze_competitor_landing_pages, get_amazon_review_insights
- Intel packs: get_intel_pack, queue_intel_pack_analysis
- Creative: remix_competitor_video, generate_competitor_hooks
- Personas: synthesize_competitor_persona, generate_persona_from_product, get_persona_copy_brief
"""

import json
import logging
import re
from typing import Dict, List, Optional
from uuid import UUID

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


async def _resolve_competitor(competitor_id: str) -> str:
    """Resolve a competitor name or UUID to a valid competitor UUID."""
    if _UUID_RE.match(competitor_id):
        return competitor_id

    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("competitors").select("id, name").execute()
    competitors = result.data or []

    search = competitor_id.lower().strip()

    # Exact match
    for c in competitors:
        if c["name"].lower() == search:
            return c["id"]

    # Substring match
    matches = [c for c in competitors if search in c["name"].lower() or c["name"].lower() in search]
    if len(matches) == 1:
        return matches[0]["id"]

    # Word overlap
    if not matches:
        search_words = set(search.split())
        matches = [c for c in competitors if search_words & set(c["name"].lower().split())]
        if len(matches) == 1:
            return matches[0]["id"]

    if matches:
        names = ", ".join(f"**{m['name']}**" for m in matches)
        raise ValueError(f"Multiple competitors match '{competitor_id}': {names}. Please be more specific.")
    raise ValueError(f"No competitor found matching '{competitor_id}'.")


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

**Persona tools:**
- synthesize_competitor_persona: Build a 4D persona from competitor research data
- generate_persona_from_product: Generate a persona from your own product data
- get_persona_copy_brief: Export a persona as a copywriting brief

**Guidelines:**
- When the user mentions a competitor by name, resolve it from the list first
- For long-running operations (landing page scrape, intel pack), explain it's queued
- Present insights in a structured, actionable format
- Connect findings back to opportunities for the user's brand
- When synthesizing personas, remind the user to review and refine the generated persona
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
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")

    Returns:
        Structured summary with products, analysis coverage, and key findings.
    """
    competitor_id = await _resolve_competitor(competitor_id)
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
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")
        belief_first: If True, runs deep belief-first analysis (default: True)

    Returns:
        Summary of analysis results or status if already analyzed.
    """
    competitor_id = await _resolve_competitor(competitor_id)
    service = ctx.deps.competitor
    stats = service.get_landing_page_stats(competitor_id)
    msg = ""

    # Step 1: Discover & scrape pages that don't have content yet
    unscraped = stats.get("total", 0) - stats.get("scraped", 0)
    if stats.get("total", 0) == 0 or unscraped > 0:
        try:
            scraped = await service.scrape_landing_pages_for_competitor(competitor_id)
            msg += f"Scraped {len(scraped)} landing pages. "
            # Refresh stats after scraping
            stats = service.get_landing_page_stats(competitor_id)
        except Exception as e:
            if stats.get("scraped", 0) == 0:
                return f"Failed to scrape landing pages: {e}"
            msg += f"Scraping had issues ({e}), continuing with {stats.get('scraped', 0)} already scraped. "

    if not msg:
        msg = f"{stats.get('scraped', 0)} landing pages scraped. "

    # Step 2: Run belief-first analysis on scraped but unanalyzed pages
    if belief_first:
        bf_stats = service.get_belief_first_analysis_stats_for_competitor(competitor_id)
        pending = bf_stats.get("pending", 0)
        if pending > 0:
            try:
                results = await service.analyze_landing_pages_belief_first_for_competitor(
                    competitor_id
                )
                msg += f"Ran belief-first analysis on {len(results)} pages. "
            except Exception as e:
                return msg + f"Analysis failed: {e}"
        elif bf_stats.get("analyzed", 0) > 0:
            msg += f"All {bf_stats['analyzed']} pages already have belief-first analysis. "
        else:
            msg += "No scraped pages available for analysis."

        # Get aggregate findings
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
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")
        product_id: Optional competitor product UUID to filter by

    Returns:
        Structured analysis of customer pain points, desires, and objections.
    """
    competitor_id = await _resolve_competitor(competitor_id)
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
        analysis_result = await service.analyze_amazon_reviews_for_competitor(competitor_id)
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
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")
        pack_id: Optional specific pack UUID. If not provided, returns the latest.

    Returns:
        Formatted intel pack with key findings.
    """
    competitor_id = await _resolve_competitor(competitor_id)
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
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")
        brand_id: UUID or name of the brand (for organization context)
        n_videos: Number of top videos to analyze (default: 10)

    Returns:
        Confirmation with job ID and estimated time.
    """
    competitor_id = await _resolve_competitor(competitor_id)
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


# ============================================================================
# PERSONA TOOLS
# ============================================================================


@competitor_agent.tool(
    metadata={
        "category": "Persona",
        "use_cases": [
            "Build persona from competitor research",
            "Reverse-engineer who a competitor is targeting",
        ],
    }
)
async def synthesize_competitor_persona(
    ctx: RunContext[AgentDependencies],
    competitor_id: str,
    brand_id: str,
    competitor_product_id: Optional[str] = None,
) -> str:
    """Synthesize a 4D persona from competitor analysis data (Amazon reviews,
    landing pages, ads).

    Requires prior research — at least one of: Amazon review analysis,
    landing page analysis, or ad analysis for this competitor. If none exist,
    run those analyses first.

    The persona is saved to the database and can be used for ad creation.

    Args:
        ctx: Run context with AgentDependencies
        competitor_id: UUID or name of the competitor (e.g. "Mars Men")
        brand_id: UUID or name of the brand tracking this competitor
        competitor_product_id: Optional competitor product UUID for product-level persona

    Returns:
        Summary of the generated persona with ID for follow-up.
    """
    competitor_id = await _resolve_competitor(competitor_id)
    brand_id = await _resolve_brand(brand_id)

    try:
        persona = await ctx.deps.persona.synthesize_competitor_persona(
            competitor_id=UUID(competitor_id),
            brand_id=UUID(brand_id),
            competitor_product_id=UUID(competitor_product_id) if competitor_product_id else None,
        )

        # Save to database
        persona_id = ctx.deps.persona.create_persona(persona)

        sections = [
            f"## Persona Generated: {persona.name}",
            f"ID: `{persona_id}`",
            f"Type: competitor",
            "",
            f"**Snapshot:** {persona.snapshot or 'N/A'}",
        ]

        if persona.demographics:
            demo = persona.demographics
            sections.append(f"**Demographics:** {demo.age_range or 'N/A'}, {demo.gender or 'N/A'}, {demo.income_level or 'N/A'}")

        if persona.self_narratives:
            sections.append(f"\n**Self-narratives:** {'; '.join(persona.self_narratives[:3])}")

        if persona.pain_points:
            emotional = persona.pain_points.emotional[:3] if persona.pain_points.emotional else []
            if emotional:
                sections.append(f"\n**Pain points:** {'; '.join(emotional)}")

        if persona.activation_events:
            sections.append(f"\n**Activation events:** {'; '.join(persona.activation_events[:3])}")

        sections.append(f"\n_Saved as persona `{persona_id}`. Use `get_persona_copy_brief` to export for ad creation._")
        return "\n".join(sections)

    except ValueError as e:
        return f"Cannot synthesize persona: {e}"
    except Exception as e:
        logger.error(f"Persona synthesis failed: {e}")
        return f"Persona synthesis failed: {e}"


@competitor_agent.tool(
    metadata={
        "category": "Persona",
        "use_cases": [
            "Generate persona for a product",
            "Create persona from product data",
        ],
    }
)
async def generate_persona_from_product(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    brand_id: Optional[str] = None,
    offer_variant_id: Optional[str] = None,
) -> str:
    """Generate a 4D persona from product data and existing ad analyses.

    Uses product details, offer variant data (if specified), and any existing
    ad image analyses to generate a comprehensive persona.

    The persona is saved to the database and can be used for ad creation.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of the product
        brand_id: Optional brand UUID (resolved from product if not provided)
        offer_variant_id: Optional offer variant UUID for variant-specific persona

    Returns:
        Summary of the generated persona with ID for follow-up.
    """
    # Resolve product name if not UUID
    resolved_product_id = product_id
    if not _UUID_RE.match(product_id):
        products = await ctx.deps.ad_creation.search_products_by_name(product_id)
        if not products:
            return f"No product found matching '{product_id}'."
        if len(products) > 1:
            names = ", ".join(f"**{p.name}**" for p in products)
            return f"Multiple products match: {names}. Please be more specific."
        resolved_product_id = str(products[0].id)

    resolved_brand_id = None
    if brand_id:
        resolved_brand_id = UUID(await _resolve_brand(brand_id))

    try:
        persona = await ctx.deps.persona.generate_persona_from_product(
            product_id=UUID(resolved_product_id),
            brand_id=resolved_brand_id,
            offer_variant_id=UUID(offer_variant_id) if offer_variant_id else None,
        )

        persona_id = ctx.deps.persona.create_persona(persona)

        sections = [
            f"## Persona Generated: {persona.name}",
            f"ID: `{persona_id}`",
            f"Type: product-specific",
            "",
            f"**Snapshot:** {persona.snapshot or 'N/A'}",
        ]

        if persona.demographics:
            demo = persona.demographics
            sections.append(f"**Demographics:** {demo.age_range or 'N/A'}, {demo.gender or 'N/A'}, {demo.income_level or 'N/A'}")

        if persona.self_narratives:
            sections.append(f"\n**Self-narratives:** {'; '.join(persona.self_narratives[:3])}")

        if persona.pain_points:
            emotional = persona.pain_points.emotional[:3] if persona.pain_points.emotional else []
            if emotional:
                sections.append(f"\n**Pain points:** {'; '.join(emotional)}")

        sections.append(f"\n_Saved as persona `{persona_id}`. Use `get_persona_copy_brief` to export for ad creation._")
        return "\n".join(sections)

    except ValueError as e:
        return f"Cannot generate persona: {e}"
    except Exception as e:
        logger.error(f"Persona generation failed: {e}")
        return f"Persona generation failed: {e}"


@competitor_agent.tool(
    metadata={
        "category": "Persona",
        "use_cases": [
            "Export persona for ad copywriting",
            "Get persona copy brief",
        ],
    }
)
async def get_persona_copy_brief(
    ctx: RunContext[AgentDependencies],
    persona_id: str,
) -> str:
    """Export a persona as a structured copywriting brief for ad creation.

    Returns the persona's key traits formatted for writing ad copy:
    desires, pain points, language patterns, objections, activation events.

    Args:
        ctx: Run context with AgentDependencies
        persona_id: UUID of the persona to export

    Returns:
        Formatted copy brief ready for use in ad creation prompts.
    """
    try:
        brief = ctx.deps.persona.export_for_copy_brief_dict(UUID(persona_id))

        sections = [
            f"## Copy Brief: {brief.get('persona_name', 'Unknown')}",
            "",
            f"**Snapshot:** {brief.get('snapshot', 'N/A')}",
        ]

        if brief.get("target_demo"):
            demo = brief["target_demo"]
            sections.append(f"\n**Target Demo:** {json.dumps(demo, default=str)[:300]}")

        if brief.get("primary_desires"):
            sections.append(f"\n**Primary Desires:**")
            for d in brief["primary_desires"]:
                sections.append(f"- {d}")

        if brief.get("top_pain_points"):
            sections.append(f"\n**Top Pain Points:**")
            for p in brief["top_pain_points"]:
                sections.append(f"- {p}")

        if brief.get("their_language"):
            sections.append(f"\n**Their Language (self-narratives):**")
            for s in brief["their_language"][:5]:
                sections.append(f"- \"{s}\"")

        if brief.get("objections"):
            sections.append(f"\n**Objections:**")
            for o in brief["objections"][:5]:
                sections.append(f"- {o}")

        if brief.get("activation_events"):
            sections.append(f"\n**Activation Events:**")
            for e in brief["activation_events"][:5]:
                sections.append(f"- {e}")

        if brief.get("allergies"):
            sections.append(f"\n**Allergies (avoid these):**")
            for a in brief["allergies"][:5]:
                sections.append(f"- {a}")

        return "\n".join(sections)

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"Failed to export copy brief: {e}")
        return f"Failed to export copy brief: {e}"
