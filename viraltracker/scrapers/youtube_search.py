"""
YouTube search scraper using streamers/youtube-scraper Apify actor

Enables keyword/hashtag discovery for YouTube content (Shorts, videos, streams).
Follows TikTok search pattern with absolute filters for viral content discovery.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from uuid import UUID

import pandas as pd
import requests
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential
from supabase import Client
from apify_client import ApifyClient

from ..core.database import get_supabase_client
from ..core.config import Config


logger = logging.getLogger(__name__)


class YouTubeSearchScraper:
    """
    YouTube search scraper for ViralTracker using Apify

    Enables keyword/hashtag discovery for YouTube Shorts and videos.
    Follows TikTok search pattern with absolute filters.

    Features:
    - Search by keyword/term
    - Separate limits for Shorts, regular videos, and streams
    - Advanced filters: date ranges, sorting, view counts
    - Project linking support
    - Automatic video_type classification (short/video/stream)
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize YouTube search scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to streamers/youtube-scraper)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or "streamers/youtube-scraper"
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

        # Get YouTube Shorts platform ID
        self.platform_id = self._get_platform_id()

    def _get_platform_id(self) -> str:
        """Get YouTube Shorts platform UUID from database"""
        result = self.supabase.table('platforms').select('id').eq('slug', 'youtube_shorts').single().execute()
        if not result.data:
            raise ValueError("YouTube Shorts platform not found in database")
        return result.data['id']

    def scrape_search(
        self,
        search_terms: List[str],
        max_shorts: int = 100,
        max_videos: int = 0,
        max_streams: int = 0,
        days_back: Optional[int] = None,
        min_views: Optional[int] = None,
        min_subscribers: Optional[int] = None,
        max_subscribers: Optional[int] = None,
        sort_by: str = "views",
        project_slug: Optional[str] = None,
        timeout: int = 300
    ) -> Tuple[int, int]:
        """
        Search YouTube by keyword/term with viral filtering criteria

        Filtering criteria:
        - days_back: Only videos from last N days
        - min_views: Minimum view count (applied post-scrape)
        - min_subscribers: Minimum channel subscriber count
        - max_subscribers: Maximum channel subscriber count (for micro-influencer content)
        - sort_by: Sort order (views, date, relevance, rating)

        Args:
            search_terms: List of search terms/keywords
            max_shorts: Maximum Shorts per term (default: 100)
            max_videos: Maximum regular videos per term (default: 0)
            max_streams: Maximum streams per term (default: 0)
            days_back: Only videos from last N days
            min_views: Minimum view count filter
            min_subscribers: Minimum channel subscriber count
            max_subscribers: Maximum channel subscriber count
            sort_by: Sort by (views, date, relevance, rating)
            project_slug: Optional project to link results to
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (terms_count, videos_scraped)
        """
        logger.info(f"Searching YouTube for {len(search_terms)} terms")
        logger.info(f"Limits: {max_shorts} Shorts, {max_videos} videos, {max_streams} streams")
        if min_views:
            logger.info(f"Filters: {min_views:,}+ views")
        if days_back:
            logger.info(f"Filters: last {days_back} days")
        if min_subscribers:
            logger.info(f"Filters: {min_subscribers:,}+ subscribers")
        if max_subscribers:
            logger.info(f"Filters: <{max_subscribers:,} subscribers")

        # Build Apify actor input
        actor_input = {
            "searchQueries": search_terms,
            "maxResults": max_videos,
            "maxResultsShorts": max_shorts,
            "maxResultStreams": max_streams,
            "sortingOrder": sort_by  # "views", "date", "relevance", "rating"
        }

        # Add date filter if specified
        if days_back:
            if days_back <= 1:
                actor_input["dateFilter"] = "today"
            elif days_back <= 7:
                actor_input["dateFilter"] = "week"
            elif days_back <= 30:
                actor_input["dateFilter"] = "month"
            else:
                actor_input["dateFilter"] = "year"

        # Start Apify run
        run_id = self._start_apify_run(actor_input)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No results from YouTube search")
            return (len(search_terms), 0)

        logger.info(f"Fetched {len(items)} results from Apify")

        # Apply post-scrape filters
        original_count = len(items)

        # Filter by min_views if specified
        if min_views:
            items = [item for item in items if item.get("viewCount", 0) >= min_views]
            logger.info(f"After min_views filter ({min_views:,}+): {len(items)}/{original_count} videos")

        # Filter by subscriber count if specified
        if min_subscribers:
            items = [item for item in items if item.get("numberOfSubscribers", 0) >= min_subscribers]
            logger.info(f"After min_subscribers filter ({min_subscribers:,}+): {len(items)}/{original_count} videos")

        if max_subscribers:
            items = [item for item in items if item.get("numberOfSubscribers", 0) < max_subscribers]
            logger.info(f"After max_subscribers filter (<{max_subscribers:,}): {len(items)}/{original_count} videos")

        if not items:
            logger.warning("No videos after filtering")
            return (len(search_terms), 0)

        # Normalize data (convert to DataFrame)
        df = self._normalize_items(items)

        if len(df) == 0:
            logger.warning("No videos were successfully normalized")
            return (len(search_terms), 0)

        # Upsert posts to database
        post_ids = self._upsert_posts(df, import_source="search")

        # Link to project if specified
        if project_slug and post_ids:
            project_id = self._get_project_id(project_slug)
            self._link_posts_to_project(post_ids, project_id)

        logger.info(f"Successfully scraped {len(post_ids)} videos from {len(search_terms)} search terms")

        return (len(search_terms), len(post_ids))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_apify_run(self, actor_input: Dict) -> str:
        """
        Start Apify actor run for YouTube search

        Args:
            actor_input: Apify actor input configuration

        Returns:
            Apify run ID
        """
        logger.info(f"Starting Apify run for YouTube search")
        logger.info(f"Search queries: {actor_input['searchQueries']}")
        logger.info(f"Max Shorts: {actor_input['maxResultsShorts']}, Videos: {actor_input['maxResults']}, Streams: {actor_input['maxResultStreams']}")

        # Use .start() not .call() to avoid SDK timeout
        run = self.apify_client.actor(self.apify_actor_id).start(run_input=actor_input)

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _poll_apify_run(self, run_id: str, timeout: int = 300) -> Dict:
        """
        Poll Apify run until completion

        Args:
            run_id: Apify run identifier
            timeout: Maximum seconds to wait

        Returns:
            Dict with datasetId and status
        """
        url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        headers = {"Authorization": f"Bearer {self.apify_token}"}

        start_time = time.time()
        wait_time = 2

        logger.info(f"Polling Apify run {run_id}...")

        while time.time() - start_time < timeout:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            run_data = response.json()
            status = run_data["data"]["status"]

            if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
                if status == "SUCCEEDED":
                    dataset_id = run_data["data"]["defaultDatasetId"]
                    logger.info(f"Apify run completed successfully. Dataset ID: {dataset_id}")
                    return {"datasetId": dataset_id, "status": status}
                else:
                    raise RuntimeError(f"Apify run failed with status: {status}")

            logger.info(f"Run status: {status}. Waiting {wait_time}s...")
            time.sleep(wait_time)
            wait_time = min(wait_time * 1.5, 30)

        raise TimeoutError(f"Apify run timeout after {timeout}s")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _fetch_dataset(self, dataset_id: str) -> List[Dict]:
        """
        Fetch complete dataset from Apify

        Args:
            dataset_id: Apify dataset identifier

        Returns:
            List of video dictionaries
        """
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        headers = {"Authorization": f"Bearer {self.apify_token}"}

        logger.info(f"Fetching dataset {dataset_id}...")

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        items = response.json()
        logger.info(f"Fetched {len(items)} items from dataset")

        # Debug: Log first item structure
        if items and len(items) > 0:
            first_item = items[0]
            logger.info(f"DEBUG - First item keys: {list(first_item.keys())[:20]}")

        return items

    def _normalize_items(self, items: List[Dict]) -> pd.DataFrame:
        """
        Normalize YouTube search results to DataFrame

        streamers/youtube-scraper returns:
        {
          "id": "VIDEO_ID",
          "title": "Video Title",
          "url": "https://www.youtube.com/shorts/VIDEO_ID",  // or /watch?v=
          "viewCount": 410458,
          "likes": 512238,
          "commentsCount": 14,
          "channelName": "Channel Name",
          "channelUrl": "https://www.youtube.com/@channel",
          "numberOfSubscribers": 6930000,
          "duration": "00:00:26",
          "date": "2021-12-21",
          "text": "Description text...",
          "thumbnailUrl": "https://i.ytimg.com/...",
          "fromYTUrl": "https://www.youtube.com/results?search_query=keyword"
        }

        Args:
            items: Raw Apify search response

        Returns:
            DataFrame with normalized videos, including video_type classification
        """
        normalized_data = []

        logger.info(f"Normalizing {len(items)} videos from YouTube search")

        for item in items:
            try:
                # Extract channel name from channelName or channelUrl
                channel_name = item.get("channelName", "")
                if not channel_name and item.get("channelUrl"):
                    # Extract from URL: https://www.youtube.com/@username
                    channel_url = item.get("channelUrl", "")
                    if "/@" in channel_url:
                        channel_name = channel_url.split("/@")[-1]

                # Parse duration (format: "00:00:26" -> seconds)
                duration_str = item.get("duration", "00:00:00")
                duration_sec = self._parse_duration(duration_str)

                # Determine video_type from URL pattern (trust Apify's classification)
                # The actor uses different URL patterns for different content types
                post_url = item.get("url", "")
                video_type = self._determine_video_type(post_url, duration_sec)

                # Parse date
                date_str = item.get("date")
                posted_at = None
                if date_str:
                    try:
                        # ISO format from Apify (may be YYYY-MM-DD or full ISO)
                        if 'T' in date_str:
                            posted_at = datetime.fromisoformat(date_str.replace('Z', '+00:00')).isoformat()
                        else:
                            # Just a date string like "2021-12-21"
                            posted_at = datetime.fromisoformat(date_str + "T00:00:00+00:00").isoformat()
                    except Exception as e:
                        logger.warning(f"Error parsing date '{date_str}': {e}")

                video_id = item.get("id", "")
                if not video_id:
                    logger.warning("Skipping video with no ID")
                    continue

                post_data = {
                    "channel": channel_name,
                    "post_url": post_url or f"https://www.youtube.com/watch?v={video_id}",
                    "post_id": video_id,
                    "posted_at": posted_at,
                    "views": item.get("viewCount", 0) or 0,
                    "likes": item.get("likes", 0) or 0,
                    "comments": item.get("commentsCount", 0) or 0,
                    "caption": (item.get("text", "") or "")[:2200],
                    "title": (item.get("title", "") or "")[:500],
                    "length_sec": duration_sec,
                    "video_type": video_type,  # NEW: Track content type
                    "search_query": item.get("fromYTUrl", ""),  # Track which query found it
                    "subscriber_count": item.get("numberOfSubscribers", 0) or 0  # Channel subscribers
                }

                # Validate essential fields
                if not post_data["post_id"] or not post_data["post_url"]:
                    logger.warning(f"Skipping video with missing essential fields")
                    continue

                # Ensure numeric fields are valid
                post_data["views"] = max(0, int(post_data["views"]))
                post_data["likes"] = max(0, int(post_data["likes"]))
                post_data["comments"] = max(0, int(post_data["comments"]))

                normalized_data.append(post_data)

            except Exception as e:
                logger.warning(f"Error normalizing video: {e}")
                continue

        df = pd.DataFrame(normalized_data)

        if len(df) > 0:
            # Deduplicate by post_url
            original_count = len(df)
            df = df.drop_duplicates(subset=['post_url'], keep='first')
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate videos")

            # Log counts by video type
            type_counts = df['video_type'].value_counts().to_dict()
            logger.info(f"Normalized {len(df)} videos: {type_counts}")
        else:
            logger.warning("No videos were successfully normalized")

        return df

    def _determine_video_type(self, url: str, duration_sec: int) -> str:
        """
        Determine video type from URL pattern

        YouTube uses different URL patterns:
        - Shorts: https://www.youtube.com/shorts/VIDEO_ID
        - Videos: https://www.youtube.com/watch?v=VIDEO_ID
        - Streams: https://www.youtube.com/watch?v=VIDEO_ID (may have isLiveContent flag)

        Trust the actor's URL pattern as the source of truth.

        Args:
            url: Video URL from Apify
            duration_sec: Video duration in seconds

        Returns:
            video_type: 'short', 'video', or 'stream'
        """
        if "/shorts/" in url:
            return "short"
        elif "/watch" in url:
            # Could be video or stream
            # For now, classify as video (stream detection would require additional metadata)
            return "video"
        else:
            # Fallback: use duration as hint (but trust URL pattern first)
            return "video"

    def _parse_duration(self, duration_str: str) -> int:
        """
        Parse duration string to seconds

        Args:
            duration_str: Duration in format "HH:MM:SS" or "MM:SS"

        Returns:
            Duration in seconds
        """
        try:
            parts = duration_str.split(':')
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            elif len(parts) == 2:
                minutes, seconds = parts
                return int(minutes) * 60 + int(seconds)
            else:
                return 0
        except:
            return 0

    def _upsert_posts(
        self,
        df: pd.DataFrame,
        import_source: str = "search"
    ) -> List[str]:
        """
        Upsert videos to database with platform_id, import_source, and video_type

        Args:
            df: Normalized videos DataFrame
            import_source: How posts were imported (default: "search")

        Returns:
            List of post UUIDs
        """
        if len(df) == 0:
            logger.warning("No videos to save")
            return []

        # First, upsert accounts for channels
        account_ids = self._upsert_accounts(df)

        # Prepare posts data
        posts_data = []
        for _, row in df.iterrows():
            post_dict = {
                "account_id": account_ids.get(row['channel']),
                "platform_id": self.platform_id,
                "post_url": row['post_url'],
                "post_id": row['post_id'],
                "posted_at": row.get('posted_at'),
                "views": int(row.get('views', 0)) if pd.notna(row.get('views')) else None,
                "likes": int(row.get('likes', 0)) if pd.notna(row.get('likes')) else None,
                "comments": int(row.get('comments', 0)) if pd.notna(row.get('comments')) else None,
                "caption": row.get('caption'),
                "length_sec": int(row.get('length_sec', 0)) if pd.notna(row.get('length_sec')) else None,
                "video_type": row.get('video_type'),  # NEW: Store video type
                "import_source": import_source,
                "is_own_content": False
            }

            # Store title in caption if caption is empty
            if not post_dict.get('caption') and row.get('title'):
                post_dict['caption'] = row.get('title')

            posts_data.append(post_dict)

        # Upsert posts in chunks
        post_ids = []
        chunk_size = 1000
        chunks = [posts_data[i:i + chunk_size] for i in range(0, len(posts_data), chunk_size)]

        for chunk in tqdm(chunks, desc="Saving videos to database"):
            try:
                result = self.supabase.table("posts").upsert(
                    chunk,
                    on_conflict="post_url"
                ).execute()

                for post in result.data:
                    post_ids.append(post['id'])

            except Exception as e:
                logger.error(f"Error upserting videos chunk: {e}")
                continue

        logger.info(f"Saved {len(post_ids)} videos to database")

        return post_ids

    def _upsert_accounts(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Upsert YouTube accounts to database

        Args:
            df: DataFrame with channel and subscriber_count columns

        Returns:
            Dict mapping channel name to account_id
        """
        # Get unique channels with their subscriber counts
        # Group by channel and take max subscriber count (in case of multiple values)
        channels_df = df[df['channel'].notna()][['channel', 'subscriber_count']]\
            .groupby('channel', as_index=False)\
            .agg({'subscriber_count': 'max'})

        account_ids = {}

        for _, row in tqdm(channels_df.iterrows(), total=len(channels_df), desc="Upserting accounts"):
            try:
                channel_name = row['channel']
                subscriber_count = int(row['subscriber_count']) if pd.notna(row['subscriber_count']) else None

                # Check if account exists
                existing = self.supabase.table('accounts')\
                    .select('id')\
                    .eq('platform_id', self.platform_id)\
                    .eq('platform_username', channel_name)\
                    .execute()

                if existing.data and len(existing.data) > 0:
                    # Account exists, update metadata
                    account_id = existing.data[0]['id']

                    update_data = {
                        "last_scraped_at": datetime.now().isoformat()
                    }

                    # Update subscriber count if we have it
                    if subscriber_count is not None:
                        update_data["follower_count"] = subscriber_count
                        update_data["metadata_updated_at"] = datetime.now().isoformat()

                    self.supabase.table('accounts').update(update_data).eq('id', account_id).execute()

                else:
                    # Create new account
                    account_data = {
                        "handle": channel_name,  # Legacy field
                        "platform_id": self.platform_id,
                        "platform_username": channel_name,
                        "last_scraped_at": datetime.now().isoformat()
                    }

                    # Add subscriber count if we have it
                    if subscriber_count is not None:
                        account_data["follower_count"] = subscriber_count
                        account_data["metadata_updated_at"] = datetime.now().isoformat()

                    result = self.supabase.table('accounts').insert(account_data).execute()
                    account_id = result.data[0]['id']

                account_ids[channel_name] = account_id

            except Exception as e:
                logger.error(f"Error upserting account {channel_name}: {e}")
                continue

        logger.info(f"Upserted {len(account_ids)} accounts")

        return account_ids

    def _get_project_id(self, project_slug: str) -> str:
        """Get project UUID from slug"""
        result = self.supabase.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not result.data:
            raise ValueError(f"Project '{project_slug}' not found")
        return result.data['id']

    def _link_posts_to_project(
        self,
        post_ids: List[str],
        project_id: str,
        import_method: str = "search"
    ):
        """
        Link videos to project via project_posts table

        Args:
            post_ids: List of post UUIDs
            project_id: Project UUID
            import_method: How posts were imported
        """
        links_data = []

        for post_id in post_ids:
            links_data.append({
                'project_id': project_id,
                'post_id': post_id,
                'import_method': import_method,
                'is_own_content': False,
                'notes': f"YouTube search on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking videos to project"):
            try:
                result = self.supabase.table("project_posts").upsert(
                    chunk,
                    on_conflict="project_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking videos chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} videos to project")
