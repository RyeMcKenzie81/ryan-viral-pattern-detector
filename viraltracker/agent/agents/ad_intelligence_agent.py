"""
Ad Intelligence Agent - Evaluates Meta ad performance, classifies creatives
by awareness level, diagnoses issues, and produces actionable recommendations.

Chat-first UX with slash commands:
- /analyze_account: Full 4-layer analysis
- /recommend: View recommendation inbox
- /fatigue_check: Check for fatigued ads
- /coverage_gaps: Analyze inventory coverage
- /congruence_check: Check creative-copy-LP alignment
- /rec_done, /rec_ignore, /rec_note: Manage recommendations

8 thin tools delegating to AdIntelligenceService facade.
"""

import logging
from datetime import date
from typing import Dict, Optional
from uuid import UUID

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies
from ...core.config import Config

logger = logging.getLogger(__name__)

ad_intelligence_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Ad Intelligence Agent for the ViralTracker system.

Your role is to analyze Meta ad account performance and provide actionable insights.

**Your capabilities:**
1. **Full Account Analysis** - Classify ads by awareness level, compute baselines,
   diagnose issues, and generate recommendations
2. **Recommendation Management** - View, acknowledge, and act on recommendations
3. **Fatigue Detection** - Identify ads suffering from audience fatigue
4. **Coverage Analysis** - Find gaps in awareness level × creative format inventory
5. **Congruence Checking** - Verify creative, copy, and landing page alignment

**How you work:**
- You use a 4-layer model: Classification → Baselines → Diagnosis → Recommendations
- Classifications are awareness-level based (unaware → most_aware)
- Baselines are contextual cohort benchmarks (p25/median/p75)
- Diagnostics use 12 rules with prerequisite checks (no silent failures)
- Recommendations include evidence and suggested actions

**Important:**
- Always identify the brand_id from context before calling tools
- Use the ChatRenderer output directly — it's already formatted for chat
- When users ask about "which ads to kill" or "what's not working", use analyze_account
- When users ask about "fatigued ads" or "frequency", use check_fatigue
- When users ask about "gaps" or "missing awareness levels", use check_coverage_gaps
"""
)


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

    config = RunConfig(days_back=days_back)

    result = await ctx.deps.ad_intelligence.full_analysis(
        brand_id=UUID(brand_id),
        org_id=ctx.deps.ad_intelligence.supabase.table("brands").select(
            "organization_id"
        ).eq("id", brand_id).limit(1).execute().data[0]["organization_id"],
        config=config,
        goal=goal or None,
    )
    return ChatRenderer.render_account_analysis(result)


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
    return ChatRenderer.render_recommendations(recs)


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
    return ChatRenderer.render_fatigue_check(result)


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
    return ChatRenderer.render_coverage_gaps(result)


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
    return ChatRenderer.render_congruence_check(result)


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
    return ChatRenderer.render_status_update(rec)


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
    return ChatRenderer.render_status_update(rec)


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
    return ChatRenderer.render_status_update(rec)


logger.info("Ad Intelligence Agent initialized with 8 tools")
