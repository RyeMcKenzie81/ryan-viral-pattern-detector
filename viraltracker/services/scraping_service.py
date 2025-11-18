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
        """Initialize scraping service with Twitter scraper"""
        self.scraper = TwitterScraper()
        logger.info("ScrapingService initialized")

    async def search_twitter(
        self,
        keyword: str,
        project: str,
        hours_back: int = 24,
        max_results: int = 100,
        min_likes: int = 0,
        min_views: int = 0
    ) -> List[Tweet]:
        """
        Search Twitter by keyword and save results to database.

        Args:
            keyword: Search keyword or hashtag
            project: Project slug to associate tweets with
            hours_back: Hours of historical data to search (default: 24)
            max_results: Maximum tweets to scrape (default: 100)
            min_likes: Minimum like count filter (default: 0)
            min_views: Minimum view count filter (default: 0)

        Returns:
            List of Tweet models that were scraped and saved

        Raises:
            ValueError: If project not found or scraping fails
        """
        logger.info(
            f"Searching Twitter for '{keyword}' (project: {project}, "
            f"hours_back: {hours_back}, max_results: {max_results})"
        )

        try:
            # Run the scrape (this saves to database automatically)
            scrape_result = self.scraper.scrape_search(
                search_terms=[keyword],
                project=project,
                max_tweets=max_results,
                min_likes=min_likes if min_likes > 0 else None,
                days_back=hours_back // 24 if hours_back >= 24 else None,
                sort="Latest",
                language="en"
            )

            # Convert scrape results to Tweet models
            tweets = []
            for result in scrape_result.get('results', []):
                # Extract tweet data from scrape result
                tweet = Tweet(
                    id=result.get('tweet_id', ''),
                    text=result.get('text', ''),
                    view_count=result.get('views', 0),
                    like_count=result.get('likes', 0),
                    reply_count=result.get('replies', 0),
                    retweet_count=result.get('retweets', 0),
                    created_at=result.get('created_at', datetime.now()),
                    author_username=result.get('author_handle', 'unknown'),
                    author_followers=result.get('author_followers', 0),
                    url=result.get('url', f"https://twitter.com/i/status/{result.get('tweet_id', '')}"),
                    media_type=result.get('media_type'),
                    is_verified=result.get('is_verified', False)
                )
                tweets.append(tweet)

            logger.info(f"Successfully scraped {len(tweets)} tweets for keyword '{keyword}'")
            return tweets

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
