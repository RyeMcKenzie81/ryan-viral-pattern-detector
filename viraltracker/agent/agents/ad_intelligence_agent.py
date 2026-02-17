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

12 thin tools delegating to AdIntelligenceService facade.
"""

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

ad_intelligence_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Ad Intelligence Agent for the ViralTracker system.

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
"""
)


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
) -> str:
    """Run full 4-layer account analysis: classify → baseline → diagnose → recommend.

    Creates an analysis run, classifies all active ads by awareness level,
    computes cohort baselines, runs diagnostic rules, and generates
    actionable recommendations.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Number of days to analyze (default: 30).
        goal: Analysis goal (e.g., 'lower_cpa', 'scale', 'stability').

    Returns:
        Formatted markdown with analysis results.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer
    from ...services.ad_intelligence.models import RunConfig

    # Interactive mode: low limits to avoid Streamlit timeout.
    # Skip new video classifications (41s each) — use cached only.
    # Cap new image classifications at 20 to stay under ~60s.
    config = RunConfig(
        days_back=days_back,
        max_classifications_per_run=20,
        max_video_classifications_per_run=0,
    )

    result = await ctx.deps.ad_intelligence.full_analysis(
        brand_id=UUID(brand_id),
        org_id=ctx.deps.ad_intelligence.supabase.table("brands").select(
            "organization_id"
        ).eq("id", brand_id).limit(1).execute().data[0]["organization_id"],
        config=config,
        goal=goal or None,
    )

    # Cache brand context and run_id for follow-up queries
    ctx.deps.result_cache.custom["ad_intelligence_brand_id"] = brand_id
    ctx.deps.result_cache.custom["ad_intelligence_brand_name"] = result.brand_name
    ctx.deps.result_cache.custom["ad_intelligence_run_id"] = str(result.run_id)

    rendered = ChatRenderer.render_account_analysis(result)
    ctx.deps.result_cache.custom["ad_intelligence_result"] = {
        "tool_name": "analyze_account",
        "rendered_markdown": rendered,
    }
    return rendered


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
) -> str:
    """Check all active ads for fatigue signals (frequency + CTR trends).

    Identifies fatigued ads (high frequency + declining CTR),
    at-risk ads (approaching thresholds), and healthy ads.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.
        days_back: Days of trend data to analyze.

    Returns:
        Formatted markdown with fatigue results.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.fatigue.check_fatigue(
        brand_id=UUID(brand_id),
        date_range_end=date.today(),
        days_back=days_back,
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
) -> str:
    """Analyze ad inventory coverage across awareness levels and formats.

    Builds an awareness level × creative format matrix and identifies
    hard gaps (zero ads), SPOFs (< 2 ads), and percentage gaps.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.

    Returns:
        Formatted markdown with coverage matrix and gaps.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.coverage.analyze_coverage(
        brand_id=UUID(brand_id),
        date_range_end=date.today(),
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
) -> str:
    """Check creative-copy-landing page awareness level alignment.

    Computes congruence scores for all classified ads and identifies
    those with significant misalignment between components.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.

    Returns:
        Formatted markdown with congruence results.
    """
    from ...services.ad_intelligence.chat_renderer import ChatRenderer

    result = await ctx.deps.ad_intelligence.congruence.check_congruence(
        brand_id=UUID(brand_id),
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

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name to analyze (will be resolved to brand_id).
        analysis_type: Type of analysis (overview, quadrant, by_type, by_visual, by_lp, compare, gaps).
        sort_by: Sort metric for rankings (roas, hook_rate, spend, ctr).
        hook_fingerprint: Specific hook fingerprint for detail view or comparison.
        compare_fingerprint: Second hook fingerprint for comparison (used with analysis_type=compare).
        limit: Maximum hooks to return (default 10).

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

    try:
        if analysis_type == "overview":
            insights = hook_service.get_hook_insights(brand_id)
            top_hooks = hook_service.get_top_hooks_by_fingerprint(
                brand_id, limit=limit, sort_by=sort_by
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
) -> str:
    """Quick view of top performing hooks ranked by a metric.

    Simpler than /hook_analysis - just returns the top N hooks
    with their key metrics and example transcripts.

    Args:
        ctx: Run context with AgentDependencies.
        brand_name: Brand name to analyze.
        metric: Ranking metric (roas, hook_rate, spend, ctr). Default: roas.
        limit: Number of hooks to return (default 5).

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

    try:
        hooks = hook_service.get_top_hooks_by_fingerprint(
            brand_id, limit=limit, sort_by=metric
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


logger.info("Ad Intelligence Agent initialized with 12 tools")
