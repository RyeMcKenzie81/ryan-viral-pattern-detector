"""
ScrapingService - Data access layer for Twitter scraping operations.

Provides async interface to Twitter scraping functionality for the agent.
Wraps TwitterScraper to provide clean service layer abstraction.
"""

import logging
from typing import List, Optional
from datetime import datetime

from ..scrapers.twitter import TwitterScraper
from .models import Tweet

logger = logging.getLogger(__name__)


class ScrapingService:
    """
    Data access service for Twitter scraping.

    Provides clean interface to scrape Twitter content by keyword
    and convert results to Tweet models for the agent.
    """

    def __init__(self):
        """Initialize scraping service (lazy scraper initialization)"""
        self.scraper = None  # Lazy initialization - only create when needed
        logger.info("ScrapingService initialized")

    def _get_scraper(self) -> TwitterScraper:
        """Get or create TwitterScraper instance (lazy initialization)."""
        if self.scraper is None:
            self.scraper = TwitterScraper()
        return self.scraper

    async def search_twitter(
        self,
        keyword: str,
        project: str,
        hours_back: int = 24,
        max_results: int = 50,
        min_likes: int = 0,
        min_views: int = 0
    ) -> tuple[List[Tweet], dict]:
        """
        Search Twitter by keyword and save results to database.

        Args:
            keyword: Search keyword or hashtag
            project: Project slug to associate tweets with
            hours_back: Hours of historical data to search (default: 24)
            max_results: Maximum tweets to scrape (default: 50, min: 50, max: 10000)
            min_likes: Minimum like count filter (default: 0)
            min_views: Minimum view count filter (default: 0)

        Returns:
            Tuple of (List of Tweet models, metadata dict with scrape stats)
            Metadata includes: tweets_count, skipped_count, requested_count

        Raises:
            ValueError: If project not found or scraping fails
        """
        logger.info(
            f"Searching Twitter for '{keyword}' (project: {project}, "
            f"hours_back: {hours_back}, max_results: {max_results})"
        )

        try:
            # Run the scrape (this saves to database automatically)
            scraper = self._get_scraper()
            scrape_result = scraper.scrape_search(
                search_terms=[keyword],
                project_slug=project,
                max_tweets=max_results,
                min_likes=min_likes if min_likes > 0 else None,
                days_back=hours_back // 24 if hours_back >= 24 else None,
                sort="Latest",
                language="en"
            )

            # scrape_search() returns stats and IDs, not tweet data
            tweets_count = scrape_result['tweets_count']
            skipped_count = scrape_result.get('skipped_count', 0)

            logger.info(f"Scrape completed: {tweets_count} tweets saved to database")
            if skipped_count > 0:
                logger.warning(f"Skipped {skipped_count} malformed tweets due to data quality issues from Apify")

            if tweets_count == 0:
                logger.warning(f"No tweets found for keyword '{keyword}'")
                return []

            # Import TwitterService to fetch tweets from database
            from .twitter_service import TwitterService
            twitter_service = TwitterService()

            # Fetch ONLY the tweets we just scraped by their IDs (not all historical tweets)
            post_ids = scrape_result.get('post_ids', [])
            if post_ids:
                tweets = await twitter_service.get_tweets_by_ids(
                    tweet_ids=post_ids,
                    project=project
                )
                logger.info(f"Successfully retrieved {len(tweets)} tweets for keyword '{keyword}' by ID")
            else:
                # Fallback: if post_ids not available, use short time window
                logger.warning("No post_ids in scrape_result, falling back to time-based query")
                tweets = await twitter_service.get_tweets(
                    project=project,
                    hours_back=0.1,  # ~6 minutes
                    min_views=min_views,
                    min_likes=min_likes
                )
                tweets = tweets[:scrape_result['tweets_count']]

            # Return tweets + metadata for agent to communicate results accurately
            metadata = {
                'tweets_count': tweets_count,
                'skipped_count': skipped_count,
                'requested_count': max_results,
                'run_id': scrape_result.get('apify_run_id'),
                'dataset_id': scrape_result.get('apify_dataset_id'),
                'keyword': keyword
            }
            return tweets, metadata

        except Exception as e:
            logger.error(f"Error scraping Twitter for '{keyword}': {e}", exc_info=True)
            raise ValueError(f"Failed to scrape Twitter: {str(e)}")

    async def get_scrape_stats(self, project: str, hours_back: int = 24) -> dict:
        """
        Get scraping statistics for a project.

        Args:
            project: Project slug
            hours_back: Hours to look back (default: 24)

        Returns:
            Dict with scraping statistics (total_tweets, avg_engagement, etc.)
        """
        # This would query the database for scraping statistics
        # For now, return empty stats
        logger.info(f"Getting scrape stats for project '{project}' (last {hours_back} hours)")

        return {
            "project": project,
            "hours_back": hours_back,
            "total_tweets": 0,
            "avg_engagement": 0.0
        }
