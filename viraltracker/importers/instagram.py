"""
Instagram URL importer

Validates Instagram URLs and saves them to database.
Metadata (views, likes, comments) is populated later by Apify scraping.
"""

import re
import logging

from .base import BaseURLImporter

logger = logging.getLogger(__name__)


class InstagramURLImporter(BaseURLImporter):
    """
    Import Instagram posts/reels via direct URL

    Validates URLs and extracts post IDs.
    Metadata will be populated later by Apify scraping.
    Works for both /p/ (posts) and /reel/ URLs.
    """

    def __init__(self, platform_id: str):
        """
        Initialize Instagram URL importer

        Args:
            platform_id: Instagram platform UUID from database
        """
        super().__init__('instagram', platform_id)

    def validate_url(self, url: str) -> bool:
        """
        Validate Instagram URL format

        Args:
            url: URL to validate

        Returns:
            True if valid Instagram URL

        Valid formats:
            - https://www.instagram.com/p/ABC123/
            - https://www.instagram.com/reel/ABC123/
            - https://instagram.com/p/ABC123/
            - http://instagram.com/reel/ABC123/
        """
        if not url:
            return False

        url_lower = url.lower()

        # Must contain instagram.com
        if 'instagram.com' not in url_lower:
            return False

        # Must be a post or reel
        if not ('/p/' in url_lower or '/reel/' in url_lower):
            return False

        return True

    def extract_post_id(self, url: str) -> str:
        """
        Extract post ID from Instagram URL

        Args:
            url: Instagram URL

        Returns:
            Post ID (shortcode)

        Examples:
            'https://www.instagram.com/reel/ABC123/' -> 'ABC123'
            'https://www.instagram.com/p/XYZ789/' -> 'XYZ789'
            'https://instagram.com/p/XYZ789/?utm_source=ig_web' -> 'XYZ789'
        """
        # Match /p/ or /reel/ followed by the shortcode
        pattern = r'/(?:p|reel)/([A-Za-z0-9_-]+)'
        match = re.search(pattern, url)

        if match:
            return match.group(1)

        return None
