"""
Base Analytics Service — shared infrastructure for GSC, GA4, and Shopify analytics.

Provides:
- Lazy-load Supabase client pattern
- Integration config loading from brand_integrations
- URL matching against seo_articles
- Batch upsert to seo_article_analytics and seo_article_rankings
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from viraltracker.services.seo_pipeline.utils import normalize_url_path

logger = logging.getLogger(__name__)

# Batch size for upserts
UPSERT_BATCH_SIZE = 100


class BaseAnalyticsService:
    """Shared base for analytics integration services."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # INTEGRATION CONFIG
    # =========================================================================

    def _load_integration_config(
        self,
        brand_id: str,
        organization_id: str,
        platform: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Load integration config from brand_integrations table.

        Args:
            brand_id: Brand UUID
            organization_id: Org UUID
            platform: Platform name (e.g., "gsc", "ga4", "shopify")

        Returns:
            Integration config dict or None
        """
        query = (
            self.supabase.table("brand_integrations")
            .select("*")
            .eq("brand_id", brand_id)
            .eq("platform", platform)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        if not result.data:
            return None

        return result.data[0].get("config", {})

    # =========================================================================
    # URL MATCHING
    # =========================================================================

    def _match_urls_to_articles(
        self,
        brand_id: str,
        url_data_pairs: List[Tuple[str, Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Match URLs from analytics data to seo_articles by normalized path.

        Args:
            brand_id: Brand UUID
            url_data_pairs: List of (url, analytics_data) tuples

        Returns:
            List of dicts with article_id + analytics data for matched URLs
        """
        if not url_data_pairs:
            return []

        # Load all articles for this brand
        article_query = (
            self.supabase.table("seo_articles")
            .select("id, published_url, keyword")
            .eq("brand_id", brand_id)
        )
        articles = article_query.execute().data or []

        # Build path → article_id mapping
        path_to_article = {}
        for article in articles:
            pub_url = article.get("published_url")
            if pub_url:
                path = normalize_url_path(pub_url)
                if path:
                    path_to_article[path] = article["id"]

        # Match analytics URLs
        matched = []
        unmatched_paths = []
        for url, data in url_data_pairs:
            path = normalize_url_path(url)
            article_id = path_to_article.get(path)
            if article_id:
                matched.append({"article_id": article_id, **data})
            else:
                unmatched_paths.append(path)

        if unmatched_paths:
            logger.warning(
                f"URL matching: {len(unmatched_paths)}/{len(url_data_pairs)} URLs unmatched. "
                f"Articles in map: {len(path_to_article)}. "
                f"Sample unmatched: {unmatched_paths[:5]}"
            )

        return matched

    # =========================================================================
    # BATCH UPSERTS
    # =========================================================================

    def _batch_upsert_analytics(
        self,
        rows: List[Dict[str, Any]],
        source: str,
    ) -> int:
        """
        Batch upsert to seo_article_analytics table.

        Each row must have: article_id, organization_id, date.
        The source is set automatically.

        Uses UPSERT on (article_id, date, source, search_type) unique constraint.

        Returns:
            Number of rows upserted
        """
        if not rows:
            return 0

        total = 0
        for i in range(0, len(rows), UPSERT_BATCH_SIZE):
            batch = rows[i:i + UPSERT_BATCH_SIZE]
            for row in batch:
                row["source"] = source
                # Default search_type for non-GSC sources
                if "search_type" not in row:
                    row["search_type"] = "web"

            try:
                self.supabase.table("seo_article_analytics").upsert(
                    batch,
                    on_conflict="article_id,date,source,search_type",
                ).execute()
                total += len(batch)
            except Exception as e:
                logger.error(f"Failed to upsert analytics batch: {e}")

        logger.info(f"Upserted {total} analytics rows (source={source})")
        return total

    def _batch_upsert_rankings(
        self,
        rows: List[Dict[str, Any]],
        source: str,
    ) -> int:
        """
        Batch upsert to seo_article_rankings table.

        Each row must have: article_id, keyword, position, checked_at.
        The source is set automatically.

        Returns:
            Number of rows upserted
        """
        if not rows:
            return 0

        total = 0
        for i in range(0, len(rows), UPSERT_BATCH_SIZE):
            batch = rows[i:i + UPSERT_BATCH_SIZE]
            for row in batch:
                row["source"] = source

            try:
                self.supabase.table("seo_article_rankings").insert(batch).execute()
                total += len(batch)
            except Exception as e:
                logger.error(f"Failed to insert rankings batch: {e}")

        logger.info(f"Inserted {total} ranking rows (source={source})")
        return total
