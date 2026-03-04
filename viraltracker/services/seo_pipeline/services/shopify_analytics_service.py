"""
Shopify Conversion Attribution Service — track blog-driven purchases.

Uses customerJourneySummary on Orders (GraphQL Admin API) to find
which blog articles led to purchases. Works on all Shopify plans
(unlike ShopifyQL which is effectively Plus-only for analytics).

Reuses existing Shopify config from brand_integrations (platform='shopify').
Same token auto-refresh pattern as CMSPublisherService.

Provides: conversion count and revenue per blog article.
Does NOT provide: raw sessions/pageviews (use GA4 for that).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from viraltracker.services.seo_pipeline.services.base_analytics_service import BaseAnalyticsService

logger = logging.getLogger(__name__)

# GraphQL query for orders with customer journey summary
ORDERS_QUERY = """
query OrdersWithJourney($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query) {
    edges {
      cursor
      node {
        id
        name
        createdAt
        totalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        customerJourneySummary {
          firstVisit {
            landingPage
          }
          lastVisit {
            landingPage
          }
        }
      }
    }
    pageInfo {
      hasNextPage
    }
  }
}
"""


class ShopifyAnalyticsService(BaseAnalyticsService):
    """Shopify conversion attribution via customerJourneySummary."""

    PLATFORM = "shopify"

    def _get_shopify_config(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Load Shopify config from brand_integrations (reuses CMS config)."""
        return self._load_integration_config(brand_id, organization_id, self.PLATFORM)

    def _graphql_request(
        self,
        config: Dict[str, Any],
        query: str,
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a Shopify GraphQL Admin API request."""
        store_domain = config.get("store_domain")
        access_token = config.get("access_token")
        api_version = config.get("api_version", "2024-10")

        if not store_domain or not access_token:
            raise ValueError("Shopify config missing store_domain or access_token")

        url = f"https://{store_domain}/admin/api/{api_version}/graphql.json"

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                headers={
                    "X-Shopify-Access-Token": access_token,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables},
            )

        if response.status_code != 200:
            raise Exception(f"Shopify GraphQL error: {response.status_code} — {response.text[:200]}")

        data = response.json()
        if "errors" in data:
            raise Exception(f"Shopify GraphQL errors: {data['errors']}")

        return data.get("data", {})

    def fetch_blog_conversions(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> List[Dict[str, Any]]:
        """
        Fetch orders with blog article landing pages from Shopify.

        Inspects customerJourneySummary.firstVisit.landingPage and
        lastVisit.landingPage, filtering for blog article paths.

        Returns:
            List of dicts: [{page_path, date, conversions, revenue}]
        """
        config = self._get_shopify_config(brand_id, organization_id)
        if not config:
            raise ValueError("Shopify integration not configured")

        since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

        # Aggregate conversions per blog page path per date
        page_date_stats: Dict[tuple, Dict[str, Any]] = {}
        cursor = None
        page_count = 0
        max_pages = 10  # Safety limit

        while page_count < max_pages:
            variables = {
                "first": 50,
                "after": cursor,
                "query": f"created_at:>={since_date}",
            }

            data = self._graphql_request(config, ORDERS_QUERY, variables)
            orders = data.get("orders", {})
            edges = orders.get("edges", [])

            if not edges:
                break

            for edge in edges:
                order = edge.get("node", {})
                journey = order.get("customerJourneySummary") or {}
                created_at = order.get("createdAt", "")
                date_str = created_at[:10] if created_at else ""

                revenue_raw = (
                    order.get("totalPriceSet", {})
                    .get("shopMoney", {})
                    .get("amount", "0")
                )
                revenue = float(revenue_raw)

                # Check both first and last visit landing pages
                landing_pages = set()
                for visit_key in ("firstVisit", "lastVisit"):
                    visit = journey.get(visit_key) or {}
                    lp = visit.get("landingPage") or ""
                    if lp and "/blogs/" in lp:
                        landing_pages.add(lp)

                for lp in landing_pages:
                    key = (lp, date_str)
                    if key not in page_date_stats:
                        page_date_stats[key] = {"conversions": 0, "revenue": 0.0}
                    page_date_stats[key]["conversions"] += 1
                    page_date_stats[key]["revenue"] += revenue

            page_info = orders.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break

            cursor = edges[-1].get("cursor")
            page_count += 1

        # Convert to list
        results = []
        for (page_path, date_str), stats in page_date_stats.items():
            results.append({
                "page_path": page_path,
                "date": date_str,
                "conversions": stats["conversions"],
                "revenue": round(stats["revenue"], 2),
            })

        return results

    def sync_to_db(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> Dict[str, int]:
        """
        Fetch Shopify conversion data and sync to seo_article_analytics.

        Returns:
            Dict with analytics_rows count
        """
        try:
            rows = self.fetch_blog_conversions(brand_id, organization_id, days_back)
        except Exception as e:
            logger.warning(f"Shopify analytics unavailable: {e}")
            return {"analytics_rows": 0}

        if not rows:
            return {"analytics_rows": 0}

        # Build URL pairs for matching
        url_pairs = []
        for row in rows:
            url_pairs.append((row["page_path"], {
                "organization_id": organization_id,
                "date": row["date"],
                "conversions": row["conversions"],
                "revenue": row["revenue"],
            }))

        matched = self._match_urls_to_articles(brand_id, url_pairs)
        analytics_count = self._batch_upsert_analytics(matched, self.PLATFORM)

        return {"analytics_rows": analytics_count}
