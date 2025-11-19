"""
Base scraper interface for all platforms
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class BaseScraper(ABC):
    """
    Abstract base class for platform scrapers

    All platform-specific scrapers (Instagram, TikTok, YouTube) must
    implement this interface.
    """

    def __init__(self, platform_config: Dict):
        """
        Initialize scraper with platform configuration

        Args:
            platform_config: Platform configuration from database
                {
                    'slug': 'instagram',
                    'name': 'Instagram Reels',
                    'scraper_type': 'apify',
                    'scraper_config': {...},
                    ...
                }
        """
        self.platform_config = platform_config
        self.platform_slug = platform_config['slug']
        self.platform_name = platform_config['name']
        self.scraper_type = platform_config.get('scraper_type')
        self.scraper_config = platform_config.get('scraper_config', {})

    @abstractmethod
    async def scrape_account(
        self,
        username: str,
        days_back: int = 120,
        post_type: str = 'all'
    ) -> List[Dict]:
        """
        Scrape posts from an account

        Args:
            username: Account username on the platform
            days_back: How many days back to scrape
            post_type: Type of posts to scrape (all, reels, videos, etc.)

        Returns:
            List of raw post dictionaries from the platform API

        Example:
            [
                {
                    'url': 'https://instagram.com/p/ABC123/',
                    'shortCode': 'ABC123',
                    'videoViewCount': 1000000,
                    'likesCount': 50000,
                    ...
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def normalize_post_data(self, raw_post: Dict) -> Dict:
        """
        Convert platform-specific data to standard format

        Args:
            raw_post: Raw post data from platform API

        Returns:
            Normalized post data in standard format:
            {
                'post_url': str,
                'post_id': str,
                'views': int,
                'likes': int,
                'comments': int,
                'caption': str,
                'posted_at': datetime,
                'length_sec': int,
                'platform_username': str,
            }
        """
        pass

    @abstractmethod
    def extract_platform_metrics(self, raw_post: Dict) -> Dict:
        """
        Extract platform-specific metrics

        Args:
            raw_post: Raw post data from platform API

        Returns:
            Platform-specific metrics in format:
            {
                'platform_slug': {
                    'metric1': value1,
                    'metric2': value2,
                    ...
                }
            }

        Example for Instagram:
            {
                'instagram': {
                    'reel_template_used': False,
                    'music_id': '12345',
                    'filter_name': 'Clarendon'
                }
            }

        Example for TikTok:
            {
                'tiktok': {
                    'sound_id': '67890',
                    'sound_name': 'Trending Audio',
                    'effects_used': ['Green Screen', 'Duet']
                }
            }
        """
        pass

    @abstractmethod
    async def get_post_metadata(self, post_url: str) -> Dict:
        """
        Get metadata for a single post URL (for direct imports)

        Args:
            post_url: URL of the post

        Returns:
            Raw post metadata (same format as scrape_account)

        Note:
            This is used by the URL importer to get basic metadata
            without scraping the entire account
        """
        pass

    def calculate_date_filter(self, days_back: int) -> datetime:
        """
        Calculate the cutoff date for scraping

        Args:
            days_back: Number of days to scrape back

        Returns:
            Cutoff datetime
        """
        return datetime.now() - timedelta(days=days_back)

    def validate_username(self, username: str) -> bool:
        """
        Validate username format (can be overridden by platform)

        Args:
            username: Username to validate

        Returns:
            True if valid, False otherwise
        """
        if not username:
            return False

        # Basic validation - alphanumeric, underscore, period
        import re
        pattern = r'^[a-zA-Z0-9_.]+$'
        return bool(re.match(pattern, username))
