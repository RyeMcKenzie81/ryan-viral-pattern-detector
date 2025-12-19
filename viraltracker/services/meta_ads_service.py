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

        Looks for an 8-character hex pattern at the start of the name,
        which should match our filename format: d4e5f6a7-WP-C3-SQ.png

        Args:
            ad_name: The Meta ad name

        Returns:
            8-char ID if found, None otherwise
        """
        if not ad_name:
            return None

        # Look for 8 hex chars at start or after common delimiters
        patterns = [
            r"^([a-f0-9]{8})",  # Start of string
            r"[\s\-_]([a-f0-9]{8})[\s\-_]",  # Between delimiters
            r"[\s\-_]([a-f0-9]{8})$",  # End of string
        ]

        for pattern in patterns:
            match = re.search(pattern, ad_name.lower())
            if match:
                return match.group(1)

        return None

    async def sync_performance_to_db(
        self,
        insights: List[Dict[str, Any]],
        brand_id: Optional[UUID] = None
    ) -> int:
        """
        Save performance insights to database.

        Args:
            insights: Normalized insight dicts from get_ad_insights()
            brand_id: Optional brand to associate with

        Returns:
            Number of records saved
        """
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()
        saved_count = 0

        for insight in insights:
            try:
                # Prepare record - use account ID from insight (set during get_ad_insights)
                record = {
                    "meta_ad_account_id": insight.get("meta_ad_account_id", self._default_ad_account_id),
                    "meta_ad_id": insight["meta_ad_id"],
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
                    "brand_id": str(brand_id) if brand_id else None,
                }

                # Upsert (on conflict with meta_ad_id + date)
                supabase.table("meta_ads_performance").upsert(
                    record,
                    on_conflict="meta_ad_id,date"
                ).execute()

                saved_count += 1

            except Exception as e:
                logger.error(f"Failed to save insight for {insight.get('meta_ad_id')}: {e}")

        logger.info(f"Saved {saved_count}/{len(insights)} performance records")
        return saved_count

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

        # Fetch all generated ads and build lookup by first 8 chars of ID
        gen_result = supabase.table("generated_ads").select(
            "id, storage_path, hook_text"
        ).execute()

        # Build lookup: first 8 chars of UUID -> ad record
        gen_ads_by_prefix = {}
        for ad in (gen_result.data or []):
            ad_id = str(ad.get("id", ""))
            if len(ad_id) >= 8:
                prefix = ad_id[:8].lower()
                gen_ads_by_prefix[prefix] = ad

        matches = []
        for meta_ad in unlinked:
            ad_name = meta_ad.get("ad_name")
            extracted_id = self.find_matching_generated_ad_id(ad_name)

            if extracted_id:
                # Look up in our prefix map
                matched_ad = gen_ads_by_prefix.get(extracted_id.lower())

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
