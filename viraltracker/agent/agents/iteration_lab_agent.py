"""Iteration Lab Specialist Agent

Surfaces the iteration opportunity and winner DNA tooling that previously
lived only in the Streamlit Iteration Lab page. Closes the "pattern
discovery / winner DNA" Phase 2 gap from the chat-first roadmap.

Core capabilities:
- Find ads with mixed-signal performance (strong on one metric, weak on
  another — e.g. high conversion + low CTR) and surface them as
  iteration opportunities with explanations + projected ROAS
- Take action on opportunities (iterate / kill / dismiss / restore)
- Bulk-queue iteration jobs for the top opportunities
- Decompose individual winners into element + visual + messaging DNA
- Find common patterns across multiple winners (replication blueprint)
- Track historical iteration outcomes (what we tried, what worked)

All tools are thin wrappers over IterationOpportunityDetector and
WinnerDNAAnalyzer in the service layer. No business logic here.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies
from ...core.config import Config

logger = logging.getLogger(__name__)


VALID_OPPORTUNITY_ACTIONS = {"iterate", "dismiss", "restore"}


iteration_lab_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Iteration Lab agent for ViralTracker.

You help the user understand which ads have iteration potential, decompose
why winners are winning, and execute iterations against them.

Two complementary capabilities:

1. **Iteration Opportunities** — find ads that are strong on one metric but
   held back by another (e.g. great conversion rate, weak CTR). Each
   opportunity has a confidence score, a strategy_category (iterate / kill
   / scale), and an evolution_mode for automated action. Use
   `find_iteration_opportunities` to scan, `get_iteration_opportunity` for
   detail, `act_on_opportunity` to execute one, `batch_iterate_winners` to
   queue multiple at once.

2. **Winner DNA** — break down WHY winners win. Per-ad: top elements + visual
   properties + messaging + cohort comparison. Across winners: common
   elements (>=50% frequency) + replication blueprint + iteration directions.
   Use `analyze_winner_dna` for one ad, `analyze_winning_patterns` for cross
   winner analysis.

Brand & product context:
- ALWAYS pass brand_id from the resolved brand UUID, not the brand name.
  Use the existing brand context from the orchestrator if set, or call
  resolve_brand_name on the way in.
- product_id is optional. If the user mentions a specific product,
  resolve it and pass it to scope opportunities/winners to that product.

Action flow guidance:
- For "show me iteration opportunities," call `find_iteration_opportunities`
  with the brand and (optionally) product. Format the top 5-10 by confidence.
- For "iterate this one," call `act_on_opportunity` with the opportunity ID.
- For "iterate my top winners," call `batch_iterate_winners`. The jobs run
  in the background (~10 min each); inform the user they'll get notified.
- For "what's working across my winners," call `analyze_winning_patterns`
  and present the common elements + replication blueprint.
- For "track record" questions, call `get_iteration_track_record`.

Provenance:
- Always include the source service in your final summary (Iteration Lab).
- For background-queued jobs, include the job_id so the user can
  follow up.

When data is missing:
- If `find_iteration_opportunities` returns empty, the brand may not have
  enough recent performance data. Suggest running ad_intelligence_analysis
  first or waiting for more spend.
- If `analyze_winning_patterns` returns None (insufficient winners),
  surface that — the brand needs at least 3 winners.
""",
)


# =============================================================================
# Iteration Opportunity Tools
# =============================================================================

@iteration_lab_agent.tool(
    metadata={
        'category': 'Iteration',
        'platform': 'Meta',
        'use_cases': [
            'Find ads with mixed-signal performance (strong + weak)',
            'Surface iteration opportunities ranked by confidence',
            'Scope opportunities to a specific product',
        ],
        'examples': [
            'What iteration opportunities do I have?',
            'Show me iteration candidates for Cortisol Booster',
            'Which ads should I iterate on?',
        ],
    }
)
async def find_iteration_opportunities(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    min_confidence: float = 0.3,
    product_id: str = "",
) -> dict:
    """Find iteration opportunities — ads that are strong on one metric and
    weak on another (e.g. high conversion rate + low CTR).

    Each opportunity includes:
    - pattern_type / pattern_label — which mismatch was detected
    - confidence (0-1) — strength of the signal
    - strong_metric / weak_metric — what's working vs what's holding it back
    - strategy_category (iterate / kill / scale) and evolution_mode
    - explanation_headline / explanation_projection — plain-language framing
    - projected_roas — if we fix the weak metric

    Detects multiple pattern types per ad: standard mixed-signal patterns,
    size-limited (high CPA at scale), fatiguing (declining CTR), and
    proven_winner (strong on everything).

    BRAND vs PRODUCT: brand_id is required. product_id is optional and scopes
    to ads associated with that product (via landing-page or name match).

    Args:
        ctx: Run context.
        brand_id: Brand UUID string (required).
        days_back: Performance window in days. Default 30.
        min_confidence: Minimum confidence threshold (0-1). Default 0.3.
        product_id: Optional product UUID to filter ads.

    Returns:
        Dict with opportunities (list of opportunity dicts sorted by confidence
        desc) and a brief summary.
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        opportunities = await ctx.deps.iteration_opportunity.detect_opportunities(
            brand_id=brand_id,
            org_id=org_id or "all",
            days_back=days_back,
            min_confidence=min_confidence,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"find_iteration_opportunities failed: {e}", exc_info=True)
        return {"error": f"Failed to detect opportunities: {e}", "opportunities": []}

    items = [
        {
            "id": o.id,
            "meta_ad_id": o.meta_ad_id,
            "ad_name": o.ad_name,
            "pattern_type": o.pattern_type,
            "pattern_label": o.pattern_label,
            "confidence": o.confidence,
            "strategy_category": o.strategy_category,
            "evolution_mode": o.evolution_mode,
            "strong_metric": o.strong_metric,
            "strong_value": o.strong_value,
            "weak_metric": o.weak_metric,
            "weak_value": o.weak_value,
            "explanation_headline": o.explanation_headline,
            "explanation_projection": o.explanation_projection,
            "projected_roas": o.projected_roas,
            "spend": o.spend,
            "thumbnail_url": o.thumbnail_url,
        }
        for o in opportunities
    ]

    return {
        "brand_id": brand_id,
        "product_id": product_id or None,
        "days_back": days_back,
        "count": len(items),
        "opportunities": items,
    }


@iteration_lab_agent.tool(
    metadata={
        'category': 'Iteration',
        'platform': 'Meta',
        'use_cases': [
            'List iteration opportunities already stored in the DB',
            'Filter opportunities by status or pattern',
        ],
        'examples': [
            'Show my open iteration opportunities',
            'What dismissed opportunities do I have?',
        ],
    }
)
async def list_stored_opportunities(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    status: str = "detected",
    pattern_filter: str = "",
) -> dict:
    """List iteration opportunities already stored in the database.

    Unlike find_iteration_opportunities (which runs detection fresh),
    this returns previously-detected opportunities filtered by status.

    Args:
        ctx: Run context.
        brand_id: Brand UUID string.
        status: One of 'detected', 'dismissed', 'actioned'. Default 'detected'.
        pattern_filter: Optional pattern_type to filter by.

    Returns:
        Dict with opportunities list (with display fields enriched).
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        opps = ctx.deps.iteration_opportunity.get_opportunities(
            brand_id=brand_id,
            org_id=org_id or "all",
            status=status,
            pattern_filter=pattern_filter or None,
        )
    except Exception as e:
        logger.error(f"list_stored_opportunities failed: {e}", exc_info=True)
        return {"error": str(e), "opportunities": []}

    return {
        "brand_id": brand_id,
        "status": status,
        "count": len(opps),
        "opportunities": opps,
    }


@iteration_lab_agent.tool(
    metadata={
        'category': 'Iteration',
        'platform': 'Meta',
        'use_cases': [
            'Iterate / dismiss / restore an iteration opportunity',
        ],
        'examples': [
            'Iterate on opportunity abc123',
            'Dismiss this opportunity',
        ],
    }
)
async def act_on_opportunity(
    ctx: RunContext[AgentDependencies],
    opportunity_id: str,
    action: str,
    brand_id: str = "",
    product_id: str = "",
) -> dict:
    """Take action on an iteration opportunity.

    Actions:
    - iterate: Run the evolution_mode against the ad. Auto-imports the ad
      to generated_ads if it's a Meta-only ad. Returns the child_ad_id.
      Requires brand_id and product_id.
    - dismiss: Mark the opportunity as dismissed (no action taken).
    - restore: Restore a dismissed opportunity to 'detected' status.

    For 'iterate', the actual evolution runs synchronously and may take
    a minute. Use batch_iterate_winners instead if you want to queue
    multiple iterations as background jobs.

    Args:
        ctx: Run context.
        opportunity_id: Opportunity UUID.
        action: One of 'iterate', 'dismiss', 'restore'.
        brand_id: Brand UUID (required for 'iterate').
        product_id: Product UUID (required for 'iterate').

    Returns:
        Dict with success flag, action result.
    """
    if action not in VALID_OPPORTUNITY_ACTIONS:
        return {
            "success": False,
            "error": f"Invalid action '{action}'. Valid: {sorted(VALID_OPPORTUNITY_ACTIONS)}",
        }

    if action == "dismiss":
        ok = ctx.deps.iteration_opportunity.dismiss_opportunity(opportunity_id)
        return {"success": ok, "action": "dismiss", "opportunity_id": opportunity_id}

    if action == "restore":
        ok = ctx.deps.iteration_opportunity.restore_opportunity(opportunity_id)
        return {"success": ok, "action": "restore", "opportunity_id": opportunity_id}

    # action == "iterate"
    if not brand_id or not product_id:
        return {
            "success": False,
            "error": "brand_id and product_id are required for action='iterate'.",
        }

    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        result = await ctx.deps.iteration_opportunity.action_opportunity(
            opportunity_id=opportunity_id,
            brand_id=brand_id,
            product_id=product_id,
            org_id=org_id or "all",
        )
    except Exception as e:
        logger.error(f"act_on_opportunity (iterate) failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    return {**result, "action": "iterate", "opportunity_id": opportunity_id}


@iteration_lab_agent.tool(
    metadata={
        'category': 'Iteration',
        'platform': 'Meta',
        'use_cases': [
            'Bulk-queue iterations for top opportunities as background jobs',
            'Iterate the top N winners without blocking the chat',
        ],
        'examples': [
            'Iterate my top 5 opportunities for Cortisol Booster',
            'Queue iterations for these 10 opportunity IDs',
        ],
    }
)
async def batch_iterate_winners(
    ctx: RunContext[AgentDependencies],
    opportunity_ids: list[str],
    brand_id: str,
    product_id: str,
    num_variations: int = 0,
) -> dict:
    """Queue iteration jobs for multiple opportunities (non-blocking).

    For each opportunity:
    1. Imports the underlying Meta ad to generated_ads if needed.
    2. Creates a winner_evolution scheduled_job.
    3. The worker picks up the job within ~1 minute.

    This is the bulk-action path. Capped at 20 opportunities per call.
    Each job takes ~10 minutes. The user gets push notifications when
    individual jobs complete.

    Side effect: seeds the Creative Genome (compute_rewards +
    update_element_scores) so winner_iteration mode can find alternative
    element values. Without this, evolution can fail.

    Args:
        ctx: Run context.
        opportunity_ids: List of opportunity UUIDs (max 20).
        brand_id: Brand UUID (required).
        product_id: Product UUID (required).
        num_variations: Optional override for variations per iteration.

    Returns:
        Dict with queued, imported, skipped counts and any errors.
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        result = await ctx.deps.iteration_opportunity.batch_queue_iterations(
            opportunity_ids=opportunity_ids,
            brand_id=brand_id,
            product_id=product_id,
            org_id=org_id or "all",
            num_variations=num_variations or None,
        )
    except Exception as e:
        logger.error(f"batch_iterate_winners failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    return result


@iteration_lab_agent.tool(
    metadata={
        'category': 'Iteration',
        'platform': 'Meta',
        'use_cases': [
            'Track record of past iterations',
            'Did our iterations actually improve performance?',
        ],
        'examples': [
            "How are our iterations doing?",
            "Track record for Martin Clinic",
        ],
    }
)
async def get_iteration_track_record(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> dict:
    """Summarize the historical track record of past iterations.

    Returns counts: total iterations actioned, how many have matured (have
    performance data), how many outperformed their parent, and average
    relative improvement.

    Args:
        ctx: Run context.
        brand_id: Brand UUID.

    Returns:
        Dict with total, matured, outperformed, avg_improvement.
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        record = ctx.deps.iteration_opportunity.get_iteration_track_record(
            brand_id=brand_id,
            org_id=org_id or "all",
        )
    except Exception as e:
        logger.error(f"get_iteration_track_record failed: {e}", exc_info=True)
        return {"error": str(e)}

    return {"brand_id": brand_id, **record}


# =============================================================================
# Winner DNA Tools
# =============================================================================

@iteration_lab_agent.tool(
    metadata={
        'category': 'Winner DNA',
        'platform': 'Meta',
        'use_cases': [
            'Decompose a single winning ad into its DNA',
            'Understand what specific elements / visuals / messaging are driving a winner',
        ],
        'examples': [
            'Why is ad 12345 winning?',
            'Break down the DNA of our top performer',
        ],
    }
)
async def analyze_winner_dna(
    ctx: RunContext[AgentDependencies],
    meta_ad_id: str,
    brand_id: str,
) -> dict:
    """Decompose a single winning ad into its DNA components.

    Returns:
    - metrics — performance numbers (ROAS, CTR, conv_rate, etc.)
    - top_elements / weak_elements — element scores from the genome
    - visual_properties — extracted visual traits (composition, color, etc.)
    - messaging — awareness level, hook type, copy patterns
    - cohort_comparison — how this ad compares to its cohort
    - active_synergies / active_conflicts — interaction effects between elements

    Use when the user asks "why is X winning" about a specific ad.

    Args:
        ctx: Run context.
        meta_ad_id: Meta ad ID (numeric string).
        brand_id: Brand UUID.

    Returns:
        WinnerDNA serialized as dict, or {"error": ...} if insufficient data.
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        dna = await ctx.deps.winner_dna.analyze_winner(
            meta_ad_id=meta_ad_id,
            brand_id=brand_id,
            org_id=org_id or "all",
        )
    except Exception as e:
        logger.error(f"analyze_winner_dna failed: {e}", exc_info=True)
        return {"error": str(e)}

    if not dna:
        return {
            "error": "Insufficient data to compute DNA for this ad. "
                    "Make sure performance + classification data exists."
        }

    return {
        "meta_ad_id": dna.meta_ad_id,
        "metrics": dna.metrics,
        "top_elements": dna.top_elements,
        "weak_elements": dna.weak_elements,
        "visual_properties": dna.visual_properties,
        "messaging": dna.messaging,
        "cohort_comparison": dna.cohort_comparison,
        "active_synergies": dna.active_synergies,
        "active_conflicts": dna.active_conflicts,
    }


@iteration_lab_agent.tool(
    metadata={
        'category': 'Winner DNA',
        'platform': 'Meta',
        'use_cases': [
            'Find common patterns across multiple winning ads',
            'Get a replication blueprint for what works',
            'Generate iteration directions based on winner patterns',
        ],
        'examples': [
            'What patterns are common across our top winners?',
            'Show me the winning DNA for Cortisol Booster',
            'What should we replicate from our winners?',
        ],
    }
)
async def analyze_winning_patterns(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    top_n: int = 10,
    min_reward: float = 0.65,
    days_back: int = 30,
    product_id: str = "",
) -> dict:
    """Find common patterns across top winners and produce a replication
    blueprint.

    Identifies the top_n winners (by reward score), runs per-winner DNA
    on each, and extracts:
    - common_elements: element values present in >=50% of winners
    - common_visual_traits: visual properties shared by >=50%
    - notable_elements / notable_visual_traits: 25-49% (also-notable)
    - anti_patterns: present in losers, absent in winners
    - iteration_directions: data-driven suggestions for next tests
    - replication_blueprint: combined element_combo + visual_directives
      that can be fed into Ad Creator V2 to replicate the winning DNA
    - cohort_summary: aggregate performance of the winner cohort
    - awareness_distribution: which awareness levels the winners hit

    Returns None (or an error) if fewer than 3 winners can be analyzed.

    Args:
        ctx: Run context.
        brand_id: Brand UUID (required).
        top_n: How many top performers to consider. Default 10.
        min_reward: Minimum reward score to qualify as winner. Default 0.65.
        days_back: Performance lookback window. Default 30.
        product_id: Optional product UUID to scope winners.

    Returns:
        CrossWinnerAnalysis serialized as dict, or {"error": ...}.
    """
    org_id = "all"  # Services treat "all" as no-filter; superuser-friendly default
    try:
        analysis = await ctx.deps.winner_dna.analyze_cross_winners(
            brand_id=brand_id,
            org_id=org_id or "all",
            top_n=top_n,
            min_reward=min_reward,
            days_back=days_back,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"analyze_winning_patterns failed: {e}", exc_info=True)
        return {"error": str(e)}

    if not analysis:
        return {
            "error": "Not enough winners to analyze (need at least 3). "
                    "Try lowering min_reward or extending days_back, "
                    "or wait for more performance data.",
        }

    return {
        "brand_id": brand_id,
        "product_id": product_id or None,
        "winner_count": analysis.winner_count,
        "common_elements": analysis.common_elements,
        "common_visual_traits": analysis.common_visual_traits,
        "notable_elements": analysis.notable_elements,
        "notable_visual_traits": analysis.notable_visual_traits,
        "anti_patterns": analysis.anti_patterns,
        "iteration_directions": analysis.iteration_directions,
        "replication_blueprint": analysis.replication_blueprint,
        "cohort_summary": analysis.cohort_summary,
        "awareness_distribution": analysis.awareness_distribution,
        "winner_thumbnails": analysis.winner_thumbnails,
    }


logger.info("Iteration Lab Agent initialized with 7 tools")
