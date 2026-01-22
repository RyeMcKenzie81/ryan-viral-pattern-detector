"""
AdScrapingService - Download and store Facebook ad assets.

This service handles:
- Extracting image/video URLs from FB ad snapshots
- Downloading assets from Facebook CDN
- Uploading to Supabase Storage (scraped-assets bucket)
- Creating scraped_ad_assets records
- Saving ads to facebook_ads table

Part of the Brand Research Pipeline (Phase 1: Foundation).
"""

import logging
import httpx
import json
from typing import List, Dict, Optional, Tuple
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class AdScrapingService:
    """Service for scraping and storing Facebook ad assets."""

    STORAGE_BUCKET = "scraped-assets"

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize AdScrapingService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("AdScrapingService initialized")

    def extract_asset_urls(self, snapshot: Dict) -> Dict[str, List[str]]:
        """
        Extract image and video URLs from FB ad snapshot.

        Args:
            snapshot: The snapshot JSONB from facebook_ads table

        Returns:
            {"images": [url1, url2], "videos": [url1]}
        """
        images = []
        videos = []

        # Handle snapshot as string or dict
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except json.JSONDecodeError:
                logger.warning("Failed to parse snapshot as JSON")
                return {"images": [], "videos": []}

        if not snapshot:
            return {"images": [], "videos": []}

        # Extract from cards array (main ad content)
        cards = snapshot.get('cards', [])
        for card in cards:
            # Video URLs (prefer HD)
            if card.get('video_hd_url'):
                videos.append(card['video_hd_url'])
            elif card.get('video_sd_url'):
                videos.append(card['video_sd_url'])

            # Image URLs (prefer original/resized over watermarked)
            if card.get('original_image_url'):
                images.append(card['original_image_url'])
            elif card.get('resized_image_url'):
                images.append(card['resized_image_url'])
            elif card.get('watermarked_resized_image_url'):
                images.append(card['watermarked_resized_image_url'])

        # Also check top-level fields
        if snapshot.get('video_hd_url'):
            videos.append(snapshot['video_hd_url'])
        if snapshot.get('original_image_url'):
            images.append(snapshot['original_image_url'])

        # Extract from 'videos' array (list of video objects)
        for video in snapshot.get('videos', []):
            if isinstance(video, dict):
                if video.get('video_hd_url'):
                    videos.append(video['video_hd_url'])
                elif video.get('video_sd_url'):
                    videos.append(video['video_sd_url'])

        # Extract from 'images' array (list of image objects or URLs)
        for image in snapshot.get('images', []):
            if isinstance(image, dict):
                if image.get('original_image_url'):
                    images.append(image['original_image_url'])
                elif image.get('resized_image_url'):
                    images.append(image['resized_image_url'])
            elif isinstance(image, str) and image.startswith('http'):
                images.append(image)

        # Also check extra_videos and extra_images
        for video in snapshot.get('extra_videos', []):
            if isinstance(video, dict):
                if video.get('video_hd_url'):
                    videos.append(video['video_hd_url'])
                elif video.get('video_sd_url'):
                    videos.append(video['video_sd_url'])

        for image in snapshot.get('extra_images', []):
            if isinstance(image, dict):
                if image.get('original_image_url'):
                    images.append(image['original_image_url'])
                elif image.get('resized_image_url'):
                    images.append(image['resized_image_url'])
            elif isinstance(image, str) and image.startswith('http'):
                images.append(image)

        # Deduplicate while preserving order
        images = list(dict.fromkeys(images))
        videos = list(dict.fromkeys(videos))

        logger.debug(f"Extracted {len(images)} images, {len(videos)} videos from snapshot")
        return {"images": images, "videos": videos}

    async def download_asset(self, url: str, timeout: float = 30.0, max_retries: int = 3) -> Optional[bytes]:
        """
        Download asset from URL with retry logic.

        Args:
            url: URL to download from
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts

        Returns:
            File bytes or None if failed
        """
        import asyncio

        # Headers to mimic browser request (FB CDN blocks non-browser requests)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,video/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=headers
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    logger.debug(f"Downloaded {len(response.content)} bytes from {url[:50]}...")
                    return response.content
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"Timeout (attempt {attempt+1}/{max_retries}) downloading: {url[:80]}...")
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning(f"HTTP error {e.response.status_code} (attempt {attempt+1}/{max_retries}) downloading: {url[:80]}...")
                # Don't retry on 4xx errors (except 429)
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    break
            except httpx.ConnectError as e:
                last_error = f"connection error: {e}"
                logger.warning(f"Connection error (attempt {attempt+1}/{max_retries}) downloading: {url[:80]}... - {e}")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Failed (attempt {attempt+1}/{max_retries}) to download {url[:80]}...: {e}")

            # Exponential backoff before retry
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                await asyncio.sleep(wait_time)

        logger.error(f"All {max_retries} attempts failed for {url[:80]}... Last error: {last_error}")
        return None

    def _get_mime_type(self, url: str, content: bytes) -> str:
        """Determine MIME type from URL extension or content."""
        url_lower = url.lower()
        if '.mp4' in url_lower or '.mov' in url_lower:
            return 'video/mp4'
        elif '.webm' in url_lower:
            return 'video/webm'
        elif '.png' in url_lower:
            return 'image/png'
        elif '.gif' in url_lower:
            return 'image/gif'
        elif '.webp' in url_lower:
            return 'image/webp'
        elif '.jpg' in url_lower or '.jpeg' in url_lower:
            return 'image/jpeg'

        # Check magic bytes
        if content[:4] == b'\x89PNG':
            return 'image/png'
        elif content[:2] == b'\xff\xd8':
            return 'image/jpeg'
        elif content[:4] == b'GIF8':
            return 'image/gif'
        elif content[:4] == b'RIFF' and content[8:12] == b'WEBP':
            return 'image/webp'
        elif content[4:8] == b'ftyp':
            return 'video/mp4'

        return 'application/octet-stream'

    def _get_extension(self, mime_type: str) -> str:
        """Get file extension from MIME type."""
        extensions = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'video/mp4': '.mp4',
            'video/webm': '.webm',
        }
        return extensions.get(mime_type, '')

    def upload_to_storage(
        self,
        content: bytes,
        facebook_ad_id: UUID,
        asset_index: int,
        mime_type: str
    ) -> Optional[str]:
        """
        Upload asset to Supabase storage.

        Args:
            content: File bytes
            facebook_ad_id: UUID of the facebook_ads record
            asset_index: Index for multiple assets per ad
            mime_type: MIME type of the content

        Returns:
            Storage path or None if failed
        """
        try:
            extension = self._get_extension(mime_type)
            filename = f"{facebook_ad_id}_{asset_index}{extension}"
            storage_path = f"{facebook_ad_id}/{filename}"

            self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                storage_path,
                content,
                {"content-type": mime_type, "upsert": "true"}
            )

            full_path = f"{self.STORAGE_BUCKET}/{storage_path}"
            logger.info(f"Uploaded asset to {full_path}")
            return full_path

        except Exception as e:
            logger.error(f"Failed to upload asset: {e}")
            return None

    def save_facebook_ad(
        self,
        ad_data: Dict,
        brand_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        scrape_source: str = "ad_library_search"
    ) -> Optional[UUID]:
        """
        Save a Facebook ad to the database.

        Args:
            ad_data: Ad data from FacebookService (FacebookAd model dict)
            brand_id: Optional brand to link
            project_id: Optional project to link
            scrape_source: Source identifier

        Returns:
            UUID of saved record or None if failed
        """
        result = self.save_facebook_ad_with_tracking(
            ad_data=ad_data,
            brand_id=brand_id,
            project_id=project_id,
            scrape_source=scrape_source
        )
        return result.get("ad_id") if result else None

    def save_facebook_ad_with_tracking(
        self,
        ad_data: Dict,
        brand_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        scrape_source: str = "ad_library_search"
    ) -> Optional[Dict]:
        """
        Save a Facebook ad to the database with longevity tracking.

        This method handles deduplication via ad_archive_id and tracks:
        - first_seen_at: When we first scraped this ad
        - last_seen_at: Last time we saw the ad as active
        - last_checked_at: Last time we checked this ad
        - times_seen: Number of times seen across scrapes

        Args:
            ad_data: Ad data from FacebookService (FacebookAd model dict)
            brand_id: Optional brand to link
            project_id: Optional project to link
            scrape_source: Source identifier

        Returns:
            Dict with ad_id, is_new, was_active (previous active status), or None if failed
        """
        try:
            ad_archive_id = ad_data.get("ad_archive_id")
            if not ad_archive_id:
                logger.error("ad_archive_id is required for saving Facebook ad")
                return None

            # Check if ad already exists
            existing_result = self.supabase.table("facebook_ads").select(
                "id, first_seen_at, is_active, last_seen_at, times_seen"
            ).eq("ad_archive_id", ad_archive_id).maybeSingle().execute()

            existing = existing_result.data
            is_new = existing is None
            was_active = existing.get("is_active") if existing else None

            now = datetime.utcnow().isoformat()
            is_currently_active = ad_data.get("is_active", False)

            # Parse snapshot to extract additional fields
            snapshot_raw = ad_data.get("snapshot")
            snapshot = {}
            if snapshot_raw:
                if isinstance(snapshot_raw, str):
                    try:
                        snapshot = json.loads(snapshot_raw)
                    except json.JSONDecodeError:
                        pass
                elif isinstance(snapshot_raw, dict):
                    snapshot = snapshot_raw

            # Extract body text (nested in body.text)
            body_obj = snapshot.get("body", {})
            ad_body = body_obj.get("text") if isinstance(body_obj, dict) else None

            # Map from FacebookAd model to database columns
            record = {
                "ad_id": ad_data.get("id"),
                "ad_archive_id": ad_archive_id,
                "page_id": ad_data.get("page_id"),
                "page_name": ad_data.get("page_name"),
                "is_active": is_currently_active,
                "start_date": ad_data.get("start_date"),
                "end_date": ad_data.get("end_date"),
                "currency": ad_data.get("currency"),
                "spend": ad_data.get("spend"),
                "impressions": ad_data.get("impressions"),
                "reach_estimate": ad_data.get("reach_estimate"),
                "snapshot": ad_data.get("snapshot"),
                "categories": ad_data.get("categories"),
                "publisher_platform": ad_data.get("publisher_platform"),
                "political_countries": ad_data.get("political_countries"),
                "entity_type": ad_data.get("entity_type"),
                "brand_id": str(brand_id) if brand_id else None,
                "project_id": str(project_id) if project_id else None,
                "scrape_source": scrape_source,
                "scraped_at": now,
                # Extracted fields from snapshot
                "link_url": snapshot.get("link_url"),
                "cta_text": snapshot.get("cta_text"),
                "cta_type": snapshot.get("cta_type"),
                "ad_title": snapshot.get("title"),
                "ad_body": ad_body,
                "caption": snapshot.get("caption"),
                "link_description": snapshot.get("link_description"),
                "page_like_count": snapshot.get("page_like_count"),
                "page_profile_uri": snapshot.get("page_profile_uri"),
                "display_format": snapshot.get("display_format"),
                # Longevity tracking - always update last_checked_at
                "last_checked_at": now,
            }

            # Handle longevity fields based on new vs existing
            if is_new:
                # New ad - set all tracking fields
                record["first_seen_at"] = now
                record["last_seen_at"] = now if is_currently_active else None
                record["times_seen"] = 1
            else:
                # Existing ad - preserve first_seen_at, update others
                record["first_seen_at"] = existing.get("first_seen_at")
                # Update last_seen_at only if currently active
                if is_currently_active:
                    record["last_seen_at"] = now
                else:
                    # Keep the previous last_seen_at (when it was last active)
                    record["last_seen_at"] = existing.get("last_seen_at")
                # Increment times_seen
                record["times_seen"] = (existing.get("times_seen") or 1) + 1

            # Upsert based on ad_archive_id
            result = self.supabase.table("facebook_ads").upsert(
                record,
                on_conflict="ad_archive_id"
            ).execute()

            if result.data:
                ad_id = UUID(result.data[0]["id"])
                action = "Created new" if is_new else "Updated"
                logger.info(f"{action} Facebook ad: {ad_id} (times_seen: {record['times_seen']})")
                return {
                    "ad_id": ad_id,
                    "is_new": is_new,
                    "was_active": was_active
                }

            return None

        except Exception as e:
            ad_archive_id = ad_data.get("ad_archive_id", "unknown")
            logger.error(f"Failed to save Facebook ad (archive_id: {ad_archive_id}): {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def save_failed_asset_record(
        self,
        facebook_ad_id: UUID,
        asset_type: str,
        original_url: str,
        brand_id: Optional[UUID] = None,
        scrape_source: str = "ad_library_search"
    ) -> Optional[UUID]:
        """
        Save a record for a failed asset download.

        Args:
            facebook_ad_id: UUID of the facebook_ads record
            asset_type: 'image' or 'video'
            original_url: Original CDN URL that failed
            brand_id: Optional brand to link
            scrape_source: Source identifier

        Returns:
            UUID of saved record or None if failed
        """
        try:
            record = {
                "facebook_ad_id": str(facebook_ad_id),
                "brand_id": str(brand_id) if brand_id else None,
                "asset_type": asset_type,
                "storage_path": None,
                "original_url": original_url,
                "file_size_bytes": None,
                "mime_type": None,
                "scrape_source": scrape_source,
                "status": "failed",
            }

            result = self.supabase.table("scraped_ad_assets").insert(record).execute()

            if result.data:
                asset_id = result.data[0]["id"]
                logger.info(f"Saved failed asset record: {asset_id}")
                return UUID(asset_id)

            return None

        except Exception as e:
            logger.error(f"Failed to save failed asset record: {e}")
            return None

    def save_asset_record(
        self,
        facebook_ad_id: UUID,
        asset_type: str,
        storage_path: str,
        original_url: str,
        file_size_bytes: int,
        mime_type: str,
        brand_id: Optional[UUID] = None,
        dimensions: Optional[Dict] = None,
        duration_sec: Optional[float] = None,
        scrape_source: str = "ad_library_search",
        status: str = "downloaded"
    ) -> Optional[UUID]:
        """
        Save a scraped asset record to the database.

        Args:
            facebook_ad_id: UUID of the facebook_ads record
            asset_type: 'image' or 'video'
            storage_path: Supabase storage path
            original_url: Original CDN URL
            file_size_bytes: Size of the file
            mime_type: MIME type
            brand_id: Optional brand to link
            dimensions: Optional {width, height}
            duration_sec: Optional video duration
            scrape_source: Source identifier
            status: Asset status ('downloaded', 'failed', 'expired', 'pending')

        Returns:
            UUID of saved record or None if failed
        """
        try:
            record = {
                "facebook_ad_id": str(facebook_ad_id),
                "brand_id": str(brand_id) if brand_id else None,
                "asset_type": asset_type,
                "storage_path": storage_path,
                "original_url": original_url,
                "file_size_bytes": file_size_bytes,
                "mime_type": mime_type,
                "dimensions": dimensions,
                "duration_sec": duration_sec,
                "scrape_source": scrape_source,
                "status": status,
            }

            result = self.supabase.table("scraped_ad_assets").insert(record).execute()

            if result.data:
                asset_id = result.data[0]["id"]
                logger.info(f"Saved asset record: {asset_id}")
                return UUID(asset_id)

            return None

        except Exception as e:
            logger.error(f"Failed to save asset record: {e}")
            return None

    async def scrape_and_store_assets(
        self,
        facebook_ad_id: UUID,
        snapshot: Dict,
        brand_id: Optional[UUID] = None,
        scrape_source: str = "ad_library_search"
    ) -> Dict[str, List[UUID]]:
        """
        Extract, download, and store all assets from an ad snapshot.

        Args:
            facebook_ad_id: UUID of the facebook_ads record
            snapshot: The snapshot data
            brand_id: Optional brand to link
            scrape_source: Source identifier

        Returns:
            {"images": [asset_id1, ...], "videos": [asset_id1, ...]}
        """
        result = {"images": [], "videos": []}

        # Extract URLs
        urls = self.extract_asset_urls(snapshot)

        # Download and store images
        for i, url in enumerate(urls["images"]):
            content = await self.download_asset(url)
            if not content:
                # Record failed download attempt
                self.save_failed_asset_record(
                    facebook_ad_id=facebook_ad_id,
                    asset_type="image",
                    original_url=url,
                    brand_id=brand_id,
                    scrape_source=scrape_source
                )
                continue

            mime_type = self._get_mime_type(url, content)
            storage_path = self.upload_to_storage(
                content, facebook_ad_id, i, mime_type
            )
            if not storage_path:
                continue

            asset_id = self.save_asset_record(
                facebook_ad_id=facebook_ad_id,
                asset_type="image",
                storage_path=storage_path,
                original_url=url,
                file_size_bytes=len(content),
                mime_type=mime_type,
                brand_id=brand_id,
                scrape_source=scrape_source
            )
            if asset_id:
                result["images"].append(asset_id)

        # Download and store videos
        for i, url in enumerate(urls["videos"]):
            logger.info(f"Downloading video {i+1}/{len(urls['videos'])} for ad {facebook_ad_id}")
            content = await self.download_asset(url, timeout=120.0)  # Longer timeout for videos
            if not content:
                logger.warning(f"Failed to download video from: {url[:80]}...")
                # Record failed download attempt
                self.save_failed_asset_record(
                    facebook_ad_id=facebook_ad_id,
                    asset_type="video",
                    original_url=url,
                    brand_id=brand_id,
                    scrape_source=scrape_source
                )
                continue
            logger.info(f"Downloaded video: {len(content)} bytes")

            mime_type = self._get_mime_type(url, content)
            storage_path = self.upload_to_storage(
                content, facebook_ad_id, len(urls["images"]) + i, mime_type
            )
            if not storage_path:
                logger.warning(f"Failed to upload video to storage for ad {facebook_ad_id}")
                continue

            asset_id = self.save_asset_record(
                facebook_ad_id=facebook_ad_id,
                asset_type="video",
                storage_path=storage_path,
                original_url=url,
                file_size_bytes=len(content),
                mime_type=mime_type,
                brand_id=brand_id,
                scrape_source=scrape_source
            )
            if asset_id:
                result["videos"].append(asset_id)

        logger.info(
            f"Scraped {len(result['images'])} images, {len(result['videos'])} videos "
            f"for ad {facebook_ad_id}"
        )
        return result

    async def scrape_and_store_competitor_assets(
        self,
        competitor_ad_id: UUID,
        competitor_id: UUID,
        snapshot: Dict,
        scrape_source: str = "competitor_research"
    ) -> Dict[str, List[UUID]]:
        """
        Extract, download, and store all assets from a competitor ad snapshot.

        Mirrors scrape_and_store_assets but stores to competitor_ad_assets table.

        Args:
            competitor_ad_id: UUID of the competitor_ads record
            competitor_id: UUID of the competitor
            snapshot: The snapshot_data
            scrape_source: Source identifier

        Returns:
            {"images": [asset_id1, ...], "videos": [asset_id1, ...]}
        """
        result = {"images": [], "videos": []}

        # Extract URLs
        urls = self.extract_asset_urls(snapshot)

        logger.info(f"Competitor ad {str(competitor_ad_id)[:8]}: found {len(urls['images'])} images, {len(urls['videos'])} videos")

        # Download and store images
        for i, url in enumerate(urls["images"][:5]):  # Limit to 5 images per ad
            content = await self.download_asset(url)
            if not content:
                continue

            mime_type = self._get_mime_type(url, content)
            storage_path = f"competitors/{competitor_id}/{competitor_ad_id}/asset_{i}.{mime_type.split('/')[-1]}"

            try:
                # Use upsert to overwrite if file exists in storage
                self.supabase.storage.from_("scraped-assets").upload(
                    storage_path,
                    content,
                    {"content-type": mime_type, "upsert": "true"}
                )
                logger.info(f"Uploaded image to storage: {storage_path}")

                # Save to competitor_ad_assets table
                record = {
                    "competitor_ad_id": str(competitor_ad_id),
                    "asset_type": "image",
                    "storage_path": f"scraped-assets/{storage_path}",
                    "original_url": url,
                    "file_size": len(content),
                    "mime_type": mime_type,
                }

                try:
                    db_result = self.supabase.table("competitor_ad_assets").insert(record).execute()
                    if db_result.data:
                        result["images"].append(UUID(db_result.data[0]["id"]))
                except Exception as db_err:
                    # Record might already exist, that's OK - file is uploaded
                    if "duplicate" in str(db_err).lower() or "already exists" in str(db_err).lower():
                        logger.debug(f"DB record already exists for {storage_path}, file uploaded successfully")
                        # Still count as success since file is there
                        result["images"].append(competitor_ad_id)  # Use ad ID as placeholder
                    else:
                        raise db_err

            except Exception as e:
                logger.warning(f"Failed to store competitor image: {e}")

        # Download and store videos
        for i, url in enumerate(urls["videos"][:2]):  # Limit to 2 videos per ad
            logger.info(f"Downloading video {i+1}/{len(urls['videos'])} for competitor ad {str(competitor_ad_id)[:8]}")
            content = await self.download_asset(url, timeout=120.0)
            if not content:
                logger.warning(f"Failed to download video from: {url[:80]}...")
                continue
            logger.info(f"Downloaded video: {len(content)} bytes")

            mime_type = self._get_mime_type(url, content)
            storage_path = f"competitors/{competitor_id}/{competitor_ad_id}/video_{i}.{mime_type.split('/')[-1]}"

            try:
                # Use upsert to overwrite if file exists in storage
                self.supabase.storage.from_("scraped-assets").upload(
                    storage_path,
                    content,
                    {"content-type": mime_type, "upsert": "true"}
                )
                logger.info(f"Uploaded video to storage: {storage_path}")

                record = {
                    "competitor_ad_id": str(competitor_ad_id),
                    "asset_type": "video",
                    "storage_path": f"scraped-assets/{storage_path}",
                    "original_url": url,
                    "file_size": len(content),
                    "mime_type": mime_type,
                }

                try:
                    db_result = self.supabase.table("competitor_ad_assets").insert(record).execute()
                    if db_result.data:
                        result["videos"].append(UUID(db_result.data[0]["id"]))
                except Exception as db_err:
                    # Record might already exist, that's OK - file is uploaded
                    if "duplicate" in str(db_err).lower() or "already exists" in str(db_err).lower():
                        logger.debug(f"DB record already exists for {storage_path}, file uploaded successfully")
                        result["videos"].append(competitor_ad_id)  # Use ad ID as placeholder
                    else:
                        raise db_err

            except Exception as e:
                logger.warning(f"Failed to store competitor video: {e}")

        logger.info(
            f"Scraped {len(result['images'])} images, {len(result['videos'])} videos "
            f"for competitor ad {str(competitor_ad_id)[:8]}"
        )
        return result

    def get_ads_without_assets(
        self,
        brand_id: Optional[UUID] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get Facebook ads that don't have scraped assets yet.

        Args:
            brand_id: Optional filter by brand
            limit: Maximum number to return

        Returns:
            List of facebook_ads records
        """
        try:
            query = self.supabase.table("facebook_ads").select(
                "id, ad_archive_id, page_name, snapshot"
            )

            if brand_id:
                query = query.eq("brand_id", str(brand_id))

            # Left join to find ads without assets
            # Note: This is a simplified version - for production, use a proper subquery
            result = query.limit(limit).execute()

            if not result.data:
                return []

            # Filter out ads that already have assets
            ads_with_assets = set()
            assets_result = self.supabase.table("scraped_ad_assets").select(
                "facebook_ad_id"
            ).execute()
            if assets_result.data:
                ads_with_assets = {r["facebook_ad_id"] for r in assets_result.data}

            return [ad for ad in result.data if ad["id"] not in ads_with_assets]

        except Exception as e:
            logger.error(f"Failed to get ads without assets: {e}")
            return []

    async def refresh_expired_assets(self, brand_id: UUID) -> Dict:
        """
        Re-scrape ads that have expired/failed assets.

        This method finds all ads with expired or failed assets, deletes those
        records, and attempts to re-download from fresh CDN URLs in the snapshot.

        Args:
            brand_id: UUID of the brand to refresh assets for

        Returns:
            {
                "refreshed": 5,
                "still_failed": 2,
                "ads_rescraped": 3
            }
        """
        # Find assets with expired/failed status for this brand
        problem_assets = self.supabase.table("scraped_ad_assets").select(
            "id, facebook_ad_id, original_url, asset_type"
        ).eq("brand_id", str(brand_id)).in_(
            "status", ["expired", "failed"]
        ).execute()

        if not problem_assets.data:
            logger.info(f"No expired/failed assets found for brand: {brand_id}")
            return {"refreshed": 0, "still_failed": 0, "ads_rescraped": 0}

        # Group by ad ID
        ads_to_rescrape = {}
        for asset in problem_assets.data:
            ad_id = asset['facebook_ad_id']
            if ad_id not in ads_to_rescrape:
                ads_to_rescrape[ad_id] = []
            ads_to_rescrape[ad_id].append(asset)

        logger.info(f"Found {len(problem_assets.data)} expired/failed assets in {len(ads_to_rescrape)} ads")

        refreshed = 0
        still_failed = 0

        for ad_id, assets in ads_to_rescrape.items():
            try:
                # Get fresh snapshot from facebook_ads
                ad_result = self.supabase.table("facebook_ads").select(
                    "snapshot"
                ).eq("id", ad_id).single().execute()

                if not ad_result.data:
                    logger.warning(f"Ad not found: {ad_id}")
                    still_failed += len(assets)
                    continue

                snapshot = ad_result.data.get('snapshot')
                if not snapshot:
                    logger.warning(f"No snapshot for ad: {ad_id}")
                    still_failed += len(assets)
                    continue

                # Extract fresh URLs from snapshot
                urls = self.extract_asset_urls(snapshot)
                all_urls = urls.get('images', []) + urls.get('videos', [])

                if not all_urls:
                    logger.warning(f"No URLs found in snapshot for ad: {ad_id}")
                    still_failed += len(assets)
                    continue

                # Delete the failed/expired asset records for this ad
                asset_ids = [a['id'] for a in assets]
                self.supabase.table("scraped_ad_assets").delete().in_("id", asset_ids).execute()
                logger.info(f"Deleted {len(asset_ids)} expired/failed records for ad: {ad_id}")

                # Re-scrape the ad
                result = await self.scrape_and_store_assets(
                    facebook_ad_id=UUID(ad_id),
                    snapshot=snapshot,
                    brand_id=brand_id,
                    scrape_source="refresh_expired"
                )

                # Count successes and failures
                # Compare to original asset count
                new_success = len(result.get('images', [])) + len(result.get('videos', []))
                original_count = len(assets)

                if new_success >= original_count:
                    refreshed += original_count
                else:
                    refreshed += new_success
                    still_failed += (original_count - new_success)

                logger.info(f"Re-scraped ad {ad_id}: {new_success} new assets")

            except Exception as e:
                logger.error(f"Failed to refresh assets for ad {ad_id}: {e}")
                still_failed += len(assets)

        logger.info(
            f"Refresh complete: {refreshed} refreshed, {still_failed} still failed, "
            f"{len(ads_to_rescrape)} ads processed"
        )

        return {
            "refreshed": refreshed,
            "still_failed": still_failed,
            "ads_rescraped": len(ads_to_rescrape)
        }
