"""Twitter/X Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import Twitter-specific tools
from ..tools_registered import (
    search_twitter_tool,
    scrape_twitter_user_tool,
    get_top_tweets_tool,
    analyze_tweet_tool,
    export_tweets_tool
)

logger = logging.getLogger(__name__)

# Create Twitter specialist agent
twitter_agent = Agent(
    model="claude-sonnet-4",
    deps_type=AgentDependencies,
    system_prompt="""You are the Twitter/X platform specialist agent.

Your ONLY responsibility is Twitter/X data operations:
- Searching and scraping tweets by keyword
- Scraping specific user timelines
- Querying database for top tweets
- Analyzing individual tweets
- Exporting tweet results to CSV/JSON/Markdown files

**Important:**
- When you retrieve tweets, ALWAYS save them to result_cache.last_twitter_query
- When exporting, use the same parameters that were used in the query
- Support multi-keyword OR logic with comma-separated keywords (e.g., "btc,bitcoin")
- Always provide clear summaries of results

**Available Services:**
- TwitterService: For API scraping
- StatsService: For database queries
- GeminiService: For AI analysis

**Result Format:**
- Provide clear, structured responses with metrics
- Show top results with engagement stats
- Include URLs for all content
- Save files to ~/Downloads/ for exports
"""
)

# Register tools
twitter_agent.tool(search_twitter_tool)
twitter_agent.tool(scrape_twitter_user_tool)
twitter_agent.tool(get_top_tweets_tool)
twitter_agent.tool(analyze_tweet_tool)
twitter_agent.tool(export_tweets_tool)

logger.info("Twitter Agent initialized with 5 tools")
