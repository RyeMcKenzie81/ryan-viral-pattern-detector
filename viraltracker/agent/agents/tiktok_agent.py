"""TikTok Platform Specialist Agent"""
import logging
from typing import List
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# Create TikTok specialist agent
tiktok_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the TikTok platform specialist agent.

Your ONLY responsibility is TikTok data operations:
- Searching TikTok by keyword for viral videos
- Searching TikTok by hashtag for trending content
- Scraping user accounts for all their posts
- Analyzing individual TikTok videos from URLs
- Batch analyzing multiple TikTok videos

**Important:**
- Save all results to result_cache.last_tiktok_query
- Provide clear summaries with view counts, likes, and engagement metrics
- Focus on identifying viral patterns and hooks
- Include video URLs for all content

**Available Services:**
- TikTokService: For scraping and data collection
- GeminiService: For AI-powered video analysis

**Result Format:**
- Provide clear, structured responses with engagement metrics
- Show top results with view counts, likes, shares, comments
- Include video URLs and creator information
- Save files to ~/Downloads/ for exports
"""
)


# ============================================================================
# TikTok Tools
# ============================================================================

@tiktok_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'TikTok',
        'rate_limit': '10/minute',
        'use_cases': [
            'Find viral TikTok videos by keyword',
            'Discover trending TikTok content',
            'Research what\'s popular on TikTok',
            'Scrape TikTok for content ideas'
        ],
        'examples': [
            'Search TikTok for \'morning routine\'',
            'Find viral videos about productivity',
            'Show me TikToks about fitness',
            'Search TikTok for #entrepreneur'
        ]
    }
)
async def search_tiktok(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """
    Search TikTok by keyword and return viral videos.

    Searches TikTok for content matching the specified keyword, filtering
    by view count, recency, and creator follower count to identify viral
    videos from emerging creators.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keyword: Search keyword or phrase
        count: Maximum number of videos to return (default: 50)
        min_views: Minimum view count filter (default: 100000)
        max_days: Maximum age of videos in days (default: 10)
        max_followers: Maximum follower count for creator (default: 50000)

    Returns:
        Summary with video count, total views, avg engagement, and top 5 videos
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
        logger.error(f"Error in search_tiktok: {e}", exc_info=True)
        return f"Error searching TikTok: {str(e)}"


@tiktok_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'TikTok',
        'rate_limit': '10/minute',
        'use_cases': [
            'Track specific TikTok hashtags',
            'Find trending videos for hashtags',
            'Monitor hashtag performance',
            'Discover hashtag content'
        ],
        'examples': [
            'Search TikTok hashtag #productivity',
            'Find videos for #smallbusiness',
            'Show me #fitness TikToks',
            'Track hashtag #entrepreneur'
        ]
    }
)
async def search_tiktok_hashtag(
    ctx: RunContext[AgentDependencies],
    hashtag: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str:
    """
    Search TikTok by hashtag and return viral videos.

    Searches TikTok for content using a specific hashtag, filtering
    by view count, recency, and creator follower count.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hashtag: Hashtag to search (with or without # prefix)
        count: Maximum number of videos to return (default: 50)
        min_views: Minimum view count filter (default: 100000)
        max_days: Maximum age of videos in days (default: 10)
        max_followers: Maximum follower count for creator (default: 50000)

    Returns:
        Summary with video count, total views, and top 5 videos
    """
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
        logger.error(f"Error in search_tiktok_hashtag: {e}", exc_info=True)
        return f"Error searching TikTok hashtag: {str(e)}"


@tiktok_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'TikTok',
        'rate_limit': '10/minute',
        'use_cases': [
            'Analyze specific TikTok creators',
            'Track competitor content strategy',
            'Study successful TikTok accounts',
            'Monitor influencer activity'
        ],
        'examples': [
            'Scrape posts from @creator',
            'Analyze TikTok user @username',
            'Get all videos from @influencer',
            'Track @competitor\'s TikToks'
        ]
    }
)
async def scrape_tiktok_user(
    ctx: RunContext[AgentDependencies],
    username: str,
    count: int = 50
) -> str:
    """
    Scrape all posts from a TikTok user/creator account.

    Fetches recent videos from a specific TikTok creator account
    and saves them to the database.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        username: TikTok username (with or without @ prefix)
        count: Maximum number of videos to scrape (default: 50)

    Returns:
        Summary with video count, total views, and average views
    """
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
        logger.error(f"Error in scrape_tiktok_user: {e}", exc_info=True)
        return f"Error scraping TikTok user: {str(e)}"


@tiktok_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'TikTok',
        'rate_limit': '15/minute',
        'use_cases': [
            'Analyze specific TikTok video performance',
            'Get insights on competitor videos',
            'Study successful TikTok content',
            'Evaluate video metrics'
        ],
        'examples': [
            'Analyze this TikTok video: [URL]',
            'Get insights on TikTok [URL]',
            'Analyze video performance for [URL]',
            'Show me metrics for this TikTok'
        ]
    }
)
async def analyze_tiktok_video(
    ctx: RunContext[AgentDependencies],
    url: str
) -> str:
    """
    Analyze a single TikTok video from URL.

    Fetches and analyzes a specific TikTok video, providing
    detailed metrics including views, likes, and engagement rate.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        url: Full TikTok video URL

    Returns:
        Analysis with creator info and video metrics
    """
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
        logger.error(f"Error in analyze_tiktok_video: {e}", exc_info=True)
        return f"Error analyzing TikTok video: {str(e)}"


@tiktok_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'TikTok',
        'rate_limit': '10/minute',
        'use_cases': [
            'Analyze multiple TikTok videos at once',
            'Compare performance across videos',
            'Bulk import viral TikTok content',
            'Aggregate video metrics'
        ],
        'examples': [
            'Analyze these TikTok videos: [URL1, URL2, URL3]',
            'Batch analyze TikToks',
            'Compare these video URLs',
            'Get metrics for multiple TikToks'
        ]
    }
)
async def analyze_tiktok_batch(
    ctx: RunContext[AgentDependencies],
    urls: List[str]
) -> str:
    """
    Batch analyze multiple TikTok videos from URLs.

    Fetches and analyzes multiple TikTok videos at once,
    providing aggregate statistics.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        urls: List of full TikTok video URLs

    Returns:
        Batch analysis summary with aggregate metrics
    """
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
        logger.error(f"Error in analyze_tiktok_batch: {e}", exc_info=True)
        return f"Error in batch analysis: {str(e)}"


logger.info("TikTok Agent initialized with 5 tools")
