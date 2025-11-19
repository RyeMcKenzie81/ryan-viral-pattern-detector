"""
YouTube URL importer

Validates YouTube Shorts URLs and saves them to database.
Metadata (views, likes, comments) is populated later by Apify scraping.
"""

import re
import logging

from .base import BaseURLImporter

logger = logging.getLogger(__name__)


class YouTubeURLImporter(BaseURLImporter):
    """
    Import YouTube Shorts via direct URL

    Validates URLs and extracts video IDs.
    Metadata will be populated later by Apify scraping or yt-dlp.
    Works for all YouTube URL formats.
    """

    def __init__(self, platform_id: str):
        """
        Initialize YouTube URL importer

        Args:
            platform_id: YouTube Shorts platform UUID from database
        """
        super().__init__('youtube_shorts', platform_id)

    def validate_url(self, url: str) -> bool:
        """
        Validate YouTube URL format

        Args:
            url: URL to validate

        Returns:
            True if valid YouTube URL

        Valid formats:
            - https://www.youtube.com/shorts/VIDEO_ID
            - https://youtu.be/VIDEO_ID
            - https://www.youtube.com/watch?v=VIDEO_ID
            - https://m.youtube.com/watch?v=VIDEO_ID
        """
        if not url:
            return False

        url_lower = url.lower()

        # Must contain youtube.com or youtu.be
        if not ('youtube.com' in url_lower or 'youtu.be' in url_lower):
            return False

        # Must have a video ID we can extract
        video_id = self.extract_post_id(url)
        return video_id is not None

    def extract_post_id(self, url: str) -> str:
        """
        Extract video ID from YouTube URL

        Args:
            url: YouTube URL

        Returns:
            Video ID

        Examples:
            'https://www.youtube.com/shorts/ABC123' -> 'ABC123'
            'https://youtu.be/XYZ789' -> 'XYZ789'
            'https://www.youtube.com/watch?v=DEF456' -> 'DEF456'
            'https://www.youtube.com/watch?v=GHI789&t=10s' -> 'GHI789'
        """
        # Pattern 1: /shorts/VIDEO_ID
        match = re.search(r'/shorts/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Pattern 2: youtu.be/VIDEO_ID
        match = re.search(r'youtu\.be/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Pattern 3: watch?v=VIDEO_ID
        match = re.search(r'[?&]v=([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Pattern 4: /v/VIDEO_ID or /embed/VIDEO_ID
        match = re.search(r'/(v|embed)/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(2)

        return None
