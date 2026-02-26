"""
Instagram Content Service - Research, scraping, outlier detection, media download.

Wraps the existing InstagramScraper with per-brand watched accounts,
statistical outlier detection, and selective media download (outliers only).

Part of the Video Tools Suite (Phase 1).
"""

import logging
import httpx
import mimetypes
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np
from scipy import stats
from supabase import Client

from ..core.config import Config
from ..core.database import get_supabase_client
from ..scrapers.instagram import InstagramScraper

logger = logging.getLogger(__name__)


class InstagramContentService:
    """Instagram content research: watched accounts, scraping, outlier detection, media download.

    Key workflow: scrape -> outlier detection -> download media for outliers only.

    All queries filter by organization_id for multi-tenant isolation.
    """

    STORAGE_BUCKET = "instagram-media"

    # Outlier detection defaults
    DEFAULT_OUTLIER_THRESHOLD = 2.0  # z-score threshold
    DEFAULT_OUTLIER_METHOD = "zscore"
    MIN_POSTS_FOR_OUTLIER = 3  # Below this, skip outlier detection

    # Media download settings
    DOWNLOAD_TIMEOUT = 60  # seconds
    MAX_DOWNLOAD_SIZE_BYTES = 500 * 1024 * 1024  # 500MB

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize InstagramContentService.

        Args:
            supabase: Optional Supabase client. Creates one if not provided.
        """
        self.supabase = supabase or get_supabase_client()
        self._scraper: Optional[InstagramScraper] = None

    @property
    def scraper(self) -> InstagramScraper:
        """Lazy-initialize the Instagram scraper."""
        if self._scraper is None:
            self._scraper = InstagramScraper(supabase_client=self.supabase)
        return self._scraper

    # ========================================================================
    # Watched Accounts CRUD
    # ========================================================================

    def add_watched_account(
        self,
        brand_id: str,
        username: str,
        organization_id: str,
        notes: Optional[str] = None,
        scrape_frequency_hours: int = 168,
    ) -> Dict:
        """
        Add an Instagram account to the watch list for a brand.

        Creates the account in the accounts table if it doesn't exist,
        then links it via instagram_watched_accounts.

        Args:
            brand_id: Brand UUID
            username: Instagram username (without @)
            organization_id: Organization UUID for multi-tenant isolation
            notes: Optional notes about why this account is being watched
            scrape_frequency_hours: How often to auto-scrape (default: 168 = weekly)

        Returns:
            Dict with the created watched account record

        Raises:
            ValueError: If the account is already being watched for this brand
        """
        username = username.strip().lstrip("@").lower()
        if not username:
            raise ValueError("Username cannot be empty")

        # Resolve real org_id for superuser "all" mode (inserts need a real UUID)
        if organization_id == "all":
            brand_row = (
                self.supabase.table("brands")
                .select("organization_id")
                .eq("id", brand_id)
                .single()
                .execute()
            )
            if not brand_row.data:
                raise ValueError(f"Brand {brand_id} not found")
            organization_id = brand_row.data["organization_id"]

        # Get Instagram platform ID
        platform_result = (
            self.supabase.table("platforms")
            .select("id")
            .eq("slug", "instagram")
            .single()
            .execute()
        )
        if not platform_result.data:
            raise ValueError("Instagram platform not found in database")
        platform_id = platform_result.data["id"]

        # Upsert account in accounts table
        account_data = {
            "platform_id": platform_id,
            "platform_username": username,
            "handle": username,
        }
        account_result = (
            self.supabase.table("accounts")
            .upsert(account_data, on_conflict="platform_id,platform_username")
            .execute()
        )
        if not account_result.data:
            raise RuntimeError(f"Failed to upsert account for {username}")
        account_id = account_result.data[0]["id"]

        # Create watched account link
        watched_data = {
            "organization_id": organization_id,
            "brand_id": brand_id,
            "account_id": account_id,
            "is_active": True,
            "scrape_frequency_hours": scrape_frequency_hours,
            "notes": notes,
        }

        try:
            result = (
                self.supabase.table("instagram_watched_accounts")
                .upsert(watched_data, on_conflict="brand_id,account_id")
                .execute()
            )
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                raise ValueError(
                    f"Account @{username} is already being watched for this brand"
                )
            raise

        record = result.data[0] if result.data else watched_data
        logger.info(f"Added watched account @{username} for brand {brand_id}")
        return record

    def remove_watched_account(self, watched_id: str) -> None:
        """
        Soft-delete a watched account (set is_active=false).

        Args:
            watched_id: UUID of the instagram_watched_accounts record
        """
        self.supabase.table("instagram_watched_accounts").update(
            {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", watched_id).execute()
        logger.info(f"Deactivated watched account {watched_id}")

    def reactivate_watched_account(self, watched_id: str) -> None:
        """
        Reactivate a previously deactivated watched account.

        Args:
            watched_id: UUID of the instagram_watched_accounts record
        """
        self.supabase.table("instagram_watched_accounts").update(
            {"is_active": True, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", watched_id).execute()
        logger.info(f"Reactivated watched account {watched_id}")

    def list_watched_accounts(
        self,
        brand_id: str,
        organization_id: str,
        include_inactive: bool = False,
    ) -> List[Dict]:
        """
        Get watched accounts for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for multi-tenant isolation
            include_inactive: Include deactivated accounts

        Returns:
            List of watched account records with account details
        """
        query = (
            self.supabase.table("instagram_watched_accounts")
            .select("*, accounts(id, platform_username, display_name, follower_count, bio, profile_pic_url, is_verified, last_scraped_at)")
            .eq("brand_id", brand_id)
        )

        # Multi-tenant filter (unless superuser "all" mode)
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        if not include_inactive:
            query = query.eq("is_active", True)

        result = query.order("created_at", desc=False).execute()
        return result.data or []

    # ========================================================================
    # Scraping
    # ========================================================================

    def scrape_account(
        self,
        watched_account_id: str,
        days_back: int = 120,
        force: bool = False,
    ) -> Dict:
        """
        Scrape an individual watched account.

        Delegates to existing InstagramScraper. Enforces min_scrape_interval
        unless force=True.

        Args:
            watched_account_id: UUID of instagram_watched_accounts record
            days_back: How many days of posts to scrape
            force: Skip min_scrape_interval check

        Returns:
            Dict with scrape results: {posts_scraped, skipped_reason}
        """
        # Get watched account details
        watched = (
            self.supabase.table("instagram_watched_accounts")
            .select("*, accounts(id, platform_username, platform_id)")
            .eq("id", watched_account_id)
            .single()
            .execute()
        )
        if not watched.data:
            raise ValueError(f"Watched account {watched_account_id} not found")

        record = watched.data
        account = record["accounts"]
        username = account["platform_username"]

        # Check min scrape interval
        if not force and record.get("last_scraped_at"):
            last_scraped = datetime.fromisoformat(
                record["last_scraped_at"].replace("Z", "+00:00")
            )
            min_interval = timedelta(hours=record.get("min_scrape_interval_hours", 24))
            if datetime.now(timezone.utc) - last_scraped < min_interval:
                hours_remaining = (
                    min_interval - (datetime.now(timezone.utc) - last_scraped)
                ).total_seconds() / 3600
                return {
                    "posts_scraped": 0,
                    "skipped_reason": f"Min scrape interval not met. Try again in {hours_remaining:.1f} hours.",
                }

        # Run scrape using Apify via the existing scraper
        logger.info(f"Scraping @{username} ({days_back} days back)")

        try:
            run_id = self.scraper._start_apify_run([username], days_back)
            result = self.scraper._poll_apify_run(run_id, timeout=300)
            items = self.scraper._fetch_dataset(result["datasetId"])

            if not items:
                logger.warning(f"No data returned for @{username}")
                # Still update last_scraped_at
                self._update_last_scraped(watched_account_id)
                return {"posts_scraped": 0, "skipped_reason": None}

            # Normalize and process
            df, account_metadata = self.scraper._normalize_items(items)

            if len(df) == 0:
                self._update_last_scraped(watched_account_id)
                return {"posts_scraped": 0, "skipped_reason": None}

            # Build account map for upsert
            account_map = {
                username: {
                    "account_id": account["id"],
                    "platform_id": account["platform_id"],
                }
            }

            # Upsert accounts metadata
            self.scraper._upsert_accounts(
                df, account_map, account["platform_id"], account_metadata
            )

            # Upsert posts
            post_ids = self.scraper._upsert_posts(df, account_map)

            # Update last_scraped_at
            self._update_last_scraped(watched_account_id)

            logger.info(f"Scraped {len(post_ids)} posts from @{username}")
            return {"posts_scraped": len(post_ids), "skipped_reason": None}

        except Exception as e:
            logger.error(f"Error scraping @{username}: {e}", exc_info=True)
            raise RuntimeError(f"Scrape failed for @{username}: {e}") from e

    def scrape_all_active(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 120,
        force: bool = False,
    ) -> Dict:
        """
        Scrape all active watched accounts for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            days_back: How many days of posts to scrape
            force: Skip min_scrape_interval check

        Returns:
            Dict with aggregate results
        """
        accounts = self.list_watched_accounts(brand_id, organization_id)

        results = {
            "total_accounts": len(accounts),
            "accounts_scraped": 0,
            "accounts_skipped": 0,
            "total_posts": 0,
            "errors": [],
        }

        for watched in accounts:
            try:
                scrape_result = self.scrape_account(
                    watched["id"], days_back=days_back, force=force
                )
                if scrape_result.get("skipped_reason"):
                    results["accounts_skipped"] += 1
                else:
                    results["accounts_scraped"] += 1
                    results["total_posts"] += scrape_result["posts_scraped"]
            except Exception as e:
                results["errors"].append(
                    {
                        "account_id": watched["id"],
                        "username": watched.get("accounts", {}).get(
                            "platform_username", "unknown"
                        ),
                        "error": str(e),
                    }
                )

        logger.info(
            f"Batch scrape for brand {brand_id}: "
            f"{results['accounts_scraped']} scraped, "
            f"{results['accounts_skipped']} skipped, "
            f"{len(results['errors'])} errors, "
            f"{results['total_posts']} posts"
        )
        return results

    def _update_last_scraped(self, watched_account_id: str) -> None:
        """Update last_scraped_at timestamp for a watched account."""
        now = datetime.now(timezone.utc).isoformat()
        self.supabase.table("instagram_watched_accounts").update(
            {"last_scraped_at": now, "updated_at": now}
        ).eq("id", watched_account_id).execute()

    # ========================================================================
    # Outlier Detection
    # ========================================================================

    def calculate_outliers(
        self,
        brand_id: str,
        organization_id: str,
        days: int = 120,
        method: str = "zscore",
        threshold: float = 2.0,
        trim_percent: float = 10.0,
    ) -> Dict:
        """
        Calculate outlier posts for all watched accounts of a brand.

        Updates is_outlier, outlier_score, outlier_method, outlier_calculated_at
        on the posts table.

        Edge cases handled:
        - N < MIN_POSTS_FOR_OUTLIER: skip detection, flag none as outliers
        - std = 0 (identical engagement): all posts get z-score = 0, none flagged

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            days: Look back N days
            method: "zscore" or "percentile"
            threshold: Z-score threshold or percentile cutoff
            trim_percent: Percent to trim for robust statistics

        Returns:
            Dict with detection results
        """
        # Get all watched account IDs for this brand
        watched = self.list_watched_accounts(brand_id, organization_id)
        if not watched:
            return {"total_posts": 0, "outliers_found": 0, "message": "No watched accounts"}

        account_ids = [w["account_id"] for w in watched]

        # Fetch posts from these accounts within date range
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Query posts for watched accounts
        posts = []
        # Process in batches to avoid URL length limits
        batch_size = 50
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i : i + batch_size]
            result = (
                self.supabase.table("posts")
                .select("id, views, likes, comments, shares, posted_at, account_id")
                .in_("account_id", batch)
                .gte("posted_at", cutoff)
                .execute()
            )
            if result.data:
                posts.extend(result.data)

        total_posts = len(posts)
        logger.info(f"Outlier detection: {total_posts} posts from {len(account_ids)} accounts")

        if total_posts < self.MIN_POSTS_FOR_OUTLIER:
            logger.warning(
                f"Only {total_posts} posts (< {self.MIN_POSTS_FOR_OUTLIER}). "
                "Skipping outlier detection."
            )
            return {
                "total_posts": total_posts,
                "outliers_found": 0,
                "message": f"Need at least {self.MIN_POSTS_FOR_OUTLIER} posts for outlier detection",
            }

        # Calculate engagement scores
        scores = []
        for post in posts:
            views = post.get("views") or 0
            likes = post.get("likes") or 0
            comments = post.get("comments") or 0
            shares = post.get("shares") or 0

            # Composite engagement score (weighted)
            score = likes * 1.0 + comments * 0.8 + shares * 0.5
            # Add engagement rate component if views > 0
            if views > 0:
                engagement_rate = (likes + comments + shares) / views
                score += engagement_rate * 1000  # Scale up for meaningful contribution
            scores.append(score)

        scores_array = np.array(scores)

        # Detect outliers
        if method == "zscore":
            outlier_flags, outlier_scores = self._zscore_detection(
                scores_array, threshold, trim_percent
            )
        elif method == "percentile":
            outlier_flags, outlier_scores = self._percentile_detection(
                scores_array, threshold
            )
        else:
            raise ValueError(f"Unknown method: {method}. Use 'zscore' or 'percentile'")

        # Update posts in database
        now = datetime.now(timezone.utc).isoformat()
        outliers_found = 0

        for post, is_outlier, score in zip(posts, outlier_flags, outlier_scores):
            update_data = {
                "is_outlier": bool(is_outlier),
                "outlier_score": float(score),
                "outlier_method": method,
                "outlier_calculated_at": now,
            }
            self.supabase.table("posts").update(update_data).eq("id", post["id"]).execute()
            if is_outlier:
                outliers_found += 1

        logger.info(f"Outlier detection complete: {outliers_found}/{total_posts} outliers")
        return {
            "total_posts": total_posts,
            "outliers_found": outliers_found,
            "method": method,
            "threshold": threshold,
        }

    def _zscore_detection(
        self,
        scores: np.ndarray,
        threshold: float,
        trim_percent: float,
    ) -> Tuple[List[bool], List[float]]:
        """
        Z-score based outlier detection with trimmed statistics.

        Args:
            scores: Array of engagement scores
            threshold: Z-score threshold
            trim_percent: Percent to trim from each end

        Returns:
            Tuple of (outlier_flags, z_scores)
        """
        trim_fraction = trim_percent / 100.0
        trimmed_mean = stats.trim_mean(scores, trim_fraction)

        # Calculate trimmed std
        sorted_scores = np.sort(scores)
        n = len(sorted_scores)
        lower_cut = int(n * trim_fraction)
        upper_cut = n - lower_cut
        if upper_cut <= lower_cut:
            upper_cut = n  # Fallback: use all
        trimmed_scores = sorted_scores[lower_cut:upper_cut]

        trimmed_std = np.std(trimmed_scores, ddof=1) if len(trimmed_scores) > 1 else 0.0

        # Handle std = 0 (identical engagement)
        if trimmed_std == 0:
            logger.warning("Standard deviation is 0 — all posts have similar engagement")
            return [False] * len(scores), [0.0] * len(scores)

        z_scores = (scores - trimmed_mean) / trimmed_std
        outlier_flags = [bool(z >= threshold) for z in z_scores]

        return outlier_flags, [float(z) for z in z_scores]

    def _percentile_detection(
        self,
        scores: np.ndarray,
        threshold: float,
    ) -> Tuple[List[bool], List[float]]:
        """
        Percentile-based outlier detection.

        Args:
            scores: Array of engagement scores
            threshold: Top N% threshold (e.g., 5.0 for top 5%)

        Returns:
            Tuple of (outlier_flags, percentile_scores)
        """
        cutoff = np.percentile(scores, 100 - threshold)

        percentile_scores = []
        outlier_flags = []
        for score in scores:
            pct = float((np.sum(scores <= score) / len(scores)) * 100)
            percentile_scores.append(pct)
            outlier_flags.append(bool(score >= cutoff))

        return outlier_flags, percentile_scores

    # ========================================================================
    # Media Download (outliers only)
    # ========================================================================

    def download_outlier_media(
        self,
        brand_id: str,
        organization_id: str,
        limit: int = 100,
    ) -> Dict:
        """
        Download media for outlier posts that haven't been downloaded yet.

        Only downloads media for posts marked as outliers (is_outlier=true).
        Creates instagram_media records and stores files in Supabase storage.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            limit: Maximum number of posts to download media for

        Returns:
            Dict with download results
        """
        # Get watched account IDs
        watched = self.list_watched_accounts(brand_id, organization_id)
        if not watched:
            return {"downloaded": 0, "failed": 0, "skipped": 0}

        account_ids = [w["account_id"] for w in watched]

        # Find outlier posts without downloaded media
        outlier_posts = []
        batch_size = 50
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i : i + batch_size]
            result = (
                self.supabase.table("posts")
                .select("id, post_url, post_id, media_type, video_type, account_id, cdn_video_url, cdn_image_url")
                .in_("account_id", batch)
                .eq("is_outlier", True)
                .order("outlier_score", desc=True)
                .limit(limit)
                .execute()
            )
            if result.data:
                outlier_posts.extend(result.data)

        if not outlier_posts:
            return {"downloaded": 0, "failed": 0, "skipped": 0, "message": "No outlier posts found"}

        # Filter out posts that already have downloaded media
        post_ids = [p["id"] for p in outlier_posts]
        existing_media = (
            self.supabase.table("instagram_media")
            .select("post_id")
            .in_("post_id", post_ids[:100])  # Limit query size
            .eq("download_status", "downloaded")
            .execute()
        )
        already_downloaded = {m["post_id"] for m in (existing_media.data or [])}

        posts_to_download = [
            p for p in outlier_posts if p["id"] not in already_downloaded
        ][:limit]

        results = {"downloaded": 0, "failed": 0, "skipped": len(already_downloaded)}

        for post in posts_to_download:
            try:
                downloaded = self._download_post_media(post, brand_id)
                if downloaded:
                    results["downloaded"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(f"Failed to download media for post {post['id']}: {e}")
                results["failed"] += 1

        logger.info(
            f"Media download for brand {brand_id}: "
            f"{results['downloaded']} downloaded, "
            f"{results['failed']} failed, "
            f"{results['skipped']} skipped"
        )
        return results

    def _download_post_media(self, post: Dict, brand_id: str) -> bool:
        """
        Download media for a single post using stored CDN URLs.

        Args:
            post: Post record dict (must include cdn_video_url / cdn_image_url)
            brand_id: Brand UUID for storage path

        Returns:
            True if at least one media file was downloaded
        """
        post_id = post["id"]

        # Build media list from stored CDN URLs (captured during scrape)
        media_urls = []
        if post.get("cdn_video_url"):
            media_urls.append({"url": post["cdn_video_url"], "type": "video"})
        if post.get("cdn_image_url"):
            media_urls.append({"url": post["cdn_image_url"], "type": "image"})

        if not media_urls:
            logger.warning(f"No stored CDN URLs for post {post_id}")
            return False

        any_downloaded = False
        for idx, media_info in enumerate(media_urls):
            url = media_info.get("url")
            media_type = media_info.get("type", "image")

            if not url:
                continue

            try:
                # Create media record first
                media_record = {
                    "post_id": post_id,
                    "media_type": media_type,
                    "media_index": idx,
                    "original_cdn_url": url,
                    "cdn_url_captured_at": datetime.now(timezone.utc).isoformat(),
                    "download_status": "downloading",
                }
                insert_result = (
                    self.supabase.table("instagram_media")
                    .insert(media_record)
                    .execute()
                )
                if not insert_result.data:
                    continue
                media_id = insert_result.data[0]["id"]

                # Download file
                file_data, content_type = self._download_file(url)

                if file_data is None:
                    self.supabase.table("instagram_media").update(
                        {"download_status": "failed", "download_error": "Download returned no data"}
                    ).eq("id", media_id).execute()
                    continue

                # Determine file extension
                ext = mimetypes.guess_extension(content_type or "") or (
                    ".mp4" if media_type == "video" else ".jpg"
                )

                # Upload to Supabase storage
                storage_path = f"{brand_id}/{post_id}/{media_id}{ext}"
                self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                    path=storage_path,
                    file=file_data,
                    file_options={"content-type": content_type or "application/octet-stream"},
                )

                # Update media record
                self.supabase.table("instagram_media").update(
                    {
                        "storage_path": storage_path,
                        "file_size_bytes": len(file_data),
                        "download_status": "downloaded",
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", media_id).execute()

                any_downloaded = True
                logger.info(f"Downloaded {media_type} for post {post_id} -> {storage_path}")

            except Exception as e:
                logger.error(f"Error downloading media index {idx} for post {post_id}: {e}")
                continue

        return any_downloaded

    def _get_media_urls_for_post(self, shortcode: str, username: str = "") -> List[Dict]:
        """
        Get media URLs for a post by shortcode.

        Attempts to fetch from Apify's Instagram post scraper for fresh CDN URLs.

        Args:
            shortcode: Instagram post shortcode
            username: Instagram username (required by Apify actor)

        Returns:
            List of {url, type} dicts
        """
        if not shortcode:
            return []

        try:
            from apify_client import ApifyClient

            client = ApifyClient(Config.APIFY_TOKEN)

            run_input = {
                "directUrls": [f"https://www.instagram.com/p/{shortcode}/"],
                "resultsLimit": 1,
            }
            if username:
                run_input["username"] = [username]

            # Use the Instagram post scraper actor for individual posts
            run = client.actor("apify/instagram-post-scraper").call(
                run_input=run_input,
                build="latest",
            )

            dataset_items = list(
                client.dataset(run["defaultDatasetId"]).iterate_items()
            )

            if not dataset_items:
                return []

            item = dataset_items[0]
            media_urls = []

            # Video
            if item.get("videoUrl"):
                media_urls.append({"url": item["videoUrl"], "type": "video"})

            # Display URL (image)
            if item.get("displayUrl"):
                media_urls.append({"url": item["displayUrl"], "type": "image"})

            # Carousel / sidecar
            for child in item.get("childPosts", []):
                if child.get("videoUrl"):
                    media_urls.append({"url": child["videoUrl"], "type": "video"})
                elif child.get("displayUrl"):
                    media_urls.append({"url": child["displayUrl"], "type": "image"})

            return media_urls

        except Exception as e:
            logger.warning(f"Failed to get media URLs for shortcode {shortcode}: {e}")
            return []

    def _download_file(self, url: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Download a file from a URL with browser-like headers.

        Args:
            url: URL to download from

        Returns:
            Tuple of (file_bytes, content_type) or (None, None) on failure
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }

        try:
            with httpx.Client(timeout=self.DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()

                if len(response.content) > self.MAX_DOWNLOAD_SIZE_BYTES:
                    logger.warning(f"File too large: {len(response.content)} bytes")
                    return None, None

                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                return response.content, content_type

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error downloading {url}: {e.response.status_code}")
            return None, None
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None, None

    # ========================================================================
    # Content Queries
    # ========================================================================

    def get_top_content(
        self,
        brand_id: str,
        organization_id: str,
        days: int = 120,
        limit: int = 50,
        outliers_only: bool = False,
        media_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get top-performing content for a brand's watched accounts.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            days: Look back N days
            limit: Maximum posts to return
            outliers_only: Only return posts flagged as outliers
            media_type: Filter by media_type (e.g., 'video', 'image')

        Returns:
            List of post records with account info, sorted by engagement
        """
        watched = self.list_watched_accounts(brand_id, organization_id)
        if not watched:
            return []

        account_ids = [w["account_id"] for w in watched]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Build query
        all_posts = []
        batch_size = 50
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i : i + batch_size]
            query = (
                self.supabase.table("posts")
                .select(
                    "id, post_url, post_id, posted_at, views, likes, comments, shares, "
                    "caption, media_type, video_type, length_sec, is_outlier, outlier_score, "
                    "accounts(id, platform_username, display_name, follower_count, profile_pic_url)"
                )
                .in_("account_id", batch)
                .gte("posted_at", cutoff)
            )

            if outliers_only:
                query = query.eq("is_outlier", True)
            if media_type:
                query = query.eq("media_type", media_type)

            query = query.order("views", desc=True).limit(limit)
            result = query.execute()
            if result.data:
                all_posts.extend(result.data)

        # Sort combined results by views descending and limit
        all_posts.sort(key=lambda p: p.get("views") or 0, reverse=True)
        return all_posts[:limit]

    def get_content_stats(
        self,
        brand_id: str,
        organization_id: str,
        days: int = 120,
    ) -> Dict:
        """
        Get aggregate content statistics for a brand's watched accounts.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            days: Look back N days

        Returns:
            Dict with aggregate stats
        """
        watched = self.list_watched_accounts(brand_id, organization_id)
        if not watched:
            return {
                "watched_accounts": 0,
                "total_posts": 0,
                "outlier_posts": 0,
                "media_downloaded": 0,
            }

        account_ids = [w["account_id"] for w in watched]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Count total posts
        total_posts = 0
        outlier_posts = 0
        all_outlier_post_ids = []
        batch_size = 50
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i : i + batch_size]
            result = (
                self.supabase.table("posts")
                .select("id, is_outlier", count="exact")
                .in_("account_id", batch)
                .gte("posted_at", cutoff)
                .execute()
            )
            if result.data:
                total_posts += len(result.data)
                for p in result.data:
                    if p.get("is_outlier"):
                        outlier_posts += 1
                        all_outlier_post_ids.append(p["id"])

        # Count outlier posts that have at least one downloaded media file
        outlier_post_ids = all_outlier_post_ids
        outliers_with_media = 0
        if outlier_post_ids:
            # Query in batches
            for i in range(0, len(outlier_post_ids), batch_size):
                batch = outlier_post_ids[i : i + batch_size]
                media_result = (
                    self.supabase.table("instagram_media")
                    .select("post_id")
                    .in_("post_id", batch)
                    .eq("download_status", "downloaded")
                    .execute()
                )
                if media_result.data:
                    outliers_with_media += len({m["post_id"] for m in media_result.data})

        return {
            "watched_accounts": len(watched),
            "total_posts": total_posts,
            "outlier_posts": outlier_posts,
            "outliers_with_media": outliers_with_media,
        }

    def get_post_media(self, post_id: str) -> List[Dict]:
        """
        Get downloaded media files for a post.

        Args:
            post_id: Post UUID

        Returns:
            List of instagram_media records
        """
        result = (
            self.supabase.table("instagram_media")
            .select("*")
            .eq("post_id", post_id)
            .order("media_index")
            .execute()
        )
        return result.data or []
