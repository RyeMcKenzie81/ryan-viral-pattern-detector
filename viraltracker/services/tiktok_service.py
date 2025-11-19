"""
TikTokService - Service layer for TikTok operations.

Provides async interfaces for TikTok scraping and analysis operations:
- Search TikTok by keyword
- Search by hashtag
- Scrape user posts
- Analyze single video
- Analyze batch of videos

Wraps TikTokScraper with clean service layer abstraction.
"""

import logging
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from ..scrapers.tiktok import TikTokScraper
from .models import TikTokVideo

logger = logging.getLogger(__name__)


class TikTokService:
    """
    Service for TikTok operations via agent.

    Provides async wrappers around TikTokScraper functionality.
    Handles scraping, filtering, and database operations.
    """

    def __init__(self):
        """Initialize TikTok service."""
        self.scraper = None  # Lazy initialization
        logger.info("TikTokService initialized")

    def _get_scraper(self) -> TikTokScraper:
        """Get or create TikTokScraper instance (lazy initialization)."""
        if self.scraper is None:
            self.scraper = TikTokScraper()
        return self.scraper

    async def search_keyword(
        self,
        keyword: str,
        project: str,
        count: int = 50,
        min_views: int = 100000,
        max_days: int = 10,
        max_followers: int = 50000,
        save_to_db: bool = True
    ) -> List[TikTokVideo]:
        """
        Search TikTok by keyword and return viral videos.

        Args:
            keyword: Search keyword or phrase
            project: Project slug for database linking
            count: Number of results to fetch (default: 50)
            min_views: Minimum view count filter (default: 100K)
            max_days: Maximum age in days (default: 10)
            max_followers: Maximum creator follower count (default: 50K)
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of TikTokVideo models
        """
        # Run scraper in thread pool (blocking I/O)
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        df, total = await loop.run_in_executor(
            None,
            lambda: scraper.search_by_keyword(
                keyword=keyword,
                count=count,
                min_views=min_views,
                max_days_old=max_days,
                max_follower_count=max_followers
            )
        )

        if len(df) == 0:
            return []

        # Save to database if requested
        if save_to_db:
            # Get project ID
            from ..core.database import get_supabase_client
            supabase = get_supabase_client()
            project_result = supabase.table("projects").select("id").eq("slug", project).execute()
            project_id = project_result.data[0]['id'] if project_result.data else None

            # Save posts
            await loop.run_in_executor(
                None,
                lambda: scraper.save_posts_to_db(df, project_id=project_id, import_source="search")
            )

        # Convert to TikTokVideo models
        videos = []
        for _, row in df.iterrows():
            video = TikTokVideo(
                id=row['post_id'],
                url=row['post_url'],
                caption=row.get('caption', ''),
                views=int(row.get('views', 0)),
                likes=int(row.get('likes', 0)),
                comments=int(row.get('comments', 0)),
                shares=int(row.get('shares', 0)),
                length_sec=int(row.get('length_sec', 0)),
                posted_at=row.get('posted_at'),
                username=row['username'],
                display_name=row.get('display_name', ''),
                follower_count=int(row.get('follower_count', 0)),
                is_verified=bool(row.get('is_verified', False)),
                download_url=row.get('download_url')
            )
            videos.append(video)

        return videos

    async def search_hashtag(
        self,
        hashtag: str,
        project: str,
        count: int = 50,
        min_views: int = 100000,
        max_days: int = 10,
        max_followers: int = 50000,
        save_to_db: bool = True
    ) -> List[TikTokVideo]:
        """
        Search TikTok by hashtag and return viral videos.

        Args:
            hashtag: Hashtag to search (with or without #)
            project: Project slug for database linking
            count: Number of results to fetch (default: 50)
            min_views: Minimum view count filter (default: 100K)
            max_days: Maximum age in days (default: 10)
            max_followers: Maximum creator follower count (default: 50K)
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of TikTokVideo models
        """
        # Clean hashtag
        clean_hashtag = hashtag.lstrip('#')

        # Run scraper in thread pool
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        df, total = await loop.run_in_executor(
            None,
            lambda: scraper.search_by_hashtag(
                hashtag=clean_hashtag,
                count=count,
                min_views=min_views,
                max_days_old=max_days,
                max_follower_count=max_followers
            )
        )

        if len(df) == 0:
            return []

        # Save to database if requested
        if save_to_db:
            from ..core.database import get_supabase_client
            supabase = get_supabase_client()
            project_result = supabase.table("projects").select("id").eq("slug", project).execute()
            project_id = project_result.data[0]['id'] if project_result.data else None

            await loop.run_in_executor(
                None,
                lambda: scraper.save_posts_to_db(df, project_id=project_id, import_source="search")
            )

        # Convert to TikTokVideo models
        videos = []
        for _, row in df.iterrows():
            video = TikTokVideo(
                id=row['post_id'],
                url=row['post_url'],
                caption=row.get('caption', ''),
                views=int(row.get('views', 0)),
                likes=int(row.get('likes', 0)),
                comments=int(row.get('comments', 0)),
                shares=int(row.get('shares', 0)),
                length_sec=int(row.get('length_sec', 0)),
                posted_at=row.get('posted_at'),
                username=row['username'],
                display_name=row.get('display_name', ''),
                follower_count=int(row.get('follower_count', 0)),
                is_verified=bool(row.get('is_verified', False)),
                download_url=row.get('download_url')
            )
            videos.append(video)

        return videos

    async def scrape_user(
        self,
        username: str,
        project: str,
        count: int = 50,
        save_to_db: bool = True
    ) -> List[TikTokVideo]:
        """
        Scrape posts from a TikTok user/creator.

        No filtering applied - fetches all posts for outlier detection.

        Args:
            username: TikTok username (with or without @)
            project: Project slug for database linking
            count: Number of posts to fetch (default: 50)
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of TikTokVideo models
        """
        # Clean username
        clean_username = username.lstrip('@')

        # Run scraper in thread pool
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        df = await loop.run_in_executor(
            None,
            lambda: scraper.scrape_user(username=clean_username, count=count)
        )

        if len(df) == 0:
            return []

        # Save to database if requested
        if save_to_db:
            from ..core.database import get_supabase_client
            supabase = get_supabase_client()
            project_result = supabase.table("projects").select("id").eq("slug", project).execute()
            project_id = project_result.data[0]['id'] if project_result.data else None

            await loop.run_in_executor(
                None,
                lambda: scraper.save_posts_to_db(df, project_id=project_id, import_source="scrape")
            )

        # Convert to TikTokVideo models
        videos = []
        for _, row in df.iterrows():
            video = TikTokVideo(
                id=row['post_id'],
                url=row['post_url'],
                caption=row.get('caption', ''),
                views=int(row.get('views', 0)),
                likes=int(row.get('likes', 0)),
                comments=int(row.get('comments', 0)),
                shares=int(row.get('shares', 0)),
                length_sec=int(row.get('length_sec', 0)),
                posted_at=row.get('posted_at'),
                username=row['username'],
                display_name=row.get('display_name', ''),
                follower_count=int(row.get('follower_count', 0)),
                is_verified=bool(row.get('is_verified', False)),
                download_url=row.get('download_url')
            )
            videos.append(video)

        return videos

    async def fetch_video_by_url(
        self,
        url: str,
        project: str,
        save_to_db: bool = True
    ) -> Optional[TikTokVideo]:
        """
        Fetch a single TikTok video by URL.

        Args:
            url: TikTok video URL
            project: Project slug for database linking
            save_to_db: Whether to save result to database (default: True)

        Returns:
            TikTokVideo model or None if not found
        """
        # Run scraper in thread pool
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        df = await loop.run_in_executor(
            None,
            lambda: scraper.fetch_video_by_url(url)
        )

        if len(df) == 0:
            return None

        # Save to database if requested
        if save_to_db:
            from ..core.database import get_supabase_client
            supabase = get_supabase_client()
            project_result = supabase.table("projects").select("id").eq("slug", project).execute()
            project_id = project_result.data[0]['id'] if project_result.data else None

            await loop.run_in_executor(
                None,
                lambda: scraper.save_posts_to_db(df, project_id=project_id, import_source="direct_url")
            )

        # Convert to TikTokVideo model
        row = df.iloc[0]
        video = TikTokVideo(
            id=row['post_id'],
            url=row['post_url'],
            caption=row.get('caption', ''),
            views=int(row.get('views', 0)),
            likes=int(row.get('likes', 0)),
            comments=int(row.get('comments', 0)),
            shares=int(row.get('shares', 0)),
            length_sec=int(row.get('length_sec', 0)),
            posted_at=row.get('posted_at'),
            username=row['username'],
            display_name=row.get('display_name', ''),
            follower_count=int(row.get('follower_count', 0)),
            is_verified=bool(row.get('is_verified', False)),
            download_url=row.get('download_url')
        )

        return video

    async def fetch_videos_by_urls(
        self,
        urls: List[str],
        project: str,
        save_to_db: bool = True
    ) -> List[TikTokVideo]:
        """
        Fetch multiple TikTok videos by URLs.

        Args:
            urls: List of TikTok video URLs
            project: Project slug for database linking
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of TikTokVideo models
        """
        videos = []

        for url in urls:
            try:
                video = await self.fetch_video_by_url(url, project, save_to_db)
                if video:
                    videos.append(video)
            except Exception as e:
                logger.warning(f"Failed to fetch video from {url}: {e}")
                continue

        return videos
