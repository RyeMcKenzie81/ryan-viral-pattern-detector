"""
Base URL importer for direct video imports
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime
import yt_dlp
import logging

from ..core.database import get_supabase_client
from ..core.models import PostCreate, ProjectPostCreate, ImportSource, ImportMethod

logger = logging.getLogger(__name__)


class BaseURLImporter(ABC):
    """
    Abstract base class for URL importers

    Uses yt-dlp to extract metadata from video URLs without downloading
    the actual video file.
    """

    def __init__(self, platform_slug: str, platform_id: str):
        """
        Initialize URL importer

        Args:
            platform_slug: Platform identifier (instagram, tiktok, youtube_shorts)
            platform_id: Platform UUID from database
        """
        self.platform_slug = platform_slug
        self.platform_id = platform_id
        self.supabase = get_supabase_client()

    async def import_url(
        self,
        url: str,
        project_id: str,
        is_own_content: bool = False,
        notes: Optional[str] = None
    ) -> Dict:
        """
        Import a single URL into a project

        Args:
            url: Video URL to import
            project_id: Project UUID to add video to
            is_own_content: Whether this is brand's own content
            notes: Optional notes about this import

        Returns:
            Dictionary with post data and import status

        Example:
            {
                'post_id': 'uuid-123',
                'post_url': 'https://instagram.com/p/ABC123/',
                'status': 'imported',
                'message': 'Successfully imported'
            }
        """
        try:
            # 1. Validate URL
            if not self.validate_url(url):
                raise ValueError(f"Invalid {self.platform_slug} URL: {url}")

            logger.info(f"Importing URL: {url}")

            # 2. Check if already exists
            existing = self.supabase.table('posts').select('id').eq('post_url', url).execute()
            if existing.data:
                post_id = existing.data[0]['id']
                logger.info(f"Post already exists: {post_id}")

                # Link to project if not already linked
                self._link_to_project(post_id, project_id, is_own_content, notes)

                return {
                    'post_id': post_id,
                    'post_url': url,
                    'status': 'already_exists',
                    'message': 'Post already exists, linked to project'
                }

            # 3. Extract metadata using yt-dlp
            logger.info("Extracting metadata...")
            metadata = await self.extract_metadata(url)

            # 4. Normalize to standard format
            normalized = self.normalize_metadata(metadata)

            # 5. Save to database
            post = self._save_post(normalized, is_own_content)

            # 6. Link to project
            self._link_to_project(post['id'], project_id, is_own_content, notes)

            logger.info(f"Successfully imported: {post['id']}")

            return {
                'post_id': post['id'],
                'post_url': post['post_url'],
                'status': 'imported',
                'message': 'Successfully imported'
            }

        except Exception as e:
            logger.error(f"Failed to import URL {url}: {str(e)}")
            raise

    @abstractmethod
    def validate_url(self, url: str) -> bool:
        """
        Check if URL is valid for this platform

        Args:
            url: URL to validate

        Returns:
            True if valid, False otherwise

        Example for Instagram:
            'instagram.com' in url and ('/p/' in url or '/reel/' in url)
        """
        pass

    async def extract_metadata(self, url: str) -> Dict:
        """
        Extract metadata using yt-dlp (works for all platforms)

        Args:
            url: Video URL

        Returns:
            Dictionary with video metadata from yt-dlp

        Note:
            This method works for Instagram, TikTok, YouTube, and 1000+ other platforms
            that yt-dlp supports. No need to override unless you want custom behavior.
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,  # Don't download video, just get metadata
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.error(f"yt-dlp failed to extract metadata: {str(e)}")
            raise

    @abstractmethod
    def normalize_metadata(self, metadata: Dict) -> PostCreate:
        """
        Convert yt-dlp metadata to standard Post format

        Args:
            metadata: Raw metadata from yt-dlp

        Returns:
            PostCreate object with normalized data

        Example:
            PostCreate(
                platform_id=self.platform_id,
                post_url=metadata['webpage_url'],
                post_id=metadata.get('id'),
                views=metadata.get('view_count', 0),
                likes=metadata.get('like_count', 0),
                comments=metadata.get('comment_count', 0),
                caption=metadata.get('description', ''),
                posted_at=datetime.fromtimestamp(metadata.get('timestamp')),
                length_sec=metadata.get('duration'),
                import_source=ImportSource.DIRECT_URL,
            )
        """
        pass

    def _save_post(self, post_data: PostCreate, is_own_content: bool) -> Dict:
        """
        Save post to database

        Args:
            post_data: PostCreate object
            is_own_content: Whether this is brand's own content

        Returns:
            Created post record
        """
        # Convert Pydantic model to dict
        data = post_data.model_dump(exclude_unset=True)
        data['is_own_content'] = is_own_content

        # Insert into database
        result = self.supabase.table('posts').insert(data).execute()

        return result.data[0]

    def _link_to_project(
        self,
        post_id: str,
        project_id: str,
        is_own_content: bool,
        notes: Optional[str] = None
    ):
        """
        Link post to project via project_posts table

        Args:
            post_id: Post UUID
            project_id: Project UUID
            is_own_content: Whether this is brand's own content
            notes: Optional notes
        """
        # Check if already linked
        existing = self.supabase.table('project_posts')\
            .select('id')\
            .eq('project_id', project_id)\
            .eq('post_id', post_id)\
            .execute()

        if existing.data:
            logger.info(f"Post {post_id} already linked to project {project_id}")
            return

        # Create link
        link_data = {
            'project_id': project_id,
            'post_id': post_id,
            'import_method': ImportMethod.DIRECT_URL.value,
            'is_own_content': is_own_content,
            'notes': notes
        }

        self.supabase.table('project_posts').insert(link_data).execute()
        logger.info(f"Linked post {post_id} to project {project_id}")
