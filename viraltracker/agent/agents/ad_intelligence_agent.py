"""
Ad Intelligence Agent - Evaluates Meta ad performance, classifies creatives
by awareness level, diagnoses issues, and produces actionable recommendations.

Chat-first UX with slash commands:
- /analyze_account: Full 4-layer analysis
- /recommend: View recommendation inbox
- /fatigue_check: Check for fatigued ads
- /coverage_gaps: Analyze inventory coverage
- /congruence_check: Check creative-copy-LP alignment
- /hook_analysis: Analyze hook performance across video ads
- /top_hooks: Quick view of top performing hooks
- /hooks_for_lp: Get best hooks for a landing page
- /rec_done, /rec_ignore, /rec_note: Manage recommendations

19 thin tools delegating to AdIntelligenceService and AdPerformanceQueryService.
"""

import asyncio
import json
import logging
from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies
from ...core.config import Config
from ...services.ad_intelligence.hook_analysis_service import HookAnalysisService

logger = logging.getLogger(__name__)


def _run_blocking_async(coro):
    """Run an async coroutine that internally blocks with sync I/O.

    Creates a new event loop on the current thread (called via asyncio.to_thread).
    This frees the main event loop for socket.io keepalive pings during
    long-running service calls like full_analysis (~134s).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


ad_intelligence_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
)


@ad_intelligence_agent.system_prompt
async def _build_system_prompt(ctx: RunContext[AgentDependencies]) -> str:
    """Build system prompt with current date injected."""
    today = date.today().isoformat()
    return f"""You are the Ad Intelligence Agent for the ViralTracker system.

**Today's date is {today}.** Use this when interpreting relative dates like "yesterday",
"last week", "this month", etc. For relative time queries, prefer using `days_back`
(e.g., days_back=1 for yesterday, days_back=7 for last week). Only use explicit
`date_start`/`date_end` when the user specifies exact dates (e.g., "January 2026").

Your role is to analyze Meta ad account performance and provide actionable insights.

**Your capabilities:**
1. **Brand Lookup** - Resolve brand names to brand IDs
2. **Full Account Analysis** - Classify ads by awareness level, compute baselines,
   diagnose issues, and generate recommendations
3. **Recommendation Management** - View, acknowledge, and act on recommendations
4. **Fatigue Detection** - Identify ads suffering from audience fatigue
5. **Coverage Analysis** - Find gaps in awareness level × creative format inventory
6. **Congruence Checking** - Verify creative, copy, and landing page alignment

**How you work:**
- You use a 4-layer model: Classification → Baselines → Diagnosis → Recommendations
- Classifications are awareness-level based (unaware → most_aware)
- Baselines are contextual cohort benchmarks (p25/median/p75)
- Diagnostics use 12 rules with prerequisite checks (no silent failures)
- Recommendations include evidence and suggested actions

**CRITICAL OUTPUT RULES:**
- ALWAYS output the tool's markdown response EXACTLY as returned. Do NOT paraphrase,
  summarize, or reformat the tool output. The tools return pre-formatted markdown with
  specific ad IDs, metric values, recommendation IDs, and action commands that the user
  needs to see verbatim.
- After outputting the tool result, you may add a brief comment or offer to help further.
- NEVER strip out ad IDs, recommendation IDs, metric values, or `/rec_done` commands.
  These are essential for the user to take action.

**Important:**
- When the user mentions a brand by name, ALWAYS call resolve_brand_name first to get the brand_id
- Never ask the user for a brand_id — look it up yourself using resolve_brand_name
- If the query includes a [Context: ...] block with a brand_id, use that brand_id directly
  WITHOUT calling resolve_brand_name again. The brand was already resolved in a previous turn.
- When users ask about "which ads to kill" or "what's not working", use analyze_account
- When users ask about "fatigued ads" or "frequency", use check_fatigue
- When users ask about "gaps" or "missing awareness levels", use check_coverage_gaps
- When users ask about "hooks" or "which hooks work", use hook_analysis or top_hooks
- When users ask about "hooks for a landing page" or "best hooks for LP", use hooks_for_lp
- For follow-up questions about a previous analysis, use the brand_id from context

**When users ask to SEE RESULTS from a previous/recent analysis:**
- Call `analyze_account` — it automatically returns cached results instantly if available
- If the tool returns cached markdown, output it EXACTLY as returned
- If the tool says the analysis is "queued" or "running", tell the user it's still in progress
- Do NOT rephrase a "queued/running" status to sound like you started a new analysis

**Performance Queries** — Direct ad performance data:
- Top/bottom ads by any metric (ROAS, spend, CTR, CPC, conversion_rate, etc.)
- Account summaries with period-over-period comparison
- Campaign and adset breakdowns
- Individual ad deep dives with daily trends
- Performance by media type (video vs image vs carousel)
- Performance by landing page / offer variant
- Performance by product
- All breakdown tools support optional awareness_level filtering
- Supports both `days_back` and explicit `date_start`/`date_end` for custom ranges

**When to use performance queries vs. analyze_account:**
- `get_top_ads` / `get_account_summary` / `get_campaign_breakdown` / `get_ad_details` → Quick data lookups ("what are my top ads?", "how much did I spend?", "show me January results")
- `analyze_account` → Deep 4-layer diagnostics with classification, baselines, and recommendations ("what's wrong with my account?", "which ads should I kill?", "show me the analysis results")
"""


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Utility',
        'platform': 'Meta',
        'use_cases': [
            'Look up brand by name',
            'Resolve brand name to brand_id',
        ],
        'examples': [
            'Analyze Wonder Paws ad account',
            'Check fatigue for WonderPaws',
        ],
    }
)
async def resolve_brand_name(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
) -> str:
    """Look up a brand by name to get its brand_id.

    ALWAYS call this first when the user mentions a brand by name.
    Use the returned brand_id for all subsequent tool calls.

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name or partial name (e.g., "Wonder Paws").

    Returns:
        JSON with matching brands including id, name, and organization_id.
    """
    logger.info(f"Resolving brand name: {brand_name}")
    brands = await ctx.deps.ad_intelligence.search_brands(brand_name)

    if not brands:
        return json.dumps({
            "success": False,
            "error": f"No brands found matching '{brand_name}'",
            "count": 0,
        })

    # Cache the first matching brand for follow-up context
    if len(brands) == 1:
        ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = brands[0]["id"]
        ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = brands[0]["name"]

    return json.dumps({
        "success": True,
        "brands": [
            {
                "id": b["id"],
                "name": b["name"],
                "organization_id": b["organization_id"],
            }
            for b in brands
        ],
        "count": len(brands),
    })


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Full account health assessment',
            'Classify ads by awareness level',
            'Find underperforming ads',
            'Get optimization recommendations',
        ],
        'examples': [
            'Analyze my ad account',
            'Which ads should I kill?',
            'How is my account performing?',
        ],
    }
)
async def analyze_account(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    goal: str = "",
    force_refresh: bool = False,
    product_id: str = "",
) -> str:
    """Run full 4-layer account analysis: classify → baseline → diagnose → recommend.

    Analysis runs in a background worker (~2-10 minutes). This tool:
    1. Returns cached results instantly if a recent analysis exists
    2. Queues a new background analysis if no cache or force_refresh=True
    3. Prevents duplicate jobs from being queued

    FOLLOW-UPS: When the user asks "is it done?" / "did the analysis finish?",
    YOU MUST CALL THIS TOOL AGAIN with the same brand_id (and product_id if set).
    Do NOT assume the analysis is complete based on elapsed time. The cache
    lookup will return the rendered markdown if it has finished.

    BRAND vs PRODUCT — these are two DIFFERENT UUIDs from two DIFFERENT tables:
    - brand_id is the UUID from the `brands` table (e.g. Martin Clinic, Savage)
    - product_id is the UUID from the `products` table (e.g. Cortisol Control,
      a product OWNED by a brand)

    For "analyze Martin Clinic's Cortisol Control product" you MUST:
    1. Call resolve_brand_name("Martin Clinic") → brand_id (e.g. abc-123-...)
    2. Call resolve_product_name("Cortisol Control") → product_id (e.g. def-456-...)
    3. Call this tool with BOTH brand_id="abc-123-..." AND product_id="def-456-..."

    Never pass the same UUID for both — that means you forgot to resolve the brand.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string from the brands table.
        days_back: Number of days to analyze (default: 30).
        goal: Analysis goal (e.g., 'lower_cpa', 'scale', 'stability').
        force_refresh: If True, queue a new analysis even if cache exists.
        product_id: Optional product UUID from the products table. If set,
            restricts analysis to ads associated with that product. Must be
            different from brand_id.

    Returns:
        Cached analysis markdown, or status message about queued job.
    """
    from ...services.pipeline_helpers import queue_one_time_job
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()
    intel_service = ctx.deps.ad_intelligence

    # Validate: brand_id and product_id must be different UUIDs
    if product_id and product_id == brand_id:
        return (
            "ERROR: brand_id and product_id are the same UUID. This usually means "
            "you skipped resolve_brand_name and passed the product UUID for both. "
            "Call resolve_brand_name first to get the actual brand UUID (different "
            "from the product UUID), then call analyze_account again with both IDs."
        )

    product_uuid = UUID(product_id) if product_id else None

    # Cache brand context for follow-up queries
    ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = brand_id
    if product_uuid:
        ctx.deps.result_cache.custom["ad_intelligence_product_id"] = str(product_uuid)
    else:
        # Clear stale product context when this is a brand-only query
        ctx.deps.result_cache.custom.pop("ad_intelligence_product_id", None)

    # --- Step 1: App-level dedup check (one-time jobs only) ---
    # Dedup is scoped to (brand_id, product_id) since brand-level and
    # product-level analyses are independent.
    try:
        queued_query = db.table("scheduled_jobs").select("id, parameters").eq(
            "brand_id", brand_id
        ).eq("job_type", "ad_intelligence_analysis").eq(
            "schedule_type", "one_time"
        ).eq("status", "active")
        queued_result = queued_query.execute()

        for row in (queued_result.data or []):
            row_params = row.get("parameters") or {}
            row_product = row_params.get("product_id")
            if (row_product or None) == (str(product_uuid) if product_uuid else None):
                scope = f" for this product" if product_uuid else ""
                return (
                    f"An ad intelligence analysis is already queued{scope}. "
                    "Please ask again in a few minutes to see the results."
                )
    except Exception as e:
        logger.warning(f"Dedup pre-check failed: {e}")

    # 1b. Check for currently running analysis runs (via scheduled_job_runs)
    try:
        from datetime import datetime, timedelta, timezone
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()

        # Get all ad_intelligence_analysis job IDs for this brand (with their params)
        job_ids_result = db.table("scheduled_jobs").select("id, parameters").eq(
            "brand_id", brand_id
        ).eq("job_type", "ad_intelligence_analysis").execute()

        if job_ids_result.data:
            # Filter to jobs that match our product scope
            target_product_str = str(product_uuid) if product_uuid else None
            matching_job_ids = [
                r["id"] for r in job_ids_result.data
                if ((r.get("parameters") or {}).get("product_id") or None) == target_product_str
            ]

            if matching_job_ids:
                running_result = db.table("scheduled_job_runs").select("id").in_(
                    "scheduled_job_id", matching_job_ids
                ).eq("status", "running").gte(
                    "started_at", stale_cutoff
                ).limit(1).execute()

                if running_result.data:
                    scope = f" for this product" if product_uuid else ""
                    return (
                        f"An ad intelligence analysis is currently running{scope}. "
                        "Please ask again in a few minutes to see the results."
                    )
    except Exception as e:
        logger.warning(f"Running-run dedup check failed: {e}")

    # --- Step 2: Check cache (scoped to product if provided) ---
    if not force_refresh:
        try:
            cached = await intel_service.get_latest_completed_analysis(
                brand_id=UUID(brand_id), days_back=days_back,
                product_id=product_uuid,
            )
            if cached and cached.rendered_markdown:
                # Serve cached result with date stamp
                completed_at = cached.completed_at or "unknown"
                scope_label = " (product-scoped)" if product_uuid else ""
                header = f"*Cached analysis from {completed_at} ({cached.config.days_back}-day window){scope_label}*\n\n"
                rendered = header + cached.rendered_markdown

                ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = cached.summary.get("brand_name", "") if cached.summary else ""
                ctx.deps.result_cache.custom["ad_intelligence_run_id"] = str(cached.id)
                ctx.deps.result_cache.custom["ad_intelligence_result"] = {
                    "tool_name": "analyze_account",
                    "rendered_markdown": rendered,
                }
                return rendered
        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")

    # Check if there's a cached analysis with different days_back (for hint)
    hint_text = ""
    if not force_refresh:
        try:
            any_cached = await intel_service.get_latest_completed_analysis_any_params(
                brand_id=UUID(brand_id),
            )
            if any_cached and any_cached.rendered_markdown:
                cached_days = any_cached.config.days_back
                hint_text = (
                    f"Latest available is a {cached_days}-day analysis from "
                    f"{any_cached.completed_at}. Queuing a fresh {days_back}-day analysis...\n\n"
                )
        except Exception as e:
            logger.warning(f"Hint lookup failed: {e}")

    # --- Step 3: Queue new analysis ---
    params = {
        "max_new": 200,
        "max_video": 15,
        "days_back": days_back,
    }
    if goal:
        params["goal"] = goal
    if product_uuid:
        params["product_id"] = str(product_uuid)

    scope_name = " (product-scoped)" if product_uuid else ""
    job_id = queue_one_time_job(
        brand_id=brand_id,
        job_type="ad_intelligence_analysis",
        parameters=params,
        trigger_source="manual",
        name=f"Ad Intelligence Analysis - Agent Chat{scope_name}",
        max_retries=2,
    )

    if job_id:
        return (
            f"{hint_text}"
            f"Queued a full ad intelligence analysis{scope_name} (job {job_id[:8]}...). "
            f"This typically takes 2-10 minutes depending on account size.\n\n"
            f"Ask me again when you're ready to see the results."
        )

    # job_id is None — could be dedup or real DB error
    # Follow-up query to distinguish
    try:
        check_result = db.table("scheduled_jobs").select("id").eq(
            "brand_id", brand_id
        ).eq("job_type", "ad_intelligence_analysis").eq(
            "schedule_type", "one_time"
        ).eq("status", "active").limit(1).execute()

        if check_result.data:
            return (
                "An ad intelligence analysis is already queued for this brand. "
                "Please ask again in a few minutes to see the results."
            )
    except Exception:
        pass

    return (
        "Failed to queue the analysis. Please try again in a moment."
    )


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'View pending recommendations',
            'Filter recommendations by status/category/priority',
        ],
        'examples': [
            'Show me recommendations',
            'What should I do next?',
            'Show critical recommendations',
        ],
    }
)
async def get_recommendations(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    status: str = "pending",
    category: str = "",
    priority: str = "",
    limit: int = 20,
) -> str:
    """Get recommendation inbox for a brand.

    Defaults to latest completed run. Supports filtering by status,
    category, and priority.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        status: Filter by status (pending, acknowledged, acted_on, ignored).
        category: Filter by category (kill, scale, iterate, test, refresh, etc.).
        priority: Filter by priority (critical, high, medium, low).
        limit: Max recommendations to return.

    Returns:
        Formatted markdown with recommendations.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    kwargs = {"limit": limit}
    if status:
        kwargs["status"] = [status]
    if category:
        kwargs["category"] = category
    if priority:
        kwargs["priority"] = priority

    recs = await ctx.deps.ad_intelligence.get_recommendation_inbox(
        brand_id=UUID(brand_id), **kwargs
    )
    rendered = ChatRenderer.render_recommendations(recs)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_recommendations",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Check for fatigued ads',
            'Monitor ad frequency',
            'Identify declining engagement',
        ],
        'examples': [
            'Check for fatigued ads',
            'Which ads have high frequency?',
            'Are any ads declining?',
        ],
    }
)
async def check_fatigue(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    product_id: str = "",
) -> str:
    """Check all active ads for fatigue signals (frequency + CTR trends).

    Identifies fatigued ads (high frequency + declining CTR),
    at-risk ads (approaching thresholds), and healthy ads.

    PRODUCT-SCOPED: Pass product_id when the user asks about a specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days of trend data to analyze.
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown with fatigue results.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.fatigue.check_fatigue(
        brand_id=UUID(brand_id),
        date_range_end=date.today(),
        days_back=days_back,
        product_id=UUID(product_id) if product_id else None,
    )
    rendered = ChatRenderer.render_fatigue_check(result)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "check_fatigue",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Find coverage gaps in ad inventory',
            'Check awareness level distribution',
            'Identify missing creative formats',
        ],
        'examples': [
            'What awareness levels am I missing?',
            'Show me coverage gaps',
            'Where are my blind spots?',
        ],
    }
)
async def check_coverage_gaps(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    product_id: str = "",
) -> str:
    """Analyze ad inventory coverage across awareness levels and formats.

    Builds an awareness level × creative format matrix and identifies
    hard gaps (zero ads), SPOFs (< 2 ads), and percentage gaps.

    PRODUCT-SCOPED: Pass product_id when the user asks about coverage for a
    specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown with coverage matrix and gaps.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.coverage.analyze_coverage(
        brand_id=UUID(brand_id),
        date_range_end=date.today(),
        product_id=UUID(product_id) if product_id else None,
    )
    rendered = ChatRenderer.render_coverage_gaps(result)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "check_coverage_gaps",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Check creative-copy-LP alignment',
            'Find misaligned ad components',
        ],
        'examples': [
            'Check ad congruence',
            'Are my ads aligned?',
            'Find misaligned creatives',
        ],
    }
)
async def check_congruence(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    product_id: str = "",
) -> str:
    """Check creative-copy-landing page awareness level alignment.

    Computes congruence scores for all classified ads and identifies
    those with significant misalignment between components.

    PRODUCT-SCOPED: Pass product_id when the user asks about a specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown with congruence results.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.congruence.check_congruence(
        brand_id=UUID(brand_id),
        product_id=UUID(product_id) if product_id else None,
    )
    rendered = ChatRenderer.render_congruence_check(result)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "check_congruence",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Action',
        'platform': 'Meta',
        'use_cases': ['Mark recommendation as acted on'],
        'examples': ['/rec_done abc123'],
    }
)
async def mark_recommendation_done(
    ctx: RunContext[AgentDependencies],
    recommendation_id: str,
) -> str:
    """Mark a recommendation as acted on (done).

    Args:
        ctx: Run context with AgentDependencies.
        recommendation_id: Recommendation UUID string.

    Returns:
        Confirmation message.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    rec = await ctx.deps.ad_intelligence.handle_rec_done(UUID(recommendation_id))
    rendered = ChatRenderer.render_status_update(rec)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "mark_recommendation_done",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Action',
        'platform': 'Meta',
        'use_cases': ['Dismiss a recommendation'],
        'examples': ['/rec_ignore abc123'],
    }
)
async def ignore_recommendation(
    ctx: RunContext[AgentDependencies],
    recommendation_id: str,
) -> str:
    """Mark a recommendation as ignored/dismissed.

    Args:
        ctx: Run context with AgentDependencies.
        recommendation_id: Recommendation UUID string.

    Returns:
        Confirmation message.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    rec = await ctx.deps.ad_intelligence.handle_rec_ignore(UUID(recommendation_id))
    rendered = ChatRenderer.render_status_update(rec)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "ignore_recommendation",
        "rendered_markdown": rendered,
    }
    return rendered


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Action',
        'platform': 'Meta',
        'use_cases': ['Add a note to a recommendation'],
        'examples': ['/rec_note abc123 "Will test next week"'],
    }
)
async def add_recommendation_note(
    ctx: RunContext[AgentDependencies],
    recommendation_id: str,
    note: str,
) -> str:
    """Add a note to a recommendation and acknowledge it.

    Args:
        ctx: Run context with AgentDependencies.
        recommendation_id: Recommendation UUID string.
        note: User note text.

    Returns:
        Confirmation message.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    rec = await ctx.deps.ad_intelligence.handle_rec_note(
        UUID(recommendation_id), note
    )
    rendered = ChatRenderer.render_status_update(rec)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "add_recommendation_note",
        "rendered_markdown": rendered,
    }
    return rendered


# =============================================================================
# Hook Analysis Tools (Phase 7)
# =============================================================================


def _format_hook_overview(insights: Dict, top_hooks: List[Dict]) -> str:
    """Format hook analysis overview as markdown."""
    lines = ["## Hook Performance Overview\n"]

    # Summary stats
    stats = insights.get("summary_stats", {})
    if stats:
        lines.append(
            f"**Hooks Analyzed:** {stats.get('total_hooks_analyzed', 0)} | "
            f"**Total Spend:** ${stats.get('total_spend', 0):,.0f} | "
            f"**Avg ROAS:** {stats.get('weighted_avg_roas', 0):.2f}x | "
            f"**Avg Hook Rate:** {stats.get('avg_hook_rate', 0):.1%}"
        )
        lines.append("")

    # Quadrant summary
    quad_summary = insights.get("quadrant_summary", {})
    if quad_summary:
        lines.append("### Quadrant Breakdown")
        lines.append(
            f"- [TARGET] **Winners:** {quad_summary.get('winners', 0)} (Scale these)\n"
            f"- [SEARCH] **Hidden Gems:** {quad_summary.get('hidden_gems', 0)} (Investigate low engagement)\n"
            f"- [WARNING] **Engaging but Not Converting:** {quad_summary.get('engaging_not_converting', 0)} (Fix downstream)\n"
            f"- [X] **Losers:** {quad_summary.get('losers', 0)} (Consider killing)"
        )
        lines.append("")

    # Top performer
    top = insights.get("top_performer")
    if top:
        lines.append("### Best Performing Hook")
        lines.append(f"**{top.get('hook_type', 'unknown')} hook** ({top.get('hook_visual_type', 'unknown')})")
        spoken = top.get("hook_transcript_spoken", "N/A") or "N/A"
        if len(spoken) > 80:
            spoken = spoken[:80] + "..."
        lines.append(f'Spoken: "{spoken}"')
        lines.append(
            f"[CHART] {top.get('ad_count', 0)} ads | "
            f"${top.get('total_spend', 0):,.0f} spend | "
            f"{top.get('avg_roas', 0):.2f}x ROAS | "
            f"{top.get('avg_hook_rate', 0):.1%} hook rate"
        )
        lines.append("")

    # Top 5 hooks table
    if top_hooks:
        lines.append("### Top Hooks by ROAS")
        for i, hook in enumerate(top_hooks[:5], 1):
            hook_type = hook.get("hook_type", "unknown")
            visual_type = hook.get("hook_visual_type", "unknown")
            spoken = hook.get("hook_transcript_spoken", "N/A") or "N/A"
            if len(spoken) > 60:
                spoken = spoken[:60] + "..."

            lines.append(f"**{i}. {hook_type} hook** ({visual_type})")
            lines.append(f'   Spoken: "{spoken}"')
            lines.append(
                f"   [CHART] {hook.get('ad_count', 0)} ads | "
                f"${hook.get('total_spend', 0):,.0f} | "
                f"{hook.get('avg_roas', 0):.2f}x ROAS | "
                f"{hook.get('avg_hook_rate', 0):.1%} hook rate"
            )
            lines.append("")

    # Recommendations
    recs = insights.get("recommendations", [])
    if recs:
        lines.append("### Actionable Insights")
        for rec in recs[:4]:
            lines.append(f"- {rec}")

    return "\n".join(lines)


def _format_quadrant_analysis(quadrants: Dict) -> str:
    """Format quadrant analysis as markdown."""
    lines = ["## Hook Quadrant Analysis (Hook Rate vs ROAS)\n"]

    quadrant_info = [
        ("winners", "[TARGET] Winners", "High hook rate + High ROAS - SCALE THESE"),
        ("hidden_gems", "[SEARCH] Hidden Gems", "Low hook rate + High ROAS - Investigate engagement"),
        ("engaging_not_converting", "[WARNING] Engaging but Not Converting", "High hook rate + Low ROAS - Fix downstream"),
        ("losers", "[X] Losers", "Low hook rate + Low ROAS - KILL THESE"),
    ]

    for key, title, desc in quadrant_info:
        hooks = quadrants.get(key, [])
        lines.append(f"### {title}")
        lines.append(f"*{desc}*")
        lines.append(f"**Count:** {len(hooks)}")
        lines.append("")

        if hooks:
            for hook in hooks[:3]:
                hook_type = hook.get("hook_type", "unknown")
                visual_type = hook.get("hook_visual_type", "unknown")
                lines.append(f"- **{hook_type}** ({visual_type})")
                lines.append(
                    f"  ${hook.get('total_spend', 0):,.0f} spend | "
                    f"{hook.get('avg_roas', 0):.2f}x ROAS | "
                    f"{hook.get('avg_hook_rate', 0):.1%} hook rate"
                )
                if hook.get("suggested_action"):
                    lines.append(f"  -> {hook.get('suggested_action')}")
            if len(hooks) > 3:
                lines.append(f"  ... and {len(hooks) - 3} more")
        lines.append("")

    return "\n".join(lines)


def _format_hooks_by_type(hooks_by_type: List[Dict]) -> str:
    """Format hooks by type breakdown as markdown."""
    lines = ["## Hook Performance by Type\n"]

    if not hooks_by_type:
        lines.append("No hook data available.")
        return "\n".join(lines)

    lines.append("| Hook Type | Ads | Spend | Avg ROAS | Hook Rate |")
    lines.append("|-----------|-----|-------|----------|-----------|")

    for item in hooks_by_type:
        hook_type = item.get("hook_type", "unknown")
        lines.append(
            f"| {hook_type.title()} | "
            f"{item.get('ad_count', 0)} | "
            f"${item.get('total_spend', 0):,.0f} | "
            f"{item.get('avg_roas', 0):.2f}x | "
            f"{item.get('avg_hook_rate', 0):.1%} |"
        )

    # Highlight best type
    if hooks_by_type:
        best = max(hooks_by_type, key=lambda x: x.get("avg_roas", 0))
        lines.append("")
        lines.append(
            f"**Best performing type:** {best.get('hook_type', 'unknown').title()} "
            f"({best.get('avg_roas', 0):.2f}x ROAS)"
        )

    return "\n".join(lines)


def _format_hooks_by_visual(hooks_by_visual: List[Dict]) -> str:
    """Format hooks by visual type breakdown as markdown."""
    lines = ["## Hook Performance by Visual Type\n"]

    if not hooks_by_visual:
        lines.append("No hook data available.")
        return "\n".join(lines)

    lines.append("| Visual Type | Ads | Spend | Avg ROAS | Hook Rate |")
    lines.append("|-------------|-----|-------|----------|-----------|")

    for item in hooks_by_visual:
        visual_type = item.get("hook_visual_type", "unknown")
        lines.append(
            f"| {visual_type.replace('_', ' ').title()} | "
            f"{item.get('ad_count', 0)} | "
            f"${item.get('total_spend', 0):,.0f} | "
            f"{item.get('avg_roas', 0):.2f}x | "
            f"{item.get('avg_hook_rate', 0):.1%} |"
        )

        # Show common elements
        elements = item.get("common_visual_elements", [])
        if elements:
            lines.append(f"  *Common elements: {', '.join(elements[:3])}*")

    return "\n".join(lines)


def _format_hooks_by_lp(hooks_by_lp: List[Dict]) -> str:
    """Format hooks by landing page as markdown."""
    lines = ["## Hook Performance by Landing Page\n"]

    if not hooks_by_lp:
        lines.append("No landing page data available.")
        return "\n".join(lines)

    for lp in hooks_by_lp[:10]:
        url = lp.get("landing_page_url", "Unknown URL")
        title = lp.get("landing_page_title", "")
        display = title[:40] if title else url[:40]
        if len(display) < len(title or url):
            display += "..."

        lines.append(f"### {display}")
        lines.append(
            f"**Hooks:** {lp.get('hook_count', 0)} | "
            f"**Spend:** ${lp.get('total_spend', 0):,.0f} | "
            f"**Avg ROAS:** {lp.get('avg_roas', 0):.2f}x"
        )

        if lp.get("best_hook_fingerprint"):
            lines.append(f"Best hook: `{lp.get('best_hook_fingerprint', '')[:12]}...`")

        # Show top hooks for this LP
        hooks = lp.get("hooks", [])
        if hooks:
            lines.append("| Hook Type | Visual | Spend | ROAS |")
            lines.append("|-----------|--------|-------|------|")
            for hook in hooks[:5]:
                lines.append(
                    f"| {hook.get('type', 'unknown')} | "
                    f"{hook.get('visual_type', 'unknown')} | "
                    f"${hook.get('spend', 0):,.0f} | "
                    f"{hook.get('roas', 0):.2f}x |"
                )
        lines.append("")

    return "\n".join(lines)


def _format_hook_comparison(comparison: Dict) -> str:
    """Format hook comparison as markdown."""
    lines = ["## Hook Comparison\n"]

    if comparison.get("error"):
        lines.append(f"Error: {comparison.get('error')}")
        return "\n".join(lines)

    hook_a = comparison.get("hook_a", {})
    hook_b = comparison.get("hook_b", {})
    winners = comparison.get("winner_by", {})

    lines.append("| Metric | Hook A | Hook B | Winner |")
    lines.append("|--------|--------|--------|--------|")

    # Type
    lines.append(
        f"| Type | {hook_a.get('type', 'unknown')} | {hook_b.get('type', 'unknown')} | - |"
    )

    # Metrics
    a_metrics = hook_a.get("metrics", {})
    b_metrics = hook_b.get("metrics", {})

    metrics = [
        ("Spend", "total_spend", "${:,.0f}"),
        ("ROAS", "avg_roas", "{:.2f}x"),
        ("Hook Rate", "avg_hook_rate", "{:.1%}"),
    ]

    for label, key, fmt in metrics:
        a_val = a_metrics.get(key, 0)
        b_val = b_metrics.get(key, 0)
        winner = winners.get(key.replace("avg_", "").replace("total_", ""), "-")
        lines.append(
            f"| {label} | {fmt.format(a_val)} | {fmt.format(b_val)} | {winner} |"
        )

    # Ad count
    lines.append(
        f"| Ad Count | {hook_a.get('ad_count', 0)} | {hook_b.get('ad_count', 0)} | - |"
    )

    lines.append("")
    lines.append(f"**Confidence:** {comparison.get('statistical_confidence', 'unknown')}")

    if comparison.get("recommendation"):
        lines.append(f"\n**Recommendation:** {comparison.get('recommendation')}")

    return "\n".join(lines)


def _format_gap_analysis(gaps: Dict) -> str:
    """Format hook gap analysis as markdown."""
    lines = ["## Hook Gap Analysis\n"]

    untested_types = gaps.get("untested_hook_types", [])
    untested_visual = gaps.get("untested_visual_types", [])
    undertested_types = gaps.get("undertested_hook_types", [])
    suggestions = gaps.get("suggestions", [])

    if untested_types:
        lines.append("### Untested Hook Types")
        lines.append(f"These hook types have never been used: **{', '.join(untested_types)}**")
        lines.append("")

    if untested_visual:
        lines.append("### Untested Visual Types")
        lines.append(f"These visual styles have never been used: **{', '.join(untested_visual)}**")
        lines.append("")

    if undertested_types:
        lines.append("### Undertested Hook Types")
        for item in undertested_types[:5]:
            lines.append(f"- **{item.get('type', 'unknown')}**: only {item.get('ad_count', 0)} ads")
        lines.append("")

    if suggestions:
        lines.append("### Recommendations")
        for sug in suggestions:
            lines.append(f"- {sug}")

    if not any([untested_types, untested_visual, undertested_types]):
        lines.append("Great coverage! All major hook types have been tested.")

    return "\n".join(lines)


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Find best performing hooks',
            'Analyze hook patterns',
            'Find hooks with high engagement but low conversion',
            'Compare hook types',
            'Find untested hook types',
        ],
        'examples': [
            'What hooks work best for Wonder Paws?',
            'Show me hooks with high hook rate but bad ROAS',
            'Which hooks are winners vs losers?',
            'Show me top hooks by hook rate',
            'Which visual hook types should I test?',
        ],
    }
)
async def hook_analysis(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    analysis_type: str = "overview",
    sort_by: str = "roas",
    hook_fingerprint: Optional[str] = None,
    compare_fingerprint: Optional[str] = None,
    limit: int = 10,
    product_id: str = "",
) -> str:
    """Analyze hook performance for a brand's video ads.

    Hooks are the first 3 seconds of video ads - critical for grabbing attention.
    This tool analyzes which hooks work best across your video ad inventory.

    Analysis types:
    - overview: Top performing hooks + key insights (default)
    - quadrant: Categorize hooks by hook_rate vs ROAS (winners, losers, etc.)
    - by_type: Performance breakdown by hook type (question, claim, etc.)
    - by_visual: Performance breakdown by visual type (unboxing, demo, etc.)
    - by_lp: Hooks grouped by landing page
    - compare: Compare two specific hooks (requires hook_fingerprint + compare_fingerprint)
    - gaps: Find untested hook types

    Sort options (for overview/by_type/by_visual):
    - roas: Return on ad spend (default)
    - hook_rate: Video hook rate (% past 3 sec)
    - spend: Total spend
    - ctr: Click-through rate

    Key insight: "quadrant" analysis reveals hooks with HIGH hook rate but LOW ROAS -
    these are engaging but not converting, suggesting downstream issues (LP, offer, etc.)

    PRODUCT-SCOPED: product_id filtering is currently only supported for
    analysis_type='overview'. For other types, omit product_id or use 'overview'.

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name to analyze (will be resolved to brand_id).
        analysis_type: Type of analysis (overview, quadrant, by_type, by_visual, by_lp, compare, gaps).
        sort_by: Sort metric for rankings (roas, hook_rate, spend, ctr).
        hook_fingerprint: Specific hook fingerprint for detail view or comparison.
        compare_fingerprint: Second hook fingerprint for comparison (used with analysis_type=compare).
        limit: Maximum hooks to return (default 10).
        product_id: Optional product UUID. Only honored when analysis_type='overview'.

    Returns:
        Formatted markdown with hook analysis results.
    """
    # Resolve brand name to brand_id
    brands = await ctx.deps.ad_intelligence.search_brands(brand_name)
    if not brands:
        return f"No brand found matching '{brand_name}'"

    brand_id = UUID(brands[0]["id"])
    brand_display_name = brands[0]["name"]

    # Instantiate hook analysis service
    hook_service = HookAnalysisService(ctx.deps.ad_intelligence.supabase)

    # Route to appropriate analysis
    valid_types = ["overview", "quadrant", "by_type", "by_visual", "by_lp", "compare", "gaps"]
    if analysis_type not in valid_types:
        return f"Invalid analysis_type. Valid options: {', '.join(valid_types)}"

    # Validate product_id is only used with supported types
    product_uuid = UUID(product_id) if product_id else None
    if product_uuid and analysis_type != "overview":
        return (
            f"product_id is only supported with analysis_type='overview'. "
            f"You requested analysis_type='{analysis_type}'. Either drop product_id "
            f"or switch to 'overview'."
        )

    try:
        if analysis_type == "overview":
            insights = hook_service.get_hook_insights(brand_id, product_id=product_uuid)
            top_hooks = hook_service.get_top_hooks_by_fingerprint(
                brand_id, limit=limit, sort_by=sort_by, product_id=product_uuid,
            )
            rendered = _format_hook_overview(insights, top_hooks)

        elif analysis_type == "quadrant":
            quadrants = hook_service.get_hooks_by_quadrant(brand_id)
            rendered = _format_quadrant_analysis(quadrants)

        elif analysis_type == "by_type":
            hooks_by_type = hook_service.get_hooks_by_type(brand_id)
            rendered = _format_hooks_by_type(hooks_by_type)

        elif analysis_type == "by_visual":
            hooks_by_visual = hook_service.get_hooks_by_visual_type(brand_id)
            rendered = _format_hooks_by_visual(hooks_by_visual)

        elif analysis_type == "by_lp":
            hooks_by_lp = hook_service.get_hooks_by_landing_page(brand_id, limit=limit)
            rendered = _format_hooks_by_lp(hooks_by_lp)

        elif analysis_type == "compare":
            if not hook_fingerprint or not compare_fingerprint:
                return "Comparison requires both hook_fingerprint and compare_fingerprint parameters."
            comparison = hook_service.get_hook_comparison(
                brand_id, hook_fingerprint, compare_fingerprint
            )
            rendered = _format_hook_comparison(comparison)

        elif analysis_type == "gaps":
            gaps = hook_service.get_untested_hook_types(brand_id)
            rendered = _format_gap_analysis(gaps)

        else:
            rendered = "Unknown analysis type."

        # Add brand context header
        output = f"**Brand:** {brand_display_name}\n\n{rendered}"

        # Cache result
        ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = str(brand_id)
        ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = brand_display_name
        ctx.deps.result_cache.custom["ad_intelligence_result"] = {
            "tool_name": "hook_analysis",
            "rendered_markdown": output,
        }

        return output

    except Exception as e:
        logger.error(f"Hook analysis failed for brand {brand_name}: {e}")
        return f"Hook analysis failed: {e}"


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Quick view of winning hooks',
            'Find hooks to scale',
        ],
        'examples': [
            'Show me the top 5 hooks for Wonder Paws',
            'What are the best performing hooks?',
            'Top hooks by ROAS',
        ],
    }
)
async def top_hooks(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    metric: str = "roas",
    limit: int = 5,
    product_id: str = "",
) -> str:
    """Quick view of top performing hooks ranked by a metric.

    Simpler than /hook_analysis - just returns the top N hooks
    with their key metrics and example transcripts.

    PRODUCT-SCOPED: Pass product_id when the user asks about hooks for a
    specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name to analyze.
        metric: Ranking metric (roas, hook_rate, spend, ctr). Default: roas.
        limit: Number of hooks to return (default 5).
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown with top hooks.
    """
    # Resolve brand name
    brands = await ctx.deps.ad_intelligence.search_brands(brand_name)
    if not brands:
        return f"No brand found matching '{brand_name}'"

    brand_id = UUID(brands[0]["id"])
    brand_display_name = brands[0]["name"]

    # Validate metric
    valid_metrics = ["roas", "hook_rate", "spend", "ctr"]
    if metric not in valid_metrics:
        return f"Invalid metric. Valid options: {', '.join(valid_metrics)}"

    # Get top hooks
    hook_service = HookAnalysisService(ctx.deps.ad_intelligence.supabase)
    product_uuid = UUID(product_id) if product_id else None

    try:
        hooks = hook_service.get_top_hooks_by_fingerprint(
            brand_id, limit=limit, sort_by=metric, product_id=product_uuid,
        )

        if not hooks:
            return f"No hook data found for {brand_display_name}. Run video ad analysis first."

        # Format output
        metric_labels = {
            "roas": "ROAS",
            "hook_rate": "Hook Rate",
            "spend": "Spend",
            "ctr": "CTR",
        }

        lines = [
            f"## Top {limit} Hooks for {brand_display_name}",
            f"*Ranked by {metric_labels[metric]}*\n",
        ]

        for i, hook in enumerate(hooks, 1):
            hook_type = hook.get("hook_type", "unknown")
            visual_type = hook.get("hook_visual_type", "unknown")
            spoken = hook.get("hook_transcript_spoken", "N/A") or "N/A"
            if len(spoken) > 70:
                spoken = spoken[:70] + "..."

            lines.append(f"**{i}. {hook_type.title()} hook** ({visual_type.replace('_', ' ')})")
            lines.append(f'   "{spoken}"')
            lines.append(
                f"   [CHART] {hook.get('ad_count', 0)} ads | "
                f"${hook.get('total_spend', 0):,.0f} spend | "
                f"{hook.get('avg_roas', 0):.2f}x ROAS | "
                f"{hook.get('avg_hook_rate', 0):.1%} hook rate"
            )
            lines.append("")

        output = "\n".join(lines)

        # Cache result
        ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = str(brand_id)
        ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = brand_display_name
        ctx.deps.result_cache.custom["ad_intelligence_result"] = {
            "tool_name": "top_hooks",
            "rendered_markdown": output,
        }

        return output

    except Exception as e:
        logger.error(f"Top hooks query failed for brand {brand_name}: {e}")
        return f"Failed to get top hooks: {e}"


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Meta',
        'use_cases': [
            'Find best hooks for a landing page',
            'Optimize hook/LP pairing',
        ],
        'examples': [
            'What hooks work best with the collagen landing page?',
            'Show me hooks used with wonderpaws.com/products/chews',
            'Best hooks for LP abc123',
        ],
    }
)
async def hooks_for_lp(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    landing_page_url: Optional[str] = None,
    landing_page_id: Optional[str] = None,
) -> str:
    """Get hook performance for a specific landing page.

    Shows which hooks drive best results when paired with this LP.
    Useful for optimizing creative/LP combinations.

    Either landing_page_url or landing_page_id must be provided.
    If neither is provided, returns all landing pages with their best hooks.

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name to analyze.
        landing_page_url: URL of landing page (partial match supported).
        landing_page_id: UUID of landing page.

    Returns:
        Formatted markdown with hooks for the landing page.
    """
    # Resolve brand name
    brands = await ctx.deps.ad_intelligence.search_brands(brand_name)
    if not brands:
        return f"No brand found matching '{brand_name}'"

    brand_id = UUID(brands[0]["id"])
    brand_display_name = brands[0]["name"]

    hook_service = HookAnalysisService(ctx.deps.ad_intelligence.supabase)

    try:
        # Get all LP data
        hooks_by_lp = hook_service.get_hooks_by_landing_page(brand_id, limit=50)

        if not hooks_by_lp:
            return f"No landing page/hook data found for {brand_display_name}."

        # Filter by URL or ID if provided
        target_lp = None
        if landing_page_id:
            for lp in hooks_by_lp:
                if lp.get("landing_page_id") == landing_page_id:
                    target_lp = lp
                    break
        elif landing_page_url:
            # Partial URL match
            url_lower = landing_page_url.lower()
            for lp in hooks_by_lp:
                lp_url = (lp.get("landing_page_url") or "").lower()
                if url_lower in lp_url or lp_url in url_lower:
                    target_lp = lp
                    break

        if target_lp:
            # Show specific LP
            lines = [f"## Hooks for Landing Page: {brand_display_name}\n"]

            url = target_lp.get("landing_page_url", "Unknown")
            title = target_lp.get("landing_page_title", "")
            lines.append(f"**URL:** {url}")
            if title:
                lines.append(f"**Title:** {title}")
            lines.append(
                f"**Total Spend:** ${target_lp.get('total_spend', 0):,.0f} | "
                f"**Avg ROAS:** {target_lp.get('avg_roas', 0):.2f}x | "
                f"**Hooks Used:** {target_lp.get('hook_count', 0)}"
            )
            lines.append("")

            hooks = target_lp.get("hooks", [])
            if hooks:
                lines.append("### Hook Performance")
                lines.append("| Hook Type | Visual Type | Spend | ROAS |")
                lines.append("|-----------|-------------|-------|------|")
                for hook in sorted(hooks, key=lambda x: x.get("roas", 0), reverse=True):
                    lines.append(
                        f"| {hook.get('type', 'unknown')} | "
                        f"{hook.get('visual_type', 'unknown')} | "
                        f"${hook.get('spend', 0):,.0f} | "
                        f"{hook.get('roas', 0):.2f}x |"
                    )
                lines.append("")

                # Best/worst hooks
                if target_lp.get("best_hook_fingerprint"):
                    lines.append(f"**Best hook fingerprint:** `{target_lp.get('best_hook_fingerprint')}`")

            output = "\n".join(lines)
        else:
            # Show all LPs summary
            if landing_page_url or landing_page_id:
                lines = [f"No matching landing page found. Available LPs for {brand_display_name}:\n"]
            else:
                lines = [f"## Landing Pages & Best Hooks: {brand_display_name}\n"]

            for lp in hooks_by_lp[:15]:
                url = lp.get("landing_page_url", "Unknown")
                display_url = url[:50] + "..." if len(url) > 50 else url
                lines.append(
                    f"- **{display_url}** | "
                    f"{lp.get('hook_count', 0)} hooks | "
                    f"${lp.get('total_spend', 0):,.0f} | "
                    f"{lp.get('avg_roas', 0):.2f}x ROAS"
                )

            if len(hooks_by_lp) > 15:
                lines.append(f"\n... and {len(hooks_by_lp) - 15} more LPs")

            lines.append("\nUse `/hooks_for_lp` with a specific URL to see hooks for that page.")
            output = "\n".join(lines)

        # Cache result
        ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = str(brand_id)
        ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = brand_display_name
        ctx.deps.result_cache.custom["ad_intelligence_result"] = {
            "tool_name": "hooks_for_lp",
            "rendered_markdown": output,
        }

        return output

    except Exception as e:
        logger.error(f"Hooks for LP query failed for brand {brand_name}: {e}")
        return f"Failed to get hooks for landing page: {e}"


# =============================================================================
# Performance Query Tools (Phase 8)
# =============================================================================


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'Rank ads by ROAS, spend, CTR, or any metric',
            'Find worst performing ads',
            'Filter by status or minimum spend',
        ],
        'examples': [
            'What are my top 5 ads by ROAS?',
            'Show worst ads by CPC with at least $50 spend',
            'Top 10 active ads by conversion rate',
        ],
    }
)
async def get_top_ads(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    sort_by: str = "roas",
    days_back: int = 30,
    limit: int = 10,
    sort_order: str = "desc",
    status_filter: str = "all",
    min_spend: float = 0.0,
    campaign_name_filter: str = "",
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    product_id: str = "",
) -> str:
    """Get top or bottom ads ranked by a performance metric.

    Use this for questions like "what are my best ads?" or "show worst performers".
    For deep diagnostics (what's wrong, which ads to kill), use analyze_account instead.

    PRODUCT-SCOPED: When the user asks about a specific product (e.g. "top ads
    for Cortisol Control"), pass the product UUID as product_id. The result
    will only include ads associated with that product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        sort_by: Metric to rank by. Valid: roas, spend, ctr, cpc, cpm, purchases,
            purchase_value, conversion_rate, impressions, reach, link_clicks,
            add_to_carts, frequency.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        limit: Number of ads to return (default 10).
        sort_order: 'desc' for top/best, 'asc' for bottom/worst.
        status_filter: 'all', 'active', or 'paused'.
        min_spend: Minimum spend threshold (e.g., 50.0 for $50+).
        campaign_name_filter: Filter to a specific campaign by name substring.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown table with top/bottom ads.
    """
    valid_sort_options = [
        "roas", "spend", "ctr", "cpc", "cpm", "purchases", "purchase_value",
        "conversion_rate", "impressions", "reach", "link_clicks", "add_to_carts",
        "frequency",
    ]
    if sort_by not in valid_sort_options:
        return f"Invalid sort_by '{sort_by}'. Valid options: {valid_sort_options}"

    valid_orders = ["desc", "asc"]
    if sort_order not in valid_orders:
        return f"Invalid sort_order '{sort_order}'. Valid options: {valid_orders}"

    valid_statuses = ["all", "active", "paused"]
    if status_filter not in valid_statuses:
        return f"Invalid status_filter '{status_filter}'. Valid options: {valid_statuses}"

    try:
        result = ctx.deps.ad_performance_query.get_top_ads(
            brand_id=brand_id,
            sort_by=sort_by,
            days_back=days_back,
            limit=limit,
            sort_order=sort_order,
            status_filter=status_filter,
            min_spend=min_spend,
            campaign_name_filter=campaign_name_filter,
            date_start=date_start,
            date_end=date_end,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"get_top_ads failed: {e}")
        return f"Failed to query top ads: {e}"

    ads = result["ads"]
    meta = result["meta"]

    if not ads:
        return (
            f"No ads found for the given filters.\n"
            f"Period: {meta['date_start']} to {meta['date_end']}"
        )

    # Format as markdown table
    direction = "Top" if sort_order == "desc" else "Bottom"
    metric_labels = {
        "roas": "ROAS", "spend": "Spend", "ctr": "CTR", "cpc": "CPC",
        "cpm": "CPM", "purchases": "Purchases", "purchase_value": "Revenue",
        "conversion_rate": "Conv Rate", "impressions": "Impressions",
        "reach": "Reach", "link_clicks": "Clicks", "add_to_carts": "ATCs",
        "frequency": "Frequency",
    }

    lines = [
        f"## {direction} {meta['returned']} Ads by {metric_labels.get(sort_by, sort_by)}",
        f"*Period: {meta['date_start']} to {meta['date_end']} | "
        f"{meta['total_matching']} ads matched filters*\n",
        "| # | Ad Name | Spend | ROAS | CTR | CPC | Purchases | Status |",
        "|---|---------|-------|------|-----|-----|-----------|--------|",
    ]

    for i, ad in enumerate(ads, 1):
        name = (ad["ad_name"] or "Unknown")[:40]
        if len(ad.get("ad_name", "") or "") > 40:
            name += "..."
        status = (ad.get("ad_status") or "-").title()
        lines.append(
            f"| {i} | {name} | "
            f"${ad['spend']:,.2f} | "
            f"{ad['roas']:.2f}x | "
            f"{ad['ctr']:.2f}% | "
            f"${ad['cpc']:.2f} | "
            f"{ad['purchases']} | "
            f"{status} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_top_ads",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'Account-level spend and performance summary',
            'Period-over-period comparison',
        ],
        'examples': [
            'How much did I spend this week?',
            'Compare this month to last month',
            'What was my ROAS last week?',
        ],
    }
)
async def get_account_summary(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    compare_previous: bool = False,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    product_id: str = "",
) -> str:
    """Get account-level performance summary with optional period comparison.

    Use this for "how much did I spend?" or "compare this week to last week".
    For deep diagnostics, use analyze_account instead.

    PRODUCT-SCOPED: When the user asks about a specific product (e.g. "how is
    Cortisol Control performing?"), pass the product UUID as product_id. The
    summary will only include ads associated with that product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        compare_previous: If true, also shows the previous period of same length
            and percentage changes.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown with account summary and optional comparison.
    """
    try:
        result = ctx.deps.ad_performance_query.get_account_summary(
            brand_id=brand_id,
            days_back=days_back,
            compare_previous=compare_previous,
            date_start=date_start,
            date_end=date_end,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"get_account_summary failed: {e}")
        return f"Failed to query account summary: {e}"

    cur = result["current"]
    meta = result["meta"]

    lines = [
        f"## Account Summary",
        f"*Period: {meta['date_start']} to {meta['date_end']} ({meta['days']} days)*\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Spend | ${cur['spend']:,.2f} |",
        f"| Impressions | {cur['impressions']:,} |",
        f"| Reach | {cur['reach']:,} |",
        f"| Link Clicks | {cur['link_clicks']:,} |",
        f"| CTR | {cur['ctr']:.2f}% |",
        f"| CPC | ${cur['cpc']:.2f} |",
        f"| CPM | ${cur['cpm']:.2f} |",
        f"| Add to Carts | {cur['add_to_carts']:,} |",
        f"| Purchases | {cur['purchases']:,} |",
        f"| Revenue | ${cur['purchase_value']:,.2f} |",
        f"| ROAS | {cur['roas']:.2f}x |",
        f"| Conv. Rate | {cur['conversion_rate']:.2f}% |",
        f"| Active Ads | {cur['unique_ads']} |",
        f"| Active Campaigns | {cur['unique_campaigns']} |",
    ]

    if compare_previous and "previous" in result:
        prev = result["previous"]
        change = result["change"]
        prev_meta = result["previous_meta"]

        def _fmt_change(val: float) -> str:
            if val > 0:
                return f"+{val:.1f}%"
            elif val < 0:
                return f"{val:.1f}%"
            return "0%"

        # Metrics where lower is better
        lower_is_better = {"cpc", "cpm"}

        def _indicator(key: str, val: float) -> str:
            if key in lower_is_better:
                return "improved" if val < 0 else ("worsened" if val > 0 else "flat")
            return "improved" if val > 0 else ("worsened" if val < 0 else "flat")

        lines.append(
            f"\n### vs Previous Period ({prev_meta['date_start']} to {prev_meta['date_end']})\n"
        )
        lines.append("| Metric | Current | Previous | Change |")
        lines.append("|--------|---------|----------|--------|")

        comparisons = [
            ("Spend", "spend", "${:,.2f}"),
            ("ROAS", "roas", "{:.2f}x"),
            ("CTR", "ctr", "{:.2f}%"),
            ("CPC", "cpc", "${:.2f}"),
            ("Purchases", "purchases", "{:,}"),
            ("Revenue", "purchase_value", "${:,.2f}"),
            ("Conv. Rate", "conversion_rate", "{:.2f}%"),
        ]

        for label, key, fmt in comparisons:
            c_val = cur.get(key, 0)
            p_val = prev.get(key, 0)
            chg = change.get(key, 0)
            lines.append(
                f"| {label} | {fmt.format(c_val)} | {fmt.format(p_val)} | {_fmt_change(chg)} |"
            )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_account_summary",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'Campaign-level performance breakdown',
            'Adset-level performance breakdown',
        ],
        'examples': [
            'Which campaigns are performing best?',
            'Show campaign breakdown by ROAS',
            'How are my ad sets doing?',
        ],
    }
)
async def get_campaign_breakdown(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    level: str = "campaign",
    days_back: int = 30,
    sort_by: str = "spend",
    limit: int = 20,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    product_id: str = "",
) -> str:
    """Get performance breakdown by campaign or adset level.

    Use this for "which campaigns are best?" or "show adset performance".

    PRODUCT-SCOPED: Pass product_id when the user asks about a specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        level: Aggregation level. Valid: 'campaign' or 'adset'.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        sort_by: Metric to sort by. Valid: roas, spend, ctr, cpc, cpm, purchases,
            purchase_value, conversion_rate, impressions, link_clicks, add_to_carts.
        limit: Number of items to return (default 20).
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown table with campaign or adset breakdown.
    """
    valid_levels = ["campaign", "adset"]
    if level not in valid_levels:
        return f"Invalid level '{level}'. Valid options: {valid_levels}"

    valid_sort_options = [
        "roas", "spend", "ctr", "cpc", "cpm", "purchases", "purchase_value",
        "conversion_rate", "impressions", "link_clicks", "add_to_carts",
    ]
    if sort_by not in valid_sort_options:
        return f"Invalid sort_by '{sort_by}'. Valid options: {valid_sort_options}"

    try:
        result = ctx.deps.ad_performance_query.get_campaign_breakdown(
            brand_id=brand_id,
            level=level,
            days_back=days_back,
            sort_by=sort_by,
            limit=limit,
            date_start=date_start,
            date_end=date_end,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"get_campaign_breakdown failed: {e}")
        return f"Failed to query campaign breakdown: {e}"

    items = result["items"]
    meta = result["meta"]

    if not items:
        return (
            f"No {level} data found.\n"
            f"Period: {meta['date_start']} to {meta['date_end']}"
        )

    level_title = "Campaign" if level == "campaign" else "Ad Set"
    name_key = "campaign_name" if level == "campaign" else "adset_name"

    lines = [
        f"## {level_title} Breakdown",
        f"*Period: {meta['date_start']} to {meta['date_end']} | "
        f"{meta['total']} total {level}s*\n",
        f"| # | {level_title} | Spend | ROAS | CTR | Purchases | Ads |",
        f"|---|{'---' * len(level_title)}|-------|------|-----|-----------|-----|",
    ]

    for i, item in enumerate(items, 1):
        name = (item.get(name_key) or "Unknown")[:35]
        if len(item.get(name_key, "") or "") > 35:
            name += "..."
        lines.append(
            f"| {i} | {name} | "
            f"${item['spend']:,.2f} | "
            f"{item['roas']:.2f}x | "
            f"{item['ctr']:.2f}% | "
            f"{item['purchases']} | "
            f"{item['ad_count']} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_campaign_breakdown",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'Deep dive into a specific ad',
            'View daily trends for an ad',
            'Look up ad by name or ID',
        ],
        'examples': [
            'Tell me about ad 12345',
            'Show me details for the collagen video ad',
            'How is my "Summer Sale" ad performing?',
        ],
    }
)
async def get_ad_details(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    ad_identifier: str,
    days_back: int = 30,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """Get detailed performance for a specific ad including daily trends.

    Searches by Meta ad ID (exact match) or ad name (substring match).
    Shows aggregate summary plus day-by-day performance trend.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        ad_identifier: Meta ad ID (exact) or ad name (substring search).
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').

    Returns:
        Formatted markdown with ad summary and daily trend table.
    """
    try:
        result = ctx.deps.ad_performance_query.get_ad_details(
            brand_id=brand_id,
            ad_identifier=ad_identifier,
            days_back=days_back,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as e:
        logger.error(f"get_ad_details failed: {e}")
        return f"Failed to query ad details: {e}"

    ad = result.get("ad")
    daily = result.get("daily", [])
    meta = result.get("meta", {})

    if not ad:
        error = meta.get("error", "Ad not found")
        suggestions = meta.get("suggestions", [])
        if suggestions:
            lines = [f"**{error}**\n", "Did you mean one of these?\n"]
            for s in suggestions:
                lines.append(f"- **{s['ad_name']}** (ID: `{s['meta_ad_id']}`, Spend: ${s['spend']:,.2f})")
            return "\n".join(lines)
        return error

    # Ad summary
    lines = [
        f"## Ad Details: {ad['ad_name']}",
        f"*ID: `{ad['meta_ad_id']}` | Status: {(ad.get('ad_status') or '-').title()} | "
        f"Campaign: {ad.get('campaign_name', '-')}*\n",
        "### Summary",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Spend | ${ad['spend']:,.2f} |",
        f"| Impressions | {ad['impressions']:,} |",
        f"| Reach | {ad.get('reach', 0):,} |",
        f"| Link Clicks | {ad['link_clicks']:,} |",
        f"| CTR | {ad['ctr']:.2f}% |",
        f"| CPC | ${ad['cpc']:.2f} |",
        f"| CPM | ${ad['cpm']:.2f} |",
        f"| Purchases | {ad['purchases']} |",
        f"| Revenue | ${ad.get('purchase_value', 0):,.2f} |",
        f"| ROAS | {ad['roas']:.2f}x |",
        f"| Conv. Rate | {ad.get('conversion_rate', 0):.2f}% |",
    ]

    # Daily trend
    if daily:
        lines.append(f"\n### Daily Trend ({meta.get('days_with_data', 0)} days)")
        lines.append("| Date | Spend | ROAS | Clicks | Purchases |")
        lines.append("|------|-------|------|--------|-----------|")

        for day in daily:
            lines.append(
                f"| {day['date']} | "
                f"${day['spend']:,.2f} | "
                f"{day['roas']:.2f}x | "
                f"{day['link_clicks']} | "
                f"{day['purchases']} |"
            )

        # Video metrics if present
        has_video = any(d.get("video_views", 0) > 0 for d in daily)
        if has_video:
            total_views = sum(d.get("video_views", 0) for d in daily)
            avg_hook = sum(d.get("hook_rate", 0) for d in daily if d.get("hook_rate", 0) > 0)
            hook_days = sum(1 for d in daily if d.get("hook_rate", 0) > 0)
            avg_hold = sum(d.get("hold_rate", 0) for d in daily if d.get("hold_rate", 0) > 0)
            hold_days = sum(1 for d in daily if d.get("hold_rate", 0) > 0)

            lines.append("\n### Video Metrics")
            lines.append(f"- **Total Video Views:** {total_views:,}")
            if hook_days > 0:
                lines.append(f"- **Avg Hook Rate:** {avg_hook / hook_days:.1%}")
            if hold_days > 0:
                lines.append(f"- **Avg Hold Rate:** {avg_hold / hold_days:.1%}")

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_ad_details",
        "rendered_markdown": output,
    }
    return output


# =============================================================================
# Breakdown Tools (Phase 9 — Media Type, Landing Page, Product)
# =============================================================================


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'Compare video vs image ad performance',
            'See which media format works best',
            'Break down performance by creative format',
        ],
        'examples': [
            'How do video ads compare to image ads?',
            'Compare video vs image ad performance',
            'Which media type has the best ROAS?',
        ],
    }
)
async def get_breakdown_by_media_type(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    awareness_level: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    product_id: str = "",
) -> str:
    """Get performance breakdown by media type (video/image/carousel/other).

    Shows aggregate spend, ROAS, CPA, CTR, and purchases for each media type.
    Uses classification data to determine creative format. Only classified ads
    are included in the breakdown.

    PRODUCT-SCOPED: Pass product_id when the user asks about a specific product.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        awareness_level: Optional filter. Valid: unaware, problem_aware, solution_aware,
            product_aware, most_aware. When set, only shows ads classified at that level.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').
        product_id: Optional product UUID. If set, restricts to ads for that product.

    Returns:
        Formatted markdown table with media type breakdown.
    """
    valid_awareness_levels = [
        "unaware", "problem_aware", "solution_aware", "product_aware", "most_aware",
    ]
    if awareness_level and awareness_level not in valid_awareness_levels:
        return f"Invalid awareness_level '{awareness_level}'. Valid: {valid_awareness_levels}"

    try:
        result = ctx.deps.ad_performance_query.get_breakdown_by_media_type(
            brand_id=brand_id,
            days_back=days_back,
            awareness_level=awareness_level,
            date_start=date_start,
            date_end=date_end,
            product_id=product_id or None,
        )
    except Exception as e:
        logger.error(f"get_breakdown_by_media_type failed: {e}")
        return f"Failed to query media type breakdown: {e}"

    groups = result["groups"]
    meta = result["meta"]

    if not groups:
        msg = meta.get("message", "No data found.")
        return f"{msg}\nPeriod: {meta['date_start']} to {meta['date_end']}"

    awareness_note = f" | Awareness: {awareness_level}" if awareness_level else ""
    lines = [
        f"## Performance by Media Type",
        f"*Period: {meta['date_start']} to {meta['date_end']}{awareness_note}*\n",
        "| Media Type | Ads | Spend | ROAS | CPA | CTR | Purchases | Revenue |",
        "|------------|-----|-------|------|-----|-----|-----------|---------|",
    ]

    for g in groups:
        cpa_str = f"${g['cpa']:,.2f}" if g['cpa'] > 0 else "-"
        lines.append(
            f"| {g['media_type']} | "
            f"{g['ad_count']} | "
            f"${g['spend']:,.2f} | "
            f"{g['roas']:.2f}x | "
            f"{cpa_str} | "
            f"{g['ctr']:.2f}% | "
            f"{g['purchases']} | "
            f"${g['purchase_value']:,.2f} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_breakdown_by_media_type",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'See which landing pages perform best',
            'Break down performance by offer variant',
            'Compare landing page ROAS and CPA',
        ],
        'examples': [
            'Which landing pages have the best ROAS?',
            'Break down performance by offer variant',
            'Show me CPA by landing page',
            'Which LPs convert best?',
        ],
    }
)
async def get_breakdown_by_landing_page(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    sort_by: str = "spend",
    limit: int = 20,
    awareness_level: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """Get performance breakdown by landing page (offer variant).

    Shows aggregate spend, ROAS, CPA, and purchases for ALL ad types
    (video, image, carousel) per landing page. For video hook-specific
    LP performance, use hook_analysis with analysis_type='by_lp' instead.

    Ads without a classified landing page go into an "Unclassified" bucket.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        sort_by: Metric to sort by. Valid: spend, roas, cpa, purchases, purchase_value,
            ctr, cpc, impressions, ad_count.
        limit: Number of landing pages to return (default 20).
        awareness_level: Optional filter. Valid: unaware, problem_aware, solution_aware,
            product_aware, most_aware.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').

    Returns:
        Formatted markdown table with landing page breakdown.
    """
    valid_awareness_levels = [
        "unaware", "problem_aware", "solution_aware", "product_aware", "most_aware",
    ]
    if awareness_level and awareness_level not in valid_awareness_levels:
        return f"Invalid awareness_level '{awareness_level}'. Valid: {valid_awareness_levels}"

    valid_sort_options = [
        "spend", "roas", "cpa", "purchases", "purchase_value",
        "ctr", "cpc", "impressions", "ad_count",
    ]
    if sort_by not in valid_sort_options:
        return f"Invalid sort_by '{sort_by}'. Valid options: {valid_sort_options}"

    try:
        result = ctx.deps.ad_performance_query.get_breakdown_by_landing_page(
            brand_id=brand_id,
            days_back=days_back,
            sort_by=sort_by,
            limit=limit,
            awareness_level=awareness_level,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as e:
        logger.error(f"get_breakdown_by_landing_page failed: {e}")
        return f"Failed to query landing page breakdown: {e}"

    items = result["items"]
    meta = result["meta"]

    if not items:
        msg = meta.get("message", "No data found.")
        return f"{msg}\nPeriod: {meta['date_start']} to {meta['date_end']}"

    awareness_note = f" | Awareness: {awareness_level}" if awareness_level else ""
    lines = [
        f"## Performance by Landing Page",
        f"*Period: {meta['date_start']} to {meta['date_end']}{awareness_note} | "
        f"{meta['total']} total LPs*\n",
        "| # | Landing Page | Ads | Spend | ROAS | CPA | Purchases |",
        "|---|-------------|-----|-------|------|-----|-----------|",
    ]

    for i, item in enumerate(items, 1):
        url = item.get("url") or "Unknown"
        title = item.get("page_title") or ""
        # Show title if available, otherwise show URL path
        if title:
            display = title[:40]
            if len(title) > 40:
                display += "..."
        else:
            # Strip protocol for cleaner display
            display_url = url.replace("https://", "").replace("http://", "")
            display = display_url[:45]
            if len(display_url) > 45:
                display += "..."
        cpa_str = f"${item['cpa']:,.2f}" if item['cpa'] > 0 else "-"
        lines.append(
            f"| {i} | {display} | "
            f"{item['ad_count']} | "
            f"${item['spend']:,.2f} | "
            f"{item['roas']:.2f}x | "
            f"{cpa_str} | "
            f"{item['purchases']} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_breakdown_by_landing_page",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        'category': 'Performance',
        'platform': 'Meta',
        'use_cases': [
            'See which products perform best',
            'Compare product ad performance',
            'Break down spend and ROAS by product',
        ],
        'examples': [
            'Which products are performing best?',
            'Show me CPA by product',
            'Which products are most profitable?',
            'Break down performance by product',
        ],
    }
)
async def get_breakdown_by_product(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    sort_by: str = "spend",
    limit: int = 20,
    awareness_level: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """Get performance breakdown by product.

    Groups ads by the product their landing page promotes. Uses product_id
    for reliable grouping when available, falls back to product_name text.
    Ads without product info go into "Unknown Product" bucket.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        sort_by: Metric to sort by. Valid: spend, roas, cpa, purchases, purchase_value,
            ctr, cpc, impressions, ad_count.
        limit: Number of products to return (default 20).
        awareness_level: Optional filter. Valid: unaware, problem_aware, solution_aware,
            product_aware, most_aware.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').

    Returns:
        Formatted markdown table with product breakdown.
    """
    valid_awareness_levels = [
        "unaware", "problem_aware", "solution_aware", "product_aware", "most_aware",
    ]
    if awareness_level and awareness_level not in valid_awareness_levels:
        return f"Invalid awareness_level '{awareness_level}'. Valid: {valid_awareness_levels}"

    valid_sort_options = [
        "spend", "roas", "cpa", "purchases", "purchase_value",
        "ctr", "cpc", "impressions", "ad_count",
    ]
    if sort_by not in valid_sort_options:
        return f"Invalid sort_by '{sort_by}'. Valid options: {valid_sort_options}"

    try:
        result = ctx.deps.ad_performance_query.get_breakdown_by_product(
            brand_id=brand_id,
            days_back=days_back,
            sort_by=sort_by,
            limit=limit,
            awareness_level=awareness_level,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as e:
        logger.error(f"get_breakdown_by_product failed: {e}")
        return f"Failed to query product breakdown: {e}"

    items = result["items"]
    meta = result["meta"]

    if not items:
        msg = meta.get("message", "No data found.")
        return f"{msg}\nPeriod: {meta['date_start']} to {meta['date_end']}"

    awareness_note = f" | Awareness: {awareness_level}" if awareness_level else ""
    lines = [
        f"## Performance by Product",
        f"*Period: {meta['date_start']} to {meta['date_end']}{awareness_note} | "
        f"{meta['total']} total products*\n",
        "| # | Product | Ads | Spend | ROAS | CPA | Purchases | Revenue |",
        "|---|---------|-----|-------|------|-----|-----------|---------|",
    ]

    for i, item in enumerate(items, 1):
        name = (item.get("product_name") or "Unknown")[:30]
        if len(item.get("product_name", "") or "") > 30:
            name += "..."
        cpa_str = f"${item['cpa']:,.2f}" if item['cpa'] > 0 else "-"
        lines.append(
            f"| {i} | {name} | "
            f"{item['ad_count']} | "
            f"${item['spend']:,.2f} | "
            f"{item['roas']:.2f}x | "
            f"{cpa_str} | "
            f"{item['purchases']} | "
            f"${item['purchase_value']:,.2f} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_breakdown_by_product",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        "category": "Query",
        "platform": "Meta Ads",
        "use_cases": [
            "Compare performance across awareness levels",
            "Find funnel gaps by awareness stage",
            "See spend distribution by awareness level",
        ],
        "examples": [
            "Break down performance by awareness level",
            "How does spend compare across awareness stages?",
            "Show me ROAS by awareness level for the last 30 days",
        ],
    }
)
async def get_breakdown_by_awareness(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 30,
    product_id: Optional[str] = None,
    format_filter: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """Get performance breakdown by consumer awareness level (Schwartz model).

    Groups classified ads by awareness level and computes spend, CTR, ROAS, CPA
    per level. Identifies funnel gaps.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        product_id: Optional product UUID to filter by.
        format_filter: Optional 'video' or 'image' to filter by creative format.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').

    Returns:
        Formatted markdown table with awareness-level breakdown.
    """
    try:
        result = ctx.deps.ad_performance_query.get_breakdown_by_awareness(
            brand_id=brand_id,
            days_back=days_back,
            product_id=product_id,
            format_filter=format_filter,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as e:
        logger.error(f"get_breakdown_by_awareness failed: {e}")
        return f"Failed to query awareness breakdown: {e}"

    levels = result.get("levels", [])
    gaps = result.get("gaps", [])

    if not levels:
        return "No classified ads found for this brand/period."

    lines = [
        "## Performance by Awareness Level",
        f"*{result.get('classified_ads', 0)} classified of {result.get('total_ads', 0)} total ads*\n",
        "| Level | Ads | Spend | ROAS | CPA | CTR | Purchases |",
        "|-------|-----|-------|------|-----|-----|-----------|",
    ]

    for lvl in levels:
        cpa_str = f"${lvl.get('cpa', 0):,.2f}" if lvl.get("cpa", 0) > 0 else "-"
        lines.append(
            f"| {lvl.get('label', lvl.get('level', '?'))} | "
            f"{lvl.get('ad_count', 0)} | "
            f"${lvl.get('spend', 0):,.2f} | "
            f"{lvl.get('roas', 0):.2f}x | "
            f"{cpa_str} | "
            f"{lvl.get('ctr', 0):.2f}% | "
            f"{lvl.get('purchases', 0)} |"
        )

    if gaps:
        lines.append(f"\n**Funnel gaps:** {', '.join(gaps)}")

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_breakdown_by_awareness",
        "rendered_markdown": output,
    }
    return output


@ad_intelligence_agent.tool(
    metadata={
        "category": "Query",
        "platform": "Meta Ads",
        "use_cases": [
            "Find top ads at a specific awareness level",
            "See best ROAS ads for problem-aware audience",
            "Top performing most-aware ads",
        ],
        "examples": [
            "Show top ads for problem_aware",
            "Best performing most_aware ads this month",
            "Top 5 solution_aware ads by ROAS",
        ],
    }
)
async def get_top_ads_by_awareness(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    awareness_level: str,
    days_back: int = 30,
    limit: int = 10,
    product_id: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """Get top performing ads for a specific awareness level, sorted by ROAS.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        awareness_level: One of: unaware, problem_aware, solution_aware, product_aware, most_aware.
        days_back: Days to look back (default 30). Ignored if date_start/date_end set.
        limit: Max ads to return (default 10).
        product_id: Optional product UUID to filter by.
        date_start: Explicit start date, ISO format (e.g., '2026-01-01').
        date_end: Explicit end date, ISO format (e.g., '2026-01-31').

    Returns:
        Formatted markdown table with top ads for that awareness level.
    """
    valid_levels = ["unaware", "problem_aware", "solution_aware", "product_aware", "most_aware"]
    if awareness_level not in valid_levels:
        return f"Invalid awareness_level '{awareness_level}'. Valid: {valid_levels}"

    try:
        result = ctx.deps.ad_performance_query.get_top_ads_by_awareness(
            brand_id=brand_id,
            awareness_level=awareness_level,
            days_back=days_back,
            limit=limit,
            product_id=product_id,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as e:
        logger.error(f"get_top_ads_by_awareness failed: {e}")
        return f"Failed to query top ads by awareness: {e}"

    ads = result.get("ads", [])
    meta = result.get("meta", {})

    if not ads:
        return f"No ads found for awareness level '{awareness_level}' in this period."

    level_label = awareness_level.replace("_", " ").title()
    lines = [
        f"## Top {level_label} Ads",
        f"*{meta.get('total', len(ads))} ads found*\n",
        "| # | Ad Name | Spend | ROAS | Purchases | Revenue | Format |",
        "|---|---------|-------|------|-----------|---------|--------|",
    ]

    for i, ad in enumerate(ads[:limit], 1):
        name = (ad.get("ad_name") or "Untitled")[:35]
        if len(ad.get("ad_name", "") or "") > 35:
            name += "..."
        fmt = ad.get("creative_format", "-")
        lines.append(
            f"| {i} | {name} | "
            f"${ad.get('spend', 0):,.2f} | "
            f"{ad.get('roas', 0):.2f}x | "
            f"{ad.get('purchases', 0)} | "
            f"${ad.get('purchase_value', 0):,.2f} | "
            f"{fmt} |"
        )

    output = "\n".join(lines)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "get_top_ads_by_awareness",
        "rendered_markdown": output,
    }
    return output


logger.info("Ad Intelligence Agent initialized with 21 tools")
