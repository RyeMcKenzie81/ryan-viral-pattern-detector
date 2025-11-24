"""Facebook Platform Specialist Agent"""
import logging
from pydantic_ai import Agent
from ..dependencies import AgentDependencies

# Import Facebook-specific tools
from ..tools_registered import (
    search_facebook_ads_tool,
    scrape_facebook_page_ads_tool
)

logger = logging.getLogger(__name__)

# Create Facebook specialist agent
facebook_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Facebook platform specialist agent.

Your ONLY responsibility is Facebook Ad Library data operations:
- Searching Facebook Ad Library by URL for competitor ads
- Scraping all ads run by specific Facebook pages
- Analyzing ad creative and copy patterns

**Important:**
- Save all results to result_cache.last_facebook_query
- Provide clear summaries of ad performance and patterns
- Focus on identifying high-performing ad creative
- Include ad URLs and page information

**Available Services:**
- FacebookService: For Ad Library scraping and data collection

**Result Format:**
- Provide clear, structured responses with ad metrics
- Show top ads with engagement data
- Include ad URLs and advertiser information
- Save files to ~/Downloads/ for exports
"""
)

# Register tools
facebook_agent.tool(search_facebook_ads_tool)
facebook_agent.tool(scrape_facebook_page_ads_tool)

logger.info("Facebook Agent initialized with 2 tools")
