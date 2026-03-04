"""
Google Search Console Service — fetch search performance and sync to DB.

OAuth2 flow:
- client_id/client_secret from env vars (app-level)
- Per-brand refresh_token, access_token, site_url in brand_integrations.config

Token refresh follows the same pattern as CMSPublisherService (auto-refresh on expiry).
"""

import json
import logging
import os
import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from viraltracker.services.seo_pipeline.services.base_analytics_service import BaseAnalyticsService

logger = logging.getLogger(__name__)


class GSCService(BaseAnalyticsService):
    """Google Search Console integration for SEO analytics."""

    PLATFORM = "gsc"

    # =========================================================================
    # OAUTH2 HELPERS
    # =========================================================================

    @staticmethod
    def get_authorization_url(redirect_uri: str, state: str) -> str:
        """
        Build Google OAuth2 authorization URL.

        Args:
            redirect_uri: OAuth callback URL
            state: JSON-encoded state (brand_id, org_id, nonce) base64'd

        Returns:
            Authorization URL to redirect user to
        """
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        if not client_id:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID env var not set")

        from urllib.parse import urlencode
        params = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/webmasters.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    @staticmethod
    def encode_oauth_state(brand_id: str, org_id: str, nonce: str) -> str:
        """Encode brand_id + org_id + nonce into OAuth state param."""
        payload = json.dumps({"brand_id": brand_id, "org_id": org_id, "nonce": nonce})
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def decode_oauth_state(state: str) -> Dict[str, str]:
        """Decode OAuth state param back to brand_id, org_id, nonce."""
        payload = base64.urlsafe_b64decode(state.encode()).decode()
        return json.loads(payload)

    @staticmethod
    def exchange_code_for_tokens(code: str, redirect_uri: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Returns:
            Dict with access_token, refresh_token, expires_in, token_type
        """
        import httpx

        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID/SECRET env vars not set")

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.status_code} — {response.text[:200]}")

        return response.json()

    def save_integration(
        self,
        brand_id: str,
        organization_id: str,
        site_url: str,
        tokens: Dict[str, Any],
    ) -> None:
        """Save GSC integration config to brand_integrations."""
        config = {
            "site_url": site_url,
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "token_expiry": (
                datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
            ).isoformat(),
        }

        # Upsert brand_integrations row
        self.supabase.table("brand_integrations").upsert(
            {
                "brand_id": brand_id,
                "organization_id": organization_id,
                "platform": self.PLATFORM,
                "config": config,
                "status": "active",
            },
            on_conflict="brand_id,platform",
        ).execute()

        logger.info(f"Saved GSC integration for brand {brand_id}")

    # =========================================================================
    # TOKEN REFRESH
    # =========================================================================

    def _get_credentials(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get valid credentials, refreshing if expired.

        Returns updated config with fresh access_token, or None if revoked.
        """
        import httpx

        token_expiry = config.get("token_expiry", "")
        if token_expiry:
            try:
                expiry = datetime.fromisoformat(token_expiry)
                if expiry > datetime.now(timezone.utc):
                    return config  # Token still valid
            except (ValueError, TypeError):
                pass

        # Token expired — refresh
        refresh_token = config.get("refresh_token")
        if not refresh_token:
            logger.warning("No refresh_token available for GSC")
            return None

        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.warning("GOOGLE_OAUTH_CLIENT_ID/SECRET not set, can't refresh")
            return None

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )

            if response.status_code != 200:
                logger.error(f"GSC token refresh failed: {response.status_code}")
                return None

            data = response.json()
            config["access_token"] = data["access_token"]
            config["token_expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
            ).isoformat()

            logger.info("GSC access token refreshed")
            return config

        except Exception as e:
            logger.error(f"GSC token refresh error: {e}")
            return None

    # =========================================================================
    # DATA FETCHING
    # =========================================================================

    def fetch_search_performance(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> List[Dict[str, Any]]:
        """
        Fetch search performance from Google Search Console API.

        Queries with dimensions [page, query, date] for the specified date range.

        Returns:
            List of row dicts with keys, clicks, impressions, ctr, position
        """
        import httpx

        config = self._load_integration_config(brand_id, organization_id, self.PLATFORM)
        if not config:
            raise ValueError("GSC integration not configured")

        config = self._get_credentials(config)
        if not config:
            raise ValueError("GSC credentials expired or revoked")

        site_url = config.get("site_url", "")
        access_token = config["access_token"]

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days_back)

        request_body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": ["page", "query", "date"],
            "rowLimit": 25000,
        }

        from urllib.parse import quote
        encoded_site_url = quote(site_url, safe="")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site_url}/searchAnalytics/query",
                headers={"Authorization": f"Bearer {access_token}"},
                json=request_body,
            )

        if response.status_code != 200:
            raise Exception(f"GSC API error: {response.status_code} — {response.text[:200]}")

        data = response.json()
        return data.get("rows", [])

    def sync_to_db(
        self,
        brand_id: str,
        organization_id: str,
        days_back: int = 28,
    ) -> Dict[str, int]:
        """
        Fetch GSC data and sync to seo_article_analytics + seo_article_rankings.

        Returns:
            Dict with analytics_rows and ranking_rows counts
        """
        rows = self.fetch_search_performance(brand_id, organization_id, days_back)

        if not rows:
            return {"analytics_rows": 0, "ranking_rows": 0}

        # Group by page URL + date for analytics
        page_date_data = {}
        ranking_rows = []

        for row in rows:
            keys = row.get("keys", [])
            if len(keys) < 3:
                continue

            page_url, query, date_str = keys[0], keys[1], keys[2]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0.0)
            position = row.get("position", 0.0)

            # Aggregate for analytics (per page+date)
            key = (page_url, date_str)
            if key not in page_date_data:
                page_date_data[key] = {
                    "clicks": 0,
                    "impressions": 0,
                    "ctr_sum": 0.0,
                    "ctr_count": 0,
                    "position_sum": 0.0,
                    "position_count": 0,
                }
            page_date_data[key]["clicks"] += clicks
            page_date_data[key]["impressions"] += impressions
            page_date_data[key]["ctr_sum"] += ctr
            page_date_data[key]["ctr_count"] += 1
            page_date_data[key]["position_sum"] += position
            page_date_data[key]["position_count"] += 1

            # Individual ranking rows (per query)
            ranking_rows.append((page_url, {
                "keyword": query,
                "position": round(position),
                "checked_at": f"{date_str}T00:00:00Z",
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr,
            }))

        # Build analytics URL pairs
        analytics_pairs = []
        for (page_url, date_str), agg in page_date_data.items():
            avg_ctr = agg["ctr_sum"] / agg["ctr_count"] if agg["ctr_count"] else 0.0
            avg_position = agg["position_sum"] / agg["position_count"] if agg["position_count"] else None
            analytics_pairs.append((page_url, {
                "organization_id": organization_id,
                "date": date_str,
                "impressions": agg["impressions"],
                "clicks": agg["clicks"],
                "ctr": round(avg_ctr, 4),
                "average_position": round(avg_position, 1) if avg_position is not None else None,
            }))

        # Match URLs to articles
        analytics_matched = self._match_urls_to_articles(brand_id, analytics_pairs)
        ranking_matched = self._match_urls_to_articles(brand_id, ranking_rows)

        # Upsert
        analytics_count = self._batch_upsert_analytics(analytics_matched, self.PLATFORM)
        ranking_count = self._batch_upsert_rankings(ranking_matched, self.PLATFORM)

        return {"analytics_rows": analytics_count, "ranking_rows": ranking_count}
