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
) -> str:
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
        Formatted string summary of outlier tweets with statistics
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
            return f"No tweets found for project '{ctx.deps.project_name}' in the last {hours_back} hours with minimum {min_views} views."

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
            return f"Invalid method '{method}'. Use 'zscore' or 'percentile'."

        if not outlier_indices:
            return (
                f"No outliers found from {len(tweets):,} tweets using {method} method with threshold {threshold}.\n\n"
                f"Suggestions:\n"
                f"- Try lowering the threshold (current: {threshold})\n"
                f"- Increase time range (current: {hours_back} hours)\n"
                f"- Lower min_views (current: {min_views})"
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

        # Format response
        success_rate = (len(outliers) / len(tweets)) * 100
        response = f"Found {len(outliers)} viral outliers from {len(tweets):,} tweets ({success_rate:.1f}% success rate)\n\n"
        response += f"**Analysis Parameters:**\n"
        response += f"- Method: {method}\n"
        response += f"- Threshold: {threshold}\n"
        response += f"- Time Range: Last {hours_back} hours\n"
        response += f"- Min Views: {min_views:,}\n\n"

        response += f"**Dataset Statistics:**\n"
        response += f"- Mean Engagement: {summary_stats['mean']:.1f}\n"
        response += f"- Median Engagement: {summary_stats['median']:.1f}\n"
        response += f"- Std Dev: {summary_stats['std']:.1f}\n\n"

        # Show top outliers
        display_count = min(limit, len(outliers))
        response += f"**Top {display_count} Viral Tweets:**\n\n"

        for i, outlier in enumerate(outliers[:display_count], 1):
            t = outlier.tweet
            response += f"{i}. **[Z={outlier.zscore:.1f}, {outlier.percentile:.0f}th percentile]**\n"
            response += f"   @{t.author_username} ({t.author_followers:,} followers)\n"
            response += f"   Views: {t.view_count:,} | Likes: {t.like_count:,} | Replies: {t.reply_count:,}\n"
            response += f"   \"{t.text[:100]}{'...' if len(t.text) > 100 else ''}\"\n"
            response += f"   {t.url}\n\n"

        if len(outliers) > display_count:
            response += f"...and {len(outliers) - display_count} more outliers\n"

        logger.info(f"Successfully found {len(outliers)} outliers")
        return response

    except Exception as e:
        logger.error(f"Error in find_outliers_tool: {e}", exc_info=True)
        return f"Error finding outliers: {str(e)}"


# ============================================================================
# Tool 2: Analyze Hooks
# ============================================================================

async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    limit: int = 20,
    min_views: int = 100
) -> str:
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
        Formatted string summary of hook analysis results with patterns
    """
    try:
        logger.info(f"Analyzing hooks: tweet_ids={tweet_ids}, hours_back={hours_back}, limit={limit}")

        # Get tweets to analyze
        if tweet_ids:
            logger.info(f"Fetching {len(tweet_ids)} specific tweets...")
            tweets = await ctx.deps.twitter.get_tweets_by_ids(tweet_ids)
            if not tweets:
                return f"No tweets found for the provided IDs: {tweet_ids}"
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
                return f"No tweets found for project '{ctx.deps.project_name}' in the last {hours_back} hours."

            # Find outliers using z-score
            engagement_scores = [t.engagement_score for t in all_tweets]
            outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
                engagement_scores,
                threshold=2.0
            )

            if not outlier_indices:
                return (
                    f"No outlier tweets found from {len(all_tweets):,} tweets to analyze.\n"
                    f"Try increasing the time range or lowering the outlier threshold."
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
            return f"Failed to analyze any tweets. Analyzed 0/{len(tweets)} successfully. Check API quota and credentials."

        # Calculate pattern statistics
        hook_types = Counter(a.hook_type for a in analyses if a.hook_type != "unknown")
        emotional_triggers = Counter(a.emotional_trigger for a in analyses if a.emotional_trigger != "unknown")
        content_patterns = Counter(a.content_pattern for a in analyses)

        avg_confidence = sum(a.hook_type_confidence for a in analyses) / len(analyses)

        # Format response
        success_rate = (len(analyses) / len(tweets)) * 100
        response = response_header
        response += f"**Analysis Results:**\n"
        response += f"- Successfully Analyzed: {len(analyses)}/{len(tweets)} ({success_rate:.0f}%)\n"
        response += f"- Failed: {failed_count}\n"
        response += f"- Average Confidence: {avg_confidence:.0%}\n\n"

        # Top hook types
        if hook_types:
            response += f"**Top Hook Types:**\n"
            for hook_type, count in hook_types.most_common(5):
                pct = (count / len(analyses)) * 100
                response += f"- {hook_type}: {count} ({pct:.0f}%)\n"
            response += "\n"

        # Top emotional triggers
        if emotional_triggers:
            response += f"**Top Emotional Triggers:**\n"
            for trigger, count in emotional_triggers.most_common(5):
                pct = (count / len(analyses)) * 100
                response += f"- {trigger}: {count} ({pct:.0f}%)\n"
            response += "\n"

        # Content patterns
        if content_patterns:
            response += f"**Content Patterns:**\n"
            for pattern, count in content_patterns.most_common(5):
                pct = (count / len(analyses)) * 100
                response += f"- {pattern}: {count} ({pct:.0f}%)\n"
            response += "\n"

        # Show example analyses
        response += f"**Example Analyses:**\n\n"
        for i, analysis in enumerate(analyses[:3], 1):
            response += f"{i}. **{analysis.hook_type}** ({analysis.hook_type_confidence:.0%} confidence)\n"
            response += f"   Trigger: {analysis.emotional_trigger}\n"
            response += f"   \"{analysis.tweet_text[:80]}{'...' if len(analysis.tweet_text) > 80 else ''}\"\n"
            response += f"   Why it works: {analysis.hook_explanation[:100]}...\n\n"

        logger.info(f"Successfully analyzed {len(analyses)} hooks")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_hooks_tool: {e}", exc_info=True)
        return f"Error analyzing hooks: {str(e)}"


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
# Export all tools
# ============================================================================

__all__ = [
    'find_outliers_tool',
    'analyze_hooks_tool',
    'export_results_tool'
]
