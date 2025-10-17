"""
Twitter URL importer

Validates Twitter URLs and saves them to database.
Metadata (views, likes, comments) is populated later by Apify scraping.
"""

import re
import logging

from .base import BaseURLImporter

logger = logging.getLogger(__name__)


class TwitterURLImporter(BaseURLImporter):
    """
    Import tweets via direct URL

    Validates URLs and extracts tweet IDs.
    Metadata will be populated later by Apify scraping.
    Works for both twitter.com and x.com domains.
    """

    def __init__(self, platform_id: str):
        """
        Initialize Twitter URL importer

        Args:
            platform_id: Twitter platform UUID from database
        """
        super().__init__('twitter', platform_id)

    def validate_url(self, url: str) -> bool:
        """
        Validate Twitter URL format

        Args:
            url: URL to validate

        Returns:
            True if valid Twitter URL

        Valid formats:
            - https://twitter.com/username/status/1234567890
            - https://x.com/username/status/1234567890
            - https://www.twitter.com/username/status/1234567890
            - https://www.x.com/username/status/1234567890
            - http://twitter.com/username/status/1234567890
        """
        if not url:
            return False

        url_lower = url.lower()

        # Must contain twitter.com or x.com
        if not ('twitter.com' in url_lower or 'x.com' in url_lower):
            return False

        # Must be a status URL
        if '/status/' not in url_lower:
            return False

        return True

    def extract_post_id(self, url: str) -> str:
        """
        Extract tweet ID from Twitter URL

        Args:
            url: Twitter URL

        Returns:
            Tweet ID (numeric string)

        Examples:
            'https://twitter.com/elonmusk/status/1728108619189874825' -> '1728108619189874825'
            'https://x.com/NASA/status/1234567890123456789' -> '1234567890123456789'
            'https://twitter.com/user/status/123?s=20' -> '123'
        """
        # Match /status/ followed by numeric tweet ID
        pattern = r'/status/(\d+)'
        match = re.search(pattern, url)

        if match:
            return match.group(1)

        return None
