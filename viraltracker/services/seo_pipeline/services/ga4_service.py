"""
Google Analytics 4 Service — fetch page analytics via GA4 Data API.

Auth: Service account (no OAuth callback needed).
User adds SA email as viewer on GA4 property.
SA JSON stored in brand_integrations config.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from viraltracker.services.seo_pipeline.services.base_analytics_service import BaseAnalyticsService

logger = logging.getLogger(__name__)


class GA4Service(BaseAnalyticsService):
    """Google Analytics 4 integration for page-level traffic analytics."""

    PLATFORM = "ga4"

    def _get_ga4_client(self, config: Dict[str, Any]):
        """
        Create GA4 Data API client from service account credentials.

        Args:
            config: brand_integrations config with sa_credentials and property_id

        Returns:
            BetaAnalyticsDataClient instance
        """
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account

        sa_creds = config.get("sa_credentials")
        if not sa_creds:
            raise ValueError("GA4 config missing sa_credentials")

        if isinstance(sa_creds, str):
            sa_creds = json.loads(sa_creds)

        credentials = service_account.Credentials.from_service_account_info(
            sa_creds,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )

        return BetaAnalyticsDataClient(credentials=credentials)

    def fetch_page_analytics(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> List[Dict[str, Any]]:
        """
        Fetch page-level analytics from GA4 Data API.

        Queries: sessions, screenPageViews, averageSessionDuration, bounceRate
        Dimension: pagePath, date

        Returns:
            List of row dicts with page_path, date, sessions, pageviews, etc.
        """
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )

        config = self._load_integration_config(brand_id, organization_id, self.PLATFORM)
        if not config:
            raise ValueError("GA4 integration not configured")

        property_id = config.get("property_id")
        if not property_id:
            raise ValueError("GA4 config missing property_id")

        client = self._get_ga4_client(config)

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days_back)

        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )],
            dimensions=[
                Dimension(name="pagePath"),
                Dimension(name="date"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="screenPageViews"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
            ],
            limit=10000,
        )

        response = client.run_report(request)

        rows = []
        for row in response.rows:
            page_path = row.dimension_values[0].value
            date_str = row.dimension_values[1].value  # YYYYMMDD format
            # Convert GA4 date format to ISO
            date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            rows.append({
                "page_path": page_path,
                "date": date_iso,
                "sessions": int(row.metric_values[0].value or 0),
                "pageviews": int(row.metric_values[1].value or 0),
                "avg_time_on_page": float(row.metric_values[2].value or 0),
                "bounce_rate": float(row.metric_values[3].value or 0),
            })

        return rows

    def sync_to_db(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> Dict[str, int]:
        """
        Fetch GA4 data and sync to seo_article_analytics.

        Returns:
            Dict with analytics_rows count
        """
        rows = self.fetch_page_analytics(brand_id, organization_id, days_back)

        if not rows:
            return {"analytics_rows": 0}

        # Build URL pairs for matching (GA4 gives page_path, not full URL)
        url_pairs = []
        for row in rows:
            # GA4 pagePath is already a path (no domain)
            page_path = row["page_path"]
            url_pairs.append((page_path, {
                "organization_id": organization_id,
                "date": row["date"],
                "sessions": row["sessions"],
                "pageviews": row["pageviews"],
                "avg_time_on_page": row["avg_time_on_page"],
                "bounce_rate": row["bounce_rate"],
            }))

        matched = self._match_urls_to_articles(brand_id, url_pairs)
        analytics_count = self._batch_upsert_analytics(matched, self.PLATFORM)

        return {"analytics_rows": analytics_count}
