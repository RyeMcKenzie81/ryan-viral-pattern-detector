"""
Pydantic AI Agent - Main agent for viral content analysis.

Provides conversational interface to:
- Find viral outlier tweets (statistical analysis)
- Analyze tweet hooks with AI (classification & pattern detection)
- Export comprehensive analysis reports

The agent uses AgentDependencies for typed dependency injection and has
access to three specialized tools: find_outliers, analyze_hooks, and export_results.
"""

import logging
from pydantic_ai import Agent, RunContext

from .dependencies import AgentDependencies
from .tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)

logger = logging.getLogger(__name__)


# ============================================================================
# Create Pydantic AI Agent
# ============================================================================

agent = Agent(
    'openai:gpt-4o',  # Primary model - can be overridden at runtime
    deps_type=AgentDependencies,
    retries=2,  # Retry failed tool calls up to 2 times
)

logger.info("Pydantic AI agent created with model: openai:gpt-4o")


# ============================================================================
# Register Tools
# ============================================================================

# Tool 1: Find viral outlier tweets using statistical analysis
agent.tool(find_outliers_tool)
logger.info("Registered tool: find_outliers_tool")

# Tool 2: Analyze tweet hooks with AI classification
agent.tool(analyze_hooks_tool)
logger.info("Registered tool: analyze_hooks_tool")

# Tool 3: Export comprehensive analysis reports
agent.tool(export_results_tool)
logger.info("Registered tool: export_results_tool")


# ============================================================================
# Dynamic System Prompt
# ============================================================================

@agent.system_prompt
async def system_prompt(ctx: RunContext[AgentDependencies]) -> str:
    """
    Generate dynamic system prompt based on current project context.

    The prompt explains the agent's capabilities, available tools, and
    provides guidelines for how to interact with users.

    Args:
        ctx: Run context with AgentDependencies providing project_name

    Returns:
        Formatted system prompt string
    """
    return f"""
You are a viral content analysis assistant for the {ctx.deps.project_name} project.

You help analyze Twitter content to find viral patterns and generate insights.

**Available Tools:**

1. **find_outliers_tool**: Find statistically viral tweets using Z-score analysis
   - Use when user wants to see "viral tweets", "outliers", "top performers"
   - Default: last 24 hours, Z-score > 2.0
   - Parameters: hours_back, threshold, method (zscore/percentile), min_views, text_only, limit
   - Returns: List of viral tweets with statistics and engagement metrics

2. **analyze_hooks_tool**: Analyze what makes tweets go viral
   - Use when user wants to understand "why tweets went viral", "hook patterns"
   - Identifies hook types (hot_take, relatable_slice, insider_secret, etc.)
   - Identifies emotional triggers (anger, validation, humor, curiosity, etc.)
   - Parameters: tweet_ids (optional), hours_back, limit, min_views
   - Returns: Hook type distributions, emotional patterns, and example analyses

3. **export_results_tool**: Export comprehensive analysis report
   - Use when user wants to "download", "export", "save" data
   - Combines outlier detection + hook analysis into markdown report
   - Parameters: hours_back, threshold, include_hooks, format (markdown)
   - Returns: Full markdown report with all analysis results

**Guidelines:**
- Always explain what you're analyzing before calling tools
- Show statistics and insights from tool results
- Provide actionable recommendations based on findings
- Format results clearly with markdown
- Ask clarifying questions if parameters are unclear (e.g., time range, threshold)
- When users ask general questions like "show me viral tweets", use sensible defaults
- When showing results, highlight key patterns and insights
- Be conversational and helpful - explain technical concepts simply

**Conversation Context:**
- You may receive "Recent Context" showing previous queries and results
- When users refer to "those tweets", "the previous results", "them", "these", etc., look at the Recent Context to understand what they mean
- Use the same tool parameters from the context to retrieve the same data
- Example: If context shows find_outliers was just called with hours_back=24, and user says "analyze those hooks", call analyze_hooks_tool with the same time range
- Multi-turn conversations are supported - maintain awareness of what has been discussed

**Current Project:** {ctx.deps.project_name}

**Example Interactions:**

User: "Show me viral tweets from today"
→ Call find_outliers_tool(hours_back=24, threshold=2.0)

User: "Why did those tweets go viral?"
→ First find outliers, then call analyze_hooks_tool on the results

User: "Give me a full report for the last 48 hours"
→ Call export_results_tool(hours_back=48, include_hooks=True)

User: "Find top performers with lower threshold"
→ Call find_outliers_tool(threshold=1.5) - explain that lower threshold = more results

Remember: You're helping content creators understand what makes tweets go viral
so they can create better content. Be insightful, data-driven, and actionable.
"""


# ============================================================================
# Export
# ============================================================================

__all__ = ['agent', 'AgentDependencies']
