"""YouTube Platform Specialist Agent"""
import logging
from typing import Optional
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

from ...core.config import Config

# Create YouTube specialist agent
youtube_agent = Agent(
    model=Config.get_model("youtube"),
    deps_type=AgentDependencies,
    system_prompt="""You are the YouTube platform specialist agent.

Your ONLY responsibility is YouTube data operations:
- Searching YouTube for viral videos and Shorts by keyword
- Finding trending content and creators
- Analyzing engagement patterns on YouTube

**Important:**
- Save all results to result_cache.last_youtube_query
- Provide clear summaries with view counts, likes, and engagement metrics
- Focus on identifying viral videos and Shorts
- Include video URLs for all content

**Available Services:**
- YouTubeService: For scraping and data collection

**Result Format:**
- Provide clear, structured responses with engagement metrics
- Show top results with view counts, likes, comments
- Include video URLs and channel information
- Save files to ~/Downloads/ for exports
"""
)


# ============================================================================
# YouTube Tools
# ============================================================================

@youtube_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'YouTube',
        'rate_limit': '10/minute',
        'use_cases': [
            'Find viral YouTube Shorts by topic',
            'Discover trending YouTube content',
            'Research what\'s performing on YouTube',
            'Scrape YouTube for content ideas'
        ],
        'examples': [
            'Search YouTube for productivity tips',
            'Find viral YouTube Shorts about fitness',
            'Show me trending videos on entrepreneurship',
            'Search YouTube for study tips'
        ]
    }
)
async def search_youtube(
    ctx: RunContext[AgentDependencies],
    keywords: str,
    max_shorts: int = 100,
    max_videos: int = 0,
    days_back: Optional[int] = None,
    min_views: Optional[int] = 100000,
    max_subscribers: Optional[int] = 50000
) -> str:
    """
    Search YouTube for viral videos and Shorts by keyword.

    Searches YouTube for content matching the specified keywords, focusing on
    viral videos and Shorts. Filters by view count, subscriber count, and recency
    to identify high-performing content from emerging creators.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keywords: Comma-separated search keywords (default: None)
        max_shorts: Maximum number of Shorts to return (default: 100)
        max_videos: Maximum number of regular videos to return (default: 0)
        days_back: Limit search to videos from last N days (default: None for all time)
        min_views: Minimum view count filter (default: 100000)
        max_subscribers: Maximum subscriber count for creator (default: 50000)

    Returns:
        Success message with video count and total views, or error message
    """
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
        logger.error(f"Error in search_youtube: {e}", exc_info=True)
        return f"Error searching YouTube: {str(e)}"


logger.info("YouTube Agent initialized with 1 tool")
