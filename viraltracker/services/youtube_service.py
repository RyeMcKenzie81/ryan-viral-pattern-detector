"""
YouTubeService - Service layer for YouTube operations.

Provides async interfaces for YouTube video scraping and analysis:
- Search YouTube by keyword
- Filter by viral metrics (views, subscribers, engagement)

Wraps YouTubeSearchScraper with clean service layer abstraction.
"""

import logging
import asyncio
from typing import List, Optional
from datetime import datetime

from ..scrapers.youtube_search import YouTubeSearchScraper
from .models import YouTubeVideo

logger = logging.getLogger(__name__)


class YouTubeService:
    """
    Service for YouTube operations via agent.

    Provides async wrappers around YouTubeSearchScraper functionality.
    Handles scraping, filtering, and database operations.
    """

    def __init__(self):
        """Initialize YouTube service."""
        self.scraper = None  # Lazy initialization
        logger.info("YouTubeService initialized")

    def _get_scraper(self) -> YouTubeSearchScraper:
        """Get or create YouTubeSearchScraper instance (lazy initialization)."""
        if self.scraper is None:
            self.scraper = YouTubeSearchScraper()
        return self.scraper

    async def search_videos(
        self,
        search_terms: List[str],
        project: str,
        max_shorts: int = 100,
        max_videos: int = 0,
        max_streams: int = 0,
        days_back: Optional[int] = None,
        min_views: Optional[int] = None,
        min_subscribers: Optional[int] = None,
        max_subscribers: Optional[int] = None,
        sort_by: str = "views",
        save_to_db: bool = True
    ) -> List[YouTubeVideo]:
        """
        Search YouTube by keyword with viral filtering.

        Args:
            search_terms: List of search terms/keywords
            project: Project slug for database linking
            max_shorts: Maximum Shorts per term (default: 100)
            max_videos: Maximum regular videos per term (default: 0)
            max_streams: Maximum streams per term (default: 0)
            days_back: Only videos from last N days
            min_views: Minimum view count filter
            min_subscribers: Minimum channel subscriber count
            max_subscribers: Maximum channel subscriber count (for micro-influencers)
            sort_by: Sort by (views, date, relevance, rating)
            save_to_db: Whether to save results to database (default: True)

        Returns:
            List of YouTubeVideo models
        """
        # Run scraper in thread pool (blocking I/O)
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        # scrape_search returns (terms_count, videos_scraped) and saves to DB
        terms_count, videos_count = await loop.run_in_executor(
            None,
            lambda: scraper.scrape_search(
                search_terms=search_terms,
                max_shorts=max_shorts,
                max_videos=max_videos,
                max_streams=max_streams,
                days_back=days_back,
                min_views=min_views,
                min_subscribers=min_subscribers,
                max_subscribers=max_subscribers,
                sort_by=sort_by,
                project_slug=project if save_to_db else None
            )
        )

        if videos_count == 0:
            return []

        # Query database to get the videos that were just scraped
        # We'll query by search_query field to get videos from this search
        from ..core.database import get_supabase_client
        supabase = get_supabase_client()

        # Get project ID
        project_result = supabase.table("projects").select("id").eq("slug", project).execute()
        if not project_result.data:
            logger.warning(f"Project not found: {project}")
            return []

        project_id = project_result.data[0]['id']

        # Query posts linked to this project
        # Get the most recent videos (ordered by created_at desc)
        query = (
            supabase.table("posts")
            .select("*")
            .eq("platform_id", scraper.platform_id)
            .order("created_at", desc=True)
            .limit(videos_count * 2)  # Get more than we need in case of duplicates
        )

        result = await loop.run_in_executor(None, lambda: query.execute())

        if not result.data:
            logger.warning("No videos found in database after scraping")
            return []

        # Convert to YouTubeVideo models
        videos = []
        for row in result.data[:videos_count]:  # Limit to actual count scraped
            try:
                video = YouTubeVideo(
                    id=row['post_id'],
                    url=row['post_url'],
                    title=row.get('title', ''),
                    caption=row.get('caption', ''),
                    views=int(row.get('views', 0)),
                    likes=int(row.get('likes', 0)),
                    comments=int(row.get('comments', 0)),
                    length_sec=int(row.get('length_sec', 0)),
                    video_type=row.get('video_type', 'video'),
                    posted_at=row.get('posted_at'),
                    channel=row.get('username', ''),
                    subscriber_count=int(row.get('follower_count', 0)),
                    search_query=row.get('search_query')
                )
                videos.append(video)
            except Exception as e:
                logger.warning(f"Failed to convert row to YouTubeVideo: {e}")
                continue

        logger.info(f"Converted {len(videos)} YouTube videos to models")
        return videos
