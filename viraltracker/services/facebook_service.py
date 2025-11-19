"""
FacebookService - Service layer for Facebook Ads operations.

Provides async interfaces for Facebook Ads scraping and analysis:
- Search Facebook Ad Library by URL
- Scrape ads from specific Facebook pages
- Filter by active status, date ranges, and countries

Wraps FacebookAdsScraper with clean service layer abstraction.
"""

import logging
import asyncio
import json
from typing import List, Optional
from datetime import datetime

from ..scrapers.facebook_ads import FacebookAdsScraper
from .models import FacebookAd

logger = logging.getLogger(__name__)


class FacebookService:
    """
    Service for Facebook Ads operations via agent.

    Provides async wrappers around FacebookAdsScraper functionality.
    Handles scraping, filtering, and database operations.
    """

    def __init__(self):
        """Initialize Facebook service."""
        self.scraper = None  # Lazy initialization
        logger.info("FacebookService initialized")

    def _get_scraper(self) -> FacebookAdsScraper:
        """Get or create FacebookAdsScraper instance (lazy initialization)."""
        if self.scraper is None:
            self.scraper = FacebookAdsScraper()
        return self.scraper

    async def search_ads(
        self,
        search_url: str,
        project: str,
        count: Optional[int] = None,
        period: str = "",
        scrape_details: bool = False,
        save_to_db: bool = True
    ) -> List[FacebookAd]:
        """
        Search Facebook Ad Library by URL.

        Args:
            search_url: Facebook Ad Library search URL
            project: Project slug for database linking
            count: Max number of ads to scrape (None = all available)
            period: Date range filter (last24h, last7d, last14d, last30d, or "" for all)
            scrape_details: Enable to scrape EU transparency details
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of FacebookAd models
        """
        # Run scraper in thread pool (blocking I/O)
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        # search_ad_library returns DataFrame
        df = await loop.run_in_executor(
            None,
            lambda: scraper.search_ad_library(
                search_url=search_url,
                count=count,
                scrape_details=scrape_details,
                period=period
            )
        )

        if len(df) == 0:
            return []

        # Note: Facebook scraper doesn't save to DB automatically like YouTube/TikTok
        # We would need to implement database saving here if needed in the future
        # For now, just convert to FacebookAd models

        # Convert to FacebookAd models
        ads = []
        for _, row in df.iterrows():
            try:
                # Parse spend if present
                spend = None
                if row.get('spend'):
                    try:
                        spend = float(row['spend'])
                    except (ValueError, TypeError):
                        pass

                ad = FacebookAd(
                    id=str(row.get('ad_id', '')),
                    ad_archive_id=str(row.get('ad_archive_id', '')),
                    url=None,  # Not provided by scraper
                    page_id=row.get('page_id'),
                    page_name=row.get('page_name', ''),
                    is_active=bool(row.get('is_active', False)),
                    start_date=row.get('start_date'),
                    end_date=row.get('end_date'),
                    currency=row.get('currency'),
                    spend=spend,
                    impressions=row.get('impressions'),
                    reach_estimate=row.get('reach_estimate'),
                    snapshot=row.get('snapshot') if isinstance(row.get('snapshot'), str) else json.dumps(row.get('snapshot', {})),
                    categories=row.get('categories') if isinstance(row.get('categories'), str) else json.dumps(row.get('categories', [])),
                    publisher_platform=row.get('publisher_platform') if isinstance(row.get('publisher_platform'), str) else json.dumps(row.get('publisher_platform', [])),
                    political_countries=row.get('political_countries') if isinstance(row.get('political_countries'), str) else json.dumps(row.get('political_countries', [])),
                    entity_type=row.get('entity_type')
                )
                ads.append(ad)
            except Exception as e:
                logger.warning(f"Failed to convert row to FacebookAd: {e}")
                continue

        logger.info(f"Converted {len(ads)} Facebook ads to models")
        return ads

    async def scrape_page_ads(
        self,
        page_url: str,
        project: str,
        count: Optional[int] = None,
        active_status: str = "all",
        country_code: str = "ALL",
        scrape_details: bool = False,
        save_to_db: bool = True
    ) -> List[FacebookAd]:
        """
        Scrape all ads run by a Facebook page.

        Args:
            page_url: Facebook page URL
            project: Project slug for database linking
            count: Max number of ads to scrape (None = all available)
            active_status: Filter by status (all, active, inactive)
            country_code: 2-letter ISO country code or "ALL"
            scrape_details: Enable to scrape EU transparency details
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of FacebookAd models
        """
        # Run scraper in thread pool (blocking I/O)
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        # scrape_page_ads returns DataFrame
        df = await loop.run_in_executor(
            None,
            lambda: scraper.scrape_page_ads(
                page_url=page_url,
                count=count,
                active_status=active_status,
                country_code=country_code,
                scrape_details=scrape_details
            )
        )

        if len(df) == 0:
            return []

        # Convert to FacebookAd models
        ads = []
        for _, row in df.iterrows():
            try:
                # Parse spend if present
                spend = None
                if row.get('spend'):
                    try:
                        spend = float(row['spend'])
                    except (ValueError, TypeError):
                        pass

                ad = FacebookAd(
                    id=str(row.get('ad_id', '')),
                    ad_archive_id=str(row.get('ad_archive_id', '')),
                    url=None,  # Not provided by scraper
                    page_id=row.get('page_id'),
                    page_name=row.get('page_name', ''),
                    is_active=bool(row.get('is_active', False)),
                    start_date=row.get('start_date'),
                    end_date=row.get('end_date'),
                    currency=row.get('currency'),
                    spend=spend,
                    impressions=row.get('impressions'),
                    reach_estimate=row.get('reach_estimate'),
                    snapshot=row.get('snapshot') if isinstance(row.get('snapshot'), str) else json.dumps(row.get('snapshot', {})),
                    categories=row.get('categories') if isinstance(row.get('categories'), str) else json.dumps(row.get('categories', [])),
                    publisher_platform=row.get('publisher_platform') if isinstance(row.get('publisher_platform'), str) else json.dumps(row.get('publisher_platform', [])),
                    political_countries=row.get('political_countries') if isinstance(row.get('political_countries'), str) else json.dumps(row.get('political_countries', [])),
                    entity_type=row.get('entity_type')
                )
                ads.append(ad)
            except Exception as e:
                logger.warning(f"Failed to convert row to FacebookAd: {e}")
                continue

        logger.info(f"Converted {len(ads)} Facebook ads from page")
        return ads
