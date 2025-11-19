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
    export_results_tool,
    get_top_tweets_tool
)
from .tools_phase15 import (
    search_twitter_tool,
    find_comment_opportunities_tool,
    export_comments_tool,
    analyze_search_term_tool,
    generate_content_tool
)
from .tools_phase16 import (
    search_tiktok_tool,
    search_tiktok_hashtag_tool,
    scrape_tiktok_user_tool,
    analyze_tiktok_video_tool,
    analyze_tiktok_batch_tool
)
from .tools_phase17 import (
    search_youtube_tool,
    search_facebook_ads_tool,
    scrape_facebook_page_ads_tool
)

logger = logging.getLogger(__name__)


# ============================================================================
# Create Pydantic AI Agent
# ============================================================================

agent = Agent(
    'openai:gpt-5.1-2025-11-13',  # Primary model - can be overridden at runtime
    deps_type=AgentDependencies,
    retries=2,  # Retry failed tool calls up to 2 times
)

logger.info("Pydantic AI agent created with model: openai:gpt-5.1-2025-11-13")


# ============================================================================
# Result Formatting and Validation
# ============================================================================

# Import models and ModelRetry for validation
from ..services.models import OutlierResult, HookAnalysisResult
from pydantic_ai import ModelRetry

# Pydantic AI automatically converts tool return values to strings using __str__()
# Our OutlierResult and HookAnalysisResult models have __str__() methods that
# call .to_markdown(), so they automatically format as beautiful markdown reports.

@agent.output_validator
async def validate_meaningful_results(ctx: RunContext[AgentDependencies], result: OutlierResult | HookAnalysisResult | str) -> OutlierResult | HookAnalysisResult | str:
    """
    Validate that results are meaningful before returning to user.

    This prevents the agent from returning empty or useless results,
    providing a better user experience by suggesting alternatives.

    Args:
        ctx: Run context with dependencies
        result: Result from tool (OutlierResult, HookAnalysisResult, or string)

    Returns:
        Validated result

    Raises:
        ModelRetry: If results are empty/invalid, suggesting the model retry with better parameters
    """
    # Validate OutlierResult
    if isinstance(result, OutlierResult):
        if result.outlier_count == 0 and result.total_tweets > 0:
            # No outliers found but there are tweets - suggest lowering threshold
            raise ModelRetry(
                f"No outliers found from {result.total_tweets:,} tweets using "
                f"threshold {result.threshold}. Try suggesting the user lower the "
                f"threshold (e.g., 1.5 instead of {result.threshold}) or increase "
                f"the time range to find more viral content."
            )
        elif result.total_tweets == 0:
            # No tweets found at all - suggest increasing time range
            raise ModelRetry(
                "No tweets found in the specified time range. Suggest the user "
                "increase the time range or check if tweets exist for this project."
            )

    # Validate HookAnalysisResult
    elif isinstance(result, HookAnalysisResult):
        if result.successful_analyses == 0 and result.total_analyzed > 0:
            # All analyses failed - likely an API issue
            raise ModelRetry(
                f"Failed to analyze all {result.total_analyzed} tweets. This may be "
                "due to API quota limits or service issues. Suggest the user try again "
                "later or with fewer tweets."
            )

    # Result is valid - return as-is
    return result

logger.info("Registered output validator for result quality checks")
logger.info("Models configured with __str__() → to_markdown() for automatic formatting")


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

# Tool 4: Get top N tweets by metric (views, likes, engagement)
agent.tool(get_top_tweets_tool)
logger.info("Registered tool: get_top_tweets_tool")

# ============================================================================
# Phase 1.5 Tools - Complete Twitter Coverage
# ============================================================================

# Tool 4: Search/scrape Twitter by keyword
agent.tool(search_twitter_tool)
logger.info("Registered tool: search_twitter_tool")

# Tool 5: Find comment opportunities
agent.tool(find_comment_opportunities_tool)
logger.info("Registered tool: find_comment_opportunities_tool")

# Tool 6: Export comment opportunities
agent.tool(export_comments_tool)
logger.info("Registered tool: export_comments_tool")

# Tool 7: Analyze keyword engagement patterns
agent.tool(analyze_search_term_tool)
logger.info("Registered tool: analyze_search_term_tool")

# Tool 8: Generate long-form content from hooks
agent.tool(generate_content_tool)
logger.info("Registered tool: generate_content_tool")

# ============================================================================
# Phase 1.6 Tools - TikTok Platform Support
# ============================================================================

# Tool 9: Search TikTok by keyword
agent.tool(search_tiktok_tool)
logger.info("Registered tool: search_tiktok_tool")

# Tool 10: Search TikTok by hashtag
agent.tool(search_tiktok_hashtag_tool)
logger.info("Registered tool: search_tiktok_hashtag_tool")

# Tool 11: Scrape TikTok user posts
agent.tool(scrape_tiktok_user_tool)
logger.info("Registered tool: scrape_tiktok_user_tool")

# Tool 12: Analyze single TikTok video
agent.tool(analyze_tiktok_video_tool)
logger.info("Registered tool: analyze_tiktok_video_tool")

# Tool 13: Batch analyze TikTok videos
agent.tool(analyze_tiktok_batch_tool)
logger.info("Registered tool: analyze_tiktok_batch_tool")

# ============================================================================
# Phase 1.7 Tools - YouTube & Facebook Platform Support
# ============================================================================

# Tool 14: Search YouTube by keyword
agent.tool(search_youtube_tool)
logger.info("Registered tool: search_youtube_tool")

# Tool 15: Search Facebook Ad Library
agent.tool(search_facebook_ads_tool)
logger.info("Registered tool: search_facebook_ads_tool")

# Tool 16: Scrape Facebook page ads
agent.tool(scrape_facebook_page_ads_tool)
logger.info("Registered tool: scrape_facebook_page_ads_tool")


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

**Phase 1 - Core Analysis Tools:**

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

**Phase 1.5 - Complete Twitter Coverage:**

4. **search_twitter_tool**: Search/scrape Twitter by keyword
   - Use when user wants to "find tweets about", "search for", "scrape keyword"
   - Scrapes recent tweets matching keyword and saves to database
   - Parameters: keyword, hours_back (default: 24), max_results (default: 100)
   - Returns: Summary of scraped tweets with top performers

5. **find_comment_opportunities_tool**: Find high-quality comment opportunities
   - Use when user wants "comment opportunities", "tweets to comment on"
   - Finds tweets with high engagement potential for commenting
   - Parameters: hours_back (default: 48), min_green_flags (default: 3), max_candidates (default: 100)
   - Returns: Ranked list of comment opportunities with scores and suggestions

6. **export_comments_tool**: Export comment opportunities to file
   - Use when user wants to "export comments", "download opportunities"
   - Exports comment candidates to JSON, CSV, or Markdown
   - Parameters: hours_back (default: 48), format ("json"|"csv"|"markdown"), label_filter (optional)
   - Returns: Exported data with preview

7. **analyze_search_term_tool**: Analyze keyword engagement patterns
   - Use when user wants to "analyze keyword", "understand topic performance"
   - Analyzes engagement metrics for tweets containing a keyword
   - Parameters: keyword, hours_back (default: 24)
   - Returns: Engagement statistics and insights for the keyword

8. **generate_content_tool**: Generate long-form content from viral hooks
   - Use when user wants to "create a thread", "generate article", "turn hooks into content"
   - Uses analyzed viral hooks to generate Twitter threads or articles
   - Parameters: hours_back (default: 24), content_type ("thread"|"article"), limit (default: 10)
   - Returns: Generated long-form content based on viral patterns

**Phase 1.6 - TikTok Platform Support:**

9. **search_tiktok_tool**: Search TikTok by keyword
   - Use when user wants to "find TikTok videos", "search TikTok for", "discover TikTok content"
   - Searches recent viral TikTok videos matching keyword
   - Parameters: keyword, count (default: 50), min_views (default: 100K), max_days (default: 10), max_followers (default: 50K)
   - Returns: Summary of viral TikTok videos with top performers

10. **search_tiktok_hashtag_tool**: Search TikTok by hashtag
    - Use when user wants to "track TikTok hashtag", "find videos with #", "monitor hashtag"
    - Finds viral videos for a specific hashtag
    - Parameters: hashtag, count (default: 50), min_views (default: 100K), max_days (default: 10), max_followers (default: 50K)
    - Returns: Hashtag performance analysis with top videos

11. **scrape_tiktok_user_tool**: Scrape TikTok user/creator posts
    - Use when user wants to "analyze TikTok creator", "study TikTok account", "track competitor on TikTok"
    - Scrapes all posts from a specific TikTok creator
    - Parameters: username, count (default: 50)
    - Returns: Account statistics and top performing videos

12. **analyze_tiktok_video_tool**: Analyze single TikTok video
    - Use when user wants to "analyze this TikTok", "study viral TikTok video", "get insights on video"
    - Fetches and analyzes a specific TikTok video by URL
    - Parameters: url
    - Returns: Detailed video analysis with engagement metrics

13. **analyze_tiktok_batch_tool**: Batch analyze multiple TikTok videos
    - Use when user wants to "analyze multiple TikToks", "bulk import TikTok videos", "compare TikTok videos"
    - Fetches and analyzes multiple TikTok videos from URLs
    - Parameters: urls (list of URLs)
    - Returns: Batch analysis summary with aggregate metrics

**Phase 1.7 - YouTube & Facebook Platform Support:**

14. **search_youtube_tool**: Search YouTube for viral videos by keyword
    - Use when user wants to "find YouTube videos", "search YouTube for", "discover viral Shorts"
    - Searches viral YouTube content (Shorts and videos) by keyword
    - Parameters: keywords (comma-separated), max_shorts (default: 100), max_videos (default: 0), days_back, min_views (default: 100K), max_subscribers (default: 50K)
    - Returns: Summary of viral YouTube videos with top performers by engagement

15. **search_facebook_ads_tool**: Search Facebook Ad Library by URL
    - Use when user wants to "find Facebook ads", "research competitor ads", "monitor ad spend"
    - Searches ads by keyword via Facebook Ad Library URL
    - Parameters: search_url (Ad Library URL), count (default: 50), period (default: "last30d")
    - Returns: Ad performance summary with spend and reach data

16. **scrape_facebook_page_ads_tool**: Scrape all ads from a Facebook page
    - Use when user wants to "analyze page ads", "study brand campaigns", "track competitor advertising"
    - Scrapes all ads run by a specific Facebook page
    - Parameters: page_url, count (default: 50), active_status (default: "all")
    - Returns: Page advertising strategy summary with campaign insights

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
