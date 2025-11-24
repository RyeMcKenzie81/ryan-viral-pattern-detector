"""TikTok Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import TikTok-specific tools
from ..tools_registered import (
    search_tiktok_tool,
    search_tiktok_hashtag_tool,
    scrape_tiktok_user_tool,
    analyze_tiktok_video_tool,
    analyze_tiktok_batch_tool
)

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

# Register tools
tiktok_agent.tool(search_tiktok_tool)
tiktok_agent.tool(search_tiktok_hashtag_tool)
tiktok_agent.tool(scrape_tiktok_user_tool)
tiktok_agent.tool(analyze_tiktok_video_tool)
tiktok_agent.tool(analyze_tiktok_batch_tool)

logger.info("TikTok Agent initialized with 5 tools")
