"""
TikTok scraper using ScrapTik (Apify actor)

Supports 3 discovery modes:
1. Keyword search - Find viral content by keyword
2. Hashtag tracking - Monitor specific hashtags
3. User/creator tracking - Scrape specific accounts

All modes support outlier detection and AI analysis.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Literal
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


SearchMode = Literal["keyword", "hashtag", "user"]


class TikTokScraper:
    """
    TikTok scraper for ViralTracker using ScrapTik (Apify)

    Features:
    - Keyword search with filters (views, recency, creator size)
    - Hashtag tracking
    - User/creator account scraping
    - Engagement metrics: views, likes, comments, shares, play duration
    - Video download URLs (watermark-free)
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize TikTok scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to scraptik~tiktok-api)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or "scraptik~tiktok-api"
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

        # Get TikTok platform ID
        self.platform_id = self._get_platform_id()

    def _get_platform_id(self) -> str:
        """Get TikTok platform UUID from database"""
        result = self.supabase.table('platforms').select('id').eq('slug', 'tiktok').single().execute()
        if not result.data:
            raise ValueError("TikTok platform not found in database. Run migration 01_migration_multi_brand.sql")
        return result.data['id']

    def search_by_keyword(
        self,
        keyword: str,
        count: int = 50,
        min_views: int = 100000,
        max_days_old: int = 10,
        max_follower_count: int = 50000,
        sort_type: int = 0,
        publish_time: int = 0,
        timeout: int = 300
    ) -> Tuple[pd.DataFrame, int]:
        """
        Search TikTok by keyword with viral filtering criteria

        Filtering criteria (applied post-scrape):
        - min_views: Minimum view count (default: 100K)
        - max_days_old: Maximum age in days (default: 10 days)
        - max_follower_count: Maximum creator follower count (default: 50K)

        Args:
            keyword: Search keyword (e.g., "productivity apps")
            count: Number of posts to fetch (default: 50)
            min_views: Minimum views filter
            max_days_old: Maximum age in days
            max_follower_count: Maximum creator follower count
            sort_type: 0=Relevance, 1=Most Liked, 3=Date
            publish_time: 0=All, 1=Yesterday, 7=Week, 30=Month, 90=3mo, 180=6mo
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (filtered_posts_df, total_scraped_count)
        """
        logger.info(f"Searching TikTok for keyword: '{keyword}'")
        logger.info(f"Filters: {min_views:,}+ views, <{max_days_old} days old, <{max_follower_count:,} followers")

        # Start Apify run
        run_id = self._start_keyword_search_run(keyword, count, sort_type, publish_time)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No results from keyword search")
            return pd.DataFrame(), 0

        # Normalize to DataFrame
        df = self._normalize_search_posts(items)

        original_count = len(df)

        # Apply filtering criteria
        if len(df) > 0:
            df = self._apply_viral_filters(
                df,
                min_views=min_views,
                max_days_old=max_days_old,
                max_follower_count=max_follower_count
            )

        logger.info(f"Filtered from {original_count} to {len(df)} posts meeting criteria")

        return df, original_count

    def search_by_hashtag(
        self,
        hashtag: str,
        count: int = 50,
        min_views: int = 100000,
        max_days_old: int = 10,
        max_follower_count: int = 50000,
        timeout: int = 300
    ) -> Tuple[pd.DataFrame, int]:
        """
        Search TikTok by hashtag with viral filtering criteria

        Args:
            hashtag: Hashtag name (without #)
            count: Number of posts to fetch
            min_views: Minimum views filter
            max_days_old: Maximum age in days
            max_follower_count: Maximum creator follower count
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (filtered_posts_df, total_scraped_count)
        """
        logger.info(f"Searching TikTok for hashtag: #{hashtag}")

        # Start Apify run
        run_id = self._start_hashtag_search_run(hashtag, count)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No results from hashtag search")
            return pd.DataFrame(), 0

        # Normalize to DataFrame
        df = self._normalize_search_posts(items)

        original_count = len(df)

        # Apply filtering criteria
        if len(df) > 0:
            df = self._apply_viral_filters(
                df,
                min_views=min_views,
                max_days_old=max_days_old,
                max_follower_count=max_follower_count
            )

        logger.info(f"Filtered from {original_count} to {len(df)} posts meeting criteria")

        return df, original_count

    def scrape_user(
        self,
        username: str,
        count: int = 50,
        timeout: int = 300
    ) -> pd.DataFrame:
        """
        Scrape posts from a specific TikTok user/creator

        This is for per-user outlier detection (3 SD from user's trimmed mean).
        No filtering applied - we want all posts to calculate baseline.

        Args:
            username: TikTok username (without @)
            count: Number of posts to fetch
            timeout: Apify timeout in seconds

        Returns:
            DataFrame with all user posts
        """
        logger.info(f"Scraping TikTok user: @{username}")

        # Start Apify run
        run_id = self._start_user_scrape_run(username, count)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning(f"No posts found for @{username}")
            return pd.DataFrame()

        # Normalize to DataFrame
        df = self._normalize_user_posts(items, username)

        logger.info(f"Scraped {len(df)} posts from @{username}")

        return df

    def fetch_video_by_url(
        self,
        url: str,
        timeout: int = 300
    ) -> pd.DataFrame:
        """
        Fetch a single TikTok video by URL

        Supports all TikTok URL formats:
        - https://www.tiktok.com/@username/video/7123456789
        - https://vt.tiktok.com/ZS12345/
        - https://vm.tiktok.com/ZS12345/

        Uses ScrapTik's post_awemeId endpoint to fetch single video.

        Args:
            url: TikTok video URL
            timeout: Apify timeout in seconds

        Returns:
            DataFrame with single video metadata
        """
        logger.info(f"Fetching TikTok video from URL: {url}")

        # Extract aweme_id from URL
        import re
        match = re.search(r'/video/(\d+)', url)
        if not match:
            raise ValueError(f"Could not extract video ID from URL: {url}. Expected format: https://www.tiktok.com/@username/video/ID")

        aweme_id = match.group(1)
        logger.info(f"Extracted aweme_id: {aweme_id}")

        # Start Apify run with post_awemeId
        run_id = self._start_post_fetch_run(aweme_id)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No video data returned from URL")
            return pd.DataFrame()

        # Normalize single post to DataFrame
        df = self._normalize_single_post(items)

        if len(df) > 0:
            logger.info(f"Fetched video: @{df.iloc[0]['username']}, {df.iloc[0]['views']:,} views")
        else:
            logger.warning("Failed to parse video data")

        return df

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_keyword_search_run(
        self,
        keyword: str,
        count: int = 50,
        sort_type: int = 0,
        publish_time: int = 0
    ) -> str:
        """
        Start Apify run for keyword search

        Args:
            keyword: Search keyword
            count: Number of posts to retrieve
            sort_type: 0=Relevance, 1=Most Liked, 3=Date
            publish_time: 0=All, 1=Yesterday, 7=Week, 30=Month, 90=3mo, 180=6mo

        Returns:
            Apify run ID
        """
        actor_input = {
            "searchPosts_keyword": keyword,
            "searchPosts_count": count,
            "searchPosts_sortType": sort_type,
            "searchPosts_publishTime": publish_time,
            "searchPosts_useFilters": True if publish_time > 0 or sort_type > 0 else False,
            "searchPosts_offset": 0
        }

        logger.info(f"Starting keyword search: '{keyword}' (count={count}, sort={sort_type})")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_hashtag_search_run(self, hashtag: str, count: int = 50) -> str:
        """
        Start Apify run for hashtag search

        Note: We need to get the challenge ID (cid) first, then fetch posts.
        For simplicity, we'll use searchHashtags to find the hashtag, then use challengePosts.

        Args:
            hashtag: Hashtag name (without #)
            count: Number of posts to retrieve

        Returns:
            Apify run ID
        """
        # For now, use searchPosts with hashtag query
        # TODO: Implement proper challengePosts endpoint after getting cid
        actor_input = {
            "searchPosts_keyword": f"#{hashtag}",
            "searchPosts_count": count,
            "searchPosts_offset": 0
        }

        logger.info(f"Starting hashtag search: #{hashtag} (count={count})")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_user_scrape_run(self, username: str, count: int = 50) -> str:
        """
        Start Apify run for user posts scraping

        Note: We need user_id or sec_user_id. We'll use usernameToId endpoint first,
        then userPosts endpoint.

        For simplicity, we'll do this in a single run by providing the username
        and letting ScrapTik handle the ID conversion.

        Args:
            username: TikTok username (without @)
            count: Number of posts to retrieve

        Returns:
            Apify run ID
        """
        # First, get user ID from username
        # We'll need to make 2 API calls: one for username->ID, one for posts
        # For now, let's use a simpler approach with searchUsers then userPosts

        actor_input = {
            "usernameToId_username": username,
            "userPosts_count": count,
            "userPosts_maxCursor": "0"
        }

        logger.info(f"Starting user scrape: @{username} (count={count})")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_post_fetch_run(self, aweme_id: str) -> str:
        """
        Start Apify run for single post fetch

        Uses ScrapTik's post_awemeId endpoint.

        Args:
            aweme_id: TikTok video ID (aweme_id)

        Returns:
            Apify run ID
        """
        actor_input = {
            "post_awemeId": aweme_id
        }

        logger.info(f"Starting post fetch for aweme_id: {aweme_id}")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_url_fetch_run(self, url: str) -> str:
        """
        Start Apify run for single video URL fetch

        Uses ScrapTik's videoWithoutWatermark endpoint which accepts URLs.
        This endpoint fetches video metadata + download URL.

        Args:
            url: TikTok video URL

        Returns:
            Apify run ID
        """
        # Extract aweme_id from URL for the videoWithoutWatermark endpoint
        # Format: https://www.tiktok.com/@username/video/7554020104241990943
        import re
        match = re.search(r'/video/(\d+)', url)
        if not match:
            raise ValueError(f"Could not extract video ID from URL: {url}")

        aweme_id = match.group(1)
        logger.info(f"Extracted aweme_id: {aweme_id}")

        # Use videoWithoutWatermark which accepts aweme_id
        actor_input = {
            "videoWithoutWatermark_aweme_id": aweme_id
        }

        logger.info(f"Starting URL fetch for aweme_id: {aweme_id}")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")

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
            List of post dictionaries
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

    def _normalize_search_posts(self, items: List[Dict]) -> pd.DataFrame:
        """
        Normalize TikTok search results to DataFrame

        ScrapTik searchPosts returns a wrapper object with search_item_list:
        {
          "search_item_list": [
            {"aweme_info": {...}},
            ...
          ]
        }

        Each aweme_info contains:
        {
          "aweme_id": "video_id",
          "author": {"unique_id": "username", "follower_count": 123, ...},
          "statistics": {"play_count": 1000, "digg_count": 50, "comment_count": 10, "share_count": 5},
          "video": {"duration": 15, "download_addr": "..."},
          "desc": "caption text",
          "create_time": 1234567890,
          ...
        }

        Args:
            items: Raw ScrapTik search response (list with wrapper object)

        Returns:
            DataFrame with normalized posts
        """
        normalized_data = []

        # Extract posts from wrapper
        posts = []
        for item in items:
            if "search_item_list" in item:
                for search_item in item["search_item_list"]:
                    if "aweme_info" in search_item:
                        posts.append(search_item["aweme_info"])

        logger.info(f"Extracted {len(posts)} posts from search results")

        for post in posts:
            try:
                # Extract core fields (note: TikTok API uses snake_case)
                author = post.get("author", {})
                stats = post.get("statistics", {})
                video = post.get("video", {})

                # Build post data
                aweme_id = post.get("aweme_id", "")
                username = author.get("unique_id", "")

                post_data = {
                    "post_id": aweme_id,
                    "post_url": f"https://www.tiktok.com/@{username}/video/{aweme_id}",
                    "username": username,
                    "display_name": author.get("nickname", ""),
                    "follower_count": author.get("follower_count", 0),
                    "is_verified": author.get("custom_verify", "") != "",

                    # Engagement metrics
                    "views": stats.get("play_count", 0),
                    "likes": stats.get("digg_count", 0),
                    "comments": stats.get("comment_count", 0),
                    "shares": stats.get("share_count", 0),

                    # Video metadata
                    "caption": post.get("desc", "")[:2200] if post.get("desc") else "",
                    "length_sec": video.get("duration", 0),
                    "download_url": video.get("download_addr", ""),

                    # Timestamp
                    "posted_at": datetime.fromtimestamp(post.get("create_time", 0)).isoformat() if post.get("create_time") else None,

                    # Platform
                    "platform_id": self.platform_id
                }

                # Validate essential fields
                if not post_data["post_id"] or not post_data["username"]:
                    logger.warning(f"Skipping post with missing essential fields")
                    continue

                normalized_data.append(post_data)

            except Exception as e:
                logger.warning(f"Error normalizing post: {e}")
                continue

        df = pd.DataFrame(normalized_data)

        if len(df) > 0:
            # Deduplicate by post_id
            original_count = len(df)
            df = df.drop_duplicates(subset=['post_id'], keep='first')
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate posts")

            logger.info(f"Normalized {len(df)} posts from {df['username'].nunique()} creators")
        else:
            logger.warning("No posts were successfully normalized")

        return df

    def _normalize_user_posts(self, items: List[Dict], username: str) -> pd.DataFrame:
        """
        Normalize TikTok user posts to DataFrame

        ScrapTik userPosts returns similar structure to searchPosts.

        Args:
            items: Raw ScrapTik user post data
            username: TikTok username

        Returns:
            DataFrame with normalized posts
        """
        # Use same normalization as search posts
        df = self._normalize_search_posts(items)

        # Filter to only this user (in case API returned extra data)
        if len(df) > 0:
            df = df[df['username'] == username]

        return df

    def _normalize_single_post(self, items: List[Dict]) -> pd.DataFrame:
        """
        Normalize a single TikTok post to DataFrame

        ScrapTik post_awemeId returns: {"aweme_detail": {...}, "status_code": 0, ...}

        Args:
            items: Raw ScrapTik post data (single item)

        Returns:
            DataFrame with normalized post
        """
        if not items or len(items) == 0:
            return pd.DataFrame()

        response = items[0]

        # Extract aweme_detail from response
        if "aweme_detail" in response:
            post = response["aweme_detail"]
            # Wrap it like search results for consistent normalization
            wrapped_items = [{"search_item_list": [{"aweme_info": post}]}]
            return self._normalize_search_posts(wrapped_items)
        elif "aweme_id" in response:
            # Direct post format - wrap it like search results
            wrapped_items = [{"search_item_list": [{"aweme_info": response}]}]
            return self._normalize_search_posts(wrapped_items)
        else:
            # Try normalizing as-is
            logger.warning(f"Unexpected post format. Keys: {list(response.keys())}")
            return pd.DataFrame()

    def _apply_viral_filters(
        self,
        df: pd.DataFrame,
        min_views: int = 100000,
        max_days_old: int = 10,
        max_follower_count: int = 50000
    ) -> pd.DataFrame:
        """
        Apply viral filtering criteria to posts

        Filters:
        1. Views: Must have over min_views (default: 100K)
        2. Recency: Must be less than max_days_old (default: 10 days)
        3. Creator size: Account must have less than max_follower_count (default: 50K)

        Args:
            df: DataFrame with posts
            min_views: Minimum view count
            max_days_old: Maximum age in days
            max_follower_count: Maximum creator follower count

        Returns:
            Filtered DataFrame
        """
        if len(df) == 0:
            return df

        original_count = len(df)

        # Filter 1: Views
        df = df[df['views'] >= min_views]
        logger.info(f"After views filter (>={min_views:,}): {len(df)}/{original_count} posts")

        # Filter 2: Recency
        if 'posted_at' in df.columns:
            cutoff_date = datetime.now() - timedelta(days=max_days_old)
            df['posted_at_dt'] = pd.to_datetime(df['posted_at'])
            df = df[df['posted_at_dt'] >= cutoff_date]
            df = df.drop(columns=['posted_at_dt'])
            logger.info(f"After recency filter (<{max_days_old} days): {len(df)}/{original_count} posts")

        # Filter 3: Creator size
        df = df[df['follower_count'] < max_follower_count]
        logger.info(f"After creator size filter (<{max_follower_count:,} followers): {len(df)}/{original_count} posts")

        return df

    def save_posts_to_db(
        self,
        df: pd.DataFrame,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        import_source: str = "scrape"
    ) -> List[str]:
        """
        Save posts to database with platform_id and optional project/brand link

        Args:
            df: DataFrame with posts
            project_id: Optional project UUID to link posts to
            brand_id: Optional brand UUID to link posts to
            import_source: How posts were imported (scrape, direct_url, csv_import)

        Returns:
            List of post UUIDs
        """
        if len(df) == 0:
            logger.warning("No posts to save")
            return []

        # First, upsert accounts (if they don't exist)
        account_ids = self._upsert_accounts(df)

        # Prepare posts data
        posts_data = []
        for _, row in df.iterrows():
            post_dict = {
                "account_id": account_ids.get(row['username']),
                "platform_id": self.platform_id,
                "post_url": row['post_url'],
                "post_id": row['post_id'],
                "posted_at": row.get('posted_at'),
                "views": int(row.get('views', 0)) if pd.notna(row.get('views')) else None,
                "likes": int(row.get('likes', 0)) if pd.notna(row.get('likes')) else None,
                "comments": int(row.get('comments', 0)) if pd.notna(row.get('comments')) else None,
                "caption": row.get('caption'),
                "length_sec": int(row.get('length_sec', 0)) if pd.notna(row.get('length_sec')) else None,
                "import_source": import_source,
                "is_own_content": False
            }

            # Add TikTok-specific fields to caption or metadata
            # For now, store shares in caption metadata
            if pd.notna(row.get('shares')):
                post_dict['caption'] = f"{post_dict.get('caption', '')}\n[TikTok shares: {int(row['shares'])}]".strip()

            posts_data.append(post_dict)

        # Upsert posts
        post_ids = []
        chunk_size = 1000
        chunks = [posts_data[i:i + chunk_size] for i in range(0, len(posts_data), chunk_size)]

        for chunk in tqdm(chunks, desc="Saving posts to database"):
            try:
                result = self.supabase.table("posts").upsert(
                    chunk,
                    on_conflict="post_url"
                ).execute()

                for post in result.data:
                    post_ids.append(post['id'])

            except Exception as e:
                logger.error(f"Error upserting posts chunk: {e}")
                continue

        logger.info(f"Saved {len(post_ids)} posts to database")

        # Link to project if provided
        if project_id and post_ids:
            self._link_posts_to_project(post_ids, project_id, import_source)

        # Link to brand if provided
        if brand_id and post_ids:
            self._link_posts_to_brand(post_ids, brand_id, import_source)

        return post_ids

    def _upsert_accounts(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Upsert TikTok accounts to database

        Args:
            df: DataFrame with username, display_name, follower_count, is_verified

        Returns:
            Dict mapping username to account_id
        """
        # Get unique accounts
        accounts_df = df[['username', 'display_name', 'follower_count', 'is_verified']].drop_duplicates(subset=['username'])

        account_ids = {}

        for _, row in tqdm(accounts_df.iterrows(), total=len(accounts_df), desc="Upserting accounts"):
            try:
                username = row['username']

                # Check if account exists
                existing = self.supabase.table('accounts')\
                    .select('id')\
                    .eq('platform_id', self.platform_id)\
                    .eq('platform_username', username)\
                    .execute()

                if existing.data and len(existing.data) > 0:
                    # Account exists, update metadata
                    account_id = existing.data[0]['id']

                    update_data = {
                        "follower_count": int(row['follower_count']) if pd.notna(row['follower_count']) else None,
                        "display_name": row.get('display_name'),
                        "is_verified": bool(row.get('is_verified', False)),
                        "last_scraped_at": datetime.now().isoformat(),
                        "metadata_updated_at": datetime.now().isoformat()
                    }

                    self.supabase.table('accounts').update(update_data).eq('id', account_id).execute()

                else:
                    # Create new account
                    account_data = {
                        "handle": username,  # Legacy field
                        "platform_id": self.platform_id,
                        "platform_username": username,
                        "follower_count": int(row['follower_count']) if pd.notna(row['follower_count']) else None,
                        "display_name": row.get('display_name'),
                        "is_verified": bool(row.get('is_verified', False)),
                        "last_scraped_at": datetime.now().isoformat(),
                        "metadata_updated_at": datetime.now().isoformat()
                    }

                    result = self.supabase.table('accounts').insert(account_data).execute()
                    account_id = result.data[0]['id']

                account_ids[username] = account_id

            except Exception as e:
                logger.error(f"Error upserting account {username}: {e}")
                continue

        logger.info(f"Upserted {len(account_ids)} accounts")

        return account_ids

    def _link_posts_to_project(
        self,
        post_ids: List[str],
        project_id: str,
        import_method: str = "scrape"
    ):
        """
        Link posts to project via project_posts table

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
                'notes': f"TikTok scrape on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking posts to project"):
            try:
                result = self.supabase.table("project_posts").upsert(
                    chunk,
                    on_conflict="project_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking posts chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} posts to project")

    def _link_posts_to_brand(
        self,
        post_ids: List[str],
        brand_id: str,
        import_method: str = "scrape"
    ):
        """
        Link posts to brand via brand_posts table

        Args:
            post_ids: List of post UUIDs
            brand_id: Brand UUID
            import_method: How posts were imported
        """
        links_data = []

        for post_id in post_ids:
            links_data.append({
                'brand_id': brand_id,
                'post_id': post_id,
                'import_method': import_method,
                'is_own_content': False,
                'notes': f"TikTok URL import on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking posts to brand"):
            try:
                result = self.supabase.table("brand_posts").upsert(
                    chunk,
                    on_conflict="brand_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking posts chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} posts to brand")
