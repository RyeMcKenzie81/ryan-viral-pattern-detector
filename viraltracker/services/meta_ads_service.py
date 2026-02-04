"""
MetaAdsService - Facebook/Meta Ads API integration for performance feedback loop.

Handles all Meta Ads API interactions with intelligent rate limiting and retries.
Fetches ad performance data, manages ad-to-generated-ad mappings, and stores
time-series performance snapshots.
"""

import logging
import asyncio
import time
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from ..core.config import Config
from .models import (
    MetaAdPerformance,
    MetaAdMapping,
    MetaCampaign,
    BrandAdAccount
)

logger = logging.getLogger(__name__)


class MetaAdsService:
    """
    Service for Meta Ads API operations with rate limiting.

    Features:
    - Automatic rate limiting (configurable)
    - Exponential backoff on rate limit errors
    - Metric normalization from arrays to flat dicts
    - Auto-matching generated ads by ID pattern in ad names
    - Time-series performance storage
    """

    # Meta API fields to request
    INSIGHT_FIELDS = [
        "ad_id",
        "ad_name",
        "adset_id",
        "adset_name",
        "campaign_id",
        "campaign_name",
        "spend",
        "impressions",
        "reach",
        "frequency",
        "cpm",
        "clicks",
        "outbound_clicks",
        "outbound_clicks_ctr",
        "cost_per_outbound_click",
        "actions",
        "action_values",
        "cost_per_action_type",
        "purchase_roas",
        "video_play_actions",
        "video_avg_time_watched_actions",
        "video_p25_watched_actions",
        "video_p50_watched_actions",
        "video_p75_watched_actions",
        "video_p100_watched_actions",
    ]

    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None
    ):
        """
        Initialize Meta Ads service.

        Args:
            access_token: Meta Graph API access token (if None, uses Config)
            ad_account_id: Default ad account ID (if None, uses Config as fallback)

        Note:
            For per-brand accounts, use get_ad_account_for_brand() or pass
            brand_id to methods. The ad_account_id here is just a fallback.
        """
        self.access_token = access_token or Config.META_GRAPH_API_TOKEN
        self._default_ad_account_id = ad_account_id or Config.META_AD_ACCOUNT_ID

        if not self.access_token:
            logger.warning("META_GRAPH_API_TOKEN not found - MetaAdsService will not work")

        # Rate limiting: Meta standard tier is 9,000 points / 300 seconds
        # We'll be conservative with 100 requests/minute
        self._last_call_time = 0.0
        self._requests_per_minute = 100
        self._min_delay = 60.0 / self._requests_per_minute

        # SDK initialization (lazy load to avoid import errors if SDK not installed)
        self._api = None
        self._ad_accounts_cache: Dict[str, Any] = {}  # Cache AdAccount objects by ID

        logger.info(f"MetaAdsService initialized (default account: {self._default_ad_account_id})")

    async def get_ad_account_for_brand(self, brand_id: UUID) -> Optional[str]:
        """
        Get the Meta ad account ID for a brand from brand_ad_accounts table.

        Args:
            brand_id: Brand UUID

        Returns:
            Meta ad account ID (e.g., "act_123456789") or None if not set up
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        result = supabase.table("brand_ad_accounts").select(
            "meta_ad_account_id"
        ).eq(
            "brand_id", str(brand_id)
        ).eq(
            "is_primary", True
        ).limit(1).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]["meta_ad_account_id"]

        return None

    async def link_brand_to_ad_account(
        self,
        brand_id: UUID,
        meta_ad_account_id: str,
        account_name: Optional[str] = None,
        is_primary: bool = True
    ) -> Dict[str, Any]:
        """
        Link a brand to a Meta ad account.

        Args:
            brand_id: Brand UUID
            meta_ad_account_id: Meta ad account ID (e.g., "act_123456789")
            account_name: Optional display name
            is_primary: Whether this is the primary account for the brand

        Returns:
            Created record
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # If setting as primary, unset other primaries first
        if is_primary:
            supabase.table("brand_ad_accounts").update(
                {"is_primary": False}
            ).eq(
                "brand_id", str(brand_id)
            ).execute()

        record = {
            "brand_id": str(brand_id),
            "meta_ad_account_id": meta_ad_account_id,
            "account_name": account_name,
            "is_primary": is_primary,
        }

        result = supabase.table("brand_ad_accounts").upsert(
            record,
            on_conflict="brand_id,meta_ad_account_id"
        ).execute()

        if result.data:
            logger.info(f"Linked brand {brand_id} to ad account {meta_ad_account_id}")
            return result.data[0]
        else:
            raise Exception("Failed to link brand to ad account")

    def _get_ad_account_id(self, brand_id: Optional[UUID] = None, ad_account_id: Optional[str] = None) -> str:
        """
        Resolve which ad account ID to use.

        Priority:
        1. Explicitly passed ad_account_id
        2. Look up from brand_ad_accounts (if brand_id provided) - requires async caller
        3. Default from config

        For async brand lookup, use get_ad_account_for_brand() first.
        """
        if ad_account_id:
            return ad_account_id
        if self._default_ad_account_id:
            return self._default_ad_account_id
        raise ValueError("No ad account ID available. Set up brand_ad_accounts or provide ad_account_id.")

    def _ensure_sdk(self) -> None:
        """Lazy-load the Meta SDK to avoid import errors."""
        if self._api is not None:
            return

        try:
            from facebook_business.api import FacebookAdsApi

            self._api = FacebookAdsApi.init(access_token=self.access_token)
            logger.info("Meta Ads SDK initialized successfully")
        except ImportError:
            raise ImportError(
                "facebook-business SDK not installed. "
                "Install with: pip install facebook-business"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Meta SDK: {e}")
            raise

    def _get_ad_account_object(self, ad_account_id: str):
        """Get or create an AdAccount object for the given ID."""
        from facebook_business.adobjects.adaccount import AdAccount

        if ad_account_id not in self._ad_accounts_cache:
            self._ad_accounts_cache[ad_account_id] = AdAccount(ad_account_id)

        return self._ad_accounts_cache[ad_account_id]

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_delay:
            wait_time = self._min_delay - elapsed
            await asyncio.sleep(wait_time)
        self._last_call_time = time.time()

    def set_rate_limit(self, requests_per_minute: int) -> None:
        """
        Set rate limit for API calls.

        Args:
            requests_per_minute: Maximum requests per minute
        """
        self._requests_per_minute = requests_per_minute
        self._min_delay = 60.0 / requests_per_minute
        logger.info(f"Rate limit set to {requests_per_minute} req/min")

    async def get_ad_insights(
        self,
        brand_id: Optional[UUID] = None,
        ad_account_id: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        days_back: int = 30,
        level: str = "ad",
        max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Fetch ad insights from Meta Ads API.

        Args:
            brand_id: Brand UUID to look up ad account from brand_ad_accounts.
            ad_account_id: Explicit ad account ID (overrides brand lookup).
            date_start: Start date (YYYY-MM-DD). If None, uses days_back.
            date_end: End date (YYYY-MM-DD). If None, uses today.
            days_back: Days to look back if date_start not provided.
            level: 'ad', 'adset', or 'campaign'
            max_retries: Maximum retries on rate limit errors.

        Returns:
            List of insight dictionaries with normalized metrics.

        Raises:
            Exception: If API call fails after retries.
        """
        self._ensure_sdk()
        await self._rate_limit()

        # Resolve ad account ID
        if not ad_account_id and brand_id:
            ad_account_id = await self.get_ad_account_for_brand(brand_id)
            if not ad_account_id:
                raise ValueError(f"No ad account linked to brand {brand_id}. Set up in brand_ad_accounts first.")

        resolved_account_id = self._get_ad_account_id(ad_account_id=ad_account_id)

        # Calculate date range
        if date_end is None:
            date_end = datetime.now().strftime("%Y-%m-%d")
        if date_start is None:
            start_dt = datetime.now() - timedelta(days=days_back)
            date_start = start_dt.strftime("%Y-%m-%d")

        params = {
            "time_range": {"since": date_start, "until": date_end},
            "level": level,
            "time_increment": 1,  # Daily breakdown
        }

        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                logger.info(f"Fetching insights for {date_start} to {date_end} from {resolved_account_id}")

                # Make API call in thread pool to avoid blocking
                insights = await asyncio.to_thread(
                    self._fetch_insights_sync,
                    resolved_account_id,
                    params
                )

                # Normalize each insight and add account ID
                normalized = []
                for i in insights:
                    norm = self.normalize_metrics(i)
                    norm["meta_ad_account_id"] = resolved_account_id
                    normalized.append(norm)

                logger.info(f"Fetched {len(normalized)} insight records")
                return normalized

            except Exception as e:
                error_str = str(e).lower()
                last_error = e

                if "rate" in error_str or "limit" in error_str or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        retry_delay = 15 * (2 ** (retry_count - 1))
                        logger.warning(f"Rate limit hit. Retry {retry_count}/{max_retries} after {retry_delay}s")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Max retries exceeded fetching insights")
                        raise Exception(f"Rate limit exceeded after {max_retries} retries: {e}")
                else:
                    logger.error(f"API error: {e}")
                    raise

        raise Exception(f"Failed to fetch insights: {last_error}")

    def _fetch_insights_sync(self, ad_account_id: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Synchronous API call (run in thread pool)."""
        ad_account = self._get_ad_account_object(ad_account_id)

        insights = ad_account.get_insights(
            fields=self.INSIGHT_FIELDS,
            params=params
        )

        # Convert to list of dicts
        return [dict(i) for i in insights]

    def _fetch_video_source_url_sync(self, video_id: str) -> Optional[str]:
        """Synchronous call to get a downloadable video source URL from Meta.

        Uses the AdVideo endpoint to get a temporary direct-download URL.

        Args:
            video_id: Meta video ID from AdCreative.

        Returns:
            Temporary video source URL or None.
        """
        from facebook_business.adobjects.advideo import AdVideo

        video = AdVideo(video_id)
        video_data = video.api_get(fields=["source"])
        return video_data.get("source")

    async def fetch_video_source_url(self, video_id: str) -> Optional[str]:
        """Get a temporary downloadable URL for a Meta video.

        Args:
            video_id: Meta video ID from AdCreative.

        Returns:
            Temporary video source URL or None.
        """
        self._ensure_sdk()
        await self._rate_limit()

        try:
            return await asyncio.to_thread(self._fetch_video_source_url_sync, video_id)
        except Exception as e:
            logger.error(f"Failed to fetch video source URL for {video_id}: {e}")
            return None

    async def fetch_ad_thumbnails(
        self,
        ad_ids: List[str],
        ad_account_id: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch thumbnail URLs and video metadata for a list of ad IDs.

        Args:
            ad_ids: List of Meta ad IDs
            ad_account_id: Ad account ID (for rate limiting context)

        Returns:
            Dict mapping ad_id -> {"thumbnail_url": str, "video_id": str|None, "is_video": bool}
        """
        if not ad_ids:
            return {}

        self._ensure_sdk()
        await self._rate_limit()

        try:
            thumbnails = await asyncio.to_thread(
                self._fetch_thumbnails_sync,
                ad_ids
            )
            logger.info(f"Fetched {len(thumbnails)} ad thumbnails")
            return thumbnails
        except Exception as e:
            logger.error(f"Failed to fetch ad thumbnails: {e}")
            return {}

    def _fetch_thumbnails_sync(self, ad_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Synchronous call to fetch ad images/thumbnails and video metadata.

        For image ads: fetches full resolution image_url
        For video ads: fetches thumbnail_url and video_id

        Returns:
            Dict mapping ad_id -> {"thumbnail_url": str, "video_id": str|None, "is_video": bool}
        """
        from facebook_business.adobjects.ad import Ad
        from facebook_business.adobjects.adcreative import AdCreative

        thumbnails: Dict[str, Dict[str, Any]] = {}
        logger.info(f"[THUMBNAILS] _fetch_thumbnails_sync called with {len(ad_ids)} ads")
        for ad_id in ad_ids:
            try:
                # Step 1: Get the creative ID from the ad
                ad = Ad(ad_id)
                ad_data = ad.api_get(fields=["id", "creative"])

                creative_data = ad_data.get("creative")
                if not creative_data:
                    logger.warning(f"[THUMBNAILS] No creative for ad {ad_id}")
                    continue

                creative_id = creative_data.get("id")
                if not creative_id:
                    continue

                # Step 2: Fetch the creative with all relevant fields
                creative = AdCreative(creative_id)
                creative_info = creative.api_get(fields=[
                    "id",
                    "thumbnail_url",
                    "image_url",
                    "image_hash",
                    "video_id",
                    "object_story_spec",
                    "object_type",
                    "asset_feed_spec",
                    "effective_object_story_id"
                ])

                # Check if this is a video ad
                # IMPORTANT: Use video_data.video_id (the uploaded asset) over top-level
                # video_id (the published reel) - only video_data has downloadable source
                video_id = creative_info.get("video_id")
                story_spec = creative_info.get("object_story_spec", {})
                video_data = story_spec.get("video_data", {})
                video_data_id = video_data.get("video_id")

                # Prefer video_data.video_id for downloads (has source access)
                if video_data_id:
                    video_id = video_data_id

                is_video = bool(video_id)
                object_type = creative_info.get("object_type", "")
                if "VIDEO" in object_type.upper():
                    is_video = True

                # Debug logging
                direct_image_url = creative_info.get("image_url")
                direct_thumb_url = creative_info.get("thumbnail_url")
                logger.info(f"Ad {ad_id}: is_video={is_video}, object_type={object_type}, video_id={video_id}, video_data_id={video_data_id}, image_url={bool(direct_image_url)}, thumbnail_url={bool(direct_thumb_url)}")

                image_url = None

                if is_video:
                    # For video ads, use thumbnail
                    image_url = creative_info.get("thumbnail_url")
                    logger.info(f"Ad {ad_id}: VIDEO - using thumbnail_url")
                else:
                    # For image ads, try multiple sources for full resolution

                    # 1. Direct image_url
                    image_url = creative_info.get("image_url")
                    if image_url:
                        logger.info(f"Ad {ad_id}: IMAGE - using direct image_url")

                    # 2. object_story_spec.link_data
                    if not image_url:
                        story_spec = creative_info.get("object_story_spec", {})
                        link_data = story_spec.get("link_data", {})
                        image_url = link_data.get("image_url") or link_data.get("picture")
                        if image_url:
                            logger.info(f"Ad {ad_id}: IMAGE - using link_data image")

                        # Also check photo_data for photo posts
                        if not image_url:
                            photo_data = story_spec.get("photo_data", {})
                            image_url = photo_data.get("url") or photo_data.get("image_url")
                            if image_url:
                                logger.info(f"Ad {ad_id}: IMAGE - using photo_data")

                    # 3. asset_feed_spec for dynamic ads
                    if not image_url:
                        asset_feed = creative_info.get("asset_feed_spec", {})
                        images = asset_feed.get("images", [])
                        if images and len(images) > 0:
                            image_url = images[0].get("url")
                            if image_url:
                                logger.info(f"Ad {ad_id}: IMAGE - using asset_feed_spec")

                    # 4. Last resort: thumbnail_url
                    if not image_url:
                        image_url = creative_info.get("thumbnail_url")
                        if image_url:
                            logger.info(f"Ad {ad_id}: IMAGE - FALLBACK to thumbnail_url (no image_url found)")

                if image_url:
                    thumbnails[ad_id] = {
                        "thumbnail_url": image_url,
                        "video_id": video_id,
                        "is_video": is_video,
                    }
                else:
                    logger.warning(f"No image found for ad {ad_id}, creative {creative_id}")

            except Exception as e:
                logger.warning(f"Could not fetch image for {ad_id}: {e}")
                continue

        return thumbnails

    def normalize_metrics(self, insight: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Meta API response to flat metrics dict.

        The 'actions' and 'cost_per_action_type' fields come back as arrays,
        so we need to extract specific action types.

        Args:
            insight: Raw insight dict from Meta API

        Returns:
            Normalized dict with flat metric fields
        """
        # Calculate CPM if not provided by API
        spend = self._parse_float(insight.get("spend"))
        impressions = self._parse_int(insight.get("impressions"))
        cpm = self._parse_float(insight.get("cpm"))
        if cpm is None and spend and impressions and impressions > 0:
            cpm = (spend / impressions) * 1000

        result = {
            "meta_ad_id": insight.get("ad_id"),
            "ad_name": insight.get("ad_name"),
            "meta_adset_id": insight.get("adset_id"),
            "adset_name": insight.get("adset_name"),
            "meta_campaign_id": insight.get("campaign_id"),
            "campaign_name": insight.get("campaign_name"),
            "date": insight.get("date_start"),
            "spend": spend,
            "impressions": impressions,
            "reach": self._parse_int(insight.get("reach")),
            "frequency": self._parse_float(insight.get("frequency")),
            "cpm": cpm,
            "link_clicks": self._extract_outbound_clicks(insight),
            "link_ctr": self._parse_float(
                insight.get("outbound_clicks_ctr", [{}])[0].get("value")
                if isinstance(insight.get("outbound_clicks_ctr"), list)
                else insight.get("outbound_clicks_ctr")
            ),
            "link_cpc": self._parse_float(
                insight.get("cost_per_outbound_click", [{}])[0].get("value")
                if isinstance(insight.get("cost_per_outbound_click"), list)
                else insight.get("cost_per_outbound_click")
            ),
            "roas": self._extract_roas(insight),
            # Extract from actions array
            "add_to_carts": self._extract_action(insight, "add_to_cart"),
            "purchases": self._extract_action(insight, "purchase"),
            "purchase_value": self._extract_action_value(insight, "purchase"),
            # Costs
            "cost_per_add_to_cart": self._extract_cost(insight, "add_to_cart"),
            # Video metrics
            "video_views": self._extract_video_metric(insight, "video_play_actions"),
            "video_avg_watch_time": self._extract_video_metric(insight, "video_avg_time_watched_actions"),
            "video_p25_watched": self._extract_video_metric(insight, "video_p25_watched_actions"),
            "video_p50_watched": self._extract_video_metric(insight, "video_p50_watched_actions"),
            "video_p75_watched": self._extract_video_metric(insight, "video_p75_watched_actions"),
            "video_p100_watched": self._extract_video_metric(insight, "video_p100_watched_actions"),
            # Raw data for extensibility
            "raw_actions": insight.get("actions"),
            "raw_costs": insight.get("cost_per_action_type"),
        }

        # Calculate conversion rate
        if result["purchases"] and result["link_clicks"]:
            result["conversion_rate"] = (result["purchases"] / result["link_clicks"]) * 100
        else:
            result["conversion_rate"] = None

        return result

    def _parse_float(self, value: Any) -> Optional[float]:
        """Safely parse float from various formats."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _parse_int(self, value: Any) -> Optional[int]:
        """Safely parse int from various formats."""
        if value is None:
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _extract_outbound_clicks(self, insight: Dict[str, Any]) -> Optional[int]:
        """Extract outbound clicks from insight."""
        outbound = insight.get("outbound_clicks")
        if isinstance(outbound, list) and len(outbound) > 0:
            return self._parse_int(outbound[0].get("value"))
        return None

    def _extract_roas(self, insight: Dict[str, Any]) -> Optional[float]:
        """Extract ROAS from insight."""
        roas = insight.get("purchase_roas")
        if isinstance(roas, list) and len(roas) > 0:
            return self._parse_float(roas[0].get("value"))
        return self._parse_float(roas)

    def _extract_action(self, insight: Dict[str, Any], action_type: str) -> Optional[int]:
        """Extract count for a specific action type."""
        actions = insight.get("actions", [])
        if not isinstance(actions, list):
            return None
        for action in actions:
            if action.get("action_type") == action_type:
                return self._parse_int(action.get("value"))
        return None

    def _extract_action_value(self, insight: Dict[str, Any], action_type: str) -> Optional[float]:
        """Extract value for a specific action type."""
        action_values = insight.get("action_values", [])
        if not isinstance(action_values, list):
            return None
        for action in action_values:
            if action.get("action_type") == action_type:
                return self._parse_float(action.get("value"))
        return None

    def _extract_cost(self, insight: Dict[str, Any], action_type: str) -> Optional[float]:
        """Extract cost for a specific action type."""
        costs = insight.get("cost_per_action_type", [])
        if not isinstance(costs, list):
            return None
        for cost in costs:
            if cost.get("action_type") == action_type:
                return self._parse_float(cost.get("value"))
        return None

    def _extract_video_metric(self, insight: Dict[str, Any], field: str) -> Optional[int]:
        """Extract video metric from insight."""
        value = insight.get(field)
        if isinstance(value, list) and len(value) > 0:
            return self._parse_int(value[0].get("value"))
        return None

    def find_matching_generated_ad_id(self, ad_name: str) -> Optional[str]:
        """
        Try to extract a generated_ad_id from the Meta ad name.

        Supports two filename formats:
        - New: d4e5f6a7-WP-C3-SQ.png (8-char ID first)
        - Old: WP-C3-a1b2c3-d4e5f6-SQ.png (6-char ID in 4th position)

        Args:
            ad_name: The Meta ad name

        Returns:
            6-8 char ID if found, None otherwise
        """
        if not ad_name:
            return None

        ad_name_lower = ad_name.lower()

        # Pattern 1: New format - 8 hex chars at start
        # Example: d4e5f6a7-WP-C3-SQ.png or "d4e5f6a7 - Summer Sale"
        patterns_8char = [
            r"^([a-f0-9]{8})",  # Start of string
            r"[\s\-_]([a-f0-9]{8})[\s\-_]",  # Between delimiters
            r"[\s\-_]([a-f0-9]{8})$",  # End of string
        ]

        for pattern in patterns_8char:
            match = re.search(pattern, ad_name_lower)
            if match:
                return match.group(1)

        # Pattern 2: Old format - 6 hex chars, typically in filename structure
        # Example: WP-C3-a1b2c3-d4e5f6-SQ.png
        # Look for the 4th segment which is the ad_id
        old_format_match = re.search(
            r"[A-Za-z]{2,4}-[A-Za-z0-9]{2,4}-[a-f0-9]{6}-([a-f0-9]{6})-[A-Za-z]{2}",
            ad_name_lower
        )
        if old_format_match:
            return old_format_match.group(1)

        # Pattern 3: Any 6 hex chars between hyphens (more flexible)
        # This catches variations of the old format
        six_char_match = re.search(r"-([a-f0-9]{6})-", ad_name_lower)
        if six_char_match:
            return six_char_match.group(1)

        return None

    async def fetch_ad_statuses(
        self,
        ad_ids: List[str],
        ad_account_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Fetch effective_status for a list of ad IDs from Meta API.

        Args:
            ad_ids: List of Meta ad IDs
            ad_account_id: Ad account ID (for rate limiting context)

        Returns:
            Dict mapping ad_id -> effective_status (ACTIVE, PAUSED, DELETED, etc.)
        """
        if not ad_ids:
            return {}

        self._ensure_sdk()

        # Deduplicate ad IDs
        unique_ids = list(set(ad_ids))

        try:
            statuses = await asyncio.to_thread(
                self._fetch_ad_statuses_sync,
                unique_ids
            )
            logger.info(f"Fetched statuses for {len(statuses)} ads")
            return statuses
        except Exception as e:
            logger.error(f"Failed to fetch ad statuses: {e}")
            return {}

    def _fetch_ad_statuses_sync(self, ad_ids: List[str]) -> Dict[str, str]:
        """Synchronous call to fetch ad statuses."""
        from facebook_business.adobjects.ad import Ad

        statuses = {}

        # Batch fetch to reduce API calls (up to 50 at a time)
        batch_size = 50
        for i in range(0, len(ad_ids), batch_size):
            batch_ids = ad_ids[i:i + batch_size]

            for ad_id in batch_ids:
                try:
                    ad = Ad(ad_id)
                    ad_data = ad.api_get(fields=["id", "effective_status"])
                    status = ad_data.get("effective_status", "UNKNOWN")
                    statuses[ad_id] = status
                except Exception as e:
                    logger.warning(f"Failed to fetch status for ad {ad_id}: {e}")
                    continue

        return statuses

    async def sync_performance_to_db(
        self,
        insights: List[Dict[str, Any]],
        brand_id: Optional[UUID] = None,
        fetch_statuses: bool = True
    ) -> int:
        """
        Save performance insights to database.

        Args:
            insights: Normalized insight dicts from get_ad_insights()
            brand_id: Optional brand to associate with
            fetch_statuses: Whether to fetch current ad statuses from Meta API

        Returns:
            Number of records saved
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()
        saved_count = 0

        # Fetch ad statuses if requested
        ad_statuses = {}
        if fetch_statuses and insights:
            unique_ad_ids = list(set(i.get("meta_ad_id") for i in insights if i.get("meta_ad_id")))
            if unique_ad_ids:
                logger.info(f"Fetching statuses for {len(unique_ad_ids)} unique ads...")
                ad_statuses = await self.fetch_ad_statuses(unique_ad_ids)

        for insight in insights:
            try:
                ad_id = insight["meta_ad_id"]

                # Prepare record - use account ID from insight (set during get_ad_insights)
                record = {
                    "meta_ad_account_id": insight.get("meta_ad_account_id", self._default_ad_account_id),
                    "meta_ad_id": ad_id,
                    "meta_adset_id": insight.get("meta_adset_id"),
                    "adset_name": insight.get("adset_name"),
                    "meta_campaign_id": insight["meta_campaign_id"],
                    "campaign_name": insight.get("campaign_name"),
                    "ad_name": insight.get("ad_name"),
                    "date": insight["date"],
                    "spend": insight.get("spend"),
                    "impressions": insight.get("impressions"),
                    "reach": insight.get("reach"),
                    "frequency": insight.get("frequency"),
                    "cpm": insight.get("cpm"),
                    "link_clicks": insight.get("link_clicks"),
                    "link_ctr": insight.get("link_ctr"),
                    "link_cpc": insight.get("link_cpc"),
                    "add_to_carts": insight.get("add_to_carts"),
                    "cost_per_add_to_cart": insight.get("cost_per_add_to_cart"),
                    "purchases": insight.get("purchases"),
                    "purchase_value": insight.get("purchase_value"),
                    "roas": insight.get("roas"),
                    "conversion_rate": insight.get("conversion_rate"),
                    "video_views": insight.get("video_views"),
                    "video_avg_watch_time": insight.get("video_avg_watch_time"),
                    "video_p25_watched": insight.get("video_p25_watched"),
                    "video_p50_watched": insight.get("video_p50_watched"),
                    "video_p75_watched": insight.get("video_p75_watched"),
                    "video_p100_watched": insight.get("video_p100_watched"),
                    "raw_actions": insight.get("raw_actions"),
                    "raw_costs": insight.get("raw_costs"),
                    "thumbnail_url": insight.get("thumbnail_url"),
                    "brand_id": str(brand_id) if brand_id else None,
                    "ad_status": ad_statuses.get(ad_id),  # Add status if fetched
                }

                # Upsert (on conflict with meta_ad_id + date)
                supabase.table("meta_ads_performance").upsert(
                    record,
                    on_conflict="meta_ad_id,date"
                ).execute()

                saved_count += 1

            except Exception as e:
                logger.error(f"Failed to save insight for {insight.get('meta_ad_id')}: {e}")

        logger.info(f"Saved {saved_count}/{len(insights)} performance records (with {len(ad_statuses)} statuses)")
        return saved_count

    async def update_missing_thumbnails(
        self,
        brand_id: Optional[UUID] = None,
        limit: int = 100
    ) -> int:
        """
        Fetch and update thumbnail URLs for ads that don't have them.

        Args:
            brand_id: Optional filter by brand
            limit: Maximum unique ads to update per batch

        Returns:
            Number of thumbnails updated
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()
        logger.info(f"[THUMBNAILS] Starting update_missing_thumbnails for brand {brand_id}")

        # Find ads without thumbnails (check for NULL)
        # Query more rows to ensure we get enough unique ad IDs
        query = supabase.table("meta_ads_performance").select(
            "meta_ad_id"
        ).is_("thumbnail_url", "null")

        if brand_id:
            query = query.eq("brand_id", str(brand_id))

        # Get more rows than limit to account for duplicates
        result = query.limit(limit * 10).execute()
        logger.info(f"[THUMBNAILS] Found {len(result.data) if result.data else 0} rows with NULL thumbnail")

        if not result.data:
            # Also check for empty string thumbnails
            query2 = supabase.table("meta_ads_performance").select(
                "meta_ad_id"
            ).eq("thumbnail_url", "")

            if brand_id:
                query2 = query2.eq("brand_id", str(brand_id))

            result = query2.limit(limit * 10).execute()
            logger.info(f"[THUMBNAILS] Found {len(result.data) if result.data else 0} rows with empty thumbnail")

        if not result.data:
            logger.info("[THUMBNAILS] No ads need thumbnails")
            return 0

        # Get unique ad IDs, limited to batch size
        all_ad_ids = list(set(r["meta_ad_id"] for r in result.data))
        ad_ids = all_ad_ids[:limit]  # Take only up to limit unique ads
        logger.info(f"[THUMBNAILS] Fetching thumbnails for {len(ad_ids)} unique ads (of {len(all_ad_ids)} total missing)")

        # Fetch thumbnails from Meta
        thumbnails = await self.fetch_ad_thumbnails(ad_ids)
        logger.info(f"[THUMBNAILS] Meta returned {len(thumbnails)} thumbnails")

        if not thumbnails:
            logger.info("[THUMBNAILS] No thumbnails returned from Meta API")
            return 0

        # Update database records (thumbnail_url + video metadata)
        updated = 0
        for ad_id, meta in thumbnails.items():
            try:
                update_data = {"thumbnail_url": meta["thumbnail_url"]}
                if meta.get("video_id"):
                    update_data["meta_video_id"] = meta["video_id"]
                if meta.get("is_video") is not None:
                    update_data["is_video"] = meta["is_video"]

                supabase.table("meta_ads_performance").update(
                    update_data
                ).eq("meta_ad_id", ad_id).execute()
                updated += 1
            except Exception as e:
                logger.error(f"[THUMBNAILS] Failed to update {ad_id}: {e}")

        logger.info(f"[THUMBNAILS] Updated {updated} thumbnails in database")
        return updated

    async def get_unlinked_ads(self, brand_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """
        Get Meta ads that aren't linked to any generated ads.

        Args:
            brand_id: Optional filter by brand

        Returns:
            List of unlinked ad dicts
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # First get all linked meta_ad_ids
        linked_result = supabase.table("meta_ad_mapping").select("meta_ad_id").execute()
        linked_ids = [r["meta_ad_id"] for r in (linked_result.data or [])]

        # Get all performance records, optionally filtered by brand
        query = supabase.table("meta_ads_performance").select("*")

        if brand_id:
            query = query.eq("brand_id", str(brand_id))

        result = query.execute()
        all_ads = result.data or []

        # Filter out linked ads and deduplicate by meta_ad_id
        seen = set()
        unlinked = []
        for ad in all_ads:
            meta_id = ad.get("meta_ad_id")
            if meta_id and meta_id not in linked_ids and meta_id not in seen:
                seen.add(meta_id)
                unlinked.append(ad)

        return unlinked

    async def create_ad_mapping(
        self,
        generated_ad_id: UUID,
        meta_ad_id: str,
        meta_campaign_id: str,
        meta_ad_account_id: Optional[str] = None,
        linked_by: str = "manual"
    ) -> Dict[str, Any]:
        """
        Create a link between a generated ad and a Meta ad.

        Args:
            generated_ad_id: ViralTracker generated_ads.id
            meta_ad_id: Meta ad ID
            meta_campaign_id: Meta campaign ID
            meta_ad_account_id: Meta ad account ID (uses default if not provided)
            linked_by: 'auto' or 'manual'

        Returns:
            Created mapping record
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        record = {
            "generated_ad_id": str(generated_ad_id),
            "meta_ad_id": meta_ad_id,
            "meta_ad_account_id": meta_ad_account_id or self._default_ad_account_id,
            "meta_campaign_id": meta_campaign_id,
            "linked_by": linked_by,
        }

        result = supabase.table("meta_ad_mapping").insert(record).execute()

        if result.data:
            logger.info(f"Created mapping: {generated_ad_id} → {meta_ad_id}")
            return result.data[0]
        else:
            raise Exception("Failed to create ad mapping")

    async def _download_and_store_asset(
        self,
        meta_ad_id: str,
        source_url: str,
        brand_id: UUID,
        asset_type: str,
        mime_type: str,
        file_extension: str,
        meta_video_id: Optional[str] = None,
    ) -> Optional[str]:
        """Download an asset from a URL and store it in Supabase storage.

        Generic helper for both video and image downloads.

        Args:
            meta_ad_id: Meta ad ID.
            source_url: URL to download the asset from.
            brand_id: Brand UUID for storage path organization.
            asset_type: 'video' or 'image'.
            mime_type: MIME type (e.g. 'video/mp4', 'image/jpeg').
            file_extension: File extension (e.g. '.mp4', '.jpg').
            meta_video_id: Meta video ID (for video assets only).

        Returns:
            Storage path string or None on failure.
        """
        from ..core.database import get_supabase_client
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=120.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            ) as http_client:
                response = await http_client.get(source_url, follow_redirects=True)
                if response.status_code != 200:
                    logger.warning(
                        f"Failed to download {asset_type} for ad {meta_ad_id}: HTTP {response.status_code}"
                    )
                    return None
                content_bytes = response.content

            file_size = len(content_bytes)
            logger.info(
                f"Downloaded {asset_type} for ad {meta_ad_id}: {file_size / 1024:.1f}KB"
            )

            # Upload to Supabase storage
            storage_key = f"{brand_id}/{meta_ad_id}{file_extension}"
            supabase = get_supabase_client()

            supabase.storage.from_("meta-ad-assets").upload(
                storage_key,
                content_bytes,
                file_options={"content-type": mime_type, "upsert": "true"},
            )

            storage_path = f"meta-ad-assets/{storage_key}"
            logger.info(f"Uploaded {asset_type} to storage: {storage_path}")

            # Record in meta_ad_assets table
            record = {
                "meta_ad_id": meta_ad_id,
                "brand_id": str(brand_id),
                "asset_type": asset_type,
                "storage_path": storage_path,
                "mime_type": mime_type,
                "file_size_bytes": file_size,
                "source_url": source_url,
                "status": "downloaded",
            }
            if meta_video_id:
                record["meta_video_id"] = meta_video_id

            supabase.table("meta_ad_assets").upsert(
                record,
                on_conflict="meta_ad_id,asset_type",
            ).execute()

            return storage_path

        except Exception as e:
            logger.error(f"Failed to download/store {asset_type} for ad {meta_ad_id}: {e}")
            return None

    async def download_and_store_video(
        self,
        meta_ad_id: str,
        video_id: str,
        brand_id: UUID,
    ) -> Optional[str]:
        """Download a video from Meta and store it in Supabase storage.

        Fetches the video source URL via the Marketing API, then delegates
        to _download_and_store_asset for download + storage.

        Args:
            meta_ad_id: Meta ad ID.
            video_id: Meta video ID from AdCreative.
            brand_id: Brand UUID for storage path organization.

        Returns:
            Storage path string or None on failure.
        """
        source_url = await self.fetch_video_source_url(video_id)
        if not source_url:
            logger.warning(f"No source URL for video {video_id} (ad {meta_ad_id}) - marking as not_downloadable")
            # Mark as not_downloadable so we don't retry on future runs
            from ..core.database import get_supabase_client
            supabase = get_supabase_client()
            supabase.table("meta_ad_assets").upsert({
                "meta_ad_id": meta_ad_id,
                "brand_id": str(brand_id),
                "asset_type": "video",
                "storage_path": "",  # No file stored
                "status": "not_downloadable",
                "meta_video_id": video_id,
            }, on_conflict="meta_ad_id,asset_type").execute()
            return None

        return await self._download_and_store_asset(
            meta_ad_id=meta_ad_id,
            source_url=source_url,
            brand_id=brand_id,
            asset_type="video",
            mime_type="video/mp4",
            file_extension=".mp4",
            meta_video_id=video_id,
        )

    async def download_and_store_image(
        self,
        meta_ad_id: str,
        image_url: str,
        brand_id: UUID,
    ) -> Optional[str]:
        """Download an ad image and store it in Supabase storage.

        For static/image ads, the image_url from the creative is the actual
        ad creative (not just a thumbnail). This stores a permanent copy.

        Args:
            meta_ad_id: Meta ad ID.
            image_url: Full-resolution image URL from the creative.
            brand_id: Brand UUID for storage path organization.

        Returns:
            Storage path string or None on failure.
        """
        if not image_url:
            logger.warning(f"No image URL for ad {meta_ad_id}")
            return None

        # Detect format from URL or default to jpg
        ext = ".jpg"
        mime = "image/jpeg"
        url_lower = image_url.lower()
        if ".png" in url_lower:
            ext = ".png"
            mime = "image/png"
        elif ".webp" in url_lower:
            ext = ".webp"
            mime = "image/webp"

        return await self._download_and_store_asset(
            meta_ad_id=meta_ad_id,
            source_url=image_url,
            brand_id=brand_id,
            asset_type="image",
            mime_type=mime,
            file_extension=ext,
        )

    async def get_asset_download_stats(self, brand_id: UUID) -> Dict[str, Any]:
        """Get statistics on asset downloads for a brand.

        Counts UNIQUE ads (not daily performance rows).

        Args:
            brand_id: Brand UUID.

        Returns:
            Dict with stats:
                - videos: {total, downloaded, not_downloadable, pending}
                - images: {total, downloaded, not_downloadable, pending}
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Fetch all performance rows and deduplicate by meta_ad_id
        # Note: meta_ads_performance has daily rows, we need unique ads
        all_perf = supabase.table("meta_ads_performance").select(
            "meta_ad_id, is_video, meta_video_id, thumbnail_url"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        # Deduplicate: track unique video and image ads
        unique_video_ads = set()
        unique_image_ads = set()

        for row in (all_perf.data or []):
            meta_ad_id = row.get("meta_ad_id")
            if not meta_ad_id:
                continue

            is_video = row.get("is_video")
            has_video_id = row.get("meta_video_id") is not None
            has_thumbnail = row.get("thumbnail_url") is not None

            if is_video and has_video_id:
                unique_video_ads.add(meta_ad_id)
            elif (not is_video or is_video is None) and has_thumbnail:
                unique_image_ads.add(meta_ad_id)

        total_videos = len(unique_video_ads)
        total_images = len(unique_image_ads)

        # Count downloaded/not_downloadable assets
        assets_result = supabase.table("meta_ad_assets").select(
            "asset_type, status"
        ).eq(
            "brand_id", str(brand_id)
        ).in_(
            "status", ["downloaded", "not_downloadable"]
        ).execute()

        videos_downloaded = 0
        videos_not_downloadable = 0
        images_downloaded = 0
        images_not_downloadable = 0

        for row in (assets_result.data or []):
            if row["asset_type"] == "video":
                if row["status"] == "downloaded":
                    videos_downloaded += 1
                else:
                    videos_not_downloadable += 1
            elif row["asset_type"] == "image":
                if row["status"] == "downloaded":
                    images_downloaded += 1
                else:
                    images_not_downloadable += 1

        # Total = current ads needing download (from performance)
        # Downloaded may exceed total if ads changed classification since download
        # For cleaner UX, pending = ads still needing download
        videos_pending = max(0, total_videos - videos_downloaded - videos_not_downloadable)
        images_pending = max(0, total_images - images_downloaded - images_not_downloadable)

        return {
            "videos": {
                "total": total_videos,
                "downloaded": min(videos_downloaded, total_videos),  # Cap at total for clean display
                "not_downloadable": videos_not_downloadable,
                "pending": videos_pending,
            },
            "images": {
                "total": total_images,
                "downloaded": min(images_downloaded, total_images),  # Cap at total for clean display
                "not_downloadable": images_not_downloadable,
                "pending": images_pending,
            },
        }

    async def download_new_ad_assets(
        self,
        brand_id: UUID,
        max_videos: int = 20,
        max_images: int = 40,
    ) -> Dict[str, int]:
        """Download ad creatives (videos + images) that aren't stored yet.

        For video ads: fetches video via Marketing API AdVideo endpoint.
        For image ads: fetches the actual ad image from the creative URL
        stored in thumbnail_url (which for image ads is the full-res image).

        Args:
            brand_id: Brand UUID.
            max_videos: Maximum videos to download in this batch.
            max_images: Maximum images to download in this batch.

        Returns:
            Dict with counts: {"videos": N, "images": N}.
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()
        downloaded = {"videos": 0, "images": 0}
        remaining_videos = max_videos
        remaining_images = max_images

        # --- Video ads ---
        video_ads_result = supabase.table("meta_ads_performance").select(
            "meta_ad_id, meta_video_id"
        ).eq(
            "brand_id", str(brand_id)
        ).eq(
            "is_video", True
        ).not_.is_(
            "meta_video_id", "null"
        ).execute()

        video_ads = {}
        for row in (video_ads_result.data or []):
            ad_id = row["meta_ad_id"]
            if ad_id not in video_ads:
                video_ads[ad_id] = row["meta_video_id"]

        # --- Image ads (non-video with a thumbnail_url) ---
        image_ads_result = supabase.table("meta_ads_performance").select(
            "meta_ad_id, thumbnail_url"
        ).eq(
            "brand_id", str(brand_id)
        ).or_(
            "is_video.is.null,is_video.eq.false"
        ).not_.is_(
            "thumbnail_url", "null"
        ).execute()

        image_ads = {}
        for row in (image_ads_result.data or []):
            ad_id = row["meta_ad_id"]
            thumb = row.get("thumbnail_url", "")
            if ad_id not in image_ads and thumb:
                image_ads[ad_id] = thumb

        # --- Check which already have assets (downloaded or marked not_downloadable) ---
        existing_result = supabase.table("meta_ad_assets").select(
            "meta_ad_id, asset_type"
        ).eq(
            "brand_id", str(brand_id)
        ).in_(
            "status", ["downloaded", "not_downloadable"]
        ).execute()

        existing_set = {
            (r["meta_ad_id"], r["asset_type"])
            for r in (existing_result.data or [])
        }

        # --- Download videos ---
        videos_to_dl = {
            ad_id: vid_id
            for ad_id, vid_id in video_ads.items()
            if (ad_id, "video") not in existing_set
        }

        if videos_to_dl and remaining_videos > 0:
            logger.info(f"Found {len(videos_to_dl)} video ads needing download")
            for meta_ad_id, video_id in list(videos_to_dl.items())[:remaining_videos]:
                result = await self.download_and_store_video(meta_ad_id, video_id, brand_id)
                if result:
                    downloaded["videos"] += 1
                await self._rate_limit()

        # --- Download images ---
        # Filter to those not already downloaded
        images_to_dl = [
            ad_id for ad_id in image_ads.keys()
            if (ad_id, "image") not in existing_set
        ]

        if images_to_dl and remaining_images > 0:
            logger.info(f"Found {len(images_to_dl)} image ads needing download")

            # Fetch fresh URLs from API (stored URLs expire)
            # Process in batches to avoid API limits
            batch_size = min(remaining_images, 50)
            ad_ids_batch = images_to_dl[:batch_size]

            fresh_urls = await self.fetch_ad_thumbnails(ad_ids_batch)
            logger.info(f"Fetched {len(fresh_urls)} fresh image URLs from API")

            for meta_ad_id in ad_ids_batch:
                if downloaded["images"] >= remaining_images:
                    break

                # Get fresh URL from API response
                ad_data = fresh_urls.get(meta_ad_id, {})
                fresh_url = ad_data.get("thumbnail_url") if isinstance(ad_data, dict) else None

                if not fresh_url:
                    logger.warning(f"No fresh URL for image ad {meta_ad_id}")
                    continue

                result = await self.download_and_store_image(meta_ad_id, fresh_url, brand_id)
                if result:
                    downloaded["images"] += 1
                await self._rate_limit()

        logger.info(
            f"Asset download complete for brand {brand_id}: "
            f"{downloaded['videos']} videos, {downloaded['images']} images "
            f"({len(videos_to_dl)} videos pending, {len(images_to_dl)} images pending)"
        )
        return downloaded

    async def fetch_ad_destination_urls(
        self,
        ad_ids: List[str],
    ) -> Dict[str, str]:
        """
        Fetch destination URLs for a list of ad IDs.

        Gets the landing page URL that users are directed to when clicking the ad.
        The URL is extracted from the AdCreative's object_story_spec.link_data.link
        or call_to_action.value.link.

        Args:
            ad_ids: List of Meta ad IDs.

        Returns:
            Dict mapping ad_id -> destination_url (original, not canonicalized).
        """
        if not ad_ids:
            return {}

        self._ensure_sdk()
        await self._rate_limit()

        try:
            destinations = await asyncio.to_thread(
                self._fetch_ad_destinations_sync,
                ad_ids
            )
            logger.info(f"Fetched {len(destinations)} ad destination URLs")
            return destinations
        except Exception as e:
            logger.error(f"Failed to fetch ad destination URLs: {e}")
            return {}

    def _fetch_ad_destinations_sync(self, ad_ids: List[str]) -> Dict[str, str]:
        """
        Synchronous call to fetch ad destination URLs.

        Tries multiple locations in the AdCreative:
        1. object_story_spec.link_data.link
        2. object_story_spec.link_data.call_to_action.value.link
        3. object_story_spec.video_data.call_to_action.value.link
        4. asset_feed_spec.link_urls

        Returns:
            Dict mapping ad_id -> destination_url.
        """
        from facebook_business.adobjects.ad import Ad
        from facebook_business.adobjects.adcreative import AdCreative

        destinations: Dict[str, str] = {}

        for ad_id in ad_ids:
            try:
                # Step 1: Get the creative ID from the ad
                ad = Ad(ad_id)
                ad_data = ad.api_get(fields=["id", "creative"])

                creative_data = ad_data.get("creative")
                if not creative_data:
                    logger.debug(f"No creative for ad {ad_id}")
                    continue

                creative_id = creative_data.get("id")
                if not creative_id:
                    continue

                # Step 2: Fetch the creative with link-related fields
                creative = AdCreative(creative_id)
                creative_info = creative.api_get(fields=[
                    "id",
                    "object_story_spec",
                    "asset_feed_spec",
                    "link_url",
                ])

                destination_url = None

                # Try 1: Direct link_url field
                destination_url = creative_info.get("link_url")

                # Try 2: object_story_spec.link_data.link
                if not destination_url:
                    story_spec = creative_info.get("object_story_spec", {})
                    link_data = story_spec.get("link_data", {})
                    destination_url = link_data.get("link")

                    # Try 2b: link_data.call_to_action.value.link
                    if not destination_url:
                        cta = link_data.get("call_to_action", {})
                        cta_value = cta.get("value", {})
                        destination_url = cta_value.get("link")

                # Try 3: object_story_spec.video_data.call_to_action.value.link
                if not destination_url:
                    story_spec = creative_info.get("object_story_spec", {})
                    video_data = story_spec.get("video_data", {})
                    cta = video_data.get("call_to_action", {})
                    cta_value = cta.get("value", {})
                    destination_url = cta_value.get("link")

                # Try 4: asset_feed_spec.link_urls (for dynamic ads)
                if not destination_url:
                    asset_feed = creative_info.get("asset_feed_spec", {})
                    link_urls = asset_feed.get("link_urls", [])
                    if link_urls and len(link_urls) > 0:
                        # Take first URL from dynamic feed
                        first_link = link_urls[0]
                        if isinstance(first_link, dict):
                            destination_url = first_link.get("website_url")
                        elif isinstance(first_link, str):
                            destination_url = first_link

                if destination_url:
                    destinations[ad_id] = destination_url
                    logger.debug(f"Ad {ad_id}: destination={destination_url[:60]}...")
                else:
                    logger.debug(f"Ad {ad_id}: no destination URL found in creative")

            except Exception as e:
                logger.warning(f"Could not fetch destination URL for {ad_id}: {e}")
                continue

        return destinations

    async def sync_ad_destinations_to_db(
        self,
        brand_id: UUID,
        organization_id: UUID,
        ad_ids: Optional[List[str]] = None,
        limit: int = 100,
    ) -> Dict[str, int]:
        """
        Fetch and store ad destination URLs for a brand.

        Fetches destination URLs from Meta API, canonicalizes them,
        and stores in meta_ad_destinations table.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            ad_ids: Optional specific ad IDs to process. If None, finds ads missing destinations.
            limit: Maximum ads to process in this batch.

        Returns:
            Dict with counts: {"fetched": N, "stored": N, "matched": N}.
        """
        from ..core.database import get_supabase_client
        from .url_canonicalizer import canonicalize_url

        supabase = get_supabase_client()
        stats = {"fetched": 0, "stored": 0, "matched": 0}

        # Get ad IDs to process
        if ad_ids is None:
            # Find ads without destination URLs
            existing_result = supabase.table("meta_ad_destinations").select(
                "meta_ad_id"
            ).eq(
                "brand_id", str(brand_id)
            ).execute()

            existing_ad_ids = {r["meta_ad_id"] for r in (existing_result.data or [])}

            # Get all ads for this brand
            ads_result = supabase.table("meta_ads_performance").select(
                "meta_ad_id"
            ).eq(
                "brand_id", str(brand_id)
            ).execute()

            all_ad_ids = list(set(r["meta_ad_id"] for r in (ads_result.data or [])))

            # Filter to ads without destinations
            ad_ids = [aid for aid in all_ad_ids if aid not in existing_ad_ids][:limit]

        if not ad_ids:
            logger.info(f"No ads need destination URL fetching for brand {brand_id}")
            return stats

        logger.info(f"Fetching destination URLs for {len(ad_ids)} ads")

        # Fetch from Meta API
        destinations = await self.fetch_ad_destination_urls(ad_ids)
        stats["fetched"] = len(destinations)

        if not destinations:
            return stats

        # Store in database with canonicalization
        for meta_ad_id, destination_url in destinations.items():
            try:
                canonical = canonicalize_url(destination_url)

                record = {
                    "organization_id": str(organization_id),
                    "brand_id": str(brand_id),
                    "meta_ad_id": meta_ad_id,
                    "destination_url": destination_url,
                    "canonical_url": canonical,
                }

                supabase.table("meta_ad_destinations").upsert(
                    record,
                    on_conflict="brand_id,meta_ad_id,canonical_url"
                ).execute()

                stats["stored"] += 1

            except Exception as e:
                logger.error(f"Failed to store destination for {meta_ad_id}: {e}")

        logger.info(
            f"Synced ad destinations for brand {brand_id}: "
            f"fetched={stats['fetched']}, stored={stats['stored']}"
        )

        return stats

    async def match_destinations_to_landing_pages(
        self,
        brand_id: UUID,
    ) -> Dict[str, Any]:
        """
        Match ad destination URLs to brand landing pages.

        Compares canonical URLs from meta_ad_destinations to brand_landing_pages
        and returns matching results.

        Args:
            brand_id: Brand UUID.

        Returns:
            Dict with:
                - matches: List of {meta_ad_id, destination_url, landing_page_id, landing_page_url}
                - unmatched_count: Number of ads with no matching LP
                - total_destinations: Total destination URLs checked
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Get all destinations for this brand
        destinations_result = supabase.table("meta_ad_destinations").select(
            "meta_ad_id, destination_url, canonical_url"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        destinations = destinations_result.data or []

        if not destinations:
            return {"matches": [], "unmatched_count": 0, "total_destinations": 0}

        # Get all landing pages for this brand
        lps_result = supabase.table("brand_landing_pages").select(
            "id, url, canonical_url"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        landing_pages = lps_result.data or []

        # Build lookup by canonical URL
        lp_by_canonical: Dict[str, Dict] = {}
        for lp in landing_pages:
            canonical = lp.get("canonical_url")
            if canonical:
                lp_by_canonical[canonical] = lp

        # Match destinations to LPs
        matches = []
        unmatched_count = 0

        for dest in destinations:
            canonical = dest.get("canonical_url")
            matched_lp = lp_by_canonical.get(canonical) if canonical else None

            if matched_lp:
                matches.append({
                    "meta_ad_id": dest["meta_ad_id"],
                    "destination_url": dest["destination_url"],
                    "canonical_url": canonical,
                    "landing_page_id": matched_lp["id"],
                    "landing_page_url": matched_lp["url"],
                })
            else:
                unmatched_count += 1

        logger.info(
            f"LP matching for brand {brand_id}: "
            f"{len(matches)} matched, {unmatched_count} unmatched "
            f"of {len(destinations)} total"
        )

        return {
            "matches": matches,
            "unmatched_count": unmatched_count,
            "total_destinations": len(destinations),
        }

    async def auto_match_ads(
        self,
        brand_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Find potential matches between Meta ads and generated ads.

        Scans Meta ad names for 8-char ID patterns and matches against
        generated_ads table.

        Args:
            brand_id: Optional filter by brand

        Returns:
            List of match suggestions with confidence
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Get unlinked Meta ads
        unlinked = await self.get_unlinked_ads(brand_id)

        # Fetch all generated ads and build lookups by ID prefixes
        gen_result = supabase.table("generated_ads").select(
            "id, storage_path, hook_text"
        ).execute()

        # Build lookups: both 6 and 8 char prefixes -> ad record
        gen_ads_by_8char = {}
        gen_ads_by_6char = {}
        for ad in (gen_result.data or []):
            ad_id = str(ad.get("id", "")).replace("-", "")  # Remove hyphens
            if len(ad_id) >= 8:
                gen_ads_by_8char[ad_id[:8].lower()] = ad
            if len(ad_id) >= 6:
                gen_ads_by_6char[ad_id[:6].lower()] = ad

        matches = []
        for meta_ad in unlinked:
            ad_name = meta_ad.get("ad_name")
            extracted_id = self.find_matching_generated_ad_id(ad_name)

            if extracted_id:
                # Look up in our prefix maps (try 8-char first, then 6-char)
                extracted_lower = extracted_id.lower()
                if len(extracted_id) == 8:
                    matched_ad = gen_ads_by_8char.get(extracted_lower)
                else:
                    matched_ad = gen_ads_by_6char.get(extracted_lower)

                if matched_ad:
                    matches.append({
                        "meta_ad": meta_ad,
                        "suggested_match": matched_ad,
                        "confidence": "high",
                        "matched_id": extracted_id,
                    })
                else:
                    # ID found in name but no matching generated ad
                    matches.append({
                        "meta_ad": meta_ad,
                        "suggested_match": None,
                        "confidence": "low",
                        "matched_id": extracted_id,
                    })

        return matches

    async def populate_classification_landing_page_ids(
        self,
        brand_id: UUID,
    ) -> Dict[str, int]:
        """
        Populate landing_page_id in ad_creative_classifications from LP matches.

        For classifications that have a matching landing page (via meta_ad_destinations),
        updates the landing_page_id field.

        Args:
            brand_id: Brand UUID.

        Returns:
            Dict with counts: {"updated": N, "already_set": N, "no_match": N}.
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()
        stats = {"updated": 0, "already_set": 0, "no_match": 0}

        # Get LP matches
        match_result = await self.match_destinations_to_landing_pages(brand_id)
        matches = match_result.get("matches", [])

        if not matches:
            logger.info(f"No LP matches to populate for brand {brand_id}")
            return stats

        # Build lookup: meta_ad_id -> landing_page_id
        lp_by_ad: Dict[str, str] = {}
        for match in matches:
            lp_by_ad[match["meta_ad_id"]] = match["landing_page_id"]

        # Get classifications that need landing_page_id populated
        classifications_result = supabase.table("ad_creative_classifications").select(
            "id, meta_ad_id, landing_page_id"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        for row in (classifications_result.data or []):
            meta_ad_id = row["meta_ad_id"]
            current_lp_id = row.get("landing_page_id")
            matched_lp_id = lp_by_ad.get(meta_ad_id)

            if current_lp_id:
                stats["already_set"] += 1
            elif matched_lp_id:
                # Update the classification with the matched LP ID
                try:
                    supabase.table("ad_creative_classifications").update({
                        "landing_page_id": matched_lp_id,
                    }).eq("id", row["id"]).execute()
                    stats["updated"] += 1
                except Exception as e:
                    logger.error(f"Failed to update classification {row['id']}: {e}")
            else:
                stats["no_match"] += 1

        logger.info(
            f"Populated landing_page_ids for brand {brand_id}: "
            f"updated={stats['updated']}, already_set={stats['already_set']}, "
            f"no_match={stats['no_match']}"
        )

        return stats

    async def get_unmatched_destination_urls(
        self,
        brand_id: UUID,
    ) -> List[Dict[str, str]]:
        """
        Get ad destination URLs that don't match any existing landing pages.

        These URLs are candidates for scraping to add new landing pages.

        Args:
            brand_id: Brand UUID.

        Returns:
            List of dicts with meta_ad_id, destination_url, canonical_url.
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Get all destinations for this brand
        destinations_result = supabase.table("meta_ad_destinations").select(
            "meta_ad_id, destination_url, canonical_url"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        destinations = destinations_result.data or []

        if not destinations:
            return []

        # Get all landing pages for this brand
        lps_result = supabase.table("brand_landing_pages").select(
            "canonical_url"
        ).eq(
            "brand_id", str(brand_id)
        ).execute()

        existing_canonicals = {lp["canonical_url"] for lp in (lps_result.data or []) if lp.get("canonical_url")}

        # Find unmatched destinations
        unmatched = []
        seen_canonicals = set()  # Dedupe by canonical URL

        for dest in destinations:
            canonical = dest.get("canonical_url")
            if canonical and canonical not in existing_canonicals and canonical not in seen_canonicals:
                seen_canonicals.add(canonical)
                unmatched.append({
                    "meta_ad_id": dest["meta_ad_id"],
                    "destination_url": dest["destination_url"],
                    "canonical_url": canonical,
                })

        logger.info(f"Found {len(unmatched)} unmatched destination URLs for brand {brand_id}")
        return unmatched

    async def backfill_unmatched_landing_pages(
        self,
        brand_id: UUID,
        organization_id: UUID,
        scrape: bool = True,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Backfill landing pages for ad destination URLs that don't have matches.

        This method:
        1. Identifies unmatched ad destinations
        2. Creates "pending" records in brand_landing_pages for each new URL
        3. Optionally scrapes the pending pages using BrandResearchService
        4. Re-runs matching to link newly scraped pages to ads

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            scrape: Whether to scrape the pending pages after creating them.
            limit: Maximum pages to scrape in this batch.

        Returns:
            Dict with results: {
                "pending_created": N,
                "pages_scraped": N,
                "pages_failed": N,
                "new_matches": N,
            }
        """
        from ..core.database import get_supabase_client
        from .url_canonicalizer import canonicalize_url

        supabase = get_supabase_client()
        results = {
            "pending_created": 0,
            "pages_scraped": 0,
            "pages_failed": 0,
            "new_matches": 0,
        }

        # Step 1: Get unmatched destination URLs
        unmatched = await self.get_unmatched_destination_urls(brand_id)

        if not unmatched:
            logger.info(f"No unmatched URLs to backfill for brand {brand_id}")
            return results

        logger.info(f"Found {len(unmatched)} unmatched URLs to backfill")

        # Step 2: Create "pending" records in brand_landing_pages
        for item in unmatched[:limit]:
            try:
                # Use the original destination_url for the record
                # but store canonical_url for matching
                # Note: brand_landing_pages doesn't have organization_id or source columns
                record = {
                    "brand_id": str(brand_id),
                    "url": item["destination_url"],
                    "canonical_url": item["canonical_url"],
                    "scrape_status": "pending",
                }

                # Upsert to handle if URL already exists
                supabase.table("brand_landing_pages").upsert(
                    record,
                    on_conflict="brand_id,url"
                ).execute()

                results["pending_created"] += 1

            except Exception as e:
                logger.error(f"Failed to create pending LP for {item['canonical_url']}: {e}")

        logger.info(f"Created {results['pending_created']} pending LP records")

        # Step 3: Optionally scrape the pending pages
        if scrape and results["pending_created"] > 0:
            try:
                from .brand_research_service import BrandResearchService
                research_service = BrandResearchService(supabase)

                scrape_result = await research_service.scrape_landing_pages_for_brand(
                    brand_id=brand_id,
                    limit=limit,
                )

                results["pages_scraped"] = scrape_result.get("pages_scraped", 0)
                results["pages_failed"] = scrape_result.get("pages_failed", 0)

            except Exception as e:
                logger.error(f"Failed to scrape landing pages: {e}")

        # Step 4: Re-run matching to link newly scraped pages
        if results["pages_scraped"] > 0:
            try:
                # Get matches after scraping
                match_result = await self.match_destinations_to_landing_pages(brand_id)
                new_match_count = len(match_result.get("matches", []))

                # Update classifications with new matches
                populate_result = await self.populate_classification_landing_page_ids(brand_id)
                results["new_matches"] = populate_result.get("updated", 0)

                logger.info(
                    f"After backfill: {new_match_count} total matches, "
                    f"{results['new_matches']} classifications updated"
                )

            except Exception as e:
                logger.error(f"Failed to re-match after scraping: {e}")

        logger.info(
            f"Backfill complete for brand {brand_id}: "
            f"pending={results['pending_created']}, scraped={results['pages_scraped']}, "
            f"failed={results['pages_failed']}, new_matches={results['new_matches']}"
        )

        return results
