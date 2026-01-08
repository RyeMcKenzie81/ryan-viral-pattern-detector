"""
Facebook Ads scraper using curious_coder/facebook-ads-library-scraper (Apify actor)

Supports 2 modes:
1. Ad Library Search - Search ads by keywords from Facebook Ad Library
2. Page Ads - Scrape all ads run by specific Facebook pages

All modes save ads to database with full metadata for future analysis.
"""

import os
import json
import time
import logging
from datetime import datetime
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


def _convert_timestamp(timestamp) -> Optional[datetime]:
    """
    Convert Unix timestamp to datetime object

    Args:
        timestamp: Unix timestamp (int or string) or None

    Returns:
        datetime object or None
    """
    if timestamp is None:
        return None

    try:
        # Handle both int and string timestamps
        ts = int(timestamp) if isinstance(timestamp, (int, float, str)) else None
        if ts:
            return datetime.fromtimestamp(ts)
    except (ValueError, TypeError):
        pass

    return None


SearchMode = Literal["ad_library", "page_ads"]


class FacebookAdsScraper:
    """
    Facebook Ads scraper for ViralTracker using curious_coder/facebook-ads-library-scraper (Apify)

    Features:
    - Ad Library search with keyword filtering
    - Page-specific ad scraping
    - Full ad metadata: spend, reach, impressions, creative snapshots
    - Political ad transparency data
    - Date range filtering
    - Active status filtering (all, active, inactive)
    """

    def __init__(
        self,
        apify_token: Optional[str] = None,
        apify_actor_id: Optional[str] = None,
        supabase_client: Optional[Client] = None
    ):
        """
        Initialize Facebook Ads scraper

        Args:
            apify_token: Apify API token (defaults to APIFY_TOKEN env var)
            apify_actor_id: Apify actor ID (defaults to curious_coder/facebook-ads-library-scraper)
            supabase_client: Supabase client (will create one if not provided)
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        self.apify_actor_id = apify_actor_id or "curious_coder/facebook-ads-library-scraper"
        self.supabase = supabase_client or get_supabase_client()

        if not self.apify_token:
            raise ValueError("Missing APIFY_TOKEN environment variable or parameter")

        # Initialize Apify client
        self.apify_client = ApifyClient(self.apify_token)

        # Get Facebook platform ID
        self.platform_id = self._get_platform_id()

    def _get_platform_id(self) -> str:
        """Get Facebook platform UUID from database"""
        result = self.supabase.table('platforms').select('id').eq('slug', 'facebook').single().execute()
        if not result.data:
            raise ValueError("Facebook platform not found in database. Run migration to add platform.")
        return result.data['id']

    def search_ad_library(
        self,
        search_url: str,
        count: Optional[int] = None,
        scrape_details: bool = False,
        period: str = "",
        timeout: int = 600
    ) -> pd.DataFrame:
        """
        Search Facebook Ad Library by URL

        Args:
            search_url: Facebook Ad Library search URL
            count: Max number of ads to scrape (None = all available)
            scrape_details: Enable to scrape EU transparency details
            period: Date range filter (last24h, last7d, last14d, last30d, or "" for all)
            timeout: Apify timeout in seconds

        Returns:
            DataFrame with ads
        """
        logger.info(f"Searching Facebook Ad Library: {search_url}")

        # Start Apify run
        run_id = self._start_ad_library_search(search_url, count, scrape_details, period)

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning("No ads found from Ad Library search")
            return pd.DataFrame()

        # Normalize to DataFrame
        df = self._normalize_ads(items)

        logger.info(f"Scraped {len(df)} ads from Ad Library")

        return df

    def scrape_page_ads(
        self,
        page_url: str,
        count: Optional[int] = None,
        active_status: str = "all",
        country_code: str = "ALL",
        scrape_details: bool = False,
        timeout: int = 600
    ) -> pd.DataFrame:
        """
        Scrape all ads run by a Facebook page

        Args:
            page_url: Facebook page URL
            count: Max number of ads to scrape (None = all available)
            active_status: Filter by status (all, active, inactive)
            country_code: 2-letter ISO country code or "ALL"
            scrape_details: Enable to scrape EU transparency details
            timeout: Apify timeout in seconds

        Returns:
            DataFrame with ads
        """
        logger.info(f"Scraping ads from Facebook page: {page_url}")

        # Start Apify run
        run_id = self._start_page_ads_scrape(
            page_url, count, active_status, country_code, scrape_details
        )

        # Poll for completion
        result = self._poll_apify_run(run_id, timeout)

        # Fetch dataset
        items = self._fetch_dataset(result['datasetId'])

        if not items:
            logger.warning(f"No ads found for page: {page_url}")
            return pd.DataFrame()

        # Normalize to DataFrame
        df = self._normalize_ads(items)

        logger.info(f"Scraped {len(df)} ads from page")

        return df

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_ad_library_search(
        self,
        search_url: str,
        count: Optional[int],
        scrape_details: bool,
        period: str
    ) -> str:
        """
        Start Apify run for Ad Library search

        Args:
            search_url: Facebook Ad Library search URL
            count: Max ads to scrape
            scrape_details: Enable detailed scraping
            period: Date range filter

        Returns:
            Apify run ID
        """
        actor_input = {
            "urls": [{"url": search_url}],
            "scrapeAdDetails": scrape_details,
            "period": period
        }

        if count is not None:
            actor_input["count"] = count

        logger.info(f"Starting Ad Library search (count={count}, details={scrape_details})")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input)

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _start_page_ads_scrape(
        self,
        page_url: str,
        count: Optional[int],
        active_status: str,
        country_code: str,
        scrape_details: bool
    ) -> str:
        """
        Start Apify run for page ads scraping

        Args:
            page_url: Facebook page URL
            count: Max ads to scrape
            active_status: Filter by status
            country_code: Country filter
            scrape_details: Enable detailed scraping

        Returns:
            Apify run ID
        """
        actor_input = {
            "urls": [{"url": page_url}],
            "scrapeAdDetails": scrape_details,
            "scrapePageAds.activeStatus": active_status,
            "scrapePageAds.countryCode": country_code
        }

        if count is not None:
            actor_input["count"] = count

        logger.info(f"Starting page ads scrape (status={active_status}, country={country_code})")

        run = self.apify_client.actor(self.apify_actor_id).call(run_input=actor_input)

        run_id = run["id"]
        logger.info(f"Apify run started: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def _poll_apify_run(self, run_id: str, timeout: int = 600) -> Dict:
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
            List of ad dictionaries
        """
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        headers = {"Authorization": f"Bearer {self.apify_token}"}

        logger.info(f"Fetching dataset {dataset_id}...")

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        items = response.json()
        logger.info(f"Fetched {len(items)} items from dataset")

        return items

    def _normalize_ads(self, items: List[Dict]) -> pd.DataFrame:
        """
        Normalize Facebook ads to DataFrame

        Args:
            items: Raw Apify response

        Returns:
            DataFrame with normalized ads
        """
        normalized_data = []

        logger.info(f"Normalizing {len(items)} ads")

        for idx, ad in enumerate(items):
            try:
                # Debug: Print first ad structure
                if idx == 0:
                    logger.info(f"First ad keys: {list(ad.keys())}")
                    logger.info(f"First ad sample: {json.dumps({k: str(v)[:100] for k, v in list(ad.items())[:5]}, indent=2)}")

                # Extract page info (handle both camelCase and snake_case from Apify)
                page_id = ad.get("pageID") or ad.get("page_id")
                page_name = ad.get("pageName") or ad.get("page_name") or ""

                # Build ad data
                # Note: Apify may use camelCase (adArchiveID) or snake_case (ad_archive_id)
                ad_archive_id = ad.get("adArchiveID") or ad.get("ad_archive_id") or ""
                ad_data = {
                    # Core identifiers
                    "ad_id": str(ad.get("adID") or ad.get("ad_id") or ""),
                    "ad_archive_id": str(ad_archive_id),
                    "page_id": str(page_id) if page_id else None,
                    "page_name": page_name,

                    # Ad metadata
                    "categories": json.dumps(ad.get("categories", [])),
                    "archive_types": json.dumps(ad.get("archive_types", [])),
                    "entity_type": ad.get("entity_type"),
                    "is_active": ad.get("is_active", False),
                    "is_profile_page": ad.get("is_profile_page", False),

                    # Creative & content
                    "snapshot": json.dumps(ad.get("snapshot", {})),
                    "contains_digital_media": ad.get("contains_digital_created_media", False),

                    # Dates
                    "start_date": _convert_timestamp(ad.get("start_date")),
                    "end_date": _convert_timestamp(ad.get("end_date")),

                    # Financial & reach
                    "currency": ad.get("currency"),
                    "spend": ad.get("spend"),
                    "impressions": ad.get("impressions_with_index"),
                    "reach_estimate": ad.get("reach_estimate"),

                    # Political & transparency
                    "political_countries": json.dumps(ad.get("political_countries", [])),
                    "state_media_label": ad.get("state_media_run_label"),
                    "is_aaa_eligible": ad.get("is_aaa_eligible", False),
                    "aaa_info": json.dumps(ad.get("aaa_info", {})),

                    # Platform & delivery
                    "publisher_platform": json.dumps(ad.get("publisher_platform", [])),
                    "gated_type": ad.get("gated_type"),

                    # Collation & grouping
                    "collation_id": ad.get("collation_id"),
                    "collation_count": ad.get("collation_count", 0),

                    # Safety & moderation
                    "has_user_reported": ad.get("has_user_reported", False),
                    "report_count": ad.get("report_count", 0),
                    "hide_data_status": ad.get("hide_data_status"),
                    "hidden_safety_data": json.dumps(ad.get("hidden_safety_data", {})),

                    # Additional data
                    "advertiser": json.dumps(ad.get("advertiser", {})),
                    "insights": json.dumps(ad.get("insights", {})),
                    "menu_items": json.dumps(ad.get("menu_items", [])),

                    # Platform
                    "platform_id": self.platform_id
                }

                # Validate essential fields
                if not ad_data["ad_id"] and not ad_data["ad_archive_id"]:
                    logger.warning(f"Skipping ad with missing ID")
                    continue

                normalized_data.append(ad_data)

            except Exception as e:
                logger.warning(f"Error normalizing ad: {e}")
                continue

        df = pd.DataFrame(normalized_data)

        if len(df) > 0:
            # Deduplicate by ad_id or ad_archive_id
            original_count = len(df)
            # Use ad_archive_id as primary, fall back to ad_id
            df['_dedup_key'] = df['ad_archive_id'].fillna(df['ad_id'])
            df = df.drop_duplicates(subset=['_dedup_key'], keep='first')
            df = df.drop(columns=['_dedup_key'])

            if len(df) < original_count:
                logger.info(f"Removed {original_count - len(df)} duplicate ads")

            logger.info(f"Normalized {len(df)} unique ads from {df['page_name'].nunique()} pages")
        else:
            logger.warning("No ads were successfully normalized")

        return df

    def save_ads_to_db(
        self,
        df: pd.DataFrame,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        import_source: str = "facebook_ads_scrape"
    ) -> List[str]:
        """
        Save ads to database with optional project/brand link

        Args:
            df: DataFrame with ads
            project_id: Optional project UUID to link ads to
            brand_id: Optional brand UUID to link ads to
            import_source: How ads were imported

        Returns:
            List of ad UUIDs
        """
        if len(df) == 0:
            logger.warning("No ads to save")
            return []

        # First, upsert pages (as accounts)
        account_ids = self._upsert_pages(df)

        # Prepare ads data
        ads_data = []
        for _, row in df.iterrows():
            ad_dict = {
                "account_id": account_ids.get(row['page_id']),
                "platform_id": self.platform_id,
                "ad_id": row.get('ad_id'),
                "ad_archive_id": row.get('ad_archive_id'),

                # Metadata
                "categories": row.get('categories'),
                "archive_types": row.get('archive_types'),
                "entity_type": row.get('entity_type'),
                "is_active": bool(row.get('is_active', False)),
                "is_profile_page": bool(row.get('is_profile_page', False)),

                # Creative
                "snapshot": row.get('snapshot'),
                "contains_digital_media": bool(row.get('contains_digital_media', False)),

                # Dates (convert to ISO strings for JSON serialization)
                "start_date": row.get('start_date').isoformat() if pd.notna(row.get('start_date')) else None,
                "end_date": row.get('end_date').isoformat() if pd.notna(row.get('end_date')) else None,

                # Financial
                "currency": row.get('currency'),
                "spend": row.get('spend'),
                "impressions": row.get('impressions'),
                "reach_estimate": row.get('reach_estimate'),

                # Political
                "political_countries": row.get('political_countries'),
                "state_media_label": row.get('state_media_label'),
                "is_aaa_eligible": bool(row.get('is_aaa_eligible', False)),
                "aaa_info": row.get('aaa_info'),

                # Platform
                "publisher_platform": row.get('publisher_platform'),
                "gated_type": row.get('gated_type'),

                # Collation
                "collation_id": row.get('collation_id'),
                "collation_count": int(row.get('collation_count', 0)) if pd.notna(row.get('collation_count')) else 0,

                # Safety
                "has_user_reported": bool(row.get('has_user_reported', False)),
                "report_count": int(row.get('report_count', 0)) if pd.notna(row.get('report_count')) else 0,
                "hide_data_status": row.get('hide_data_status'),
                "hidden_safety_data": row.get('hidden_safety_data'),

                # Additional
                "advertiser": row.get('advertiser'),
                "insights": row.get('insights'),
                "menu_items": row.get('menu_items'),

                "import_source": import_source
            }

            ads_data.append(ad_dict)

        # Upsert ads
        ad_ids = []
        chunk_size = 1000
        chunks = [ads_data[i:i + chunk_size] for i in range(0, len(ads_data), chunk_size)]

        for chunk in tqdm(chunks, desc="Saving ads to database"):
            try:
                result = self.supabase.table("facebook_ads").upsert(
                    chunk,
                    on_conflict="ad_archive_id"
                ).execute()

                for ad in result.data:
                    ad_ids.append(ad['id'])

            except Exception as e:
                logger.error(f"Error upserting ads chunk: {e}")
                continue

        logger.info(f"Saved {len(ad_ids)} ads to database")

        # Link to project if provided
        if project_id and ad_ids:
            self._link_ads_to_project(ad_ids, project_id, import_source)

        # Link to brand if provided
        if brand_id and ad_ids:
            self._link_ads_to_brand(ad_ids, brand_id, import_source)

        return ad_ids

    def _upsert_pages(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Upsert Facebook pages to accounts table

        Args:
            df: DataFrame with page_id, page_name

        Returns:
            Dict mapping page_id to account_id
        """
        # Get unique pages
        pages_df = df[['page_id', 'page_name']].drop_duplicates(subset=['page_id']).dropna(subset=['page_id'])

        account_ids = {}

        for _, row in tqdm(pages_df.iterrows(), total=len(pages_df), desc="Upserting pages"):
            try:
                page_id = str(row['page_id'])
                page_name = row['page_name']

                # Check if account exists
                existing = self.supabase.table('accounts')\
                    .select('id')\
                    .eq('platform_id', self.platform_id)\
                    .eq('platform_username', page_id)\
                    .execute()

                if existing.data and len(existing.data) > 0:
                    # Account exists
                    account_id = existing.data[0]['id']

                    # Update metadata
                    update_data = {
                        "display_name": page_name,
                        "metadata_updated_at": datetime.now().isoformat()
                    }

                    self.supabase.table('accounts').update(update_data).eq('id', account_id).execute()

                else:
                    # Create new account
                    account_data = {
                        "handle": page_id,  # Legacy field
                        "platform_id": self.platform_id,
                        "platform_username": page_id,
                        "display_name": page_name,
                        "metadata_updated_at": datetime.now().isoformat()
                    }

                    result = self.supabase.table('accounts').insert(account_data).execute()
                    account_id = result.data[0]['id']

                account_ids[page_id] = account_id

            except Exception as e:
                logger.error(f"Error upserting page {page_id}: {e}")
                continue

        logger.info(f"Upserted {len(account_ids)} pages")

        return account_ids

    def _link_ads_to_project(
        self,
        ad_ids: List[str],
        project_id: str,
        import_method: str = "facebook_ads_scrape"
    ):
        """Link ads to project via project_facebook_ads table"""
        links_data = []

        for ad_id in ad_ids:
            links_data.append({
                'project_id': project_id,
                'ad_id': ad_id,
                'import_method': import_method,
                'notes': f"Facebook ads scrape on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking ads to project"):
            try:
                result = self.supabase.table("project_facebook_ads").upsert(
                    chunk,
                    on_conflict="project_id,ad_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking ads chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} ads to project")

    def _link_ads_to_brand(
        self,
        ad_ids: List[str],
        brand_id: str,
        import_method: str = "facebook_ads_scrape"
    ):
        """Link ads to brand via brand_facebook_ads table"""
        links_data = []

        for ad_id in ad_ids:
            links_data.append({
                'brand_id': brand_id,
                'ad_id': ad_id,
                'import_method': import_method,
                'notes': f"Facebook ads scrape on {datetime.now().strftime('%Y-%m-%d')}"
            })

        # Process in chunks
        chunk_size = 1000
        chunks = [links_data[i:i + chunk_size] for i in range(0, len(links_data), chunk_size)]

        linked_count = 0

        for chunk in tqdm(chunks, desc="Linking ads to brand"):
            try:
                result = self.supabase.table("brand_facebook_ads").upsert(
                    chunk,
                    on_conflict="brand_id,ad_id"
                ).execute()
                linked_count += len(result.data)

            except Exception as e:
                logger.error(f"Error linking ads chunk: {e}")
                continue

        logger.info(f"Linked {linked_count} ads to brand")
