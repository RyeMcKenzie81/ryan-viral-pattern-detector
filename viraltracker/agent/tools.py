"""
Pydantic AI Agent Tools - Tool functions for the Viraltracker agent.

These tools wrap the services layer to provide agent-callable functions for:
- Finding viral outlier tweets (statistical analysis)
- Analyzing tweet hooks with AI (classification & pattern detection)
- Exporting results in various formats

Each tool is an async function that takes RunContext[AgentDependencies] as its first
parameter and returns a formatted string response for the agent.
"""

import logging
from typing import Optional, List
from pydantic_ai import RunContext
from collections import Counter

from .dependencies import AgentDependencies
from ..services.models import OutlierTweet, OutlierResult, HookAnalysisResult

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Find Outliers
# ============================================================================

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
                method=f"INVALID: {method}",
                outliers=[],
                mean_engagement=0.0,
                median_engagement=0.0,
                std_engagement=0.0
            )

        if not outlier_indices:
            # Return result with zero outliers but include statistics
            summary_stats = ctx.deps.stats.calculate_summary_stats(engagement_scores)
            return OutlierResult(
                total_tweets=len(tweets),
                outlier_count=0,
                threshold=threshold,
                method=method,
                outliers=[],
                mean_engagement=summary_stats['mean'],
                median_engagement=summary_stats['median'],
                std_engagement=summary_stats['std']
            )

        # Build OutlierTweet objects
        outliers = []
        for idx, *metrics in outlier_indices:
            tweet = tweets[idx]

            if method == "zscore":
                zscore = metrics[0]
                percentile = ctx.deps.stats.calculate_percentile(tweet.engagement_score, engagement_scores)
            else:  # percentile method
                # percentile method returns (idx, value, percentile)
                percentile = metrics[1]
                zscore = ctx.deps.stats.calculate_zscore(tweet.engagement_score, engagement_scores)

            outliers.append(OutlierTweet(
                tweet=tweet,
                zscore=zscore,
                percentile=percentile,
                rank=0  # Will be set after sorting
            ))

        # Sort by engagement score (descending)
        outliers.sort(key=lambda o: o.tweet.engagement_score, reverse=True)

        # Assign ranks
        for i, outlier in enumerate(outliers, 1):
            outlier.rank = i

        # Mark outliers in database
        for outlier in outliers:
            await ctx.deps.twitter.mark_as_outlier(
                tweet_id=outlier.tweet.id,
                zscore=outlier.zscore,
                threshold=threshold
            )

        # Calculate summary statistics
        summary_stats = ctx.deps.stats.calculate_summary_stats(engagement_scores)

        logger.info(f"Successfully found {len(outliers)} outliers")

        # Return structured result
        return OutlierResult(
            total_tweets=len(tweets),
            outlier_count=len(outliers),
            threshold=threshold,
            method=method,
            outliers=outliers[:limit],  # Limit outliers for display (full list too large)
            mean_engagement=summary_stats['mean'],
            median_engagement=summary_stats['median'],
            std_engagement=summary_stats['std']
        )

    except Exception as e:
        logger.error(f"Error in find_outliers_tool: {e}", exc_info=True)
        # Return empty result with error logged
        # Let the exception propagate - agent can handle it better than hiding it
        raise


# ============================================================================
# Tool 2: Analyze Hooks
# ============================================================================

async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    limit: int = 20,
    min_views: int = 100
) -> HookAnalysisResult:
    """
    Analyze tweet hooks using AI classification.

    Uses Gemini AI to classify hook types, emotional triggers,
    and content patterns for viral tweets.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        tweet_ids: Optional list of specific tweet IDs to analyze
        hours_back: Hours to look back if no tweet_ids (default: 24)
        limit: Max tweets to analyze (default: 20)
        min_views: Minimum views for auto-selected tweets (default: 100)

    Returns:
        HookAnalysisResult model with structured data and markdown export
    """
    try:
        logger.info(f"Analyzing hooks: tweet_ids={tweet_ids}, hours_back={hours_back}, limit={limit}")

        # Get tweets to analyze
        if tweet_ids:
            logger.info(f"Fetching {len(tweet_ids)} specific tweets...")
            tweets = await ctx.deps.twitter.get_tweets_by_ids(tweet_ids)
            if not tweets:
                # Return empty result - no tweets found for IDs
                return HookAnalysisResult(
                    total_analyzed=len(tweet_ids) if tweet_ids else 0,
                    successful_analyses=0,
                    failed_analyses=len(tweet_ids) if tweet_ids else 0,
                    analyses=[]
                )
        else:
            logger.info(f"Finding outlier tweets from last {hours_back} hours...")
            # Get recent tweets
            all_tweets = await ctx.deps.twitter.get_tweets(
                project=ctx.deps.project_name,
                hours_back=hours_back,
                min_views=min_views,
                text_only=True
            )

            if not all_tweets:
                # Return empty result - no tweets in time range
                return HookAnalysisResult(
                    total_analyzed=0,
                    successful_analyses=0,
                    failed_analyses=0,
                    analyses=[]
                )

            # Find outliers using z-score
            engagement_scores = [t.engagement_score for t in all_tweets]
            outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
                engagement_scores,
                threshold=2.0
            )

            if not outlier_indices:
                # Return empty result - no outliers found
                return HookAnalysisResult(
                    total_analyzed=len(all_tweets),
                    successful_analyses=0,
                    failed_analyses=0,
                    analyses=[]
                )

            # Select outlier tweets, limited by 'limit' parameter
            tweets = [all_tweets[idx] for idx, _ in outlier_indices[:limit]]
            logger.info(f"Selected {len(tweets)} outlier tweets for hook analysis")

        # Analyze hooks with AI
        analyses = []
        failed_count = 0

        response_header = f"Analyzing {len(tweets)} viral tweet hooks...\n\n"

        for i, tweet in enumerate(tweets, 1):
            try:
                logger.info(f"Analyzing tweet {i}/{len(tweets)}: {tweet.id}")

                # Call Gemini to analyze hook
                analysis = await ctx.deps.gemini.analyze_hook(
                    tweet_text=tweet.text,
                    tweet_id=tweet.id
                )

                # Save to database
                await ctx.deps.twitter.save_hook_analysis(analysis)
                analyses.append(analysis)

                logger.info(f"Successfully analyzed tweet {i}/{len(tweets)}: {analysis.hook_type}")

            except Exception as e:
                logger.error(f"Error analyzing tweet {tweet.id}: {e}")
                failed_count += 1
                continue

        if not analyses:
            # All analyses failed - return empty result
            return HookAnalysisResult(
                total_analyzed=len(tweets),
                successful_analyses=0,
                failed_analyses=len(tweets),
                analyses=[]
            )

        # Create result model with successful analyses
        result = HookAnalysisResult(
            total_analyzed=len(tweets),
            successful_analyses=len(analyses),
            failed_analyses=failed_count,
            analyses=analyses
        )

        # Compute patterns (populates top_hook_types, top_emotional_triggers, avg_confidence)
        result.compute_patterns()

        logger.info(f"Successfully analyzed {len(analyses)} hooks")
        return result

    except Exception as e:
        logger.error(f"Error in analyze_hooks_tool: {e}", exc_info=True)
        # Let exception propagate - agent can handle it better than hiding it
        raise


# ============================================================================
# Tool 3: Export Results
# ============================================================================

async def export_results_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    include_hooks: bool = True,
    format: str = "markdown"
) -> str:
    """
    Export comprehensive analysis report in markdown format.

    Combines outlier detection and hook analysis into a
    formatted markdown report.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Outlier threshold (default: 2.0)
        include_hooks: Include hook analysis (default: True)
        format: Output format - currently only 'markdown' supported (default: 'markdown')

    Returns:
        Markdown-formatted comprehensive analysis report
    """
    try:
        logger.info(f"Exporting results: hours_back={hours_back}, include_hooks={include_hooks}")

        # Step 1: Run outlier detection
        logger.info("Step 1: Running outlier detection...")
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=100,
            text_only=True
        )

        if not tweets:
            return f"No tweets found for project '{ctx.deps.project_name}' in the last {hours_back} hours."

        # Calculate outliers
        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
            engagement_scores,
            threshold=threshold
        )

        # Build OutlierResult model
        outliers = []
        for idx, zscore in outlier_indices:
            tweet = tweets[idx]
            percentile = ctx.deps.stats.calculate_percentile(tweet.engagement_score, engagement_scores)

            outliers.append(OutlierTweet(
                tweet=tweet,
                zscore=zscore,
                percentile=percentile,
                rank=0
            ))

        # Sort and rank
        outliers.sort(key=lambda o: o.tweet.engagement_score, reverse=True)
        for i, outlier in enumerate(outliers, 1):
            outlier.rank = i

        summary_stats = ctx.deps.stats.calculate_summary_stats(engagement_scores)

        outlier_result = OutlierResult(
            total_tweets=len(tweets),
            outlier_count=len(outliers),
            threshold=threshold,
            method="zscore",
            outliers=outliers,
            mean_engagement=summary_stats['mean'],
            median_engagement=summary_stats['median'],
            std_engagement=summary_stats['std']
        )

        # Step 2: Run hook analysis if requested
        hook_result = None
        if include_hooks and outliers:
            logger.info("Step 2: Running hook analysis on outliers...")

            analyses = []
            # Limit to top 10 outliers for hook analysis
            for outlier in outliers[:10]:
                try:
                    analysis = await ctx.deps.gemini.analyze_hook(
                        tweet_text=outlier.tweet.text,
                        tweet_id=outlier.tweet.id
                    )
                    await ctx.deps.twitter.save_hook_analysis(analysis)
                    analyses.append(analysis)
                except Exception as e:
                    logger.error(f"Error analyzing hook for tweet {outlier.tweet.id}: {e}")
                    continue

            if analyses:
                hook_result = HookAnalysisResult(
                    total_analyzed=len(outliers[:10]),
                    successful_analyses=len(analyses),
                    failed_analyses=len(outliers[:10]) - len(analyses),
                    analyses=analyses
                )
                hook_result.compute_patterns()

        # Step 3: Generate markdown report
        logger.info("Step 3: Generating markdown report...")

        if format == "markdown":
            # Build comprehensive markdown report
            from datetime import datetime

            report = f"# Viral Tweet Analysis Report\n\n"
            report += f"**Project:** {ctx.deps.project_name}\n"
            report += f"**Period:** Last {hours_back} hours\n"
            report += f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

            report += "---\n\n"

            # Outlier section
            report += outlier_result.to_markdown()

            # Hook analysis section
            if hook_result:
                report += "\n---\n\n"
                report += hook_result.to_markdown()

            logger.info("Report generated successfully")
            return report
        else:
            return f"Unsupported format: {format}. Currently only 'markdown' is supported."

    except Exception as e:
        logger.error(f"Error in export_results_tool: {e}", exc_info=True)
        return f"Error exporting results: {str(e)}"


# ============================================================================
# Tool 4: Get Top Tweets
# ============================================================================

async def get_top_tweets_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    sort_by: str = "views",
    limit: int = 10,
    min_views: int = 0,
    text_only: bool = False
) -> str:
    """
    Get top N tweets sorted by a specific metric (views, likes, engagement).

    Unlike find_outliers_tool which finds statistically viral tweets,
    this simply returns the top N tweets sorted by the chosen metric.

    Use this when users ask for:
    - "Top 10 tweets by views"
    - "Show me the most liked tweets"
    - "Tweets with highest engagement"

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        sort_by: Metric to sort by - 'views', 'likes', 'engagement' (default: 'views')
        limit: Number of tweets to return (default: 10)
        min_views: Minimum view count filter (default: 0)
        text_only: Only include text tweets, no media (default: False)

    Returns:
        Formatted string with top tweets
    """
    try:
        logger.info(f"Getting top {limit} tweets sorted by {sort_by} (last {hours_back} hours)")

        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=text_only
        )

        if not tweets:
            return f"No tweets found in the last {hours_back} hours."

        # Sort by chosen metric
        if sort_by == "views":
            sorted_tweets = sorted(tweets, key=lambda t: t.view_count, reverse=True)
        elif sort_by == "likes":
            sorted_tweets = sorted(tweets, key=lambda t: t.like_count, reverse=True)
        elif sort_by == "engagement":
            sorted_tweets = sorted(tweets, key=lambda t: t.engagement_score, reverse=True)
        else:
            return f"Invalid sort_by parameter: {sort_by}. Use 'views', 'likes', or 'engagement'."

        # Take top N
        top_tweets = sorted_tweets[:limit]

        # Calculate statistics for all tweets
        engagement_scores = [t.engagement_score for t in tweets]
        summary_stats = ctx.deps.stats.calculate_summary_stats(engagement_scores)

        # Format response
        response = f"Top {len(top_tweets)} tweets by {sort_by} (last {hours_back} hours)\n\n"
        response += f"**Dataset Statistics:**\n"
        response += f"- Total Tweets: {len(tweets)}\n"
        response += f"- Mean Engagement: {summary_stats['mean']:.2f}\n"
        response += f"- Median Engagement: {summary_stats['median']:.2f}\n\n"

        response += f"**Top {len(top_tweets)} Tweets:**\n\n"

        for i, tweet in enumerate(top_tweets, 1):
            # Calculate Z-score and percentile for context
            zscore = ctx.deps.stats.calculate_zscore(tweet.engagement_score, engagement_scores)
            percentile = ctx.deps.stats.calculate_percentile(tweet.engagement_score, engagement_scores)

            response += f"**{i}. @{tweet.author_username}** ({tweet.author_followers:,} followers)\n"
            response += f"   Views: {tweet.view_count:,} | Likes: {tweet.like_count:,} | Replies: {tweet.reply_count} | Retweets: {tweet.retweet_count}\n"
            response += f"   Engagement Rate: {tweet.engagement_rate:.2%} | Z-Score: {zscore:.2f} | Percentile: {percentile:.1f}%\n"
            response += f"   \"{tweet.text[:150]}{'...' if len(tweet.text) > 150 else ''}\"\n"
            response += f"   {tweet.url}\n\n"

        # Add export suggestion
        response += "---\n\n"
        response += "**Want to download these results?** Ask me to:\n"
        response += "- \"Export these top tweets to a file\"\n"
        response += f"- \"Give me a full report for the last {hours_back} hours\"\n"
        response += "- \"Download these results as markdown/JSON\"\n"

        logger.info(f"Successfully returned top {len(top_tweets)} tweets by {sort_by}")
        return response

    except Exception as e:
        logger.error(f"Error in get_top_tweets_tool: {e}", exc_info=True)
        return f"Error getting top tweets: {str(e)}"


# ============================================================================
# Export all tools
# ============================================================================

__all__ = [
    'find_outliers_tool',
    'analyze_hooks_tool',
    'export_results_tool',
    'get_top_tweets_tool'
]
