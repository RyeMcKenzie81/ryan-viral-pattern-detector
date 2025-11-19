"""
Phase 1.7 Agent Tools - YouTube & Facebook Platform Support

Adds 3 new tools for YouTube and Facebook platform coverage:
1. search_youtube_tool - Search YouTube by keyword
2. search_facebook_ads_tool - Search Facebook Ad Library
3. scrape_facebook_page_ads_tool - Scrape ads from Facebook page

Expands agent capabilities to include video and advertising platforms.
"""

import logging
from typing import Optional
from pydantic_ai import RunContext

from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Search YouTube by Keyword
# ============================================================================

async def search_youtube_tool(
    ctx: RunContext[AgentDependencies],
    keywords: str,  # Comma-separated search terms
    max_shorts: int = 100,
    max_videos: int = 0,
    days_back: Optional[int] = None,
    min_views: Optional[int] = 100000,
    max_subscribers: Optional[int] = 50000
) -> str:
    """
    Search YouTube for viral videos by keyword.

    Use this when users want to:
    - Find viral YouTube Shorts about a topic
    - Discover YouTube content by keyword
    - Research what's trending on YouTube

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        keywords: Comma-separated search terms (e.g., "productivity,focus,study tips")
        max_shorts: Maximum Shorts per term (default: 100)
        max_videos: Maximum regular videos per term (default: 0)
        days_back: Only videos from last N days (optional)
        min_views: Minimum view count (default: 100K for viral content)
        max_subscribers: Maximum channel subscribers (default: 50K for micro-influencers)

    Returns:
        Formatted string summary of YouTube search results
    """
    try:
        # Parse keywords
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
            return (
                f"No YouTube videos found for keywords: {keywords}\n\n"
                f"Filters applied:\n"
                f"- Minimum views: {min_views:,}\n"
                f"- Maximum subscribers: {max_subscribers:,}\n"
                + (f"- Last {days_back} days\n" if days_back else "")
                + "\nTry lowering the filters or searching different keywords."
            )

        # Calculate summary statistics
        total_views = sum(v.views for v in videos)
        total_engagement = sum(v.likes + v.comments for v in videos)
        avg_engagement_rate = sum(v.engagement_rate for v in videos) / len(videos)

        # Count by video type
        shorts_count = sum(1 for v in videos if v.video_type == 'short')
        videos_count = sum(1 for v in videos if v.video_type == 'video')

        # Format response
        response = f"Found {len(videos)} viral YouTube videos for keywords: {keywords}\n\n"
        response += f"**Summary Statistics:**\n"
        response += f"- Total Videos: {len(videos)} ({shorts_count} Shorts, {videos_count} regular videos)\n"
        response += f"- Total Views: {total_views:,}\n"
        response += f"- Total Engagement: {total_engagement:,}\n"
        response += f"- Average Engagement Rate: {avg_engagement_rate:.2%}\n"
        response += f"- Average Video Length: {sum(v.length_sec for v in videos) / len(videos):.0f} seconds\n\n"

        # Show top 5 videos by engagement
        top_videos = sorted(videos, key=lambda v: v.engagement_score, reverse=True)[:5]
        response += f"**Top 5 Videos by Engagement:**\n\n"

        for i, video in enumerate(top_videos, 1):
            response += f"{i}. {video.channel} ({video.subscriber_count:,} subscribers)\n"
            response += f"   Type: {video.video_type.upper()} | Views: {video.views:,} | Likes: {video.likes:,} | Comments: {video.comments:,}\n"
            response += f"   Title: \"{video.title[:80]}{'...' if len(video.title) > 80 else ''}\"\n"
            response += f"   {video.url}\n\n"

        response += f"All {len(videos)} videos saved to database for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully found {len(videos)} YouTube videos")
        return response

    except Exception as e:
        logger.error(f"Error in search_youtube_tool: {e}", exc_info=True)
        return f"Error searching YouTube: {str(e)}"


# ============================================================================
# Tool 2: Search Facebook Ad Library
# ============================================================================

async def search_facebook_ads_tool(
    ctx: RunContext[AgentDependencies],
    search_url: str,  # Facebook Ad Library search URL
    count: Optional[int] = 50,
    period: str = "last30d"
) -> str:
    """
    Search Facebook Ad Library by URL.

    Use this when users want to:
    - Find competitor ads by keyword
    - Research ad strategies for specific topics
    - Monitor ad spend trends

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        search_url: Facebook Ad Library search URL
        count: Maximum ads to scrape (default: 50)
        period: Date range (last24h, last7d, last14d, last30d, or "" for all)

    Returns:
        Formatted string summary of Facebook ads
    """
    try:
        logger.info(f"Searching Facebook Ad Library: {search_url}")

        ads = await ctx.deps.facebook.search_ads(
            search_url=search_url,
            project=ctx.deps.project_name,
            count=count,
            period=period,
            save_to_db=True
        )

        if not ads:
            return (
                f"No Facebook ads found for the provided search URL.\n\n"
                f"Please verify:\n"
                f"- URL is from Facebook Ad Library\n"
                f"- Search parameters are correct\n"
                f"- Ads exist for the specified criteria"
            )

        # Calculate statistics
        active_ads = sum(1 for ad in ads if ad.is_active)
        inactive_ads = len(ads) - active_ads

        # Calculate spend statistics (only for ads with spend data)
        ads_with_spend = [ad for ad in ads if ad.spend is not None]
        total_spend = sum(ad.spend for ad in ads_with_spend) if ads_with_spend else 0
        avg_spend = total_spend / len(ads_with_spend) if ads_with_spend else 0

        # Calculate reach statistics
        ads_with_reach = [ad for ad in ads if ad.reach_estimate is not None]
        total_reach = sum(ad.reach_estimate for ad in ads_with_reach) if ads_with_reach else 0

        # Format response
        response = f"Found {len(ads)} Facebook ads\n\n"
        response += f"**Ad Library Summary:**\n"
        response += f"- Total Ads: {len(ads)}\n"
        response += f"- Active: {active_ads} | Inactive: {inactive_ads}\n"
        response += f"- Unique Pages: {len(set(ad.page_name for ad in ads))}\n"

        if ads_with_spend:
            currency = ads_with_spend[0].currency or "USD"
            response += f"- Total Spend: {currency} {total_spend:,.2f}\n"
            response += f"- Average Spend: {currency} {avg_spend:,.2f}\n"

        if ads_with_reach:
            response += f"- Total Estimated Reach: {total_reach:,}\n\n"
        else:
            response += "\n"

        # Show top 5 ads by engagement score (or spend if available)
        if ads_with_spend:
            top_ads = sorted(ads_with_spend, key=lambda a: a.spend, reverse=True)[:5]
            response += f"**Top 5 Ads by Spend:**\n\n"
            metric_key = "spend"
        else:
            top_ads = sorted(ads, key=lambda a: a.engagement_score, reverse=True)[:5]
            response += f"**Top 5 Ads by Engagement:**\n\n"
            metric_key = "engagement"

        for i, ad in enumerate(top_ads, 1):
            response += f"{i}. {ad.page_name}\n"
            response += f"   Status: {'Active' if ad.is_active else 'Inactive'}"

            if ad.spend and ad.currency:
                response += f" | Spend: {ad.currency} {ad.spend:,.2f}"
            if ad.reach_estimate:
                response += f" | Reach: {ad.reach_estimate:,}"
            if ad.impressions:
                response += f" | Impressions: {ad.impressions:,}"

            response += "\n"

            if ad.start_date:
                response += f"   Started: {ad.start_date.strftime('%Y-%m-%d')}"
                if ad.end_date:
                    response += f" | Ended: {ad.end_date.strftime('%Y-%m-%d')}"
                elif ad.is_active:
                    response += " | Still Running"
                response += "\n"

            response += f"   Archive ID: {ad.ad_archive_id}\n\n"

        response += f"All {len(ads)} ads analyzed for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully found {len(ads)} Facebook ads")
        return response

    except Exception as e:
        logger.error(f"Error in search_facebook_ads_tool: {e}", exc_info=True)
        return f"Error searching Facebook ads: {str(e)}"


# ============================================================================
# Tool 3: Scrape Facebook Page Ads
# ============================================================================

async def scrape_facebook_page_ads_tool(
    ctx: RunContext[AgentDependencies],
    page_url: str,  # Facebook page URL
    count: Optional[int] = 50,
    active_status: str = "all"
) -> str:
    """
    Scrape all ads run by a Facebook page.

    Use this when users want to:
    - Analyze competitor ad campaigns
    - Study brand advertising strategies
    - Track page advertising history

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        page_url: Facebook page URL
        count: Maximum ads to scrape (default: 50)
        active_status: Filter by status - "all", "active", or "inactive"

    Returns:
        Formatted string summary of page advertising strategy
    """
    try:
        logger.info(f"Scraping ads from Facebook page: {page_url}")

        ads = await ctx.deps.facebook.scrape_page_ads(
            page_url=page_url,
            project=ctx.deps.project_name,
            count=count,
            active_status=active_status,
            save_to_db=True
        )

        if not ads:
            return (
                f"No ads found for the Facebook page.\n\n"
                f"Please verify:\n"
                f"- Page URL is correct\n"
                f"- Page has run ads before\n"
                f"- Page is not private or restricted"
            )

        # Get page name from first ad
        page_name = ads[0].page_name if ads else "Unknown Page"

        # Calculate statistics
        active_ads = sum(1 for ad in ads if ad.is_active)
        inactive_ads = len(ads) - active_ads

        # Calculate spend statistics
        ads_with_spend = [ad for ad in ads if ad.spend is not None]
        total_spend = sum(ad.spend for ad in ads_with_spend) if ads_with_spend else 0
        avg_spend = total_spend / len(ads_with_spend) if ads_with_spend else 0

        # Calculate reach statistics
        ads_with_reach = [ad for ad in ads if ad.reach_estimate is not None]
        total_reach = sum(ad.reach_estimate for ad in ads_with_reach) if ads_with_reach else 0
        avg_reach = total_reach / len(ads_with_reach) if ads_with_reach else 0

        # Calculate duration statistics
        ads_with_duration = [ad for ad in ads if ad.days_active is not None]
        avg_duration = sum(ad.days_active for ad in ads_with_duration) / len(ads_with_duration) if ads_with_duration else 0

        # Format response
        response = f"**{page_name} - Advertising Analysis**\n\n"
        response += f"Scraped {len(ads)} ads from this page\n\n"

        response += f"**Campaign Overview:**\n"
        response += f"- Total Ads: {len(ads)}\n"
        response += f"- Currently Active: {active_ads}\n"
        response += f"- Inactive/Ended: {inactive_ads}\n"

        if ads_with_spend:
            currency = ads_with_spend[0].currency or "USD"
            response += f"- Total Ad Spend: {currency} {total_spend:,.2f}\n"
            response += f"- Average Spend per Ad: {currency} {avg_spend:,.2f}\n"

        if ads_with_reach:
            response += f"- Total Estimated Reach: {total_reach:,}\n"
            response += f"- Average Reach per Ad: {avg_reach:,.0f}\n"

        if ads_with_duration:
            response += f"- Average Campaign Duration: {avg_duration:.0f} days\n"

        response += "\n"

        # Show top 5 active ads if available, otherwise top 5 by spend
        active_only = [ad for ad in ads if ad.is_active]
        if active_only and len(active_only) >= 3:
            top_ads = sorted(active_only, key=lambda a: a.engagement_score, reverse=True)[:5]
            response += f"**Top {min(5, len(top_ads))} Currently Active Ads:**\n\n"
        elif ads_with_spend:
            top_ads = sorted(ads_with_spend, key=lambda a: a.spend, reverse=True)[:5]
            response += f"**Top {min(5, len(top_ads))} Ads by Spend:**\n\n"
        else:
            top_ads = sorted(ads, key=lambda a: a.engagement_score, reverse=True)[:5]
            response += f"**Top {min(5, len(top_ads))} Ads:**\n\n"

        for i, ad in enumerate(top_ads, 1):
            response += f"{i}. {'Active' if ad.is_active else 'Inactive'} Ad"

            if ad.spend and ad.currency:
                response += f" | Spend: {ad.currency} {ad.spend:,.2f}"
            if ad.reach_estimate:
                response += f" | Reach: {ad.reach_estimate:,}"

            response += "\n"

            if ad.start_date:
                response += f"   Started: {ad.start_date.strftime('%Y-%m-%d')}"
                if ad.end_date:
                    response += f" - {ad.end_date.strftime('%Y-%m-%d')}"
                    if ad.days_active:
                        response += f" ({ad.days_active} days)"
                elif ad.is_active:
                    response += " (still running)"
                response += "\n"

            response += f"   Archive ID: {ad.ad_archive_id}\n\n"

        response += f"**Insights:**\n"
        if active_ads > 0:
            response += f"- Page is actively advertising with {active_ads} live campaigns\n"
        else:
            response += f"- Page currently has no active ads\n"

        if ads_with_spend and avg_spend > 0:
            response += f"- Average investment per campaign: {currency} {avg_spend:,.2f}\n"

        if avg_duration > 0:
            response += f"- Typical campaign runs for {avg_duration:.0f} days\n"

        response += f"\nAll {len(ads)} ads analyzed for project '{ctx.deps.project_name}'."

        logger.info(f"Successfully scraped {len(ads)} ads from page")
        return response

    except Exception as e:
        logger.error(f"Error in scrape_facebook_page_ads_tool: {e}", exc_info=True)
        return f"Error scraping Facebook page ads: {str(e)}"


# ============================================================================
# Export all tools
# ============================================================================

__all__ = [
    'search_youtube_tool',
    'search_facebook_ads_tool',
    'scrape_facebook_page_ads_tool'
]
