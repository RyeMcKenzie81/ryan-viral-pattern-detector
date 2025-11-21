"""
Registered Agent Tools - Tools using the new auto-registration system.

This file demonstrates the new pattern for creating agent tools that
automatically generate both agent functions and API endpoints.

Example usage:
    @tool_registry.register(
        name="my_tool",
        description="Description of what the tool does",
        category="Twitter",  # or "TikTok", "YouTube", "Facebook", "General"
        rate_limit="20/minute"
    )
    async def my_tool(
        ctx: RunContext[AgentDependencies],
        param1: str,
        param2: int = 10
    ) -> SomeResultModel:
        # Tool implementation
        pass

Benefits:
- Single definition creates both agent tool AND API endpoint
- Type-safe parameters automatically validated
- Consistent error handling
- Auto-generated request/response models
- Easy to add new tools
"""

import logging
from typing import Optional, List
from pydantic_ai import RunContext

from .dependencies import AgentDependencies
from .tool_registry import tool_registry
from ..services.models import OutlierResult, HookAnalysisResult

logger = logging.getLogger(__name__)


# ============================================================================
# Phase 1 - Core Analysis Tools
# ============================================================================

@tool_registry.register(
    name="find_outliers_tool",
    description="Find viral outlier tweets using statistical analysis",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Find top performing content",
        "Identify viral tweets",
        "Discover engagement patterns",
        "Track statistical outliers"
    ],
    examples=[
        "Show me viral tweets from today",
        "Find top performers from last 48 hours",
        "What tweets are outliers this week?",
        "Show me statistically viral content"
    ]
)
async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore",
    min_views: int = 100,
    text_only: bool = True,
    limit: int = 10
) -> OutlierResult:
    """
    Find viral outlier tweets using statistical analysis.

    Uses Z-score or percentile method to identify tweets with
    exceptionally high engagement relative to the dataset.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Statistical threshold - for zscore: std deviations (default: 2.0), for percentile: top % (default: 2.0)
        method: 'zscore' or 'percentile' (default: 'zscore')
        min_views: Minimum view count filter (default: 100)
        text_only: Only include text tweets, no media (default: True)
        limit: Max outliers to return in summary (default: 10)

    Returns:
        OutlierResult model with structured data and markdown export
    """
    try:
        logger.info(f"Finding outliers: hours_back={hours_back}, threshold={threshold}, method={method}")

        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=text_only
        )

        if not tweets:
            # Return empty result
            return OutlierResult(
                total_tweets=0,
                outlier_count=0,
                threshold=threshold,
                method=method,
                outliers=[],
                mean_engagement=0.0,
                median_engagement=0.0,
                std_engagement=0.0
            )

        logger.info(f"Fetched {len(tweets)} tweets, calculating outliers...")

        # Extract engagement scores
        engagement_scores = [t.engagement_score for t in tweets]

        # Calculate outliers based on method
        if method == "zscore":
            outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
                engagement_scores,
                threshold=threshold
            )
        elif method == "percentile":
            outlier_indices = ctx.deps.stats.calculate_percentile_outliers(
                engagement_scores,
                threshold=threshold
            )
        else:
            # Invalid method - return empty result with error in method field
            logger.error(f"Invalid method: {method}")
            return OutlierResult(
                total_tweets=len(tweets),
                outlier_count=0,
                threshold=threshold,
                method=f"INVALID:{method}",
                outliers=[],
                mean_engagement=0.0,
                median_engagement=0.0,
                std_engagement=0.0
            )

        # Get outlier tweets
        outlier_tweets = [tweets[i] for i in outlier_indices]

        # Sort by engagement score (descending)
        outlier_tweets.sort(key=lambda t: t.engagement_score, reverse=True)

        # Calculate statistics
        from ..services.statistics_service import StatisticsService
        stats = StatisticsService()
        mean_eng, median_eng, std_eng = stats.calculate_engagement_stats(engagement_scores)

        # Create OutlierTweet objects with rankings
        from ..services.models import OutlierTweet
        outlier_objs = []
        for rank, tweet in enumerate(outlier_tweets[:limit], 1):
            # Calculate Z-score and percentile for this tweet
            zscore = (tweet.engagement_score - mean_eng) / std_eng if std_eng > 0 else 0
            percentile = (sum(1 for s in engagement_scores if s <= tweet.engagement_score) / len(engagement_scores)) * 100

            outlier_objs.append(OutlierTweet(
                tweet=tweet,
                rank=rank,
                zscore=zscore,
                percentile=percentile
            ))

        # Return result
        result = OutlierResult(
            total_tweets=len(tweets),
            outlier_count=len(outlier_tweets),
            threshold=threshold,
            method=method,
            outliers=outlier_objs,
            mean_engagement=mean_eng,
            median_engagement=median_eng,
            std_engagement=std_eng
        )

        logger.info(f"Found {len(outlier_tweets)} outliers from {len(tweets)} tweets")
        return result

    except Exception as e:
        logger.error(f"Error in find_outliers_tool: {e}", exc_info=True)
        # Return empty result on error
        return OutlierResult(
            total_tweets=0,
            outlier_count=0,
            threshold=threshold,
            method=method,
            outliers=[],
            mean_engagement=0.0,
            median_engagement=0.0,
            std_engagement=0.0
        )


@tool_registry.register(
    name="analyze_hooks_tool",
    description="Analyze tweet hooks with AI to identify patterns and emotional triggers",
    category="Analysis",
    platform="Twitter",
    rate_limit="10/minute",  # Lower rate limit for AI-heavy operations
    use_cases=[
        "Understand viral hook patterns",
        "Identify emotional triggers",
        "Analyze content strategies",
        "Extract viral patterns"
    ],
    examples=[
        "Analyze hooks from top tweets today",
        "What patterns make these tweets viral?",
        "Show me emotional triggers in top content",
        "Analyze viral hooks from this week"
    ]
)
async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    limit: int = 10,
    min_views: int = 1000
) -> HookAnalysisResult:
    """
    Analyze tweet hooks using AI to identify viral patterns.

    Identifies:
    - Hook types (hot_take, relatable_slice, insider_secret, etc.)
    - Emotional triggers (anger, validation, humor, curiosity, etc.)
    - Content patterns

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        tweet_ids: Specific tweet IDs to analyze (optional)
        hours_back: Hours to look back if tweet_ids not provided (default: 24)
        limit: Max tweets to analyze (default: 10)
        min_views: Minimum view count filter (default: 1000)

    Returns:
        HookAnalysisResult with analysis for each tweet
    """
    try:
        logger.info(f"Analyzing hooks: tweet_ids={tweet_ids}, hours_back={hours_back}, limit={limit}")

        # Get tweets to analyze
        if tweet_ids:
            # Fetch specific tweets by ID
            tweets = await ctx.deps.twitter.get_tweets_by_ids(tweet_ids)
        else:
            # Fetch recent tweets
            tweets = await ctx.deps.twitter.get_tweets(
                project=ctx.deps.project_name,
                hours_back=hours_back,
                min_views=min_views,
                text_only=True
            )

            # Sort by engagement and take top N
            tweets.sort(key=lambda t: t.engagement_score, reverse=True)
            tweets = tweets[:limit]

        if not tweets:
            # Return empty result
            return HookAnalysisResult(
                total_analyzed=0,
                successful_analyses=0,
                failed_analyses=0,
                analyses=[]
            )

        logger.info(f"Analyzing {len(tweets)} tweets with Gemini AI...")

        # Analyze each tweet
        analyses = []
        failed = 0

        for tweet in tweets:
            try:
                analysis = await ctx.deps.gemini.analyze_hook(
                    tweet_id=tweet.tweet_id,
                    tweet_text=tweet.text,
                    author_username=tweet.author_username,
                    engagement_metrics={
                        'views': tweet.view_count,
                        'likes': tweet.like_count,
                        'replies': tweet.reply_count,
                        'retweets': tweet.retweet_count
                    }
                )
                analyses.append(analysis)
            except Exception as e:
                logger.error(f"Failed to analyze tweet {tweet.tweet_id}: {e}")
                failed += 1

        # Return result
        result = HookAnalysisResult(
            total_analyzed=len(tweets),
            successful_analyses=len(analyses),
            failed_analyses=failed,
            analyses=analyses
        )

        logger.info(f"Analyzed {len(analyses)} tweets successfully, {failed} failed")
        return result

    except Exception as e:
        logger.error(f"Error in analyze_hooks_tool: {e}", exc_info=True)
        # Return empty result on error
        return HookAnalysisResult(
            total_analyzed=0,
            successful_analyses=0,
            failed_analyses=0,
            analyses=[]
        )


@tool_registry.register(
    name="verify_scrape_tool",
    description="Verify a Twitter scrape by checking database for scraped tweets",
    category="Ingestion",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Verify scrape completed successfully",
        "Check if data quality warnings affected results",
        "Confirm tweet count after malformed data skipped",
        "Double-check database for recent scrapes"
    ],
    examples=[
        "Verify the scrape for BTC",
        "Check if the parenting scrape completed",
        "Did all tweets get saved?",
        "Verify the last scrape"
    ]
)
async def verify_scrape_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 1
) -> str:
    """
    Verify a Twitter scrape by checking the database for recently saved tweets.

    Use this when:
    - User reports data quality warnings during scraping
    - User wants to confirm scrape completion
    - Verifying if tweets were saved successfully to database

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search keyword to verify (e.g., "BTC", "parenting")
        hours_back: Hours to look back for tweets (default: 1 hour for recent scrapes)

    Returns:
        Verification report with tweet counts and confirmation
    """
    try:
        logger.info(f"Verifying scrape for keyword '{keyword}' (last {hours_back} hours)...")

        # Query database for tweets containing the keyword
        all_tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=0,
            text_only=False  # Include all tweets
        )

        # Filter tweets that contain the keyword (case-insensitive)
        keyword_lower = keyword.lower()
        matching_tweets = [
            t for t in all_tweets
            if keyword_lower in t.text.lower()
        ]

        if not matching_tweets:
            return (
                f"**⚠️ VERIFICATION FAILED**\n\n"
                f"No tweets found containing '{keyword}' in the last {hours_back} hours.\n\n"
                f"**Possible reasons:**\n"
                f"- Scrape may have failed completely\n"
                f"- Keyword not present in tweet text (only searches text, not metadata)\n"
                f"- Time window too narrow (try increasing hours_back)\n"
                f"- Tweets not yet indexed in database\n\n"
                f"**Suggestions:**\n"
                f"- Try running the scrape again\n"
                f"- Increase time window: verify_scrape_tool(keyword='{keyword}', hours_back=2)\n"
                f"- Check if keyword appears in tweet text vs metadata"
            )

        # Calculate statistics
        total_views = sum(t.view_count for t in matching_tweets)
        total_likes = sum(t.like_count for t in matching_tweets)
        total_engagement = sum(t.like_count + t.reply_count + t.retweet_count for t in matching_tweets)
        avg_engagement_rate = sum(t.engagement_rate for t in matching_tweets) / len(matching_tweets)

        # Get top tweet
        top_tweet = max(matching_tweets, key=lambda t: t.engagement_score)

        # Format successful verification
        response = f"**✅ VERIFICATION SUCCESSFUL**\n\n"
        response += f"Found **{len(matching_tweets)} tweets** containing '{keyword}' in the database (last {hours_back} hours).\n\n"

        response += f"**Database Verification:**\n"
        response += f"- Total Tweets: {len(matching_tweets)}\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Likes: {total_likes:,}\n"
        response += f"- Total Engagement: {total_engagement:,}\n"
        response += f"- Avg Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        response += f"**Top Performing Tweet:**\n"
        response += f"- @{top_tweet.author_username} ({top_tweet.author_followers:,} followers)\n"
        response += f"- Views: {top_tweet.view_count:,} | Likes: {top_tweet.like_count:,}\n"
        response += f"- Text: \"{top_tweet.text[:100]}{'...' if len(top_tweet.text) > 100 else ''}\"\n"
        response += f"- URL: {top_tweet.url}\n\n"

        response += f"**Conclusion:** The scrape completed successfully and tweets are saved in the database. ✓"

        logger.info(f"Verified {len(matching_tweets)} tweets for keyword '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in verify_scrape_tool: {e}", exc_info=True)
        return (
            f"**❌ VERIFICATION ERROR**\n\n"
            f"Failed to verify scrape for '{keyword}': {str(e)}\n\n"
            f"This may indicate a database connection issue or internal error."
        )


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'find_outliers_tool',
    'analyze_hooks_tool',
    'verify_scrape_tool'
]
