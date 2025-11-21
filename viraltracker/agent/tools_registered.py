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
# Phase 1 - Twitter Export & Discovery Tools
# ============================================================================

@tool_registry.register(
    name="export_results_tool",
    description="Export comprehensive analysis report combining outliers and hooks",
    category="Export",
    platform="Twitter",
    rate_limit="10/minute",
    use_cases=[
        "Generate full analysis report with outliers and hooks",
        "Export viral tweet insights to markdown",
        "Create comprehensive content strategy document",
        "Download complete engagement analysis"
    ],
    examples=[
        "Export a full analysis report for the last 24 hours",
        "Create a comprehensive report with hooks",
        "Give me a markdown export of viral tweets",
        "Download complete analysis for this week"
    ]
)
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
        from ..services.models import OutlierTweet
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

        from ..services.models import OutlierResult
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
                from ..services.models import HookAnalysisResult
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


@tool_registry.register(
    name="get_top_tweets_tool",
    description="Query EXISTING database for top tweets by views/likes/engagement (does NOT scrape new data from Twitter)",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Look up top tweets by view count from database",
        "Find most viewed tweets containing keyword in database",
        "Query database for tweets sorted by engagement",
        "Show top tweets already saved in database"
    ],
    examples=[
        "Show me the top 10 tweets by views from the database",
        "Look up the most viewed tweets containing 'bitcoin' in our database",
        "What are the top tweets with 'productivity' in the database?",
        "Find the 20 most popular tweets about 'AI' from last 48 hours in the database"
    ]
)
async def get_top_tweets_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    sort_by: str = "views",
    limit: int = 10,
    min_views: int = 0,
    text_only: bool = False,
    keyword: Optional[str] = None
) -> str:
    """
    Query existing database for top tweets sorted by a specific metric.

    Unlike find_outliers_tool which finds statistically viral tweets,
    this simply returns the top N tweets sorted by the chosen metric.

    Use this when users ask to:
    - Look up tweets in the database
    - Find top tweets by views/likes/engagement from database
    - Query database for tweets containing a keyword

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        sort_by: Metric to sort by - 'views', 'likes', 'engagement' (default: 'views')
        limit: Number of tweets to return (default: 10)
        min_views: Minimum view count filter (default: 0)
        text_only: Only include text tweets, no media (default: False)
        keyword: Optional keyword to filter tweets (case-insensitive)

    Returns:
        Formatted string with top tweets from database
    """
    try:
        keyword_str = f" containing '{keyword}'" if keyword else ""
        logger.info(f"Getting top {limit} tweets{keyword_str} sorted by {sort_by} (last {hours_back} hours)")

        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=text_only
        )

        if not tweets:
            return f"No tweets found in the last {hours_back} hours."

        # Filter by keyword if provided
        if keyword:
            keyword_lower = keyword.lower()
            tweets = [t for t in tweets if keyword_lower in t.text.lower()]

            if not tweets:
                return f"No tweets found containing '{keyword}' in the last {hours_back} hours."

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
        keyword_str = f" containing '{keyword}'" if keyword else ""
        response = f"Top {len(top_tweets)} tweets{keyword_str} by {sort_by} from database (last {hours_back} hours)\n\n"
        response += f"**Dataset Statistics:**\n"
        response += f"- Total Tweets{keyword_str}: {len(tweets)}\n"
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


@tool_registry.register(
    name="export_tweets_tool",
    description="Export filtered tweet lists to CSV, JSON, or markdown format with file download",
    category="Export",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Export tweet search results to downloadable file",
        "Download filtered tweets by keyword or views",
        "Save tweet lists for external reporting",
        "Export top performing tweets by metric"
    ],
    examples=[
        "Export these tweets to CSV",
        "Download the bitcoin tweets as JSON",
        "Give me these results in markdown format",
        "Export the top 10 tweets to a file"
    ]
)
async def export_tweets_tool(
    ctx: RunContext[AgentDependencies],
    keyword: Optional[str] = None,
    hours_back: int = 24,
    sort_by: str = "views",
    limit: int = 100,
    min_views: int = 0,
    format: str = "csv"
) -> str:
    """
    Export filtered tweet lists to CSV, JSON, or markdown format.

    Saves actual files to ~/Downloads/ directory and returns file path.
    Use this when users want to download or export tweet results,
    especially after showing them a list of tweets.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Optional keyword filter (e.g., "bitcoin")
        hours_back: Hours to look back (default: 24)
        sort_by: Metric to sort by - 'views', 'likes', 'engagement' (default: 'views')
        limit: Number of tweets to export (default: 100)
        min_views: Minimum view count filter (default: 0)
        format: Export format - 'csv', 'json', or 'markdown' (default: 'csv')

    Returns:
        String with export summary, file path, and data preview
    """
    try:
        from datetime import datetime
        from pathlib import Path
        import csv
        import json

        logger.info(f"Exporting tweets: keyword={keyword}, sort_by={sort_by}, format={format}")

        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=False
        )

        if not tweets:
            return f"No tweets found in the last {hours_back} hours."

        # Filter by keyword if provided
        if keyword:
            keyword_lower = keyword.lower()
            tweets = [t for t in tweets if keyword_lower in t.text.lower()]
            if not tweets:
                return f"No tweets found containing '{keyword}' in the last {hours_back} hours."

        # Sort by chosen metric
        if sort_by == "views":
            sorted_tweets = sorted(tweets, key=lambda t: t.view_count, reverse=True)
        elif sort_by == "likes":
            sorted_tweets = sorted(tweets, key=lambda t: t.like_count, reverse=True)
        elif sort_by == "engagement":
            sorted_tweets = sorted(tweets, key=lambda t: t.engagement_score, reverse=True)
        else:
            return f"Invalid sort_by parameter: {sort_by}. Use 'views', 'likes', or 'engagement'."

        # Limit results
        export_tweets = sorted_tweets[:limit]

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        keyword_slug = f"_{keyword.replace(' ', '_')}" if keyword else ""
        downloads_dir = Path.home() / "Downloads"
        file_path = downloads_dir / f"tweets_export{keyword_slug}_{timestamp}.{format}"

        # Generate export data and save to file
        if format == "csv":
            # Write CSV file
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow([
                    'username', 'followers', 'views', 'likes', 'replies', 'retweets',
                    'engagement_rate', 'engagement_score', 'text', 'url', 'created_at'
                ])

                # Write data rows
                for tweet in export_tweets:
                    writer.writerow([
                        tweet.author_username,
                        tweet.author_followers,
                        tweet.view_count,
                        tweet.like_count,
                        tweet.reply_count,
                        tweet.retweet_count,
                        f"{tweet.engagement_rate:.4f}",
                        f"{tweet.engagement_score:.2f}",
                        tweet.text.replace('\n', ' ').replace('\r', ' '),
                        tweet.url,
                        tweet.created_at.isoformat() if hasattr(tweet, 'created_at') else ''
                    ])

            # Generate preview
            preview_tweets = export_tweets[:3]
            preview = "username,followers,views,likes,replies,retweets,engagement_rate,engagement_score,text,url,created_at\n"
            for tweet in preview_tweets:
                preview += f"{tweet.author_username},{tweet.author_followers},{tweet.view_count},{tweet.like_count},"
                preview += f"{tweet.reply_count},{tweet.retweet_count},{tweet.engagement_rate:.4f},"
                preview += f"{tweet.engagement_score:.2f},\"{tweet.text[:50]}...\",{tweet.url},...\n"

            response = f"**✅ CSV Export Complete**\n\n"
            response += f"Exported {len(export_tweets)} tweets to CSV format"
            if keyword:
                response += f" (filtered by '{keyword}')"
            response += f"\n\n📁 **File saved to:** `{file_path}`\n\n"
            response += f"**Preview (first 3 rows):**\n```csv\n{preview}```\n\n"
            response += f"📊 **Import into:** Excel, Google Sheets, or any CSV-compatible tool"

        elif format == "json":
            # Convert tweets to dict
            tweet_dicts = []
            for tweet in export_tweets:
                tweet_dicts.append({
                    'username': tweet.author_username,
                    'followers': tweet.author_followers,
                    'views': tweet.view_count,
                    'likes': tweet.like_count,
                    'replies': tweet.reply_count,
                    'retweets': tweet.retweet_count,
                    'engagement_rate': tweet.engagement_rate,
                    'engagement_score': tweet.engagement_score,
                    'text': tweet.text,
                    'url': tweet.url,
                    'created_at': tweet.created_at.isoformat() if hasattr(tweet, 'created_at') else None
                })

            # Write JSON file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(tweet_dicts, f, indent=2)

            # Show preview (first 2 tweets)
            preview_data = tweet_dicts[:2]
            preview_json = json.dumps(preview_data, indent=2)

            response = f"**✅ JSON Export Complete**\n\n"
            response += f"Exported {len(export_tweets)} tweets to JSON format"
            if keyword:
                response += f" (filtered by '{keyword}')"
            response += f"\n\n📁 **File saved to:** `{file_path}`\n\n"
            response += f"**Preview (first 2 tweets):**\n```json\n{preview_json}\n```"

        elif format == "markdown":
            # Generate markdown report
            md = f"# Tweet Export Report\n\n"
            md += f"**Project:** {ctx.deps.project_name}\n"
            md += f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            md += f"**Period:** Last {hours_back} hours\n"
            md += f"**Sort by:** {sort_by}\n"
            if keyword:
                md += f"**Keyword filter:** {keyword}\n"
            md += f"**Total tweets:** {len(export_tweets)}\n\n"
            md += "---\n\n"

            # Add tweets
            for i, tweet in enumerate(export_tweets, 1):
                md += f"## {i}. @{tweet.author_username}\n\n"
                md += f"**Followers:** {tweet.author_followers:,}  \n"
                md += f"**Views:** {tweet.view_count:,}  \n"
                md += f"**Likes:** {tweet.like_count:,}  \n"
                md += f"**Replies:** {tweet.reply_count}  \n"
                md += f"**Retweets:** {tweet.retweet_count}  \n"
                md += f"**Engagement Rate:** {tweet.engagement_rate:.2%}  \n"
                md += f"**Engagement Score:** {tweet.engagement_score:.2f}  \n\n"
                md += f"**Tweet:**\n> {tweet.text}\n\n"
                md += f"**URL:** {tweet.url}\n\n"
                md += "---\n\n"

            # Write markdown file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(md)

            # Show preview (first tweet)
            if export_tweets:
                preview_tweet = export_tweets[0]
                preview = f"## 1. @{preview_tweet.author_username}\n\n"
                preview += f"**Views:** {preview_tweet.view_count:,} | **Likes:** {preview_tweet.like_count:,}\n\n"
                preview += f"> {preview_tweet.text[:100]}...\n\n"

            response = f"**✅ Markdown Export Complete**\n\n"
            response += f"Exported {len(export_tweets)} tweets to markdown format"
            if keyword:
                response += f" (filtered by '{keyword}')"
            response += f"\n\n📁 **File saved to:** `{file_path}`\n\n"
            response += f"**Preview:**\n{preview}"

        else:
            return f"Unsupported format: {format}. Use 'csv', 'json', or 'markdown'."

        logger.info(f"Successfully exported {len(export_tweets)} tweets to {file_path}")
        return response

    except Exception as e:
        logger.error(f"Error in export_tweets_tool: {e}", exc_info=True)
        return f"Error exporting tweets: {str(e)}"


# ============================================================================
# Phase 1.5 - Complete Twitter Coverage (Ingestion, Analysis, Generation, Export)
# ============================================================================

@tool_registry.register(
    name="search_twitter_tool",
    description="Scrape FRESH tweets from Twitter by keyword and save to database (does NOT query existing database)",
    category="Ingestion",
    platform="Twitter",
    rate_limit="10/minute",
    use_cases=[
        "Scrape NEW tweets from Twitter by keyword",
        "Build NEW dataset for viral content analysis",
        "Collect FRESH tweets for audience research",
        "Ingest NEW tweets about a topic into database"
    ],
    examples=[
        "Scrape fresh tweets about 'productivity tips' from Twitter",
        "Collect NEW tweets about #startups from Twitter",
        "Ingest 5000 NEW tweets mentioning AI from Twitter",
        "Scrape recent tweets about parenting from Twitter and save to database"
    ]
)
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

        # Use scraping service to search Twitter - returns (tweets, metadata)
        tweets, metadata = await ctx.deps.scraping.search_twitter(
            keyword=keyword,
            project=ctx.deps.project_name,
            hours_back=hours_back,
            max_results=max_results
        )

        if not tweets:
            return f"No tweets found for keyword '{keyword}' in the last {hours_back} hours."

        # Extract metadata
        tweets_count = metadata.get('tweets_count', len(tweets))
        skipped_count = metadata.get('skipped_count', 0)
        requested_count = metadata.get('requested_count', max_results)
        run_id = metadata.get('run_id')

        # Calculate summary statistics
        total_views = sum(t.view_count for t in tweets)
        total_likes = sum(t.like_count for t in tweets)
        total_engagement = sum(t.like_count + t.reply_count + t.retweet_count for t in tweets)
        avg_engagement_rate = sum(t.engagement_rate for t in tweets) / len(tweets)

        # Calculate actual total found by Apify
        actual_found = tweets_count + skipped_count

        # Format response with clear scraping details
        response = f"**✅ SCRAPE COMPLETED: {tweets_count} tweets saved to database**\n\n"
        response += f"**Keyword:** \"{keyword}\"\n"
        response += f"**Timeframe:** Last {hours_back} hours\n"
        response += f"**Apify Run ID:** `{run_id}`\n\n"

        response += f"**SCRAPE RESULTS:**\n"
        response += f"- **You requested:** {requested_count:,} tweets\n"
        response += f"- **Apify actually found:** {actual_found:,} tweets matching '{keyword}' in last {hours_back} hours\n"

        if actual_found < requested_count:
            response += f"- **Why fewer?** Only {actual_found:,} tweets exist matching your criteria in this timeframe\n"

        response += f"- **Valid tweets saved:** {tweets_count:,} tweets ✓\n"

        if skipped_count > 0:
            skip_percentage = (skipped_count / actual_found) * 100
            response += f"- **Skipped (malformed data):** {skipped_count:,} tweets ({skip_percentage:.1f}%)\n\n"
            response += f"⚠️ **DATA QUALITY NOTE:** {skipped_count} tweets were skipped due to Apify returning malformed data.\n\n"
        else:
            response += f"\n"

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
            response += f"   \"{tweet.text[:100]}{'...' if len(tweet.text) > 100 else ''}\"\n\n"

        logger.info(f"Successfully scraped {len(tweets)} tweets for '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in search_twitter_tool: {e}", exc_info=True)
        return f"Error searching Twitter: {str(e)}"


@tool_registry.register(
    name="find_comment_opportunities_tool",
    description="Find high-quality comment opportunities from recent tweets",
    category="Discovery",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Find tweets to comment on for engagement",
        "Identify high-quality conversation starters",
        "Get comment suggestions with AI-generated responses",
        "Build engagement strategy"
    ],
    examples=[
        "Find comment opportunities from last 48 hours",
        "Show me tweets to engage with",
        "Get comment suggestions for viral tweets",
        "Find green flag comment opportunities"
    ]
)
async def find_comment_opportunities_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    min_green_flags: int = 3,
    max_candidates: int = 100
) -> str:
    """Find high-quality comment opportunities from recent tweets."""
    try:
        logger.info(f"Finding comment opportunities (hours_back: {hours_back})...")

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
                f"- Run 'twitter generate-comments' CLI command first\n"
                f"- Lower min_green_flags (current: {min_green_flags})\n"
                f"- Increase time range (current: {hours_back} hours)"
            )

        stats = await ctx.deps.comment.get_comment_stats(
            project=ctx.deps.project_name,
            hours_back=hours_back
        )

        response = f"Found {len(opportunities)} comment opportunities\n\n"
        response += f"**Statistics:**\n"
        response += f"- Total: {stats['total']}\n"
        response += f"- Green Flags: {stats['greens']} ({(stats['greens']/stats['total']*100):.1f}%)\n"
        response += f"- Average Score: {stats['avg_score']:.2f}\n\n"

        response += f"**Top 10 Opportunities:**\n\n"
        for i, opp in enumerate(opportunities[:10], 1):
            label = opp.get('label', 'unknown')
            score = opp.get('score_total', 0.0)
            tweet_text = opp.get('tweet_text', '')[:80]

            emoji = "🟢" if label == "green" else "🟡" if label == "yellow" else "🔴"
            response += f"{i}. {emoji} Score: {score:.2f}\n"
            response += f"   Tweet: \"{tweet_text}...\"\n\n"

        logger.info(f"Found {len(opportunities)} comment opportunities")
        return response

    except Exception as e:
        logger.error(f"Error in find_comment_opportunities_tool: {e}", exc_info=True)
        return f"Error finding comment opportunities: {str(e)}"


@tool_registry.register(
    name="export_comments_tool",
    description="Export comment opportunities to file in various formats",
    category="Export",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Download comment opportunities for review",
        "Export data for external analysis",
        "Save results to JSON/CSV/markdown",
        "Archive engagement opportunities"
    ],
    examples=[
        "Export comment opportunities as JSON",
        "Download green flag comments to CSV",
        "Export last 48 hours of opportunities",
        "Give me markdown export of comments"
    ]
)
async def export_comments_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    format: str = "json",
    label_filter: Optional[str] = None
) -> str:
    """Export comment opportunities to file."""
    try:
        logger.info(f"Exporting comment opportunities (format: {format})...")

        data = await ctx.deps.comment.export_comment_opportunities(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            format=format,
            label_filter=label_filter
        )

        if not data:
            return f"No comment opportunities to export for the last {hours_back} hours."

        filter_text = f" (filtered by: {label_filter})" if label_filter else ""
        response = f"Exported {len(data)} comment opportunities{filter_text}\n\n"

        if format == "json":
            import json
            json_preview = json.dumps(data[:3], indent=2)
            response += f"**JSON Preview (first 3):**\n```json\n{json_preview}\n```\n"

        response += f"\nTotal records: {len(data)}"

        logger.info(f"Exported {len(data)} comment opportunities as {format}")
        return response

    except Exception as e:
        logger.error(f"Error in export_comments_tool: {e}", exc_info=True)
        return f"Error exporting comments: {str(e)}"


@tool_registry.register(
    name="analyze_search_term_tool",
    description="Analyze engagement patterns and performance for a keyword",
    category="Analysis",
    platform="Twitter",
    rate_limit="20/minute",
    use_cases=[
        "Understand keyword performance metrics",
        "Analyze engagement trends for topics",
        "Get insights on content themes",
        "Evaluate search term effectiveness"
    ],
    examples=[
        "Analyze engagement for 'productivity'",
        "How is the keyword 'startup' performing?",
        "Show me metrics for #AI tweets",
        "Analyze search term performance"
    ]
)
async def analyze_search_term_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24
) -> str:
    """Analyze engagement patterns for a keyword/search term."""
    try:
        logger.info(f"Analyzing search term '{keyword}'...")

        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=0
        )

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

        total_views = sum(t.view_count for t in matching_tweets)
        total_likes = sum(t.like_count for t in matching_tweets)
        avg_engagement_rate = sum(t.engagement_rate for t in matching_tweets) / len(matching_tweets)

        best_tweet = max(matching_tweets, key=lambda t: t.engagement_score)

        response = f"Analysis for keyword: '{keyword}'\n\n"
        response += f"**Dataset:**\n"
        response += f"- Tweets Found: {len(matching_tweets)}\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Likes: {total_likes:,}\n"
        response += f"- Avg Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        response += f"**Best Performing Tweet:**\n"
        response += f"- @{best_tweet.author_username}\n"
        response += f"- Views: {best_tweet.view_count:,} | Likes: {best_tweet.like_count:,}\n"

        logger.info(f"Analyzed {len(matching_tweets)} tweets for keyword '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_search_term_tool: {e}", exc_info=True)
        return f"Error analyzing search term: {str(e)}"


@tool_registry.register(
    name="generate_content_tool",
    description="Generate long-form content (threads/articles) from viral tweet hooks",
    category="Generation",
    platform="Twitter",
    rate_limit="5/minute",
    use_cases=[
        "Create Twitter threads from viral hooks",
        "Generate articles based on popular tweets",
        "Turn insights into long-form content",
        "Expand viral tweets into detailed posts"
    ],
    examples=[
        "Generate a thread from today's viral tweets",
        "Create an article from top hooks",
        "Turn viral tweets into a Twitter thread",
        "Generate content from last 24 hours"
    ]
)
async def generate_content_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    content_type: str = "thread",
    limit: int = 10
) -> str:
    """Generate long-form content from viral tweet hooks."""
    try:
        logger.info(f"Generating {content_type} content from viral hooks...")

        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=100,
            text_only=True
        )

        if not tweets:
            return f"No tweets found in the last {hours_back} hours to generate content from."

        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = ctx.deps.stats.calculate_zscore_outliers(
            engagement_scores,
            threshold=2.0
        )

        if not outlier_indices:
            return f"No viral tweets found in the last {hours_back} hours."

        outlier_tweets = [tweets[idx] for idx, _ in outlier_indices[:limit]]

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
            return "Failed to analyze hooks for viral tweets."

        content = await ctx.deps.gemini.generate_content(
            hook_analyses=hook_analyses,
            content_type=content_type
        )

        response = f"Generated {content_type} from {len(hook_analyses)} viral hooks\n\n"
        response += "---\n\n"
        response += content

        logger.info(f"Generated {content_type} from {len(hook_analyses)} hooks")
        return response

    except Exception as e:
        logger.error(f"Error in generate_content_tool: {e}", exc_info=True)
        return f"Error generating content: {str(e)}"


# ============================================================================
# Phase 1.6 - TikTok Platform Support
# ============================================================================

@tool_registry.register(
    name="search_tiktok_tool",
    description="Search TikTok by keyword for viral videos",
    category="Ingestion",
    platform="TikTok",
    rate_limit="10/minute",
    use_cases=[
        "Find viral TikTok videos by keyword",
        "Discover trending TikTok content",
        "Research what's popular on TikTok",
        "Scrape TikTok for content ideas"
    ],
    examples=[
        "Search TikTok for 'morning routine'",
        "Find viral videos about productivity",
        "Show me TikToks about fitness",
        "Search TikTok for #entrepreneur"
    ]
)
async def search_tiktok_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """Search TikTok by keyword and return viral videos."""
    try:
        logger.info(f"Searching TikTok for keyword: '{keyword}'")

        videos = await ctx.deps.tiktok.search_keyword(
            keyword=keyword,
            project=ctx.deps.project_name,
            count=count,
            min_views=min_views,
            max_days=max_days,
            max_followers=max_followers,
            save_to_db=True
        )

        if not videos:
            return f"No TikTok videos found for '{keyword}' matching the criteria."

        total_views = sum(v.views for v in videos)
        avg_engagement_rate = sum(v.engagement_rate for v in videos) / len(videos)

        response = f"Found {len(videos)} viral TikTok videos for '{keyword}'\n\n"
        response += f"**Summary:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Avg Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        top_videos = sorted(videos, key=lambda v: v.engagement_score, reverse=True)[:5]
        response += f"**Top 5 Videos:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. @{video.username} - {video.views:,} views\n"
            response += f"   {video.url}\n\n"

        logger.info(f"Successfully found {len(videos)} TikTok videos")
        return response

    except Exception as e:
        logger.error(f"Error in search_tiktok_tool: {e}", exc_info=True)
        return f"Error searching TikTok: {str(e)}"


@tool_registry.register(
    name="search_tiktok_hashtag_tool",
    description="Search TikTok by hashtag for trending videos",
    category="Ingestion",
    platform="TikTok",
    rate_limit="10/minute",
    use_cases=[
        "Track specific TikTok hashtags",
        "Find trending videos for hashtags",
        "Monitor hashtag performance",
        "Discover hashtag content"
    ],
    examples=[
        "Search TikTok hashtag #productivity",
        "Find videos for #smallbusiness",
        "Show me #fitness TikToks",
        "Track hashtag #entrepreneur"
    ]
)
async def search_tiktok_hashtag_tool(
    ctx: RunContext[AgentDependencies],
    hashtag: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """Search TikTok by hashtag and return viral videos."""
    try:
        clean_hashtag = hashtag.lstrip('#')
        logger.info(f"Searching TikTok for hashtag: #{clean_hashtag}")

        videos = await ctx.deps.tiktok.search_hashtag(
            hashtag=clean_hashtag,
            project=ctx.deps.project_name,
            count=count,
            min_views=min_views,
            max_days=max_days,
            max_followers=max_followers,
            save_to_db=True
        )

        if not videos:
            return f"No TikTok videos found for #{clean_hashtag}."

        total_views = sum(v.views for v in videos)

        response = f"Found {len(videos)} videos for #{clean_hashtag}\n\n"
        response += f"- Total Views: {total_views:,}\n\n"

        top_videos = sorted(videos, key=lambda v: v.views, reverse=True)[:5]
        response += f"**Top 5 Videos:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. @{video.username} - {video.views:,} views\n"

        logger.info(f"Found {len(videos)} videos for #{clean_hashtag}")
        return response

    except Exception as e:
        logger.error(f"Error in search_tiktok_hashtag_tool: {e}", exc_info=True)
        return f"Error searching TikTok hashtag: {str(e)}"


@tool_registry.register(
    name="scrape_tiktok_user_tool",
    description="Scrape all posts from a TikTok user account",
    category="Ingestion",
    platform="TikTok",
    rate_limit="10/minute",
    use_cases=[
        "Analyze specific TikTok creators",
        "Track competitor content strategy",
        "Study successful TikTok accounts",
        "Monitor influencer activity"
    ],
    examples=[
        "Scrape posts from @creator",
        "Analyze TikTok user @username",
        "Get all videos from @influencer",
        "Track @competitor's TikToks"
    ]
)
async def scrape_tiktok_user_tool(
    ctx: RunContext[AgentDependencies],
    username: str,
    count: int = 50
) -> str:
    """Scrape posts from a TikTok user/creator account."""
    try:
        clean_username = username.lstrip('@')
        logger.info(f"Scraping TikTok user: @{clean_username}")

        videos = await ctx.deps.tiktok.scrape_user(
            username=clean_username,
            project=ctx.deps.project_name,
            count=count,
            save_to_db=True
        )

        if not videos:
            return f"No videos found for @{clean_username}."

        total_views = sum(v.views for v in videos)
        avg_views = total_views / len(videos)

        response = f"Scraped {len(videos)} videos from @{clean_username}\n\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Average Views: {avg_views:,.0f}\n"

        logger.info(f"Successfully scraped {len(videos)} videos")
        return response

    except Exception as e:
        logger.error(f"Error in scrape_tiktok_user_tool: {e}", exc_info=True)
        return f"Error scraping TikTok user: {str(e)}"


@tool_registry.register(
    name="analyze_tiktok_video_tool",
    description="Analyze a single TikTok video from URL",
    category="Analysis",
    platform="TikTok",
    rate_limit="15/minute",
    use_cases=[
        "Analyze specific TikTok video performance",
        "Get insights on competitor videos",
        "Study successful TikTok content",
        "Evaluate video metrics"
    ],
    examples=[
        "Analyze this TikTok video: [URL]",
        "Get insights on TikTok [URL]",
        "Analyze video performance for [URL]",
        "Show me metrics for this TikTok"
    ]
)
async def analyze_tiktok_video_tool(
    ctx: RunContext[AgentDependencies],
    url: str
) -> str:
    """Analyze a single TikTok video from URL."""
    try:
        logger.info(f"Analyzing TikTok video: {url}")

        video = await ctx.deps.tiktok.fetch_video_by_url(
            url=url,
            project=ctx.deps.project_name,
            save_to_db=True
        )

        if not video:
            return f"Failed to fetch TikTok video from URL: {url}"

        response = f"**TikTok Video Analysis**\n\n"
        response += f"**Creator:** @{video.username}\n"
        response += f"- Followers: {video.follower_count:,}\n\n"
        response += f"**Metrics:**\n"
        response += f"- Views: {video.views:,}\n"
        response += f"- Likes: {video.likes:,}\n"
        response += f"- Engagement Rate: {video.engagement_rate:.2%}\n"

        logger.info(f"Successfully analyzed TikTok video")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_tiktok_video_tool: {e}", exc_info=True)
        return f"Error analyzing TikTok video: {str(e)}"


@tool_registry.register(
    name="analyze_tiktok_batch_tool",
    description="Batch analyze multiple TikTok videos from URLs",
    category="Analysis",
    platform="TikTok",
    rate_limit="10/minute",
    use_cases=[
        "Analyze multiple TikTok videos at once",
        "Compare performance across videos",
        "Bulk import viral TikTok content",
        "Aggregate video metrics"
    ],
    examples=[
        "Analyze these TikTok videos: [URL1, URL2, URL3]",
        "Batch analyze TikToks",
        "Compare these video URLs",
        "Get metrics for multiple TikToks"
    ]
)
async def analyze_tiktok_batch_tool(
    ctx: RunContext[AgentDependencies],
    urls: List[str]
) -> str:
    """Batch analyze multiple TikTok videos from URLs."""
    try:
        logger.info(f"Batch analyzing {len(urls)} TikTok videos")

        videos = await ctx.deps.tiktok.fetch_videos_by_urls(
            urls=urls,
            project=ctx.deps.project_name,
            save_to_db=True
        )

        if not videos:
            return f"No videos could be fetched from the provided URLs."

        total_views = sum(v.views for v in videos)
        avg_views = total_views / len(videos)

        response = f"**Batch Analysis Complete**\n\n"
        response += f"- Videos Fetched: {len(videos)}/{len(urls)}\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Average Views: {avg_views:,.0f}\n"

        logger.info(f"Successfully batch analyzed {len(videos)} videos")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_tiktok_batch_tool: {e}", exc_info=True)
        return f"Error in batch analysis: {str(e)}"


# ============================================================================
# Phase 1.7 - YouTube & Facebook Platform Support
# ============================================================================

@tool_registry.register(
    name="search_youtube_tool",
    description="Search YouTube for viral videos and Shorts by keyword",
    category="Ingestion",
    platform="YouTube",
    rate_limit="10/minute",
    use_cases=[
        "Find viral YouTube Shorts by topic",
        "Discover trending YouTube content",
        "Research what's performing on YouTube",
        "Scrape YouTube for content ideas"
    ],
    examples=[
        "Search YouTube for productivity tips",
        "Find viral YouTube Shorts about fitness",
        "Show me trending videos on entrepreneurship",
        "Search YouTube for study tips"
    ]
)
async def search_youtube_tool(
    ctx: RunContext[AgentDependencies],
    keywords: str,
    max_shorts: int = 100,
    max_videos: int = 0,
    days_back: Optional[int] = None,
    min_views: Optional[int] = 100000,
    max_subscribers: Optional[int] = 50000
) -> str:
    """Search YouTube for viral videos by keyword."""
    try:
        search_terms = [k.strip() for k in keywords.split(',')]
        logger.info(f"Searching YouTube for {len(search_terms)} keywords")

        videos = await ctx.deps.youtube.search_videos(
            search_terms=search_terms,
            project=ctx.deps.project_name,
            max_shorts=max_shorts,
            max_videos=max_videos,
            days_back=days_back,
            min_views=min_views,
            max_subscribers=max_subscribers,
            save_to_db=True
        )

        if not videos:
            return f"No YouTube videos found for keywords: {keywords}"

        total_views = sum(v.views for v in videos)

        response = f"Found {len(videos)} viral YouTube videos\n\n"
        response += f"- Total Views: {total_views:,}\n"

        logger.info(f"Successfully found {len(videos)} YouTube videos")
        return response

    except Exception as e:
        logger.error(f"Error in search_youtube_tool: {e}", exc_info=True)
        return f"Error searching YouTube: {str(e)}"


@tool_registry.register(
    name="search_facebook_ads_tool",
    description="Search Facebook Ad Library by URL for competitor ads",
    category="Ingestion",
    platform="Facebook",
    rate_limit="10/minute",
    use_cases=[
        "Find competitor ads by keyword",
        "Research ad strategies for topics",
        "Monitor ad spend trends",
        "Analyze advertising campaigns"
    ],
    examples=[
        "Search Facebook ads for 'productivity'",
        "Find competitor ads in Ad Library",
        "Show me ads about fitness",
        "Search Facebook Ad Library"
    ]
)
async def search_facebook_ads_tool(
    ctx: RunContext[AgentDependencies],
    search_url: str,
    count: Optional[int] = 50,
    period: str = "last30d"
) -> str:
    """Search Facebook Ad Library by URL."""
    try:
        logger.info(f"Searching Facebook Ad Library")

        ads = await ctx.deps.facebook.search_ads(
            search_url=search_url,
            project=ctx.deps.project_name,
            count=count,
            period=period,
            save_to_db=True
        )

        if not ads:
            return f"No Facebook ads found."

        response = f"Found {len(ads)} Facebook ads\n\n"
        response += f"- Active: {sum(1 for ad in ads if ad.is_active)}\n"

        logger.info(f"Successfully found {len(ads)} Facebook ads")
        return response

    except Exception as e:
        logger.error(f"Error in search_facebook_ads_tool: {e}", exc_info=True)
        return f"Error searching Facebook ads: {str(e)}"


@tool_registry.register(
    name="scrape_facebook_page_ads_tool",
    description="Scrape all ads run by a specific Facebook page",
    category="Ingestion",
    platform="Facebook",
    rate_limit="10/minute",
    use_cases=[
        "Analyze competitor ad campaigns",
        "Study brand advertising strategies",
        "Track page advertising history",
        "Monitor campaign performance"
    ],
    examples=[
        "Scrape ads from Facebook page [URL]",
        "Get all ads from this page",
        "Analyze Facebook page advertising",
        "Show me ads run by [brand]"
    ]
)
async def scrape_facebook_page_ads_tool(
    ctx: RunContext[AgentDependencies],
    page_url: str,
    count: Optional[int] = 50,
    active_status: str = "all"
) -> str:
    """Scrape all ads run by a Facebook page."""
    try:
        logger.info(f"Scraping ads from Facebook page")

        ads = await ctx.deps.facebook.scrape_page_ads(
            page_url=page_url,
            project=ctx.deps.project_name,
            count=count,
            active_status=active_status,
            save_to_db=True
        )

        if not ads:
            return f"No ads found for the Facebook page."

        response = f"Scraped {len(ads)} ads from page\n\n"
        response += f"- Currently Active: {sum(1 for ad in ads if ad.is_active)}\n"

        logger.info(f"Successfully scraped {len(ads)} ads")
        return response

    except Exception as e:
        logger.error(f"Error in scrape_facebook_page_ads_tool: {e}", exc_info=True)
        return f"Error scraping Facebook page ads: {str(e)}"


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'find_outliers_tool',
    'analyze_hooks_tool',
    'verify_scrape_tool',
    'export_results_tool',
    'get_top_tweets_tool',
    'export_tweets_tool',
    'search_twitter_tool',
    'find_comment_opportunities_tool',
    'export_comments_tool',
    'analyze_search_term_tool',
    'generate_content_tool',
    'search_tiktok_tool',
    'search_tiktok_hashtag_tool',
    'scrape_tiktok_user_tool',
    'analyze_tiktok_video_tool',
    'analyze_tiktok_batch_tool',
    'search_youtube_tool',
    'search_facebook_ads_tool',
    'scrape_facebook_page_ads_tool'
]
