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
    category="Twitter",
    rate_limit="20/minute"
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
    category="Twitter",
    rate_limit="10/minute"  # Lower rate limit for AI-heavy operations
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


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'find_outliers_tool',
    'analyze_hooks_tool'
]
