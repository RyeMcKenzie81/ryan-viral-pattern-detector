"""
Instagram scraper using Apify actor

Scrapes Instagram posts for accounts linked to a project.
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


class InstagramScraper:
    """
    Instagram scraper for ViralTracker using Apify

    Scrapes Instagram accounts linked to a project and stores posts
    with proper multi-brand schema relationships.
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize Instagram scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to apify/instagram-scraper)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or os.getenv("APIFY_ACTOR_ID", "apify/instagram-scraper")
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

    def scrape_project(
        self,
        project_slug: str,
        days_back: int = 120,
        post_type: str = "reels",
        timeout: int = 300
    ) -> Tuple[int, int]:
        """
        Scrape all accounts linked to a project

        Args:
            project_slug: Project slug
            days_back: Number of days to scrape back
            post_type: Type of posts (reels, posts, tagged)
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (accounts_scraped, posts_scraped)
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

        # Filter for Instagram accounts only
        instagram_accounts = []
        for item in accounts_result.data:
            if item['accounts']['platforms']['slug'] == 'instagram':
                instagram_accounts.append({
                    'account_id': item['accounts']['id'],
                    'username': item['accounts']['platform_username'],
                    'platform_id': item['accounts']['platform_id']
                })

        if not instagram_accounts:
            raise ValueError(f"No Instagram accounts found for project '{project_slug}'")

        platform_id = instagram_accounts[0]['platform_id']  # All should have same platform_id
        usernames = [acc['username'] for acc in instagram_accounts]

        logger.info(f"Found {len(usernames)} Instagram accounts to scrape")

        # Start Apify scrape
        run_id = self._start_apify_run(usernames, days_back, post_type)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch and normalize data
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No data returned from Apify")
            return (len(usernames), 0)

        # Normalize items and extract account metadata
        df, account_metadata = self._normalize_items(items)

        # Filter to only requested accounts
        if len(df) > 0:
            original_count = len(df)
            df = df[df['account'].isin(usernames)]
            filtered_count = original_count - len(df)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} posts from unrelated accounts")

        if len(df) == 0:
            logger.warning("No posts to process after filtering")
            return (len(usernames), 0)

        # Create account mapping (username -> account_id, platform_id)
        account_map = {
            acc['username']: {
                'account_id': acc['account_id'],
                'platform_id': acc['platform_id']
            }
            for acc in instagram_accounts
        }

        # Upsert accounts (update last_scraped_at and metadata)
        self._upsert_accounts(df, account_map, platform_id, account_metadata)

        # Upsert posts (with platform_id, import_source)
        post_ids = self._upsert_posts(df, account_map)

        # Link posts to project
        self._link_posts_to_project(post_ids, project_id)

        # Populate metadata for imported URLs
        updated_count = self._populate_imported_url_metadata(df)
        if updated_count > 0:
            logger.info(f"Populated metadata for {updated_count} imported URLs")

        return (len(usernames), len(post_ids))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_apify_run(
        self,
        usernames: List[str],
        days_back: int = 120,
        post_type: str = "reels"
    ) -> str:
        """
        Start Apify actor run for Instagram scraping

        Args:
            usernames: List of Instagram usernames
            days_back: Number of days to scrape back
            post_type: Type of posts to scrape

        Returns:
            Apify run ID
        """
        # Convert usernames to Instagram profile URLs
        direct_urls = [f"https://www.instagram.com/{username}/" for username in usernames]

        actor_input = {
            "directUrls": direct_urls,
            "resultsType": "details",  # Get profile details with metadata and latestPosts
            "resultsLimit": 200,
            "onlyPostsNewerThan": f"{days_back} days",
            "addParentData": False,
            "maxRequestRetries": 3,
            "enhanceUserSearchWithFacebookPage": False
        }

        # Note: NOT using isUserReelFeedURL because it prevents profile metadata from being returned
        # With resultsType: "details", we get profile objects with latestPosts arrays

        logger.info(f"Starting Apify run for {len(usernames)} usernames ({days_back} days back, {post_type})")

        # Use Apify client to start the run (handles "apify/instagram-scraper" format correctly)
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
            logger.info(f"DEBUG - First item keys: {list(first_item.keys())[:15]}")
            logger.info(f"DEBUG - Has 'username': {'username' in first_item}")
            logger.info(f"DEBUG - Has 'latestPosts': {'latestPosts' in first_item}")
            logger.info(f"DEBUG - Has 'ownerUsername': {'ownerUsername' in first_item}")
            if 'latestPosts' in first_item:
                logger.info(f"DEBUG - latestPosts count: {len(first_item.get('latestPosts', []))}")

        return items

    def _normalize_items(self, items: List[Dict]) -> Tuple[pd.DataFrame, Dict[str, Dict]]:
        """
        Normalize Apify items to standard DataFrame format and extract account metadata

        Apify returns profile-level data:
        {
          "username": "...",
          "fullName": "...",
          "biography": "...",
          "followersCount": 123,
          "latestPosts": [...]
        }

        Args:
            items: Raw Apify profile data (each item is a profile with posts)

        Returns:
            Tuple of (posts_df, account_metadata_dict)
        """
        normalized_data = []
        account_metadata = {}

        for profile in items:
            try:
                # Extract account metadata from profile level
                username = profile.get("username", "unknown")

                if username and username not in account_metadata:
                    # Map Apify profile fields to our schema
                    account_metadata[username] = {
                        "follower_count": profile.get("followersCount"),
                        "following_count": profile.get("followsCount"),
                        "bio": profile.get("biography"),
                        "display_name": profile.get("fullName"),
                        "profile_pic_url": profile.get("profilePicUrlHD") or profile.get("profilePicUrl"),
                        "is_verified": profile.get("verified", False),
                        "account_type": "business" if profile.get("isBusinessAccount") else "personal",
                        "external_url": profile.get("externalUrl"),
                    }

                # Extract posts from latestPosts array
                latest_posts = profile.get("latestPosts", [])

                for post in latest_posts:
                    post_data = {
                        "account": username,
                        "post_url": f"https://www.instagram.com/p/{post.get('shortCode')}/" if post.get('shortCode') else "",
                        "post_id": post.get("shortCode", ""),
                        "posted_at": post.get("timestamp"),
                        "likes": post.get("likesCount", 0),
                        "comments": post.get("commentsCount", 0),
                        "caption": post.get("caption", "")[:2200] if post.get("caption") else "",
                        "length_sec": post.get("videoDuration")
                    }

                    # Handle views (priority: videoViewCount > likesCount)
                    views = post.get("videoViewCount") or post.get("likesCount", 0)
                    post_data["views"] = max(0, int(views)) if views is not None else 0

                    # Validate and convert data types
                    post_data["likes"] = max(0, int(post_data["likes"]) if post_data["likes"] else 0)
                    post_data["comments"] = max(0, int(post_data["comments"]) if post_data["comments"] else 0)

                    if post_data["length_sec"]:
                        try:
                            post_data["length_sec"] = max(1, min(3600, int(float(post_data["length_sec"]))))
                        except:
                            post_data["length_sec"] = None

                    # Parse timestamp
                    if post_data["posted_at"]:
                        try:
                            post_data["posted_at"] = pd.to_datetime(post_data["posted_at"]).isoformat()
                        except:
                            post_data["posted_at"] = None

                    # Skip if essential fields are missing
                    if not post_data["post_url"] or not post_data["account"]:
                        logger.warning(f"Skipping post with missing essential fields")
                        continue

                    normalized_data.append(post_data)

            except Exception as e:
                logger.warning(f"Error normalizing profile: {e}")
                continue

        df = pd.DataFrame(normalized_data)
        if len(df) > 0:
            # Deduplicate by post_url (keep first occurrence)
            original_count = len(df)
            df = df.drop_duplicates(subset=['post_url'], keep='first')
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate posts")

            logger.info(f"Normalized {len(df)} posts from {df['account'].nunique()} accounts")
            logger.info(f"Extracted metadata for {len(account_metadata)} accounts")
        else:
            logger.warning("No posts were successfully normalized")

        return df, account_metadata

    def _upsert_accounts(
        self,
        df: pd.DataFrame,
        account_map: Dict[str, Dict],
        platform_id: str,
        account_metadata: Dict[str, Dict]
    ):
        """
        Update last_scraped_at and metadata for accounts

        Args:
            df: DataFrame with 'account' column
            account_map: Mapping of username to account_id and platform_id
            platform_id: Platform UUID
            account_metadata: Account metadata extracted from Apify
        """
        unique_handles = df['account'].unique().tolist()

        for handle in tqdm(unique_handles, desc="Updating accounts"):
            try:
                if handle in account_map:
                    account_id = account_map[handle]['account_id']

                    # Build update data
                    update_data = {
                        "last_scraped_at": datetime.now().isoformat()
                    }

                    # Add metadata if available for this account
                    if handle in account_metadata:
                        metadata = account_metadata[handle]

                        # Add all metadata fields
                        if metadata.get('follower_count') is not None:
                            update_data['follower_count'] = int(metadata['follower_count'])
                        if metadata.get('following_count') is not None:
                            update_data['following_count'] = int(metadata['following_count'])
                        if metadata.get('bio'):
                            update_data['bio'] = metadata['bio']
                        if metadata.get('display_name'):
                            update_data['display_name'] = metadata['display_name']
                        if metadata.get('profile_pic_url'):
                            update_data['profile_pic_url'] = metadata['profile_pic_url']
                        if metadata.get('is_verified') is not None:
                            update_data['is_verified'] = metadata['is_verified']

                        # Update metadata timestamp
                        update_data['metadata_updated_at'] = datetime.now().isoformat()

                    # Update account
                    self.supabase.table("accounts").update(update_data).eq("id", account_id).execute()
                else:
                    logger.warning(f"Account {handle} not in account_map, skipping")

            except Exception as e:
                logger.error(f"Error updating account {handle}: {e}")
                continue

        logger.info(f"Updated {len(unique_handles)} accounts with metadata")

    def _upsert_posts(
        self,
        df: pd.DataFrame,
        account_map: Dict[str, Dict]
    ) -> List[str]:
        """
        Upsert posts to database with platform_id and import_source

        Args:
            df: Normalized posts DataFrame
            account_map: Mapping of username to account_id and platform_id

        Returns:
            List of post UUIDs
        """
        # Add account_id and platform_id to DataFrame
        df['account_id'] = df['account'].map(lambda x: account_map.get(x, {}).get('account_id'))
        df['platform_id'] = df['account'].map(lambda x: account_map.get(x, {}).get('platform_id'))

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

        for chunk in tqdm(chunks, desc="Upserting posts"):
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
                logger.error(f"Error upserting posts chunk: {e}")
                continue

        logger.info(f"Upserted {len(post_ids)} posts")
        return post_ids

    def _link_posts_to_project(
        self,
        post_ids: List[str],
        project_id: str
    ):
        """
        Link posts to project via project_posts table

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

        for chunk in tqdm(chunks, desc="Linking posts to project"):
            try:
                # Use upsert to handle duplicates
                result = self.supabase.table("project_posts").upsert(
                    chunk,
                    on_conflict="project_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking posts chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} posts to project")

    def _populate_imported_url_metadata(self, df: pd.DataFrame) -> int:
        """
        Populate metadata for URLs that were imported without metadata

        This finds posts that have the same URL as scraped posts but are
        missing metadata (views, likes, etc.), and populates them.

        Args:
            df: DataFrame with scraped posts

        Returns:
            Number of posts updated
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

        # Create URL to data mapping from scraped posts
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
