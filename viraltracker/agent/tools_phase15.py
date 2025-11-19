"""
Phase 1.5 Agent Tools - Complete Twitter Coverage

Adds 5 new tools to expand Twitter platform capabilities:
1. search_twitter_tool - Search/scrape Twitter by keyword
2. find_comment_opportunities_tool - Find comment opportunities
3. export_comments_tool - Export comment opportunities
4. analyze_search_term_tool - Analyze keyword engagement patterns
5. generate_content_tool - Generate long-form content from hooks

These tools complete Twitter coverage for the agent.
"""

import logging
from typing import Optional, List
from pydantic_ai import RunContext

from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Search Twitter
# ============================================================================

async def search_twitter_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24,
    max_results: int = 5000
) -> str:
    """
    Search/scrape Twitter by keyword and save results to database.

    Use this when users want to:
    - Find tweets about a topic
    - Discover viral content for a keyword
    - Scrape recent tweets matching a search term

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search keyword or hashtag (e.g., "parenting tips", "#productivity")
        hours_back: Hours of historical data to search (default: 24)
        max_results: Maximum tweets to scrape (default: 5000, supports up to 10000)

    Returns:
        Formatted string summary of scraping results
    """
    try:
        logger.info(f"Searching Twitter for '{keyword}'...")

        # Use scraping service to search Twitter
        tweets = await ctx.deps.scraping.search_twitter(
            keyword=keyword,
            project=ctx.deps.project_name,
            hours_back=hours_back,
            max_results=max_results
        )

        if not tweets:
            return f"No tweets found for keyword '{keyword}' in the last {hours_back} hours."

        # Calculate summary statistics
        total_views = sum(t.view_count for t in tweets)
        total_likes = sum(t.like_count for t in tweets)
        total_engagement = sum(t.like_count + t.reply_count + t.retweet_count for t in tweets)
        avg_engagement_rate = sum(t.engagement_rate for t in tweets) / len(tweets)

        # Format response
        response = f"Successfully scraped {len(tweets)} tweets for '{keyword}'\n\n"
        response += f"**Summary Statistics:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Likes: {total_likes:,}\n"
        response += f"- Total Engagement: {total_engagement:,}\n"
        response += f"- Avg Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        # Show top 5 tweets by engagement
        top_tweets = sorted(tweets, key=lambda t: t.engagement_score, reverse=True)[:5]
        response += f"**Top 5 Tweets by Engagement:**\n\n"

        for i, tweet in enumerate(top_tweets, 1):
            response += f"{i}. @{tweet.author_username} ({tweet.author_followers:,} followers)\n"
            response += f"   Views: {tweet.view_count:,} | Likes: {tweet.like_count:,}\n"
            response += f"   \"{tweet.text[:100]}{'...' if len(tweet.text) > 100 else ''}\"\n"
            response += f"   {tweet.url}\n\n"

        response += f"All {len(tweets)} tweets have been saved to the database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully scraped {len(tweets)} tweets for '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in search_twitter_tool: {e}", exc_info=True)
        return f"Error searching Twitter: {str(e)}"


# ============================================================================
# Tool 2: Find Comment Opportunities
# ============================================================================

async def find_comment_opportunities_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    min_green_flags: int = 3,
    max_candidates: int = 100
) -> str:
    """
    Find high-quality comment opportunities from recent tweets.

    Use this when users want to:
    - Find tweets to comment on for engagement
    - Identify comment opportunities
    - Get comment suggestions

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 48)
        min_green_flags: Minimum green flag score filter (default: 3)
        max_candidates: Maximum opportunities to return (default: 100)

    Returns:
        Formatted string summary of comment opportunities
    """
    try:
        logger.info(f"Finding comment opportunities (hours_back: {hours_back})...")

        # Get comment opportunities from database
        opportunities = await ctx.deps.comment.get_comment_opportunities(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_green_flags=min_green_flags,
            max_candidates=max_candidates
        )

        if not opportunities:
            return (
                f"No comment opportunities found in the last {hours_back} hours.\n\n"
                f"Suggestions:\n"
                f"- Run 'twitter generate-comments' CLI command first to generate opportunities\n"
                f"- Lower min_green_flags (current: {min_green_flags})\n"
                f"- Increase time range (current: {hours_back} hours)"
            )

        # Get statistics
        stats = await ctx.deps.comment.get_comment_stats(
            project=ctx.deps.project_name,
            hours_back=hours_back
        )

        # Format response
        response = f"Found {len(opportunities)} comment opportunities\n\n"
        response += f"**Statistics:**\n"
        response += f"- Total Opportunities: {stats['total']}\n"
        response += f"- Green Flags: {stats['greens']} ({(stats['greens']/stats['total']*100):.1f}%)\n"
        response += f"- Yellow Flags: {stats['yellows']} ({(stats['yellows']/stats['total']*100):.1f}%)\n"
        response += f"- Red Flags: {stats['reds']} ({(stats['reds']/stats['total']*100):.1f}%)\n"
        response += f"- Average Score: {stats['avg_score']:.2f}\n\n"

        # Show top 10 opportunities
        response += f"**Top 10 Comment Opportunities:**\n\n"
        for i, opp in enumerate(opportunities[:10], 1):
            label = opp.get('label', 'unknown')
            score = opp.get('score_total', 0.0)
            tweet_text = opp.get('tweet_text', '')[:80]
            suggested_comment = opp.get('suggested_response', '')[:100]

            emoji = "🟢" if label == "green" else "🟡" if label == "yellow" else "🔴"
            response += f"{i}. {emoji} Score: {score:.2f}\n"
            response += f"   Tweet: \"{tweet_text}...\"\n"
            response += f"   Suggested: \"{suggested_comment}...\"\n\n"

        response += f"\nUse 'export_comments_tool' to download all opportunities to a file."

        logger.info(f"Found {len(opportunities)} comment opportunities")
        return response

    except Exception as e:
        logger.error(f"Error in find_comment_opportunities_tool: {e}", exc_info=True)
        return f"Error finding comment opportunities: {str(e)}"


# ============================================================================
# Tool 3: Export Comments
# ============================================================================

async def export_comments_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    format: str = "json",
    label_filter: Optional[str] = None
) -> str:
    """
    Export comment opportunities to file.

    Use this when users want to:
    - Download comment opportunities
    - Export data for review
    - Save results to a file

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 48)
        format: Export format - 'json', 'csv', or 'markdown' (default: 'json')
        label_filter: Optional filter by label - 'green', 'yellow', or 'red'

    Returns:
        Formatted string with export summary and data preview
    """
    try:
        logger.info(f"Exporting comment opportunities (format: {format})...")

        # Export comment opportunities
        data = await ctx.deps.comment.export_comment_opportunities(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            format=format,
            label_filter=label_filter
        )

        if not data:
            return f"No comment opportunities to export for the last {hours_back} hours."

        # Format response based on export format
        filter_text = f" (filtered by: {label_filter})" if label_filter else ""
        response = f"Exported {len(data)} comment opportunities{filter_text}\n\n"

        if format == "json":
            import json
            json_preview = json.dumps(data[:3], indent=2)
            response += f"**JSON Preview (first 3 records):**\n```json\n{json_preview}\n```\n\n"

        elif format == "csv":
            # Show CSV header and first 3 rows
            if data:
                headers = list(data[0].keys())
                response += f"**CSV Preview:**\n"
                response += f"{','.join(headers)}\n"
                for row in data[:3]:
                    values = [str(row.get(h, '')) for h in headers]
                    response += f"{','.join(values)}\n"
                response += "\n"

        elif format == "markdown":
            response += f"**Markdown Preview:**\n\n"
            for i, item in enumerate(data[:5], 1):
                response += f"### {i}. {item.get('label', 'unknown').upper()}\n"
                response += f"Score: {item.get('score_total', 0):.2f}\n"
                response += f"Tweet: {item.get('tweet_text', '')[:100]}...\n\n"

        response += f"\nTotal records: {len(data)}"

        logger.info(f"Exported {len(data)} comment opportunities as {format}")
        return response

    except Exception as e:
        logger.error(f"Error in export_comments_tool: {e}", exc_info=True)
        return f"Error exporting comments: {str(e)}"


# ============================================================================
# Tool 4: Analyze Search Term
# ============================================================================

async def analyze_search_term_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24
) -> str:
    """
    Analyze engagement patterns for a keyword/search term.

    Use this when users want to:
    - Understand keyword performance
    - Analyze engagement trends
    - Get insights on a topic

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Keyword to analyze
        hours_back: Hours of data to analyze (default: 24)

    Returns:
        Formatted string with keyword analysis and insights
    """
    try:
        logger.info(f"Analyzing search term '{keyword}'...")

        # First, get tweets for this keyword from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=0
        )

        # Filter tweets matching the keyword (simple text search)
        keyword_lower = keyword.lower()
        matching_tweets = [
            t for t in tweets
            if keyword_lower in t.text.lower()
        ]

        if not matching_tweets:
            return (
                f"No tweets found containing '{keyword}' in the last {hours_back} hours.\n\n"
                f"Suggestion: Try using 'search_twitter_tool' to scrape tweets for this keyword first."
            )

        # Calculate statistics
        total_views = sum(t.view_count for t in matching_tweets)
        total_likes = sum(t.like_count for t in matching_tweets)
        total_engagement = sum(t.like_count + t.reply_count + t.retweet_count for t in matching_tweets)
        avg_views = total_views / len(matching_tweets) if matching_tweets else 0
        avg_engagement_rate = sum(t.engagement_rate for t in matching_tweets) / len(matching_tweets) if matching_tweets else 0

        # Find best performing tweet
        best_tweet = max(matching_tweets, key=lambda t: t.engagement_score)

        # Format response
        response = f"Analysis for keyword: '{keyword}'\n\n"
        response += f"**Dataset:**\n"
        response += f"- Time Range: Last {hours_back} hours\n"
        response += f"- Tweets Found: {len(matching_tweets)}\n\n"

        response += f"**Engagement Metrics:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Likes: {total_likes:,}\n"
        response += f"- Total Engagement: {total_engagement:,}\n"
        response += f"- Avg Views per Tweet: {avg_views:,.0f}\n"
        response += f"- Avg Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        response += f"**Best Performing Tweet:**\n"
        response += f"- Author: @{best_tweet.author_username} ({best_tweet.author_followers:,} followers)\n"
        response += f"- Views: {best_tweet.view_count:,} | Likes: {best_tweet.like_count:,}\n"
        response += f"- Engagement Rate: {best_tweet.engagement_rate:.2%}\n"
        response += f"- Text: \"{best_tweet.text[:150]}{'...' if len(best_tweet.text) > 150 else ''}\"\n"
        response += f"- URL: {best_tweet.url}\n\n"

        response += f"**Insights:**\n"
        if avg_engagement_rate > 0.05:
            response += f"- High engagement! This keyword resonates well with audiences.\n"
        elif avg_engagement_rate > 0.02:
            response += f"- Moderate engagement. Consider testing different angles.\n"
        else:
            response += f"- Lower engagement. May need stronger hooks or different framing.\n"

        logger.info(f"Analyzed {len(matching_tweets)} tweets for keyword '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_search_term_tool: {e}", exc_info=True)
        return f"Error analyzing search term: {str(e)}"


# ============================================================================
# Tool 5: Generate Content
# ============================================================================

async def generate_content_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    content_type: str = "thread",
    limit: int = 10
) -> str:
    """
    Generate long-form content from viral tweet hooks.

    Use this when users want to:
    - Create a Twitter thread from viral hooks
    - Generate an article based on popular tweets
    - Turn insights into long-form content

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back for viral tweets (default: 24)
        content_type: Type of content - 'thread' or 'article' (default: 'thread')
        limit: Number of viral tweets to use as inspiration (default: 10)

    Returns:
        Generated long-form content (thread or article)
    """
    try:
        logger.info(f"Generating {content_type} content from viral hooks...")

        # Step 1: Find viral tweets (outliers)
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=100,
            text_only=True
        )

        if not tweets:
            return f"No tweets found in the last {hours_back} hours to generate content from."

        # Calculate outliers
        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
            engagement_scores,
            threshold=2.0
        )

        if not outlier_indices:
            return (
                f"No viral tweets found in the last {hours_back} hours.\n"
                f"Try increasing the time range or lowering the outlier threshold."
            )

        # Get outlier tweets
        outlier_tweets = [tweets[idx] for idx, _ in outlier_indices[:limit]]

        # Step 2: Analyze hooks for these tweets
        hook_analyses = []
        for tweet in outlier_tweets:
            try:
                analysis = await ctx.deps.gemini.analyze_hook(
                    tweet_text=tweet.text,
                    tweet_id=tweet.id
                )
                hook_analyses.append(analysis)
            except Exception as e:
                logger.warning(f"Failed to analyze hook for tweet {tweet.id}: {e}")
                continue

        if not hook_analyses:
            return "Failed to analyze hooks for viral tweets. Please try again."

        # Step 3: Generate content
        content = await ctx.deps.gemini.generate_content(
            hook_analyses=hook_analyses,
            content_type=content_type
        )

        # Format response
        response = f"Generated {content_type} from {len(hook_analyses)} viral hooks\n\n"
        response += f"**Source Tweets:**\n"
        response += f"- Time Range: Last {hours_back} hours\n"
        response += f"- Viral Tweets Analyzed: {len(hook_analyses)}\n"
        response += f"- Content Type: {content_type}\n\n"
        response += "---\n\n"
        response += content

        logger.info(f"Generated {content_type} from {len(hook_analyses)} hooks")
        return response

    except Exception as e:
        logger.error(f"Error in generate_content_tool: {e}", exc_info=True)
        return f"Error generating content: {str(e)}"


# ============================================================================
# Export all tools
# ============================================================================

__all__ = [
    'search_twitter_tool',
    'find_comment_opportunities_tool',
    'export_comments_tool',
    'analyze_search_term_tool',
    'generate_content_tool'
]
