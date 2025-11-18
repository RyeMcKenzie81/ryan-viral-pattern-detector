"""
Phase 1.6 Agent Tools - TikTok Platform Support

Adds 5 new tools for TikTok platform coverage:
1. search_tiktok_tool - Search TikTok by keyword
2. search_tiktok_hashtag_tool - Search by hashtag
3. scrape_tiktok_user_tool - Scrape user posts
4. analyze_tiktok_video_tool - Analyze single video
5. analyze_tiktok_batch_tool - Batch analyze videos

Expands agent capabilities from Twitter-only to multi-platform.
"""

import logging
from typing import Optional, List
from pydantic_ai import RunContext

from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Search TikTok by Keyword
# ============================================================================

async def search_tiktok_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """
    Search TikTok by keyword and return viral videos.

    Use this when users want to:
    - Find TikTok videos about a topic
    - Discover viral TikTok content by keyword
    - Research what's trending on TikTok

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search keyword or phrase (e.g., "productivity apps", "morning routine")
        count: Number of videos to fetch (default: 50)
        min_views: Minimum view count filter (default: 100K)
        max_days: Maximum age in days (default: 10 days)
        max_followers: Maximum creator follower count (default: 50K for micro-influencers)

    Returns:
        Formatted string summary of TikTok search results
    """
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
            return (
                f"No TikTok videos found for '{keyword}' matching the criteria.\n\n"
                f"Filters applied:\n"
                f"- Minimum views: {min_views:,}\n"
                f"- Maximum age: {max_days} days\n"
                f"- Maximum creator followers: {max_followers:,}\n\n"
                f"Try lowering the filters or searching a different keyword."
            )

        # Calculate summary statistics
        total_views = sum(v.views for v in videos)
        total_engagement = sum(v.likes + v.comments + v.shares for v in videos)
        avg_engagement_rate = sum(v.engagement_rate for v in videos) / len(videos)

        # Format response
        response = f"Found {len(videos)} viral TikTok videos for '{keyword}'\n\n"
        response += f"**Summary Statistics:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Engagement: {total_engagement:,}\n"
        response += f"- Average Engagement Rate: {avg_engagement_rate:.2%}\n"
        response += f"- Average Video Length: {sum(v.length_sec for v in videos) / len(videos):.0f} seconds\n\n"

        # Show top 5 videos by engagement
        top_videos = sorted(videos, key=lambda v: v.engagement_score, reverse=True)[:5]
        response += f"**Top 5 Videos by Engagement:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. @{video.username} ({video.follower_count:,} followers)\n"
            response += f"   Views: {video.views:,} | Likes: {video.likes:,} | Comments: {video.comments:,}\n"
            response += f"   Caption: \"{video.caption[:80]}{'...' if len(video.caption) > 80 else ''}\"\n"
            response += f"   {video.url}\n\n"

        response += f"All {len(videos)} videos saved to database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully found {len(videos)} TikTok videos for '{keyword}'")
        return response

    except Exception as e:
        logger.error(f"Error in search_tiktok_tool: {e}", exc_info=True)
        return f"Error searching TikTok: {str(e)}"


# ============================================================================
# Tool 2: Search TikTok by Hashtag
# ============================================================================

async def search_tiktok_hashtag_tool(
    ctx: RunContext[AgentDependencies],
    hashtag: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """
    Search TikTok by hashtag and return viral videos.

    Use this when users want to:
    - Track specific TikTok hashtags
    - Find trending videos for a hashtag
    - Monitor hashtag performance

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hashtag: Hashtag to search (with or without #)
        count: Number of videos to fetch (default: 50)
        min_views: Minimum view count filter (default: 100K)
        max_days: Maximum age in days (default: 10 days)
        max_followers: Maximum creator follower count (default: 50K)

    Returns:
        Formatted string summary of hashtag search results
    """
    try:
        # Clean hashtag
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
            return (
                f"No TikTok videos found for #{clean_hashtag} matching the criteria.\n\n"
                f"Try lowering the filters or checking a different hashtag."
            )

        # Calculate statistics
        total_views = sum(v.views for v in videos)
        avg_length = sum(v.length_sec for v in videos) / len(videos)

        # Format response
        response = f"Found {len(videos)} viral videos for #{clean_hashtag}\n\n"
        response += f"**Hashtag Performance:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Videos Analyzed: {len(videos)}\n"
        response += f"- Average Length: {avg_length:.0f} seconds\n\n"

        # Show top 5
        top_videos = sorted(videos, key=lambda v: v.views, reverse=True)[:5]
        response += f"**Top 5 Performing Videos:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. @{video.username} - {video.views:,} views\n"
            response += f"   Engagement: {video.likes:,} likes | {video.comments:,} comments | {video.shares:,} shares\n"
            response += f"   {video.url}\n\n"

        response += f"All videos saved to database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully found {len(videos)} videos for #{clean_hashtag}")
        return response

    except Exception as e:
        logger.error(f"Error in search_tiktok_hashtag_tool: {e}", exc_info=True)
        return f"Error searching TikTok hashtag: {str(e)}"


# ============================================================================
# Tool 3: Scrape TikTok User
# ============================================================================

async def scrape_tiktok_user_tool(
    ctx: RunContext[AgentDependencies],
    username: str,
    count: int = 50
) -> str:
    """
    Scrape posts from a TikTok user/creator account.

    Use this when users want to:
    - Analyze a specific TikTok creator
    - Track competitor content
    - Study successful TikTok accounts

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        username: TikTok username (with or without @)
        count: Number of posts to fetch (default: 50)

    Returns:
        Formatted string summary of user's content
    """
    try:
        # Clean username
        clean_username = username.lstrip('@')
        logger.info(f"Scraping TikTok user: @{clean_username}")

        videos = await ctx.deps.tiktok.scrape_user(
            username=clean_username,
            project=ctx.deps.project_name,
            count=count,
            save_to_db=True
        )

        if not videos:
            return (
                f"No videos found for @{clean_username}.\n\n"
                f"Please check:\n"
                f"- Username is correct\n"
                f"- Account is public\n"
                f"- Account has posted videos"
            )

        # Calculate account statistics
        total_views = sum(v.views for v in videos)
        avg_views = total_views / len(videos) if videos else 0
        median_views = sorted([v.views for v in videos])[len(videos) // 2] if videos else 0
        max_views = max(v.views for v in videos) if videos else 0

        follower_count = videos[0].follower_count if videos else 0

        # Format response
        response = f"Scraped {len(videos)} videos from @{clean_username}\n\n"
        response += f"**Account Statistics:**\n"
        response += f"- Followers: {follower_count:,}\n"
        response += f"- Videos Scraped: {len(videos)}\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Average Views: {avg_views:,.0f}\n"
        response += f"- Median Views: {median_views:,}\n"
        response += f"- Best Performance: {max_views:,} views\n\n"

        # Show top 5 videos
        top_videos = sorted(videos, key=lambda v: v.views, reverse=True)[:5]
        response += f"**Top 5 Videos by Views:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. {video.views:,} views\n"
            response += f"   Likes: {video.likes:,} | Comments: {video.comments:,}\n"
            response += f"   Caption: \"{video.caption[:60]}{'...' if len(video.caption) > 60 else ''}\"\n"
            response += f"   {video.url}\n\n"

        response += f"All videos saved to database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully scraped {len(videos)} videos from @{clean_username}")
        return response

    except Exception as e:
        logger.error(f"Error in scrape_tiktok_user_tool: {e}", exc_info=True)
        return f"Error scraping TikTok user: {str(e)}"


# ============================================================================
# Tool 4: Analyze Single TikTok Video
# ============================================================================

async def analyze_tiktok_video_tool(
    ctx: RunContext[AgentDependencies],
    url: str
) -> str:
    """
    Analyze a single TikTok video from URL.

    Use this when users want to:
    - Analyze a specific TikTok video
    - Get insights on a competitor's viral video
    - Study successful TikTok content

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        url: TikTok video URL

    Returns:
        Formatted string with video analysis
    """
    try:
        logger.info(f"Analyzing TikTok video: {url}")

        video = await ctx.deps.tiktok.fetch_video_by_url(
            url=url,
            project=ctx.deps.project_name,
            save_to_db=True
        )

        if not video:
            return (
                f"Failed to fetch TikTok video from URL: {url}\n\n"
                f"Please check:\n"
                f"- URL is valid and accessible\n"
                f"- Video is public\n"
                f"- URL format is correct (e.g., https://www.tiktok.com/@user/video/ID)"
            )

        # Calculate metrics
        engagement_rate = video.engagement_rate
        engagement_score = video.engagement_score

        # Format response
        response = f"**TikTok Video Analysis**\n\n"
        response += f"**Creator:** @{video.username}\n"
        response += f"- Followers: {video.follower_count:,}\n"
        response += f"- Verified: {'Yes' if video.is_verified else 'No'}\n\n"

        response += f"**Video Metrics:**\n"
        response += f"- Views: {video.views:,}\n"
        response += f"- Likes: {video.likes:,}\n"
        response += f"- Comments: {video.comments:,}\n"
        response += f"- Shares: {video.shares:,}\n"
        response += f"- Engagement Rate: {engagement_rate:.2%}\n"
        response += f"- Engagement Score: {engagement_score:,.0f}\n"
        response += f"- Length: {video.length_sec} seconds\n\n"

        response += f"**Caption:**\n\"{video.caption}\"\n\n"

        response += f"**Analysis:**\n"
        if engagement_rate > 0.10:
            response += "- Exceptional engagement! This video resonated strongly with viewers.\n"
        elif engagement_rate > 0.05:
            response += "- Strong engagement. This video performed well above average.\n"
        elif engagement_rate > 0.02:
            response += "- Good engagement. Solid performance for this creator.\n"
        else:
            response += "- Lower engagement. May indicate topic mismatch or timing issues.\n"

        response += f"\nVideo saved to database for project '{ctx.deps.project_name}'.\n"
        response += f"URL: {video.url}"

        logger.info(f"Successfully analyzed TikTok video: {video.id}")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_tiktok_video_tool: {e}", exc_info=True)
        return f"Error analyzing TikTok video: {str(e)}"


# ============================================================================
# Tool 5: Batch Analyze TikTok Videos
# ============================================================================

async def analyze_tiktok_batch_tool(
    ctx: RunContext[AgentDependencies],
    urls: List[str]
) -> str:
    """
    Batch analyze multiple TikTok videos from URLs.

    Use this when users want to:
    - Analyze multiple TikTok videos at once
    - Compare performance across videos
    - Bulk import viral TikTok content

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        urls: List of TikTok video URLs

    Returns:
        Formatted string with batch analysis summary
    """
    try:
        logger.info(f"Batch analyzing {len(urls)} TikTok videos")

        videos = await ctx.deps.tiktok.fetch_videos_by_urls(
            urls=urls,
            project=ctx.deps.project_name,
            save_to_db=True
        )

        if not videos:
            return (
                f"No videos could be fetched from the provided URLs.\n\n"
                f"Attempted to fetch {len(urls)} videos but all failed.\n"
                f"Please check that the URLs are valid and videos are public."
            )

        # Calculate batch statistics
        total_views = sum(v.views for v in videos)
        avg_views = total_views / len(videos)
        avg_engagement_rate = sum(v.engagement_rate for v in videos) / len(videos)

        # Format response
        response = f"**Batch Analysis Complete**\n\n"
        response += f"- URLs Provided: {len(urls)}\n"
        response += f"- Videos Fetched: {len(videos)}\n"
        response += f"- Failed: {len(urls) - len(videos)}\n\n"

        response += f"**Aggregate Metrics:**\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Average Views: {avg_views:,.0f}\n"
        response += f"- Average Engagement Rate: {avg_engagement_rate:.2%}\n\n"

        # Show all fetched videos
        response += f"**Videos Analyzed:**\n\n"

        for i, video in enumerate(videos, 1):
            response += f"{i}. @{video.username} - {video.views:,} views\n"
            response += f"   Engagement: {video.likes:,} likes | ER: {video.engagement_rate:.2%}\n"
            response += f"   {video.url}\n\n"

        response += f"All {len(videos)} videos saved to database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully batch analyzed {len(videos)}/{len(urls)} TikTok videos")
        return response

    except Exception as e:
        logger.error(f"Error in analyze_tiktok_batch_tool: {e}", exc_info=True)
        return f"Error in batch analysis: {str(e)}"


# ============================================================================
# Export all tools
# ============================================================================

__all__ = [
    'search_tiktok_tool',
    'search_tiktok_hashtag_tool',
    'scrape_tiktok_user_tool',
    'analyze_tiktok_video_tool',
    'analyze_tiktok_batch_tool'
]
