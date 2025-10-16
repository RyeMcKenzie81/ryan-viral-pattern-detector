"""
YouTube Shorts scraper using streamers/youtube-shorts-scraper Apify actor

Scrapes YouTube Shorts for channels linked to a project.
Follows the same pattern as Instagram scraper for per-account outlier detection.
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


class YouTubeScraper:
    """
    YouTube Shorts scraper for ViralTracker using Apify

    Scrapes YouTube channels linked to a project and stores Shorts
    with proper multi-brand schema relationships.
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize YouTube Shorts scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to streamers/youtube-shorts-scraper)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or "streamers/youtube-shorts-scraper"
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

    def scrape_project(
        self,
        project_slug: str,
        max_results: int = 50,
        days_back: Optional[int] = None,
        sort_by: str = "NEWEST",
        timeout: int = 300
    ) -> Tuple[int, int]:
        """
        Scrape all YouTube channels linked to a project

        Args:
            project_slug: Project slug
            max_results: Maximum Shorts per channel
            days_back: Only scrape Shorts from last N days (optional)
            sort_by: Sort order (NEWEST, POPULAR, OLDEST)
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (channels_scraped, shorts_scraped)
        """
        # Get project
        project_result = self.supabase.table('projects').select('id, name').eq('slug', project_slug).single().execute()
        if not project_result.data:
            raise ValueError(f"Project '{project_slug}' not found")

        project_id = project_result.data['id']
        project_name = project_result.data['name']

        logger.info(f"Scraping project: {project_name}")

        # Get accounts linked to project
        accounts_result = self.supabase.table('project_accounts').select('''
            accounts!inner(
                id,
                platform_username,
                platform_id,
                platforms!inner(id, slug)
            )
        ''').eq('project_id', project_id).execute()

        if not accounts_result.data:
            raise ValueError(f"No accounts found for project '{project_slug}'")

        # Filter for YouTube channels only
        youtube_channels = []
        for item in accounts_result.data:
            if item['accounts']['platforms']['slug'] == 'youtube_shorts':
                youtube_channels.append({
                    'account_id': item['accounts']['id'],
                    'username': item['accounts']['platform_username'],
                    'platform_id': item['accounts']['platform_id']
                })

        if not youtube_channels:
            raise ValueError(f"No YouTube channels found for project '{project_slug}'")

        platform_id = youtube_channels[0]['platform_id']  # All should have same platform_id
        channel_names = [ch['username'] for ch in youtube_channels]

        logger.info(f"Found {len(channel_names)} YouTube channels to scrape")

        # Start Apify scrape
        run_id = self._start_apify_run(channel_names, max_results, days_back, sort_by)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch and normalize data
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No data returned from Apify")
            return (len(channel_names), 0)

        # Normalize items and extract channel metadata
        df, channel_metadata = self._normalize_items(items)

        # Filter to only requested channels
        if len(df) > 0:
            original_count = len(df)
            df = df[df['channel'].isin(channel_names)]
            filtered_count = original_count - len(df)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} Shorts from unrelated channels")

        if len(df) == 0:
            logger.warning("No Shorts to process after filtering")
            return (len(channel_names), 0)

        # Create channel mapping (username -> account_id, platform_id)
        channel_map = {
            ch['username']: {
                'account_id': ch['account_id'],
                'platform_id': ch['platform_id']
            }
            for ch in youtube_channels
        }

        # Upsert channels (update last_scraped_at and metadata)
        self._upsert_channels(df, channel_map, platform_id, channel_metadata)

        # Upsert posts (with platform_id, import_source)
        post_ids = self._upsert_posts(df, channel_map)

        # Link posts to project
        self._link_posts_to_project(post_ids, project_id)

        # Populate metadata for imported URLs
        updated_count = self._populate_imported_url_metadata(df)
        if updated_count > 0:
            logger.info(f"Populated metadata for {updated_count} imported URLs")

        return (len(channel_names), len(post_ids))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_apify_run(
        self,
        channel_names: List[str],
        max_results: int = 50,
        days_back: Optional[int] = None,
        sort_by: str = "NEWEST"
    ) -> str:
        """
        Start Apify actor run for YouTube Shorts scraping

        Args:
            channel_names: List of YouTube channel usernames (without @)
            max_results: Maximum Shorts per channel
            days_back: Only scrape Shorts from last N days
            sort_by: Sort order (NEWEST, POPULAR, OLDEST)

        Returns:
            Apify run ID
        """
        actor_input = {
            "channels": channel_names,
            "maxResultsShorts": max_results,
            "sortChannelShortsBy": sort_by
        }

        if days_back:
            # Format days_back as a relative time string (e.g., "90 days")
            actor_input["oldestPostDate"] = f"{days_back} days"

        logger.info(f"Starting Apify run for {len(channel_names)} channels (max_results={max_results}, sort={sort_by})")

        # Use Apify client to start the run (use .start() not .call() to avoid SDK timeout)
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
            List of Shorts dictionaries
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
            logger.info(f"DEBUG - First item keys: {list(first_item.keys())[:15]}")
            logger.info(f"DEBUG - Has 'channelUsername': {'channelUsername' in first_item}")
            logger.info(f"DEBUG - Has 'title': {'title' in first_item}")

        return items

    def _normalize_items(self, items: List[Dict]) -> Tuple[pd.DataFrame, Dict[str, Dict]]:
        """
        Normalize Apify items to standard DataFrame format and extract channel metadata

        Apify streamers/youtube-shorts-scraper returns Shorts with embedded channel data:
        {
          "title": "...",
          "id": "VIDEO_ID",
          "url": "https://www.youtube.com/shorts/VIDEO_ID",
          "viewCount": 1180,
          "date": "2025-06-24T10:01:00.000Z",
          "likes": 198,
          "commentsCount": 0,
          "channelUsername": "username",
          "channelName": "Channel Name",
          "numberOfSubscribers": 1390000,
          "isChannelVerified": false,
          "duration": "00:00:26",
          "text": "Description",
          ...
        }

        Args:
            items: Raw Apify Shorts data (each item is a Short)

        Returns:
            Tuple of (shorts_df, channel_metadata_dict)
        """
        normalized_data = []
        channel_metadata = {}

        for short in items:
            try:
                # Extract channel username
                channel_username = short.get("channelUsername", "")
                if not channel_username:
                    logger.warning("Skipping Short with no channel username")
                    continue

                # Extract channel metadata (collect from all Shorts, will use latest)
                if channel_username:
                    channel_metadata[channel_username] = {
                        "follower_count": short.get("numberOfSubscribers", 0),
                        "display_name": short.get("channelName", ""),
                        "is_verified": short.get("isChannelVerified", False),
                        "channel_id": short.get("channelId", ""),
                    }

                # Parse duration (format: "00:00:26" -> seconds)
                duration_str = short.get("duration", "00:00:00")
                duration_sec = self._parse_duration(duration_str)

                # Parse date
                date_str = short.get("date")
                posted_at = None
                if date_str:
                    try:
                        # ISO format from Apify
                        posted_at = datetime.fromisoformat(date_str.replace('Z', '+00:00')).isoformat()
                    except:
                        pass

                video_id = short.get("id", "")
                if not video_id:
                    logger.warning("Skipping Short with no video ID")
                    continue

                post_data = {
                    "channel": channel_username,
                    "post_url": short.get("url", f"https://www.youtube.com/shorts/{video_id}"),
                    "post_id": video_id,
                    "posted_at": posted_at,
                    "likes": short.get("likes", 0) or 0,
                    "comments": short.get("commentsCount", 0) or 0,
                    "caption": (short.get("text", "") or "")[:2200],
                    "title": (short.get("title", "") or "")[:500],
                    "length_sec": duration_sec
                }

                # Handle views
                views = short.get("viewCount", 0) or 0
                post_data["views"] = max(0, int(views)) if views is not None else 0

                # Validate and convert data types
                post_data["likes"] = max(0, int(post_data["likes"]) if post_data["likes"] else 0)
                post_data["comments"] = max(0, int(post_data["comments"]) if post_data["comments"] else 0)

                if post_data["length_sec"]:
                    try:
                        post_data["length_sec"] = max(1, min(3600, int(post_data["length_sec"])))
                    except:
                        post_data["length_sec"] = None

                # Skip if essential fields are missing
                if not post_data["post_url"] or not post_data["channel"]:
                    logger.warning(f"Skipping Short with missing essential fields")
                    continue

                normalized_data.append(post_data)

            except Exception as e:
                logger.warning(f"Error normalizing Short: {e}")
                continue

        df = pd.DataFrame(normalized_data)
        if len(df) > 0:
            # Deduplicate by post_url (keep first occurrence)
            original_count = len(df)
            df = df.drop_duplicates(subset=['post_url'], keep='first')
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate Shorts")

            logger.info(f"Normalized {len(df)} Shorts from {df['channel'].nunique()} channels")
            logger.info(f"Extracted metadata for {len(channel_metadata)} channels")
        else:
            logger.warning("No Shorts were successfully normalized")

        return df, channel_metadata

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

    def _upsert_channels(
        self,
        df: pd.DataFrame,
        channel_map: Dict[str, Dict],
        platform_id: str,
        channel_metadata: Dict[str, Dict]
    ):
        """
        Update last_scraped_at and metadata for channels

        Args:
            df: DataFrame with 'channel' column
            channel_map: Mapping of username to account_id and platform_id
            platform_id: Platform UUID
            channel_metadata: Channel metadata extracted from Apify
        """
        unique_channels = df['channel'].unique().tolist()

        for channel in tqdm(unique_channels, desc="Updating channels"):
            try:
                if channel in channel_map:
                    account_id = channel_map[channel]['account_id']

                    # Build update data
                    update_data = {
                        "last_scraped_at": datetime.now().isoformat()
                    }

                    # Add metadata if available for this channel
                    if channel in channel_metadata:
                        metadata = channel_metadata[channel]

                        # Add all metadata fields
                        if metadata.get('follower_count') is not None:
                            update_data['follower_count'] = int(metadata['follower_count'])
                        if metadata.get('display_name'):
                            update_data['display_name'] = metadata['display_name']
                        if metadata.get('is_verified') is not None:
                            update_data['is_verified'] = metadata['is_verified']

                        # Update metadata timestamp
                        update_data['metadata_updated_at'] = datetime.now().isoformat()

                    # Update account
                    self.supabase.table("accounts").update(update_data).eq("id", account_id).execute()
                else:
                    logger.warning(f"Channel {channel} not in channel_map, skipping")

            except Exception as e:
                logger.error(f"Error updating channel {channel}: {e}")
                continue

        logger.info(f"Updated {len(unique_channels)} channels with metadata")

    def _upsert_posts(
        self,
        df: pd.DataFrame,
        channel_map: Dict[str, Dict]
    ) -> List[str]:
        """
        Upsert Shorts to database with platform_id and import_source

        Args:
            df: Normalized Shorts DataFrame
            channel_map: Mapping of username to account_id and platform_id

        Returns:
            List of post UUIDs
        """
        # Add account_id and platform_id to DataFrame
        df['account_id'] = df['channel'].map(lambda x: channel_map.get(x, {}).get('account_id'))
        df['platform_id'] = df['channel'].map(lambda x: channel_map.get(x, {}).get('platform_id'))

        # Remove rows where account_id or platform_id is missing
        df = df.dropna(subset=['account_id', 'platform_id'])

        # Prepare data for upsert
        posts_data = df[[
            'account_id', 'platform_id', 'post_url', 'post_id', 'posted_at',
            'views', 'likes', 'comments', 'caption', 'length_sec'
        ]].replace({pd.NA: None, float('nan'): None}).to_dict('records')

        # Add import_source to all posts
        for post in posts_data:
            post['import_source'] = 'scrape'
            # Clean up None values and ensure integers
            for key, value in post.items():
                if pd.isna(value):
                    post[key] = None
                elif key in ['views', 'likes', 'comments', 'length_sec'] and value is not None:
                    try:
                        post[key] = int(value)
                    except (ValueError, TypeError):
                        post[key] = None

        # Process in chunks (1000 at a time)
        chunk_size = 1000
        total_posts = len(posts_data)
        chunks = [posts_data[i:i + chunk_size] for i in range(0, total_posts, chunk_size)]

        post_ids = []

        for chunk in tqdm(chunks, desc="Upserting Shorts"):
            try:
                # Use upsert to handle duplicates
                result = self.supabase.table("posts").upsert(
                    chunk,
                    on_conflict="post_url"
                ).execute()

                # Collect post IDs
                for post in result.data:
                    post_ids.append(post['id'])

            except Exception as e:
                logger.error(f"Error upserting Shorts chunk: {e}")
                continue

        logger.info(f"Upserted {len(post_ids)} Shorts")
        return post_ids

    def _link_posts_to_project(
        self,
        post_ids: List[str],
        project_id: str
    ):
        """
        Link Shorts to project via project_posts table

        Args:
            post_ids: List of post UUIDs
            project_id: Project UUID
        """
        links_data = []

        for post_id in post_ids:
            links_data.append({
                'project_id': project_id,
                'post_id': post_id,
                'import_method': 'scrape',
                'is_own_content': False,
                'notes': f"Scraped on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking Shorts to project"):
            try:
                # Use upsert to handle duplicates
                result = self.supabase.table("project_posts").upsert(
                    chunk,
                    on_conflict="project_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking Shorts chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} Shorts to project")

    def _populate_imported_url_metadata(self, df: pd.DataFrame) -> int:
        """
        Populate metadata for URLs that were imported without metadata

        This finds Shorts that have the same URL as scraped Shorts but are
        missing metadata (views, likes, etc.), and populates them.

        Args:
            df: DataFrame with scraped Shorts

        Returns:
            Number of Shorts updated
        """
        if len(df) == 0:
            return 0

        # Get all URLs from this scrape batch
        scraped_urls = df['post_url'].unique().tolist()

        if not scraped_urls:
            return 0

        # Find posts with same URLs but missing metadata (views is NULL)
        # Process in batches to avoid URL too long errors
        batch_size = 100
        posts_to_update = []

        for i in range(0, len(scraped_urls), batch_size):
            batch = scraped_urls[i:i + batch_size]
            try:
                result = self.supabase.table('posts')\
                    .select('id, post_url')\
                    .in_('post_url', batch)\
                    .is_('views', 'null')\
                    .execute()

                if result.data:
                    posts_to_update.extend(result.data)

            except Exception as e:
                logger.warning(f"Error querying posts batch: {e}")
                continue

        if not posts_to_update:
            return 0

        # Create URL to data mapping from scraped Shorts
        url_data_map = {}
        for _, row in df.iterrows():
            url_data_map[row['post_url']] = {
                'views': row.get('views'),
                'likes': row.get('likes'),
                'comments': row.get('comments'),
                'caption': row.get('caption'),
                'posted_at': row.get('posted_at'),
                'length_sec': row.get('length_sec')
            }

        # Update each post
        updated_count = 0
        for post in tqdm(posts_to_update, desc="Populating imported URL metadata"):
            try:
                url = post['post_url']
                if url in url_data_map:
                    data = url_data_map[url]

                    # Clean up data
                    update_data = {}
                    for key, value in data.items():
                        if pd.notna(value):
                            if key in ['views', 'likes', 'comments', 'length_sec']:
                                update_data[key] = int(value)
                            else:
                                update_data[key] = value

                    if update_data:
                        self.supabase.table('posts').update(update_data).eq('id', post['id']).execute()
                        updated_count += 1

            except Exception as e:
                logger.warning(f"Error updating post {post['id']}: {e}")
                continue

        return updated_count
