"""Twitter/X Platform Specialist Agent"""
import logging
from typing import Optional
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# Create Twitter specialist agent
twitter_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Twitter/X platform specialist agent.

**CRITICAL PARAMETER HANDLING:**
When users specify numeric limits, ALWAYS extract and pass them to tool parameters:
- "100 tweets" → max_results=100
- "limit to 500" → max_results=500
- "find 200 tweets" → max_results=200
- "top 1000 tweets" → max_results=1000
- "get 50 tweets" → max_results=50
- If no limit specified → use default (50)
- NOTE: Apify minimum is 50 tweets

**Examples:**
User: "Find 100 viral tweets about AI"
→ Call: search_twitter(keyword="AI", max_results=100)

User: "Show me 500 tweets from last 24 hours"
→ Call: search_twitter(keyword="tweets", hours_back=24, max_results=500)

User: "Search for 200 tweets about Bitcoin"
→ Call: search_twitter(keyword="Bitcoin", max_results=200)

Your ONLY responsibility is Twitter/X data operations:
- Searching and scraping tweets by keyword
- Querying database for top tweets by engagement
- Finding comment opportunities on viral tweets
- Analyzing search term performance
- Generating content from viral hooks
- Verifying scrape results
- Exporting tweet and comment data to files

**Important:**
- When you retrieve tweets, ALWAYS save them to result_cache.last_twitter_query
- When exporting, use the same parameters that were used in the query
- Support multi-keyword OR logic with comma-separated keywords (e.g., "btc,bitcoin")
- Always provide clear summaries of results with engagement metrics

**Available Services:**
- TwitterService: For API scraping
- StatsService: For database queries
- GeminiService: For AI analysis and content generation

**Result Format:**
- Provide clear, structured responses with metrics
- Show top results with engagement stats (views, likes, retweets)
- Include URLs for all content
- Save files to ~/Downloads/ for exports
"""
)


# ============================================================================
# Twitter Tools
# ============================================================================

@twitter_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Twitter',
        'rate_limit': '10/minute',
        'use_cases': [
            'Scrape NEW tweets from Twitter by keyword',
            'Build NEW dataset for viral content analysis',
            'Collect FRESH tweets for audience research',
            'Ingest NEW tweets about a topic into database'
        ],
        'examples': [
            'Scrape fresh tweets about \'productivity tips\' from Twitter',
            'Collect NEW tweets about #startups from Twitter',
            'Ingest 5000 NEW tweets mentioning AI from Twitter',
            'Scrape recent tweets about parenting from Twitter and save to database'
        ]
    }
)
async def search_twitter(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24,
    max_results: int = 50
) -> str:
    """
    Search/scrape Twitter by keyword and save results to database.

    Scrapes fresh tweets from Twitter matching the specified keyword,
    saves them to the database, and returns a summary of results including
    engagement metrics and top performing tweets.

    Use this when users want to:
    - Find tweets about a topic
    - Discover viral content for a keyword
    - Scrape recent tweets matching a search term

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search keyword or hashtag (e.g., "parenting tips", "#productivity")
        hours_back: Hours of historical data to search (default: 24)
        max_results: Maximum tweets to scrape (default: 50, min: 50, max: 10000)
                    CRITICAL: Always extract numeric limits from user prompts:
                    - "100 tweets" → max_results=100
                    - "500 tweets" → max_results=500
                    - "limit to 200" → max_results=200
                    - "find 1000 tweets" → max_results=1000
                    Note: Apify minimum is 50 tweets
                    If no limit specified, use default (50)

    Returns:
        Formatted string summary of scraping results with stats and top 5 tweets
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
        logger.error(f"Error in search_twitter: {e}", exc_info=True)
        return f"Error searching Twitter: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Look up top tweets by view count from database',
            'Find most viewed tweets containing keyword in database',
            'Query database for tweets sorted by engagement',
            'Show top tweets already saved in database'
        ],
        'examples': [
            'Show me the top 10 tweets by views from the database',
            'Look up the most viewed tweets containing \'bitcoin\' in our database',
            'What are the top tweets with \'productivity\' in the database?',
            'Find the 20 most popular tweets about \'AI\' from last 48 hours in the database'
        ]
    }
)
async def get_top_tweets(
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
    this simply returns the top N tweets sorted by the chosen metric
    from the database.

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
        keyword: Optional keyword filter - supports multiple keywords with OR logic
                 Single: "bitcoin" or Multiple: "btc,bitcoin" (comma-separated)

    Returns:
        Formatted string with top tweets from database sorted by chosen metric
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

        # Filter by keyword(s) if provided - supports multiple keywords with OR logic
        if keyword:
            # Split comma-separated keywords and convert to lowercase
            keywords = [k.strip().lower() for k in keyword.split(',')]

            # Filter tweets that contain ANY of the keywords (OR logic)
            tweets = [t for t in tweets if any(kw in t.text.lower() for kw in keywords)]

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
        logger.error(f"Error in get_top_tweets: {e}", exc_info=True)
        return f"Error getting top tweets: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Export tweet search results to downloadable file',
            'Download filtered tweets by keyword or views',
            'Save tweet lists for external reporting',
            'Export top performing tweets by metric'
        ],
        'examples': [
            'Export these tweets to CSV',
            'Download the bitcoin tweets as JSON',
            'Give me these results in markdown format',
            'Export the top 10 tweets to a file'
        ]
    }
)
async def export_tweets(
    ctx: RunContext[AgentDependencies],
    keyword: Optional[str] = None,
    hours_back: int = 24,
    sort_by: str = "views",
    limit: int = 100,
    min_views: int = 0
):
    """
    Export filtered tweet lists with download buttons for CSV, JSON, and Markdown.

    Use this when users want to download or export tweet results.
    Returns a structured result that Streamlit UI will render with 3 download buttons.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Optional keyword filter - supports multiple keywords with OR logic
                 Single: "bitcoin" or Multiple: "btc,bitcoin" (comma-separated)
        hours_back: Hours to look back (default: 24)
        sort_by: Metric to sort by - 'views', 'likes', 'engagement' (default: 'views')
        limit: Number of tweets to export (default: 100)
        min_views: Minimum view count filter (default: 0)

    Returns:
        TweetExportResult with tweets and download capabilities
    """
    try:
        from viraltracker.services.models import TweetExportResult

        logger.info(f"Exporting tweets: keyword={keyword}, sort_by={sort_by}")

        # Fetch tweets from database
        tweets = await ctx.deps.twitter.get_tweets(
            project=ctx.deps.project_name,
            hours_back=hours_back,
            min_views=min_views,
            text_only=False
        )

        if not tweets:
            # Return empty result
            return TweetExportResult(
                total_tweets=0,
                keyword_filter=keyword,
                hours_back=hours_back,
                sort_by=sort_by,
                tweets=[],
                total_views=0,
                total_likes=0,
                total_engagement=0,
                avg_engagement_rate=0.0
            )

        # Filter by keyword(s) if provided - supports multiple keywords with OR logic
        if keyword:
            # Split comma-separated keywords and convert to lowercase
            keywords = [k.strip().lower() for k in keyword.split(',')]

            # Filter tweets that contain ANY of the keywords (OR logic)
            tweets = [t for t in tweets if any(kw in t.text.lower() for kw in keywords)]

            if not tweets:
                # Return empty result
                return TweetExportResult(
                    total_tweets=0,
                    keyword_filter=keyword,
                    hours_back=hours_back,
                    sort_by=sort_by,
                    tweets=[],
                    total_views=0,
                    total_likes=0,
                    total_engagement=0,
                    avg_engagement_rate=0.0
                )

        # Sort by chosen metric
        if sort_by == "views":
            sorted_tweets = sorted(tweets, key=lambda t: t.view_count, reverse=True)
        elif sort_by == "likes":
            sorted_tweets = sorted(tweets, key=lambda t: t.like_count, reverse=True)
        elif sort_by == "engagement":
            sorted_tweets = sorted(tweets, key=lambda t: t.engagement_score, reverse=True)
        else:
            raise ValueError(f"Invalid sort_by parameter: {sort_by}. Use 'views', 'likes', or 'engagement'.")

        # Limit results
        export_tweets = sorted_tweets[:limit]

        # Calculate summary statistics
        total_views = sum(t.view_count for t in export_tweets)
        total_likes = sum(t.like_count for t in export_tweets)
        total_engagement = sum(
            t.like_count + t.reply_count + t.retweet_count
            for t in export_tweets
        )
        avg_engagement_rate = (
            sum(t.engagement_rate for t in export_tweets) / len(export_tweets)
            if export_tweets else 0.0
        )

        # Create result object
        result = TweetExportResult(
            total_tweets=len(export_tweets),
            keyword_filter=keyword,
            hours_back=hours_back,
            sort_by=sort_by,
            tweets=export_tweets,
            total_views=total_views,
            total_likes=total_likes,
            total_engagement=total_engagement,
            avg_engagement_rate=avg_engagement_rate
        )

        logger.info(f"Successfully created export result with {len(export_tweets)} tweets")
        return result

    except Exception as e:
        logger.error(f"Error in export_tweets: {e}", exc_info=True)
        raise


@twitter_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Find tweets to comment on for engagement',
            'Identify high-quality conversation starters',
            'Get comment suggestions with AI-generated responses',
            'Build engagement strategy'
        ],
        'examples': [
            'Find comment opportunities from last 48 hours',
            'Show me tweets to engage with',
            'Get comment suggestions for viral tweets',
            'Find green flag comment opportunities'
        ]
    }
)
async def find_comment_opportunities(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    min_green_flags: int = 3,
    max_candidates: int = 100
) -> str:
    """
    Find high-quality comment opportunities from recent tweets.

    Searches for tweets that would be good candidates for commenting,
    based on AI-generated quality scores and green/yellow/red flag classification.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 48)
        min_green_flags: Minimum number of green flags required (default: 3)
        max_candidates: Maximum candidates to analyze (default: 100)

    Returns:
        Summary with statistics and top 10 comment opportunities
    """
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
        logger.error(f"Error in find_comment_opportunities: {e}", exc_info=True)
        return f"Error finding comment opportunities: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Download comment opportunities for review',
            'Export data for external analysis',
            'Save results to JSON/CSV/markdown',
            'Archive engagement opportunities'
        ],
        'examples': [
            'Export comment opportunities as JSON',
            'Download green flag comments to CSV',
            'Export last 48 hours of opportunities',
            'Give me markdown export of comments'
        ]
    }
)
async def export_comments(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 48,
    format: str = "json",
    label_filter: Optional[str] = None
) -> str:
    """
    Export comment opportunities to file.

    Exports previously generated comment opportunities to various formats
    for external analysis or manual review.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 48)
        format: Output format - 'json', 'csv', or 'markdown' (default: 'json')
        label_filter: Filter by label - 'green', 'yellow', or 'red' (optional)

    Returns:
        Summary of exported data with preview
    """
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
        logger.error(f"Error in export_comments: {e}", exc_info=True)
        return f"Error exporting comments: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Understand keyword performance metrics',
            'Analyze engagement trends for topics',
            'Get insights on content themes',
            'Evaluate search term effectiveness'
        ],
        'examples': [
            'Analyze engagement for \'productivity\'',
            'How is the keyword \'startup\' performing?',
            'Show me metrics for #AI tweets',
            'Analyze search term performance'
        ]
    }
)
async def analyze_search_term(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24
) -> str:
    """
    Analyze engagement patterns for a keyword/search term.

    Examines all tweets in the database containing the specified keyword
    and provides aggregate statistics and best performing content.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Keyword to analyze (case-insensitive)
        hours_back: Hours to look back (default: 24)

    Returns:
        Analysis report with metrics and best performing tweet
    """
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
                f"Suggestion: Try using 'search_twitter' to scrape tweets for this keyword first."
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
        logger.error(f"Error in analyze_search_term: {e}", exc_info=True)
        return f"Error analyzing search term: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Twitter',
        'rate_limit': '5/minute',
        'use_cases': [
            'Create Twitter threads from viral hooks',
            'Generate articles based on popular tweets',
            'Turn insights into long-form content',
            'Expand viral tweets into detailed posts'
        ],
        'examples': [
            'Generate a thread from today\'s viral tweets',
            'Create an article from top hooks',
            'Turn viral tweets into a Twitter thread',
            'Generate content from last 24 hours'
        ]
    }
)
async def generate_content(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    content_type: str = "thread",
    limit: int = 10
) -> str:
    """
    Generate long-form content from viral tweet hooks.

    Identifies viral tweets using statistical analysis, analyzes their hooks
    using AI, and generates long-form content (threads, articles, etc.) based
    on the patterns and insights discovered.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back for viral content (default: 24)
        content_type: Type of content to generate - 'thread' or 'article' (default: 'thread')
        limit: Maximum number of viral hooks to analyze (default: 10)

    Returns:
        Generated content with introduction and formatted output
    """
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
        logger.error(f"Error in generate_content: {e}", exc_info=True)
        return f"Error generating content: {str(e)}"


@twitter_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Verify scrape completed successfully',
            'Check if data quality warnings affected results',
            'Confirm tweet count after malformed data skipped',
            'Double-check database for recent scrapes'
        ],
        'examples': [
            'Verify the scrape for BTC',
            'Check if the parenting scrape completed',
            'Did all tweets get saved?',
            'Verify the last scrape'
        ]
    }
)
async def verify_scrape(
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
                f"- Increase time window: verify_scrape(keyword='{keyword}', hours_back=2)\n"
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
        logger.error(f"Error in verify_scrape: {e}", exc_info=True)
        return (
            f"**❌ VERIFICATION ERROR**\n\n"
            f"Failed to verify scrape for '{keyword}': {str(e)}\n\n"
            f"This may indicate a database connection issue or internal error."
        )


logger.info("Twitter Agent initialized with 8 tools")
