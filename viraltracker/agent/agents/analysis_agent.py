"""Analysis Specialist Agent"""
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


logger.info("Analysis Agent initialized with 6 tools")
