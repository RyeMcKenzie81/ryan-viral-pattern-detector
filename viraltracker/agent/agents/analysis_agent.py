"""Analysis Specialist Agent"""
import json
import logging
from typing import Optional, List
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies
from ...services.models import OutlierResult, HookAnalysisResult, OutlierTweet

logger = logging.getLogger(__name__)

from ...core.config import Config

# Create Analysis specialist agent
analysis_agent = Agent(
    model=Config.get_model("analysis"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Analysis specialist agent.

Your ONLY responsibility is advanced analysis operations:
- Finding viral outlier tweets using statistical analysis (z-score, IQR, percentile methods)
- Analyzing tweet hooks with AI to identify patterns and emotional triggers
- Exporting comprehensive analysis reports combining outliers and hooks

**Important:**
- Save all results to result_cache.last_analysis_result
- Provide clear insights into what makes content go viral
- Focus on identifying patterns, hooks, and emotional triggers
- Generate actionable insights for content creators

**Available Services:**
- StatsService: For statistical analysis and database queries
- GeminiService: For AI-powered hook and pattern analysis
- BrandResearchService: For brand research summaries and landing page stats
- SEOProjectService: For SEO project listing and status
- KeywordDiscoveryService: For discovering long-tail keywords
- SEOAnalyticsService: For ranking tracking and history
- OpportunityMinerService: For finding "striking distance" keyword opportunities
- ArticleTrackingService: For listing and tracking SEO articles
- GA4Service: For Google Analytics page analytics and traffic sources
- RedditSentimentService: For Reddit scraping and sentiment analysis

**Result Format:**
- Provide clear, structured responses with statistical insights
- Show top viral content with engagement metrics
- Include pattern analysis and hook breakdowns
- Export results to CSV, JSON, or markdown formats
- Save files to ~/Downloads/ for exports
"""
)

# ============================================================================
# Analysis Tools - Migrated from @tool_registry to @agent.tool pattern
# ============================================================================

@analysis_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Twitter',
        'rate_limit': '20/minute',
        'use_cases': [
            'Find top performing content',
            'Identify viral tweets',
            'Discover engagement patterns',
            'Track statistical outliers'
        ],
        'examples': [
            'Show me viral tweets from today',
            'Find top performers from last 48 hours',
            'What tweets are outliers this week?',
            'Show me statistically viral content'
        ]
    }
)
async def find_outliers(
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
        from ...services.statistics_service import StatisticsService
        stats = StatisticsService()
        mean_eng, median_eng, std_eng = stats.calculate_engagement_stats(engagement_scores)

        # Create OutlierTweet objects with rankings
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
        logger.error(f"Error in find_outliers: {e}", exc_info=True)
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


@analysis_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Twitter',
        'rate_limit': '10/minute',
        'use_cases': [
            'Understand viral hook patterns',
            'Identify emotional triggers',
            'Analyze content strategies',
            'Extract viral patterns'
        ],
        'examples': [
            'Analyze hooks from top tweets today',
            'What patterns make these tweets viral?',
            'Show me emotional triggers in top content',
            'Analyze viral hooks from this week'
        ]
    }
)
async def analyze_hooks(
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
        logger.error(f"Error in analyze_hooks: {e}", exc_info=True)
        # Return empty result on error
        return HookAnalysisResult(
            total_analyzed=0,
            successful_analyses=0,
            failed_analyses=0,
            analyses=[]
        )


@analysis_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'Twitter',
        'rate_limit': '10/minute',
        'use_cases': [
            'Generate full analysis report with outliers and hooks',
            'Export viral tweet insights to markdown',
            'Create comprehensive content strategy document',
            'Download complete engagement analysis'
        ],
        'examples': [
            'Export a full analysis report for the last 24 hours',
            'Create a comprehensive report with hooks',
            'Give me a markdown export of viral tweets',
            'Download complete analysis for this week'
        ]
    }
)
async def export_results(
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
        logger.error(f"Error in export_results: {e}", exc_info=True)
        return f"Error exporting results: {str(e)}"


# ============================================================================
# Brand Research Tools
# ============================================================================


@analysis_agent.tool(
    metadata={
        "category": "Query",
        "platform": "Brand Research",
        "use_cases": [
            "Get brand research overview",
            "Check research analysis counts",
            "See what research exists for a brand",
        ],
        "examples": [
            "What research do we have for BobaNutrition?",
            "Show me the research summary for Wonder Paws",
            "How many analyses exist for this brand?",
        ],
    }
)
async def get_research_summary(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """Get a summary of brand research: analysis counts, landing pages, and insights.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Brand UUID string.

    Returns:
        Formatted summary of research status for the brand.
    """
    try:
        from uuid import UUID

        # Get analysis count
        analyses = ctx.deps.brand_research.get_analyses_for_brand(UUID(brand_id))
        analysis_count = len(analyses) if analyses else 0

        # Get landing page stats
        lp_stats = ctx.deps.brand_research.get_landing_page_stats(UUID(brand_id))

        # Get belief-first analysis stats
        belief_stats = ctx.deps.brand_research.get_belief_first_analysis_stats(UUID(brand_id))

        lines = [
            f"## Brand Research Summary\n",
            f"- **Ad analyses:** {analysis_count}",
            f"- **Landing pages scraped:** {lp_stats.get('total', 0)}",
            f"- **Landing pages analyzed:** {lp_stats.get('analyzed', 0)}",
            f"- **Belief-first analyses:** {belief_stats.get('total', 0)}",
        ]

        # Breakdown by analysis type if available
        if analyses:
            types = {}
            for a in analyses:
                t = a.get("analysis_type", "unknown")
                types[t] = types.get(t, 0) + 1
            if types:
                lines.append("\n**Analysis breakdown:**")
                for t, count in sorted(types.items(), key=lambda x: -x[1]):
                    lines.append(f"  - {t}: {count}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_research_summary failed: {e}")
        return f"Failed to get research summary: {e}"


# ============================================================================
# SEO Tools
# ============================================================================


@analysis_agent.tool(
    metadata={
        "category": "Query",
        "platform": "SEO",
        "use_cases": [
            "List SEO projects",
            "Check what SEO work exists",
            "Find SEO project for a brand",
        ],
        "examples": [
            "What SEO projects do we have?",
            "List SEO projects for BobaNutrition",
            "Show me active SEO projects",
        ],
    }
)
async def list_seo_projects(
    ctx: RunContext[AgentDependencies],
    brand_id: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """List SEO content projects, optionally filtered by brand and status.

    Args:
        ctx: Run context with AgentDependencies.
        brand_id: Optional brand UUID to filter by.
        status: Optional status filter (e.g., 'active', 'completed', 'draft').

    Returns:
        Formatted list of SEO projects.
    """
    if not ctx.deps.seo_project:
        return "SEO service is not available. Check that OPENAI_API_KEY is configured."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        projects = ctx.deps.seo_project.list_projects(
            organization_id=org_id,
            brand_id=brand_id,
            status=status,
        )

        if not projects:
            return "No SEO projects found."

        lines = [f"**SEO Projects** ({len(projects)} found)\n"]
        for p in projects:
            status_icon = {"active": "🟢", "completed": "✅", "draft": "📝"}.get(
                p.get("status", ""), "❓"
            )
            line = (
                f"{status_icon} **{p.get('name', 'Untitled')}** — {p.get('status', 'unknown')}"
            )
            if p.get("brand_id"):
                line += f" | Brand: {p['brand_id'][:8]}..."
            line += f"\n   ID: `{p['id']}`"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"list_seo_projects failed: {e}")
        return f"Failed to list SEO projects: {e}"


@analysis_agent.tool(
    metadata={
        "category": "Query",
        "platform": "SEO",
        "use_cases": [
            "Check SEO project status",
            "See pipeline progress",
            "Get project details",
        ],
        "examples": [
            "What's the status of SEO project abc-123?",
            "Show me the SEO pipeline progress",
        ],
    }
)
async def get_seo_project_status(
    ctx: RunContext[AgentDependencies],
    project_id: str,
) -> str:
    """Get details and pipeline status for a specific SEO project.

    Args:
        ctx: Run context with AgentDependencies.
        project_id: SEO project UUID string.

    Returns:
        Project details including pipeline status and configuration.
    """
    if not ctx.deps.seo_project:
        return "SEO service is not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        project = ctx.deps.seo_project.get_project(project_id, org_id)

        if not project:
            return f"No SEO project found with ID {project_id}."

        lines = [
            f"## SEO Project: {project.get('name', 'Untitled')}",
            f"**ID:** {project['id']}",
            f"**Status:** {project.get('status', 'unknown')}",
        ]

        if project.get("config"):
            config = project["config"]
            if config.get("target_keyword"):
                lines.append(f"**Target keyword:** {config['target_keyword']}")
            if config.get("word_count_target"):
                lines.append(f"**Word count target:** {config['word_count_target']}")

        if project.get("workflow_state"):
            lines.append(f"**Pipeline stage:** {project['workflow_state']}")

        if project.get("created_at"):
            lines.append(f"**Created:** {project['created_at']}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_seo_project_status failed: {e}")
        return f"Failed to get SEO project status: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "Find long-tail keywords",
            "Discover keyword ideas from seeds",
        ],
    }
)
async def discover_keywords(
    ctx: RunContext[AgentDependencies],
    project_id: str,
    seed_keywords: List[str],
    min_word_count: int = 3,
    max_word_count: int = 8,
) -> str:
    """Discover long-tail keywords from seed terms using Google Autocomplete.

    Expands seed keywords into hundreds of long-tail variations via autocomplete
    suggestions. Keywords are saved to the project for enrichment and scoring.

    Args:
        ctx: Run context with AgentDependencies
        project_id: SEO project UUID
        seed_keywords: List of seed keywords (e.g. ["cortisol supplements", "stress relief"])
        min_word_count: Minimum words per keyword (default: 3)
        max_word_count: Maximum words per keyword (default: 8)

    Returns:
        Summary of discovered keywords with counts.
    """
    if not ctx.deps.seo_keyword_discovery:
        return "Keyword discovery service not available."

    try:
        result = await ctx.deps.seo_keyword_discovery.discover_keywords(
            project_id=project_id,
            seeds=seed_keywords,
            min_word_count=min_word_count,
            max_word_count=max_word_count,
        )

        total = result.get("total_keywords", 0)
        saved = result.get("saved_count", 0)
        keywords = result.get("keywords", [])

        lines = [
            f"**Keyword Discovery Complete**",
            f"- Seeds: {', '.join(seed_keywords)}",
            f"- Total discovered: {total}",
            f"- New keywords saved: {saved}",
        ]

        if keywords:
            lines.append(f"\n**Sample keywords** (showing first 15):")
            for kw in keywords[:15]:
                if isinstance(kw, dict):
                    lines.append(f"- {kw.get('keyword', kw)}")
                else:
                    lines.append(f"- {kw}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"discover_keywords failed: {e}")
        return f"Keyword discovery failed: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "Find SEO opportunities",
            "Striking distance keywords",
            "What keywords can we rank for",
        ],
    }
)
async def scan_seo_opportunities(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """Scan for "striking distance" keyword opportunities (positions 4-20).

    Finds keywords where the brand is close to page 1 or already on page 1
    but not yet in top 3. These are high-ROI opportunities for content
    optimization or new content.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: Brand UUID string

    Returns:
        Scored list of keyword opportunities with current position and potential.
    """
    if not ctx.deps.seo_opportunity_miner:
        return "SEO opportunity mining service not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        opportunities = ctx.deps.seo_opportunity_miner.scan_opportunities(
            brand_id=brand_id,
            organization_id=org_id,
        )

        if not opportunities:
            return "No striking-distance opportunities found. This could mean no GSC data is available or all keywords are already ranking well."

        lines = [f"**SEO Opportunities** ({len(opportunities)} found)\n"]
        for i, opp in enumerate(opportunities[:20], 1):
            keyword = opp.get("keyword", "unknown")
            position = opp.get("position", "?")
            clicks = opp.get("clicks", 0)
            impressions = opp.get("impressions", 0)
            score = opp.get("score", 0)
            lines.append(
                f"{i}. **{keyword}** — Position: {position}, "
                f"Clicks: {clicks}, Impressions: {impressions}, "
                f"Score: {score:.1f}"
            )

        if len(opportunities) > 20:
            lines.append(f"\n_...and {len(opportunities) - 20} more opportunities_")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"scan_seo_opportunities failed: {e}")
        return f"Opportunity scan failed: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "Check keyword rankings",
            "How are our articles ranking",
            "SEO ranking dashboard",
        ],
    }
)
async def get_seo_rankings(
    ctx: RunContext[AgentDependencies],
    project_id: str,
) -> str:
    """Get latest keyword rankings for all articles in an SEO project.

    Shows current ranking position for each published article and its
    target keyword.

    Args:
        ctx: Run context with AgentDependencies
        project_id: SEO project UUID

    Returns:
        Table of articles with their current rankings.
    """
    if not ctx.deps.seo_analytics:
        return "SEO analytics service not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        rankings = ctx.deps.seo_analytics.get_latest_rankings(
            project_id=project_id,
            organization_id=org_id,
        )

        if not rankings:
            return "No ranking data available for this project. Rankings are populated after articles are published and indexed."

        lines = [f"**SEO Rankings** ({len(rankings)} articles tracked)\n"]
        for r in rankings:
            keyword = r.get("keyword", "unknown")
            position = r.get("position", "?")
            title = r.get("title", r.get("article_id", "")[:12] + "...")
            checked = r.get("checked_at", "")[:10] if r.get("checked_at") else "N/A"
            pos_display = f"#{position}" if position else "Not ranking"
            lines.append(f"- **{title}** → `{keyword}` — {pos_display} (as of {checked})")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_seo_rankings failed: {e}")
        return f"Failed to get rankings: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "List SEO articles",
            "Show published articles",
            "What content have we published",
        ],
    }
)
async def list_seo_articles(
    ctx: RunContext[AgentDependencies],
    project_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """List SEO articles, optionally filtered by project, brand, and status.

    Args:
        ctx: Run context with AgentDependencies
        project_id: Optional SEO project UUID to filter by
        brand_id: Optional brand UUID to filter by
        status: Optional status filter (e.g. 'published', 'draft', 'in_review')

    Returns:
        List of articles with status, word count, and publication details.
    """
    if not ctx.deps.seo_article_tracking:
        return "Article tracking service not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        articles = ctx.deps.seo_article_tracking.list_articles(
            organization_id=org_id,
            project_id=project_id,
            brand_id=brand_id,
            status=status,
        )

        if not articles:
            return "No SEO articles found matching those filters."

        lines = [f"**SEO Articles** ({len(articles)} found)\n"]
        for a in articles[:25]:
            title = a.get("title", "Untitled")
            art_status = a.get("status", "unknown")
            keyword = a.get("target_keyword", "")
            word_count = a.get("word_count", "?")
            status_icon = {
                "published": "✅",
                "draft": "📝",
                "in_review": "👀",
                "generating": "⚙️",
            }.get(art_status, "❓")
            line = f"{status_icon} **{title}** — {art_status}"
            if keyword:
                line += f" · Keyword: `{keyword}`"
            if word_count and word_count != "?":
                line += f" · {word_count} words"
            lines.append(line)

        if len(articles) > 25:
            lines.append(f"\n_...and {len(articles) - 25} more articles_")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"list_seo_articles failed: {e}")
        return f"Failed to list articles: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "Show page analytics",
            "Which pages get the most traffic",
            "GA4 page performance",
        ],
    }
)
async def get_page_analytics(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 28,
) -> str:
    """Get page-level analytics from Google Analytics 4.

    Shows sessions, pageviews, bounce rate, and average engagement time
    for each page. Requires GA4 integration to be configured.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: Brand UUID string
        days_back: Number of days to look back (default: 28)

    Returns:
        Page analytics table sorted by sessions.
    """
    if not ctx.deps.seo_ga4:
        return "GA4 service not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        pages = ctx.deps.seo_ga4.fetch_page_analytics(
            brand_id=brand_id,
            organization_id=org_id,
            days_back=days_back,
        )

        if not pages:
            return "No page analytics data available. Check that GA4 integration is configured for this brand."

        lines = [f"**Page Analytics** (last {days_back} days, {len(pages)} pages)\n"]
        for p in pages[:20]:
            path = p.get("page_path", p.get("page", "unknown"))
            sessions = p.get("sessions", 0)
            pageviews = p.get("pageviews", p.get("screenPageViews", 0))
            bounce = p.get("bounce_rate", p.get("bounceRate", "N/A"))
            if isinstance(bounce, (int, float)):
                bounce = f"{bounce:.0%}" if bounce <= 1 else f"{bounce:.0f}%"
            lines.append(
                f"- **{path}** — Sessions: {sessions}, "
                f"Pageviews: {pageviews}, Bounce: {bounce}"
            )

        if len(pages) > 20:
            lines.append(f"\n_...and {len(pages) - 20} more pages_")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_page_analytics failed: {e}")
        return f"Failed to get page analytics: {e}"


@analysis_agent.tool(
    metadata={
        "category": "SEO",
        "use_cases": [
            "Traffic sources breakdown",
            "Where is traffic coming from",
            "Channel performance",
        ],
    }
)
async def get_traffic_sources(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    days_back: int = 28,
) -> str:
    """Get traffic source breakdown from Google Analytics 4.

    Shows sessions by channel (organic search, direct, social, referral, etc.).
    Requires GA4 integration to be configured.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: Brand UUID string
        days_back: Number of days to look back (default: 28)

    Returns:
        Traffic sources sorted by session count.
    """
    if not ctx.deps.seo_ga4:
        return "GA4 service not available."

    try:
        org_id = getattr(ctx.deps, "_organization_id", None) or "all"
        sources = ctx.deps.seo_ga4.fetch_traffic_sources(
            brand_id=brand_id,
            organization_id=org_id,
            days_back=days_back,
        )

        if not sources:
            return "No traffic source data available. Check that GA4 integration is configured for this brand."

        lines = [f"**Traffic Sources** (last {days_back} days)\n"]
        total_sessions = sum(s.get("sessions", 0) for s in sources)

        for s in sources:
            channel = s.get("channel", s.get("sessionDefaultChannelGroup", "unknown"))
            sessions = s.get("sessions", 0)
            pct = f"{sessions / total_sessions:.1%}" if total_sessions > 0 else "N/A"
            lines.append(f"- **{channel}** — {sessions} sessions ({pct})")

        if total_sessions:
            lines.append(f"\n**Total sessions:** {total_sessions}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_traffic_sources failed: {e}")
        return f"Failed to get traffic sources: {e}"


# ============================================================================
# REDDIT RESEARCH TOOLS
# ============================================================================


@analysis_agent.tool(
    metadata={
        "category": "Reddit",
        "use_cases": [
            "Search Reddit for customer sentiment",
            "What does Reddit say about X",
            "Find Reddit discussions about a topic",
        ],
    }
)
async def search_reddit(
    ctx: RunContext[AgentDependencies],
    queries: list[str],
    subreddits: Optional[List[str]] = None,
) -> str:
    """Search Reddit for posts matching queries and return top results.

    Scrapes Reddit via Apify and returns the most relevant posts with
    engagement metrics. Use this for quick research on what people say
    about a topic, product category, or pain point.

    Args:
        ctx: Run context with AgentDependencies
        queries: List of search queries (e.g. ["cortisol supplements side effects"])
        subreddits: Optional list of subreddits to search (e.g. ["Supplements", "health"])

    Returns:
        Top Reddit posts with titles, scores, comment counts, and URLs.
    """
    from viraltracker.services.models import RedditScrapeConfig

    config = RedditScrapeConfig(
        search_queries=queries,
        subreddits=subreddits,
    )

    try:
        posts, comments = ctx.deps.reddit_sentiment.scrape_reddit(config, timeout=120)
    except Exception as e:
        return f"Reddit scrape failed: {e}"

    if not posts:
        return "No Reddit posts found for those queries."

    # Sort by score and return top 15
    sorted_posts = sorted(posts, key=lambda p: p.score, reverse=True)[:15]

    lines = [f"**Found {len(posts)} posts** (showing top {len(sorted_posts)}):\n"]
    for i, post in enumerate(sorted_posts, 1):
        lines.append(
            f"{i}. **{post.title}** (r/{post.subreddit})\n"
            f"   Score: {post.score} · Comments: {post.num_comments} · "
            f"URL: {post.url}"
        )

    return "\n".join(lines)


@analysis_agent.tool(
    metadata={
        "category": "Reddit",
        "use_cases": [
            "Analyze Reddit sentiment for a topic",
            "Extract pain points from Reddit",
            "What are people complaining about on Reddit",
        ],
    }
)
async def analyze_reddit_sentiment(
    ctx: RunContext[AgentDependencies],
    queries: list[str],
    subreddits: Optional[List[str]] = None,
    product_context: Optional[str] = None,
) -> str:
    """Run full Reddit sentiment analysis: scrape, score relevance, and extract quotes.

    This is a comprehensive analysis that:
    1. Scrapes Reddit for matching posts
    2. Scores each post for relevance using Claude
    3. Extracts categorized quotes (pain points, objections, desires, etc.)

    Takes 1-3 minutes depending on volume. Use for deep customer research.

    Args:
        ctx: Run context with AgentDependencies
        queries: Search queries (e.g. ["insomnia natural remedies"])
        subreddits: Optional subreddits to target
        product_context: Optional product description for relevance scoring

    Returns:
        Structured sentiment analysis with categorized quotes.
    """
    from viraltracker.services.models import RedditScrapeConfig

    config = RedditScrapeConfig(
        search_queries=queries,
        subreddits=subreddits,
    )

    service = ctx.deps.reddit_sentiment

    # Step 1: Scrape
    try:
        posts, _ = service.scrape_reddit(config, timeout=120)
    except Exception as e:
        return f"Reddit scrape failed: {e}"

    if not posts:
        return "No Reddit posts found for those queries."

    # Step 2: Score relevance
    try:
        scored = await service.score_relevance(
            posts,
            topic_context=", ".join(queries),
            threshold=0.5,
        )
    except Exception as e:
        return f"Relevance scoring failed: {e}. Got {len(posts)} raw posts."

    if not scored:
        return f"Found {len(posts)} posts but none scored as relevant."

    # Step 3: Extract categorized quotes
    try:
        categories = await service.categorize_and_extract_quotes(
            scored,
            product_context=product_context,
        )
    except Exception as e:
        return f"Quote extraction failed: {e}. {len(scored)} relevant posts found."

    # Format results
    lines = [
        f"**Reddit Sentiment Analysis** — {len(scored)}/{len(posts)} posts relevant\n"
    ]

    for category, quotes in categories.items():
        if quotes:
            lines.append(f"### {category.value.replace('_', ' ').title()} ({len(quotes)})")
            for q in quotes[:3]:
                lines.append(f"- \"{q.quote}\" — r/{q.subreddit} (score: {q.engagement_score})")
            if len(quotes) > 3:
                lines.append(f"  _{len(quotes) - 3} more..._")
            lines.append("")

    return "\n".join(lines)


logger.info("Analysis Agent initialized with 14 tools")
