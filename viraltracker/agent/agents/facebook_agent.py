"""Facebook Platform Specialist Agent"""
import logging
from typing import Optional
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

from ...core.config import Config

# Create Facebook specialist agent
facebook_agent = Agent(
    model=Config.get_model("facebook"),
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

# ============================================================================
# Facebook Tools - Migrated from @tool_registry to @agent.tool pattern
# ============================================================================

@facebook_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Find competitor ads by keyword',
            'Research ad strategies for topics',
            'Monitor ad spend trends',
            'Analyze advertising campaigns'
        ],
        'examples': [
            'Search Facebook ads for "productivity"',
            'Find competitor ads in Ad Library',
            'Show me ads about fitness',
            'Search Facebook Ad Library'
        ]
    }
)
async def search_facebook_ads(
    ctx: RunContext[AgentDependencies],
    search_url: str,
    count: Optional[int] = 50,
    period: str = "last30d"
) -> str:
    """
    Search Facebook Ad Library by URL.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        search_url: Facebook Ad Library search URL
        count: Number of ads to retrieve (default: 50)
        period: Time period for ads (default: 'last30d')

    Returns:
        Summary string of found Facebook ads
    """
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
        logger.error(f"Error in search_facebook_ads: {e}", exc_info=True)
        return f"Error searching Facebook ads: {str(e)}"


@facebook_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Analyze competitor ad campaigns',
            'Study brand advertising strategies',
            'Track page advertising history',
            'Monitor campaign performance'
        ],
        'examples': [
            'Scrape ads from Facebook page [URL]',
            'Get all ads from this page',
            'Analyze Facebook page advertising',
            'Show me ads run by [brand]'
        ]
    }
)
async def scrape_facebook_page_ads(
    ctx: RunContext[AgentDependencies],
    page_url: str,
    count: Optional[int] = 50,
    active_status: str = "all"
) -> str:
    """
    Scrape all ads run by a Facebook page.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        page_url: Facebook page URL
        count: Number of ads to retrieve (default: 50)
        active_status: Filter by status - 'all', 'active', or 'inactive' (default: 'all')

    Returns:
        Summary string of scraped Facebook page ads
    """
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
        logger.error(f"Error in scrape_facebook_page_ads: {e}", exc_info=True)
        return f"Error scraping Facebook page ads: {str(e)}"


logger.info("Facebook Agent initialized with 2 tools")
