"""
Instagram URL importer
"""

from datetime import datetime
from typing import Dict
import logging

from .base import BaseURLImporter
from ..core.models import PostCreate, ImportSource

logger = logging.getLogger(__name__)


class InstagramURLImporter(BaseURLImporter):
    """
    Import Instagram posts/reels via direct URL

    Uses yt-dlp to extract metadata without downloading the video.
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

    def normalize_metadata(self, metadata: Dict) -> PostCreate:
        """
        Convert yt-dlp metadata to PostCreate format

        Args:
            metadata: Raw metadata from yt-dlp

        Returns:
            PostCreate object with normalized Instagram data

        Note:
            yt-dlp extracts different fields depending on whether the user
            is logged in. We handle both cases gracefully.
        """
        # Extract post ID from URL
        post_id = metadata.get('id') or metadata.get('display_id')

        # Get timestamp
        timestamp = metadata.get('timestamp')
        posted_at = datetime.fromtimestamp(timestamp) if timestamp else None

        # Views (may not be available for all posts)
        views = metadata.get('view_count', 0) or metadata.get('play_count', 0)

        # Likes
        likes = metadata.get('like_count', 0)

        # Comments
        comments = metadata.get('comment_count', 0)

        # Caption/description
        caption = metadata.get('description', '') or metadata.get('title', '')

        # Duration
        duration = metadata.get('duration')
        length_sec = int(duration) if duration else None

        # Username
        username = metadata.get('uploader') or metadata.get('uploader_id') or metadata.get('channel')

        # Create PostCreate object
        return PostCreate(
            platform_id=self.platform_id,
            post_url=metadata['webpage_url'],
            post_id=post_id,
            views=views if views > 0 else None,
            likes=likes if likes > 0 else None,
            comments=comments if comments > 0 else None,
            caption=caption[:2200] if caption else None,  # Max 2200 chars
            posted_at=posted_at,
            length_sec=length_sec,
            import_source=ImportSource.DIRECT_URL,
        )

    def extract_platform_specific_metrics(self, metadata: Dict) -> Dict:
        """
        Extract Instagram-specific metrics

        Args:
            metadata: Raw metadata from yt-dlp

        Returns:
            Dictionary with Instagram-specific data

        Example:
            {
                'instagram': {
                    'is_video': True,
                    'product_type': 'clips',  # reels are called 'clips' internally
                    'has_audio': True,
                }
            }
        """
        return {
            'instagram': {
                'is_video': metadata.get('is_live', False) == False,
                'uploader': metadata.get('uploader'),
                'uploader_id': metadata.get('uploader_id'),
                'has_audio': metadata.get('audio_channels', 0) > 0,
            }
        }
