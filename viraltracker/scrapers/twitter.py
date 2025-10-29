"""
Twitter scraper using apidojo/tweet-scraper Apify actor

Supports 2 discovery modes:
1. Keyword search - Find viral content by keyword, hashtag, or advanced query
2. Account scraping - Scrape specific Twitter accounts with outlier detection

Phase 1: Simple filters (video, image, quote, verified, blue)
Phase 2: Advanced filters (geo, mentions, replies, etc.)
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta, timezone
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


class TwitterScraper:
    """
    Twitter scraper for ViralTracker using apidojo/tweet-scraper (Apify)

    Features:
    - Keyword/hashtag search with Twitter query language
    - Account scraping with date chunking (monthly/weekly/daily)
    - Outlier detection (3SD from trimmed mean)
    - Batch query processing (max 5 queries per run)
    - Engagement metrics: likes, retweets, replies, quotes, bookmarks

    Actor Limitations:
    - Max 1 concurrent run
    - Max 5 queries batched
    - Min 50 tweets per query (enforced)
    - No monitoring/real-time use
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize Twitter scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to apidojo/tweet-scraper)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or "apidojo/tweet-scraper"
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

        # Get Twitter platform ID
        self.platform_id = self._get_platform_id()

    def _get_platform_id(self) -> str:
        """Get Twitter platform UUID from database"""
        result = self.supabase.table('platforms').select('id').eq('slug', 'twitter').single().execute()
        if not result.data:
            raise ValueError("Twitter platform not found in database. Run migration 2025-10-16_add_twitter_platform.sql")
        return result.data['id']

    def scrape_search(
        self,
        search_terms: List[str],
        max_tweets: int = 100,
        min_likes: Optional[int] = None,
        min_retweets: Optional[int] = None,
        min_replies: Optional[int] = None,
        min_quotes: Optional[int] = None,
        days_back: Optional[int] = None,
        only_video: bool = False,
        only_image: bool = False,
        only_quote: bool = False,
        only_verified: bool = False,
        only_blue: bool = False,
        raw_query: bool = False,
        sort: str = "Latest",
        language: str = "en",
        project_slug: Optional[str] = None,
        timeout: int = 300
    ) -> Dict:
        """
        Search Twitter by keywords/hashtags

        Args:
            search_terms: List of search terms or full Twitter queries (if raw_query=True)
            max_tweets: Tweets per term (minimum 50, enforced)
            min_likes: Minimum like count filter
            min_retweets: Minimum retweet count filter
            min_replies: Minimum reply count filter
            min_quotes: Minimum quote tweet count filter
            days_back: Only tweets from last N days
            only_video: Only tweets with video
            only_image: Only tweets with images
            only_quote: Only quote tweets
            only_verified: Only verified users
            only_blue: Only Twitter Blue users
            raw_query: Use search_terms as-is (don't build query)
            sort: "Latest" or "Top"
            language: Tweet language ISO code (default: en)
            project_slug: Project slug to link results
            timeout: Apify timeout in seconds

        Returns:
            Dict with keys:
                - terms_count: Number of search terms
                - tweets_count: Number of tweets scraped
                - apify_run_id: Apify actor run ID (single batch only)
                - apify_dataset_id: Apify dataset ID (single batch only)
        """
        if max_tweets < 50:
            raise ValueError("Minimum 50 tweets required per query (actor limitation)")

        logger.info(f"Searching Twitter for {len(search_terms)} terms")
        logger.info(f"Max tweets per term: {max_tweets}")

        # Build queries if not raw
        if not raw_query:
            queries = [
                self._build_twitter_query(
                    term, min_likes, min_retweets, min_replies, min_quotes, days_back,
                    only_video, only_image, only_quote
                )
                for term in search_terms
            ]
            logger.info(f"Built {len(queries)} Twitter queries")
        else:
            queries = search_terms
            logger.info(f"Using {len(queries)} raw queries")

        # Batch queries (max 5 per run)
        all_tweets = []
        batch_size = 5
        last_run_id = None
        last_dataset_id = None

        for i in range(0, len(queries), batch_size):
            batch = queries[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} queries")

            # Start Apify run
            run_id = self._start_search_run(
                batch, max_tweets, only_verified, only_blue,
                only_image, only_video, only_quote, sort, language
            )

            # Poll for completion
            result = self._poll_apify_run(run_id, timeout)

            # Fetch dataset
            items = self._fetch_dataset(result['datasetId'])

            all_tweets.extend(items)

            # Store IDs (for single batch scenarios)
            last_run_id = run_id
            last_dataset_id = result['datasetId']

        if not all_tweets:
            logger.warning("No tweets found")
            return {
                'terms_count': len(search_terms),
                'tweets_count': 0,
                'apify_run_id': last_run_id,
                'apify_dataset_id': last_dataset_id
            }

        # Normalize to DataFrame
        df = self._normalize_tweets(all_tweets)

        logger.info(f"Fetched {len(df)} tweets total")

        # Save to database
        project_id = None
        if project_slug:
            project_id = self._get_project_id(project_slug)

        post_ids = self.save_posts_to_db(df, project_id=project_id, import_source="search")

        return {
            'terms_count': len(search_terms),
            'tweets_count': len(post_ids),
            'apify_run_id': last_run_id,
            'apify_dataset_id': last_dataset_id
        }

    def scrape_accounts(
        self,
        project_id: str,
        max_tweets_per_account: int = 500,
        days_back: Optional[int] = None,
        chunk_by: str = "monthly",
        timeout: int = 300
    ) -> Dict[str, int]:
        """
        Scrape accounts linked to project with date chunking

        Automatically chunks date ranges to respect ~800 tweet limit per query.
        Calculates 3SD outliers per account.

        Args:
            project_id: Project UUID or slug (will be converted to UUID)
            max_tweets_per_account: Max tweets to fetch per account
            days_back: Only tweets from last N days (None = all time)
            chunk_by: "monthly", "weekly", or "daily"
            timeout: Apify timeout per run

        Returns:
            Dict with scraping stats
        """
        logger.info(f"Scraping Twitter accounts for project {project_id}")
        logger.info(f"Chunk strategy: {chunk_by}")

        # Convert slug to UUID if needed
        try:
            from uuid import UUID
            UUID(project_id)
            # It's already a UUID
        except ValueError:
            # It's a slug, convert to UUID
            project_id = self._get_project_id(project_id)

        # Get accounts linked to project
        accounts = self._get_project_accounts(project_id)

        if not accounts:
            logger.warning("No Twitter accounts linked to this project")
            return {"accounts": 0, "tweets": 0, "outliers": 0}

        logger.info(f"Found {len(accounts)} Twitter accounts")

        # Calculate date range
        end_date = datetime.now(timezone.utc)
        if days_back:
            start_date = end_date - timedelta(days=days_back)
        else:
            # Default: 1 year back
            start_date = end_date - timedelta(days=365)

        # Chunk date ranges
        date_chunks = self._chunk_date_ranges(start_date, end_date, chunk_by)
        logger.info(f"Split into {len(date_chunks)} date chunks")

        stats = {"accounts_processed": len(accounts), "total_tweets": 0, "outliers": 0}

        # Scrape each account with date chunking
        for account in accounts:
            username = account['platform_username']

            # Batch date chunks (max 5 per Apify run to respect actor limits)
            batch_size = 5
            date_chunk_batches = [date_chunks[i:i + batch_size] for i in range(0, len(date_chunks), batch_size)]

            logger.info(f"\nScraping @{username} ({len(date_chunks)} date chunks → {len(date_chunk_batches)} batched runs)")

            account_tweets = []

            # Process batches of date chunks
            for batch_idx, chunk_batch in enumerate(date_chunk_batches, 1):
                # Build OR query for multiple date ranges in one Apify run
                queries = []
                for chunk_start, chunk_end in chunk_batch:
                    query = f"from:{username} since:{chunk_start.strftime('%Y-%m-%d')} until:{chunk_end.strftime('%Y-%m-%d')}"
                    queries.append(query)

                try:
                    logger.info(f"  Batch {batch_idx}/{len(date_chunk_batches)}: {len(queries)} date ranges")

                    # Start Apify run with batched queries
                    run_id = self._start_search_run(
                        queries,
                        max_items=800,  # Max per query
                        sort="Latest"
                    )

                    # Poll for completion
                    result = self._poll_apify_run(run_id, timeout)

                    # Fetch dataset
                    items = self._fetch_dataset(result['datasetId'])

                    account_tweets.extend(items)

                    logger.info(f"  Batch {batch_idx}: Retrieved {len(items)} tweets")

                    # Respect rate limits between batches (2 minutes)
                    if batch_idx < len(date_chunk_batches):
                        logger.info(f"  Waiting 120s before next batch (rate limit compliance)...")
                        time.sleep(120)

                except Exception as e:
                    logger.error(f"Error scraping batch {batch_idx} for @{username}: {e}")
                    continue

            if not account_tweets:
                logger.warning(f"No tweets found for @{username}")
                continue

            # Normalize tweets
            df = self._normalize_tweets(account_tweets)

            # Save to database
            post_ids = self.save_posts_to_db(df, project_id=project_id, import_source="scrape")

            stats["total_tweets"] += len(post_ids)

            # Calculate outliers for this account
            outliers = self._calculate_outliers(account['id'], threshold_sd=3.0)
            stats["outliers"] += len(outliers)

            logger.info(f"@{username}: {len(post_ids)} tweets, {len(outliers)} outliers")

        return stats

    def _build_twitter_query(
        self,
        search_term: str,
        min_likes: Optional[int],
        min_retweets: Optional[int],
        min_replies: Optional[int],
        min_quotes: Optional[int],
        days_back: Optional[int],
        only_video: bool,
        only_image: bool,
        only_quote: bool
    ) -> str:
        """
        Build Twitter query from parameters with multi-filter OR logic

        Examples:
          "dog training" + days_back=7 + min_likes=1000
          → "dog training since:2024-10-09 min_faves:1000"

          "puppy" + only_video=True
          → "puppy filter:video"

          "pets" + only_video=True + only_image=True
          → "pets (filter:video OR filter:images)"

          "viral" + min_likes=1000 + min_replies=100
          → "viral min_faves:1000 min_replies:100"
        """
        query_parts = [search_term]

        # Date filter
        if days_back:
            since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime('%Y-%m-%d')
            query_parts.append(f"since:{since_date}")

        # Engagement filters
        if min_likes:
            query_parts.append(f"min_faves:{min_likes}")
        if min_retweets:
            query_parts.append(f"min_retweets:{min_retweets}")
        if min_replies:
            query_parts.append(f"min_replies:{min_replies}")
        if min_quotes:
            # Note: Twitter doesn't have native min_quotes filter in query language
            # This would need to be filtered post-scrape or we rely on actor support
            # For now, logging a warning
            logger.warning("min_quotes filter not supported in Twitter query language (will be applied post-scrape if actor supports it)")

        # Content type filters (with OR logic for multi-filter)
        content_filters = []
        if only_video:
            content_filters.append("filter:video")
        if only_image:
            content_filters.append("filter:images")
        if only_quote:
            content_filters.append("filter:quote")

        if content_filters:
            if len(content_filters) == 1:
                # Single filter: append as-is
                query_parts.append(content_filters[0])
            else:
                # Multiple filters: wrap in parentheses with OR
                filter_group = "(" + " OR ".join(content_filters) + ")"
                query_parts.append(filter_group)

        # Exclude retweets by default (focus on original content)
        query_parts.append("-filter:retweets")

        query = " ".join(query_parts)
        logger.info(f"Built query: {query}")

        return query

    def _chunk_date_ranges(
        self,
        start_date: datetime,
        end_date: datetime,
        chunk_by: str
    ) -> List[Tuple[datetime, datetime]]:
        """
        Chunk date range to respect 800-tweet limit per query

        Args:
            start_date: Start date
            end_date: End date
            chunk_by: "monthly", "weekly", or "daily"

        Returns:
            List of (start, end) datetime tuples
        """
        chunks = []

        if chunk_by == "monthly":
            delta = timedelta(days=30)
        elif chunk_by == "weekly":
            delta = timedelta(days=7)
        elif chunk_by == "daily":
            delta = timedelta(days=1)
        else:
            raise ValueError(f"Invalid chunk_by: {chunk_by}. Use 'monthly', 'weekly', or 'daily'")

        current = start_date
        while current < end_date:
            next_date = min(current + delta, end_date)
            chunks.append((current, next_date))
            current = next_date

        return chunks

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_search_run(
        self,
        search_terms: List[str],
        max_items: int = 100,
        only_verified: bool = False,
        only_blue: bool = False,
        only_image: bool = False,
        only_video: bool = False,
        only_quote: bool = False,
        sort: str = "Latest",
        language: str = "en"
    ) -> str:
        """
        Start Apify run for Twitter search

        Args:
            search_terms: List of Twitter queries (max 5)
            max_items: Max tweets per query
            only_verified: Only verified users
            only_blue: Only Twitter Blue users
            only_image: Only tweets with images
            only_video: Only tweets with video
            only_quote: Only quote tweets
            sort: "Latest" or "Top"
            language: Tweet language

        Returns:
            Apify run ID
        """
        actor_input = {
            "searchTerms": search_terms,
            "maxItems": max_items,
            "sort": sort,
            "tweetLanguage": language,
            "onlyVerifiedUsers": only_verified,
            "onlyTwitterBlue": only_blue,
            "onlyImage": only_image,
            "onlyVideo": only_video,
            "onlyQuote": only_quote,
            "includeSearchTerms": False  # Don't need search term in output
        }

        logger.info(f"Starting Twitter search: {len(search_terms)} queries, {max_items} tweets each")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input)

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
            List of tweet dictionaries
        """
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        headers = {"Authorization": f"Bearer {self.apify_token}"}

        logger.info(f"Fetching dataset {dataset_id}...")

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        items = response.json()
        logger.info(f"Fetched {len(items)} tweets from dataset")

        return items

    def _normalize_tweets(self, items: List[Dict]) -> pd.DataFrame:
        """
        Normalize Twitter search results to DataFrame

        apidojo/tweet-scraper returns:
        {
          "type": "tweet",
          "id": "1728108619189874825",
          "url": "https://x.com/elonmusk/status/...",
          "text": "Tweet content...",
          "viewCount": 123456,
          "retweetCount": 11311,
          "replyCount": 6526,
          "likeCount": 104121,
          "quoteCount": 2915,
          "bookmarkCount": 702,
          "createdAt": "Fri Nov 24 17:49:36 +0000 2023",
          "lang": "en",
          "isReply": false,
          "isRetweet": false,
          "isQuote": true,
          "author": {
            "userName": "elonmusk",
            "name": "Elon Musk",
            "isVerified": true,
            "isBlueVerified": true,
            "followers": 172669889,
            ...
          }
        }

        Args:
            items: Raw tweet data from actor

        Returns:
            DataFrame with normalized tweets
        """
        normalized_data = []

        logger.info(f"Normalizing {len(items)} tweets")

        for tweet in items:
            try:
                author = tweet.get("author", {})

                # Parse timestamp
                created_at_str = tweet.get("createdAt")
                posted_at = None
                if created_at_str:
                    # Format: "Fri Nov 24 17:49:36 +0000 2023"
                    try:
                        posted_at = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y").isoformat()
                    except:
                        logger.warning(f"Could not parse date: {created_at_str}")

                tweet_data = {
                    "post_id": str(tweet.get("id", "")),
                    "post_url": tweet.get("url", ""),
                    "username": author.get("userName", ""),
                    "display_name": author.get("name", ""),
                    "follower_count": author.get("followers", 0),
                    "is_verified": author.get("isVerified", False) or author.get("isBlueVerified", False),

                    # Engagement metrics
                    "likes": tweet.get("likeCount", 0),
                    "retweets": tweet.get("retweetCount", 0),
                    "replies": tweet.get("replyCount", 0),
                    "quotes": tweet.get("quoteCount", 0),
                    "bookmarks": tweet.get("bookmarkCount", 0),
                    "views": tweet.get("viewCount", 0),  # Twitter impressions/views

                    # Content
                    "caption": tweet.get("text", "")[:2200],
                    "lang": tweet.get("lang", ""),

                    # Metadata
                    "posted_at": posted_at,
                    "is_reply": tweet.get("isReply", False),
                    "is_retweet": tweet.get("isRetweet", False),
                    "is_quote": tweet.get("isQuote", False),

                    # Platform
                    "platform_id": self.platform_id,
                    "video_type": "post"  # All tweets are "post" type
                }

                # Validate essential fields
                if not tweet_data["post_id"] or not tweet_data["username"]:
                    logger.warning(f"Skipping tweet with missing essential fields")
                    continue

                normalized_data.append(tweet_data)

            except Exception as e:
                logger.warning(f"Error normalizing tweet: {e}")
                continue

        df = pd.DataFrame(normalized_data)

        if len(df) > 0:
            # Deduplicate by post_id
            original_count = len(df)
            df = df.drop_duplicates(subset=['post_id'], keep='first')
            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate tweets")

            logger.info(f"Normalized {len(df)} tweets from {df['username'].nunique()} accounts")
        else:
            logger.warning("No tweets were successfully normalized")

        return df

    def save_posts_to_db(
        self,
        df: pd.DataFrame,
        project_id: Optional[str] = None,
        import_source: str = "search"
    ) -> List[str]:
        """
        Save tweets to database

        Args:
            df: DataFrame with tweets
            project_id: Optional project UUID to link tweets to
            import_source: How tweets were imported (search, scrape, direct_url)

        Returns:
            List of post UUIDs
        """
        if len(df) == 0:
            logger.warning("No tweets to save")
            return []

        # First, upsert accounts
        account_ids = self._upsert_accounts(df)

        # Prepare posts data
        posts_data = []
        for _, row in df.iterrows():
            # Twitter metrics mapping:
            # - viewCount → views (impressions)
            # - likes → likes
            # - replies → comments
            # - retweets → shares
            # - quotes, bookmarks → currently not stored (could add to platform_specific_data in future)

            post_dict = {
                "account_id": account_ids.get(row['username']),
                "platform_id": self.platform_id,
                "post_url": row['post_url'],
                "post_id": row['post_id'],
                "posted_at": row.get('posted_at'),
                "views": int(row.get('views', 0)) if pd.notna(row.get('views')) else None,
                "likes": int(row.get('likes', 0)) if pd.notna(row.get('likes')) else None,
                "comments": int(row.get('replies', 0)) if pd.notna(row.get('replies')) else None,
                "shares": int(row.get('retweets', 0)) if pd.notna(row.get('retweets')) else None,
                "caption": row.get('caption'),
                "video_type": "post",
                "import_source": import_source,
                "is_own_content": False
            }

            posts_data.append(post_dict)

        # Upsert posts
        post_ids = []
        chunk_size = 1000
        chunks = [posts_data[i:i + chunk_size] for i in range(0, len(posts_data), chunk_size)]

        for chunk in tqdm(chunks, desc="Saving tweets to database"):
            try:
                # Debug: Log first post_url to verify format
                if chunk:
                    logger.debug(f"Sample post_url: {chunk[0].get('post_url')}")
                    logger.debug(f"Sample post data: account_id={chunk[0].get('account_id')}, platform_id={chunk[0].get('platform_id')}")

                result = self.supabase.table("posts").upsert(
                    chunk,
                    on_conflict="post_url"
                ).execute()

                if result.data:
                    for post in result.data:
                        post_ids.append(post['id'])
                else:
                    logger.warning(f"Upsert returned no data for chunk of {len(chunk)} tweets")
                    logger.warning(f"This usually means all tweets already exist or there was a silent failure")

            except Exception as e:
                logger.error(f"Error upserting tweets chunk: {e}")
                logger.error(f"First post in failed chunk: {chunk[0] if chunk else 'empty'}")
                continue

        logger.info(f"Saved {len(post_ids)} tweets to database")

        # Link to project if provided
        if project_id and post_ids:
            self._link_posts_to_project(post_ids, project_id, import_source)

        return post_ids

    def _upsert_accounts(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Upsert Twitter accounts to database

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
                logger.error(f"Error upserting account @{username}: {e}")
                continue

        logger.info(f"Upserted {len(account_ids)} accounts")

        return account_ids

    def _link_posts_to_project(
        self,
        post_ids: List[str],
        project_id: str,
        import_method: str = "search"
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
                'notes': f"Twitter scrape on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking tweets to project"):
            try:
                result = self.supabase.table("project_posts").upsert(
                    chunk,
                    on_conflict="project_id,post_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking tweets chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} tweets to project")

    def _get_project_id(self, project_slug: str) -> str:
        """Get project UUID from slug"""
        result = self.supabase.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not result.data:
            raise ValueError(f"Project not found: {project_slug}")
        return result.data['id']

    def _get_project_accounts(self, project_id: str) -> List[Dict]:
        """Get Twitter accounts linked to project"""
        result = self.supabase.table('project_accounts')\
            .select('account_id, accounts(id, platform_username)')\
            .eq('project_id', project_id)\
            .execute()

        if not result.data:
            return []

        # Filter to Twitter accounts
        twitter_accounts = []
        for link in result.data:
            account = link.get('accounts')
            if account:
                # Check if this account belongs to Twitter platform
                acc_check = self.supabase.table('accounts')\
                    .select('id, platform_id, platform_username')\
                    .eq('id', account['id'])\
                    .eq('platform_id', self.platform_id)\
                    .single()\
                    .execute()

                if acc_check.data:
                    twitter_accounts.append(acc_check.data)

        return twitter_accounts

    def _calculate_outliers(
        self,
        account_id: str,
        threshold_sd: float = 3.0
    ) -> List[str]:
        """
        Calculate statistical outliers (3SD from trimmed mean)

        Args:
            account_id: Account UUID
            threshold_sd: Standard deviation threshold

        Returns:
            List of outlier post IDs
        """
        # Get all posts for this account
        result = self.supabase.table('posts')\
            .select('id, likes')\
            .eq('account_id', account_id)\
            .execute()

        if not result.data or len(result.data) < 10:
            logger.warning(f"Not enough posts for outlier detection (need 10+, have {len(result.data) if result.data else 0})")
            return []

        # Extract engagement scores (likes)
        scores = [p['likes'] for p in result.data if p.get('likes')]

        if len(scores) < 10:
            logger.warning("Not enough valid engagement scores")
            return []

        # Calculate trimmed mean (remove top/bottom 10%)
        sorted_scores = sorted(scores)
        trim_count = int(len(sorted_scores) * 0.1)
        trimmed_scores = sorted_scores[trim_count:-trim_count] if trim_count > 0 else sorted_scores

        import numpy as np
        mean = np.mean(trimmed_scores)
        std = np.std(trimmed_scores)

        threshold = mean + (threshold_sd * std)

        logger.info(f"Outlier detection: mean={mean:.0f}, std={std:.0f}, threshold={threshold:.0f}")

        # Find outliers
        outliers = []
        for post in result.data:
            if post.get('likes', 0) > threshold:
                outliers.append(post['id'])

                # Mark as outlier in post_review table (if not already marked)
                try:
                    self.supabase.table('post_review').upsert({
                        'post_id': post['id'],
                        'is_outlier': True,
                        'outlier_score': post['likes'] / mean if mean > 0 else 0,
                        'updated_at': datetime.now().isoformat()
                    }, on_conflict='post_id').execute()
                except Exception as e:
                    logger.warning(f"Error marking outlier: {e}")

        logger.info(f"Found {len(outliers)} outliers")

        return outliers
