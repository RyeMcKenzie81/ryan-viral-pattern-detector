"""
Base URL importer for direct video imports

URL importers validate and save URLs without fetching metadata.
Metadata (views, likes, comments) is populated later by Apify scraping.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime
import logging

from ..core.database import get_supabase_client
from ..core.models import PostCreate, ImportSource, ImportMethod

logger = logging.getLogger(__name__)


class BaseURLImporter(ABC):
    """
    Abstract base class for URL importers

    Validates URLs and saves them to the database.
    Metadata is populated later by Apify scraping.
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

        Validates the URL and saves it to the database.
        Metadata (views, likes, comments) will be populated later by Apify scraping.

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

            # 2. Extract post ID from URL
            post_id = self.extract_post_id(url)
            if not post_id:
                raise ValueError(f"Could not extract post ID from URL: {url}")

            # 3. Check if already exists
            existing = self.supabase.table('posts').select('id').eq('post_url', url).execute()
            if existing.data:
                db_post_id = existing.data[0]['id']
                logger.info(f"Post already exists: {db_post_id}")

                # Link to project if not already linked
                self._link_to_project(db_post_id, project_id, is_own_content, notes)

                return {
                    'id': db_post_id,
                    'post_url': url,
                    'post_id': post_id,
                    'status': 'already_exists',
                    'message': 'Post already exists, linked to project'
                }

            # 4. Create minimal post record (metadata will be populated by Apify later)
            post_data = PostCreate(
                platform_id=self.platform_id,
                post_url=url,
                post_id=post_id,
                import_source=ImportSource.DIRECT_URL,
            )

            # 5. Save to database
            post = self._save_post(post_data, is_own_content)

            # 6. Link to project
            self._link_to_project(post['id'], project_id, is_own_content, notes)

            logger.info(f"Successfully imported: {post['id']}")

            return {
                'id': post['id'],
                'post_url': post['post_url'],
                'post_id': post_id,
                'status': 'imported',
                'message': 'Successfully imported (metadata will be populated by next scrape)'
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

    @abstractmethod
    def extract_post_id(self, url: str) -> str:
        """
        Extract post ID from URL

        Args:
            url: Video URL

        Returns:
            Post ID string

        Example for Instagram:
            'https://www.instagram.com/reel/ABC123/' -> 'ABC123'
            'https://www.instagram.com/p/XYZ789/' -> 'XYZ789'
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
        # Convert Pydantic model to dict (mode='json' converts UUIDs to strings)
        data = post_data.model_dump(exclude_unset=True, mode='json')
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
