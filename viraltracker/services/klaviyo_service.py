"""
Klaviyo Service — OAuth token management, campaigns, flows, and metrics.

Uses httpx for HTTP calls (consistent with GoogleDriveService pattern).
Tokens stored in brand_integrations with platform='klaviyo'.
All methods require brand_id + org_id for multi-tenancy.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from viraltracker.services.klaviyo_oauth_utils import refresh_klaviyo_token

logger = logging.getLogger(__name__)


class KlaviyoService:
    """Klaviyo integration — OAuth, campaigns, flows, metrics."""

    PLATFORM = "klaviyo"
    BASE_URL = "https://a.klaviyo.com"
    API_REVISION = "2025-07-15"

    # Tiered rate limits (requests per second)
    _TIER_LIMITS = {
        "XS": 1,
        "S": 3,
        "M": 10,
        "L": 75,
        "XL": 350,
    }

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()
        self._refresh_locks: Dict[Tuple[str, str], threading.Lock] = defaultdict(threading.Lock)
        self._tier_last_call: Dict[str, float] = defaultdict(float)
        self._daily_flow_creates: Dict[str, int] = defaultdict(int)
        self._daily_flow_date: Optional[str] = None

    # =========================================================================
    # MULTI-TENANCY
    # =========================================================================

    def _resolve_org_id(self, org_id: str, brand_id: str) -> str:
        """Resolve 'all' to a real UUID before any DB insert."""
        if org_id != "all":
            return org_id
        result = (
            self.supabase.table("brands")
            .select("organization_id")
            .eq("id", brand_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["organization_id"]
        raise ValueError(f"Cannot resolve org_id for brand {brand_id}")

    # =========================================================================
    # TOKEN MANAGEMENT
    # =========================================================================

    def save_integration(
        self,
        brand_id: str,
        org_id: str,
        tokens: Dict[str, Any],
        account_id: str = "",
        account_name: str = "",
    ) -> None:
        """Save Klaviyo integration to brand_integrations."""
        real_org_id = self._resolve_org_id(org_id, brand_id)
        config = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "token_expiry": (
                datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
            ).isoformat(),
            "last_token_refresh_at": datetime.now(timezone.utc).isoformat(),
            "account_id": account_id,
            "account_name": account_name,
        }

        self.supabase.table("brand_integrations").upsert(
            {
                "brand_id": brand_id,
                "organization_id": real_org_id,
                "platform": self.PLATFORM,
                "config": config,
            },
            on_conflict="brand_id,platform",
        ).execute()

        logger.info(f"Saved Klaviyo integration for brand {brand_id}")

    def save_pending_oauth(
        self,
        brand_id: str,
        org_id: str,
        nonce: str,
        code_verifier: str,
    ) -> None:
        """Store PKCE code_verifier in a temporary DB row for cross-tab safety."""
        real_org_id = self._resolve_org_id(org_id, brand_id)
        config = {
            "nonce": nonce,
            "code_verifier": code_verifier,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.supabase.table("brand_integrations").upsert(
            {
                "brand_id": brand_id,
                "organization_id": real_org_id,
                "platform": "klaviyo_pending",
                "config": config,
            },
            on_conflict="brand_id,platform",
        ).execute()

    def get_pending_oauth(self, brand_id: str, org_id: str, nonce: str) -> Optional[str]:
        """Retrieve code_verifier for a pending OAuth flow, validating nonce."""
        query = (
            self.supabase.table("brand_integrations")
            .select("config, organization_id")
            .eq("brand_id", brand_id)
            .eq("platform", "klaviyo_pending")
            .limit(1)
        )
        result = query.execute()
        if not result.data:
            return None
        row = result.data[0]
        config = row.get("config", {})
        if config.get("nonce") != nonce:
            logger.warning(f"Nonce mismatch for brand {brand_id}")
            return None
        # Verify org_id matches (prevent cross-org token confusion)
        if org_id != "all" and row.get("organization_id") and row["organization_id"] != org_id:
            logger.warning(f"Org mismatch in pending OAuth for brand {brand_id}")
            return None
        return config.get("code_verifier")

    def delete_pending_oauth(self, brand_id: str, org_id: str = "") -> None:
        """Remove the temporary pending row after exchange or failure."""
        query = self.supabase.table("brand_integrations").delete().eq(
            "brand_id", brand_id
        ).eq("platform", "klaviyo_pending")
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        query.execute()

    def _get_credentials(self, brand_id: str, org_id: str) -> Tuple[str, Dict]:
        """Load and refresh Klaviyo credentials with per-brand locking.

        Returns:
            (access_token, config) or raises on failure.
        """
        lock_key = (brand_id, self.PLATFORM)
        with self._refresh_locks[lock_key]:
            query = (
                self.supabase.table("brand_integrations")
                .select("config")
                .eq("brand_id", brand_id)
                .eq("platform", self.PLATFORM)
            )
            if org_id != "all":
                query = query.eq("organization_id", org_id)
            result = query.limit(1).execute()

            if not result.data:
                raise ValueError("Klaviyo not connected for this brand")

            config = result.data[0].get("config", {})
            if not config.get("access_token"):
                raise ValueError("Klaviyo integration has no access token")

            refreshed = refresh_klaviyo_token(config)
            if refreshed is None:
                raise ValueError("Klaviyo token refresh failed — please reconnect")

            if refreshed.get("access_token") != config.get("access_token"):
                self.supabase.table("brand_integrations").update(
                    {"config": refreshed}
                ).eq("brand_id", brand_id).eq("platform", self.PLATFORM).execute()

            return refreshed["access_token"], refreshed

    def is_connected(self, brand_id: str, org_id: str) -> bool:
        """Check if Klaviyo is connected for this brand."""
        try:
            query = (
                self.supabase.table("brand_integrations")
                .select("id")
                .eq("brand_id", brand_id)
                .eq("platform", self.PLATFORM)
            )
            if org_id != "all":
                query = query.eq("organization_id", org_id)
            result = query.limit(1).execute()
            return bool(result.data)
        except Exception:
            return False

    def disconnect(self, brand_id: str, org_id: str, force: bool = False) -> Dict[str, Any]:
        """Remove Klaviyo integration. Returns warning if active campaigns/flows exist."""
        if not force:
            try:
                campaigns = self.get_campaigns(brand_id, org_id, filter_status="sending")
                flows = self.get_flows(brand_id, org_id)
                live_flows = [f for f in flows if f.get("status") == "live"]
                if campaigns or live_flows:
                    return {
                        "warning": True,
                        "active_campaigns": len(campaigns),
                        "live_flows": len(live_flows),
                        "message": (
                            f"Found {len(campaigns)} active campaign(s) and "
                            f"{len(live_flows)} live flow(s). Pass force=True to proceed."
                        ),
                    }
            except Exception:
                pass  # Proceed with disconnect if we can't check

        query = self.supabase.table("brand_integrations").delete().eq(
            "brand_id", brand_id
        ).eq("platform", self.PLATFORM)
        if org_id != "all":
            query = query.eq("organization_id", org_id)
        query.execute()
        logger.info(f"Disconnected Klaviyo for brand {brand_id}")
        return {"warning": False, "disconnected": True}

    # =========================================================================
    # HTTP INFRASTRUCTURE
    # =========================================================================

    def _rate_limit(self, tier: str = "M") -> None:
        """Enforce tiered rate limiting between API calls."""
        rps = self._TIER_LIMITS.get(tier, 10)
        min_delay = 1.0 / rps
        now = time.time()
        elapsed = now - self._tier_last_call[tier]
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self._tier_last_call[tier] = time.time()

    def _make_request(
        self,
        method: str,
        path: str,
        brand_id: str,
        org_id: str,
        tier: str = "M",
        max_retries: int = 3,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make an authenticated Klaviyo API request with rate limiting and retry.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE).
            path: API path (e.g., /api/campaigns).
            brand_id: Brand UUID.
            org_id: Organization UUID or "all".
            tier: Rate limit tier (XS, S, M, L, XL).
            max_retries: Max retry attempts on 429/5xx.
            **kwargs: Passed to httpx (json, params, data, etc.).

        Returns:
            Parsed response dict.
        """
        access_token, _ = self._get_credentials(brand_id, org_id)

        headers = {
            "Authorization": f"Klaviyo-API-Key {access_token}",
            "revision": self.API_REVISION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = f"{self.BASE_URL}{path}"
        last_error = None

        for attempt in range(max_retries):
            self._rate_limit(tier)
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.request(method, url, headers=headers, **kwargs)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 15))
                    wait = retry_after * (2 ** attempt)
                    logger.warning(f"Klaviyo 429 on {path}, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = 15 * (2 ** attempt)
                    logger.warning(f"Klaviyo {response.status_code} on {path}, retrying in {wait}s")
                    time.sleep(wait)
                    continue

                if response.status_code >= 400:
                    raise Exception(
                        f"Klaviyo API error {response.status_code} on {method} {path}: "
                        f"{response.text[:500]}"
                    )

                if response.status_code == 204:
                    return {}

                return self._parse_jsonapi_response(response.json())

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Timeout on {path}, attempt {attempt + 1}")
                continue

        raise Exception(f"Klaviyo request failed after {max_retries} retries: {last_error}")

    def _parse_jsonapi_response(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a JSON:API response, flattening attributes and handling sideloads.

        Handles single resource, resource collections, and included sideloads.

        Returns:
            Normalized dict with 'data' (list or dict), 'included', 'links'.
        """
        try:
            raw_data = body.get("data")
            included = body.get("included", [])
            links = body.get("links", {})

            def flatten(resource: Dict) -> Dict:
                flat = {"id": resource.get("id"), "type": resource.get("type")}
                flat.update(resource.get("attributes", {}))
                rels = resource.get("relationships", {})
                if rels:
                    flat["relationships"] = rels
                return flat

            if isinstance(raw_data, list):
                data = [flatten(r) for r in raw_data]
            elif isinstance(raw_data, dict):
                data = flatten(raw_data)
            else:
                data = raw_data

            result: Dict[str, Any] = {"data": data}
            if included:
                result["included"] = [flatten(r) for r in included]
            if links:
                result["links"] = links
            return result

        except Exception as e:
            logger.error(f"JSON:API parse error: {e}, body keys: {list(body.keys())}")
            return {"data": body, "parse_error": str(e)}

    # =========================================================================
    # ACCOUNT INFO
    # =========================================================================

    def get_account_info(self, brand_id: str, org_id: str) -> Dict[str, Any]:
        """GET /api/accounts/ — returns account details."""
        result = self._make_request("GET", "/api/accounts/", brand_id, org_id, tier="S")
        data = result.get("data")
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # =========================================================================
    # LISTS & SEGMENTS
    # =========================================================================

    def get_lists(self, brand_id: str, org_id: str) -> List[Dict]:
        """GET /api/lists — returns all lists."""
        result = self._make_request("GET", "/api/lists/", brand_id, org_id, tier="L")
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    def get_segments(self, brand_id: str, org_id: str) -> List[Dict]:
        """GET /api/segments — returns all segments."""
        result = self._make_request("GET", "/api/segments/", brand_id, org_id, tier="L")
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    # =========================================================================
    # TEMPLATES
    # =========================================================================

    def get_templates(self, brand_id: str, org_id: str) -> List[Dict]:
        """GET /api/templates — returns all email templates."""
        result = self._make_request("GET", "/api/templates/", brand_id, org_id, tier="L")
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    # =========================================================================
    # CAMPAIGNS (Phase 1)
    # =========================================================================

    def get_campaigns(
        self,
        brand_id: str,
        org_id: str,
        filter_status: Optional[str] = None,
    ) -> List[Dict]:
        """GET /api/campaigns — requires channel filter for email."""
        params: Dict[str, str] = {"filter": "equals(messages.channel,'email')"}
        if filter_status:
            params["filter"] += f",equals(status,'{filter_status}')"
        result = self._make_request(
            "GET", "/api/campaigns/", brand_id, org_id, tier="L", params=params
        )
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    def create_campaign(
        self,
        brand_id: str,
        org_id: str,
        name: str,
        audiences: Dict[str, Any],
        channel: str = "email",
    ) -> Dict[str, Any]:
        """POST /api/campaigns — create a new campaign."""
        payload = {
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": name,
                    "channel": channel,
                    "audiences": audiences,
                },
            }
        }
        result = self._make_request(
            "POST", "/api/campaigns/", brand_id, org_id, tier="M", json=payload
        )
        return result.get("data", {})

    def update_campaign_message(
        self,
        brand_id: str,
        org_id: str,
        message_id: str,
        template_id: Optional[str] = None,
        subject: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PATCH /api/campaign-messages/{id} — update campaign message content."""
        attrs: Dict[str, Any] = {}
        if subject:
            attrs["label"] = subject
        content: Dict[str, Any] = {}
        if subject:
            content["subject"] = subject
        if from_email:
            content["from_email"] = from_email
        if from_name:
            content["from_label"] = from_name
        if content:
            attrs["content"] = content

        render_options: Dict[str, Any] = {}
        if template_id:
            render_options["template_id"] = template_id
        if render_options:
            attrs["render_options"] = render_options

        payload = {
            "data": {
                "type": "campaign-message",
                "id": message_id,
                "attributes": attrs,
            }
        }
        result = self._make_request(
            "PATCH", f"/api/campaign-messages/{message_id}/", brand_id, org_id,
            tier="M", json=payload,
        )
        return result.get("data", {})

    def send_campaign(
        self,
        brand_id: str,
        org_id: str,
        campaign_id: str,
        send_strategy: Optional[Dict[str, Any]] = None,
        scheduled_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/campaign-send-jobs — send or schedule a campaign.

        Returns:
            Dict with job_id for polling status.
        """
        attrs: Dict[str, Any] = {}
        if scheduled_at:
            attrs["send_strategy"] = {
                "method": "static",
                "options_static": {"datetime": scheduled_at},
            }
        elif send_strategy:
            attrs["send_strategy"] = send_strategy
        else:
            attrs["send_strategy"] = {"method": "immediate"}

        payload = {
            "data": {
                "type": "campaign-send-job",
                "attributes": attrs,
                "relationships": {
                    "campaign": {
                        "data": {"type": "campaign", "id": campaign_id}
                    }
                },
            }
        }
        result = self._make_request(
            "POST", "/api/campaign-send-jobs/", brand_id, org_id, tier="M", json=payload
        )
        return result.get("data", {})

    def get_send_job_status(
        self, brand_id: str, org_id: str, job_id: str
    ) -> Dict[str, Any]:
        """GET /api/campaign-send-jobs/{id} — poll send job status."""
        result = self._make_request(
            "GET", f"/api/campaign-send-jobs/{job_id}/", brand_id, org_id, tier="M"
        )
        return result.get("data", {})

    # =========================================================================
    # FLOWS (Phase 2)
    # =========================================================================

    def get_flows(self, brand_id: str, org_id: str) -> List[Dict]:
        """GET /api/flows — XS tier (1/s, 15/min)."""
        result = self._make_request("GET", "/api/flows/", brand_id, org_id, tier="XS")
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    def get_flow_detail(self, brand_id: str, org_id: str, flow_id: str) -> Dict[str, Any]:
        """GET /api/flows/{id} with definition field."""
        result = self._make_request(
            "GET", f"/api/flows/{flow_id}/", brand_id, org_id, tier="XS",
            params={"additional-fields[flow]": "definition"},
        )
        return result.get("data", {})

    def create_flow_from_template(
        self,
        brand_id: str,
        org_id: str,
        template_name: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a flow from a pre-built template definition.

        Args:
            template_name: One of 'post_purchase', 'welcome_series',
                          'abandoned_cart', 'winback'.
            config: Template-specific params (template_ids, delays, brand_name).

        Returns:
            Created flow data.
        """
        self._check_daily_flow_quota(brand_id)

        builders = {
            "post_purchase": self._build_post_purchase_flow,
            "welcome_series": self._build_welcome_series_flow,
            "abandoned_cart": self._build_abandoned_cart_flow,
            "winback": self._build_winback_flow,
        }
        builder = builders.get(template_name)
        if not builder:
            raise ValueError(f"Unknown flow template: {template_name}")

        definition = builder(**config)
        payload = {
            "data": {
                "type": "flow",
                "attributes": {
                    "name": config.get("flow_name", f"{template_name.replace('_', ' ').title()} Flow"),
                    "status": "draft",
                    "definition": definition,
                },
            }
        }
        result = self._make_request(
            "POST", "/api/flows/", brand_id, org_id, tier="XS", json=payload
        )
        self._increment_daily_flow_quota(brand_id)
        return result.get("data", {})

    def update_flow_status(
        self, brand_id: str, org_id: str, flow_id: str, status: str
    ) -> Dict[str, Any]:
        """PATCH /api/flows/{id} — update flow status (draft/manual/live)."""
        payload = {
            "data": {
                "type": "flow",
                "id": flow_id,
                "attributes": {"status": status},
            }
        }
        result = self._make_request(
            "PATCH", f"/api/flows/{flow_id}/", brand_id, org_id, tier="XS", json=payload
        )
        return result.get("data", {})

    # --- Daily quota tracking ---

    def _check_daily_flow_quota(self, brand_id: str, limit: int = 100) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_flow_date != today:
            self._daily_flow_creates.clear()
            self._daily_flow_date = today
        count = self._daily_flow_creates.get(brand_id, 0)
        if count >= limit:
            raise Exception(
                f"Daily flow creation limit reached ({limit}/day). "
                "Try again tomorrow or use the Klaviyo UI."
            )

    def _increment_daily_flow_quota(self, brand_id: str) -> None:
        self._daily_flow_creates[brand_id] = self._daily_flow_creates.get(brand_id, 0) + 1

    def get_daily_flow_usage(self, brand_id: str) -> Dict[str, int]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_flow_date != today:
            return {"used": 0, "limit": 100}
        return {"used": self._daily_flow_creates.get(brand_id, 0), "limit": 100}

    # --- Flow template builders ---

    @staticmethod
    def _build_post_purchase_flow(
        template_ids: List[str],
        delays: Optional[List[int]] = None,
        brand_name: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Build a post-purchase email flow definition.

        Default sequence:
        1. Thank you (immediate)
        2. Product tips (3 days)
        3. Review request + referral (7 days)
        4. Loyalty/reorder prompt (14 days)
        """
        delays = delays or [0, 3, 7, 14]
        import uuid
        actions = []
        for i, (tmpl_id, delay_days) in enumerate(zip(template_ids, delays)):
            action_id = str(uuid.uuid4())
            action = {
                "temporary_id": action_id,
                "type": "SEND_EMAIL",
                "settings": {"template_id": tmpl_id},
            }
            if delay_days > 0:
                action["time_delay"] = {"amount": delay_days, "unit": "days"}
            actions.append(action)

        return {
            "trigger": {
                "type": "METRIC",
                "metric_name": "Placed Order",
                "filters": [{"dimension": "flow_message_count", "operator": "equals", "value": 0}],
            },
            "actions": actions,
        }

    @staticmethod
    def _build_welcome_series_flow(
        template_ids: List[str],
        delays: Optional[List[int]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        delays = delays or [0, 1, 3, 7]
        import uuid
        actions = []
        for tmpl_id, delay_days in zip(template_ids, delays):
            action = {
                "temporary_id": str(uuid.uuid4()),
                "type": "SEND_EMAIL",
                "settings": {"template_id": tmpl_id},
            }
            if delay_days > 0:
                action["time_delay"] = {"amount": delay_days, "unit": "days"}
            actions.append(action)

        return {
            "trigger": {"type": "LIST", "list_trigger": "ADDED_TO_LIST"},
            "actions": actions,
        }

    @staticmethod
    def _build_abandoned_cart_flow(
        template_ids: List[str],
        delays: Optional[List[int]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        delays = delays or [1, 4, 24]  # hours for abandoned cart
        import uuid
        actions = []
        for tmpl_id, delay_hours in zip(template_ids, delays):
            action = {
                "temporary_id": str(uuid.uuid4()),
                "type": "SEND_EMAIL",
                "settings": {"template_id": tmpl_id},
            }
            if delay_hours > 0:
                action["time_delay"] = {"amount": delay_hours, "unit": "hours"}
            actions.append(action)

        return {
            "trigger": {"type": "METRIC", "metric_name": "Started Checkout"},
            "actions": actions,
        }

    @staticmethod
    def _build_winback_flow(
        template_ids: List[str],
        delays: Optional[List[int]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        delays = delays or [30, 45, 60, 90]
        import uuid
        actions = []
        for tmpl_id, delay_days in zip(template_ids, delays):
            action = {
                "temporary_id": str(uuid.uuid4()),
                "type": "SEND_EMAIL",
                "settings": {"template_id": tmpl_id},
            }
            if delay_days > 0:
                action["time_delay"] = {"amount": delay_days, "unit": "days"}
            actions.append(action)

        return {
            "trigger": {
                "type": "METRIC",
                "metric_name": "Placed Order",
                "filters": [{"dimension": "days_since_last_order", "operator": "greater_than", "value": 30}],
            },
            "actions": actions,
        }

    # =========================================================================
    # METRICS / ANALYTICS (Phase 3)
    # =========================================================================

    def get_campaign_metrics(
        self,
        brand_id: str,
        org_id: str,
        campaign_ids: List[str],
        timeframe: str = "last_30_days",
    ) -> List[Dict]:
        """POST /api/campaign-values-reports — fetch campaign performance metrics."""
        payload = {
            "data": {
                "type": "campaign-values-report",
                "attributes": {
                    "timeframe": {"key": timeframe},
                    "campaign_ids": campaign_ids,
                    "statistics": [
                        "opens", "unique_opens", "clicks", "unique_clicks",
                        "bounces", "unsubscribes", "conversions", "revenue",
                        "recipients",
                    ],
                },
            }
        }
        result = self._make_request(
            "POST", "/api/campaign-values-reports/", brand_id, org_id, tier="S", json=payload
        )
        data = result.get("data", [])
        return data if isinstance(data, list) else [data] if data else []

    def get_flow_metrics(
        self,
        brand_id: str,
        org_id: str,
        flow_ids: List[str],
        timeframe: str = "last_30_days",
    ) -> List[Dict]:
        """POST /api/flow-values-reports — fetch flow performance metrics."""
        payload = {
            "data": {
                "type": "flow-values-report",
                "attributes": {
                    "timeframe": {"key": timeframe},
                    "flow_ids": flow_ids,
                    "statistics": [
                        "opens", "unique_opens", "clicks", "unique_clicks",
                        "bounces", "unsubscribes", "conversions", "revenue",
                        "recipients",
                    ],
                },
            }
        }
        result = self._make_request(
            "POST", "/api/flow-values-reports/", brand_id, org_id, tier="S", json=payload
        )
        data = result.get("data", [])
        return data if isinstance(data, list) else [data] if data else []

    def sync_metrics_to_cache(
        self,
        brand_id: str,
        org_id: str,
    ) -> Dict[str, int]:
        """Fetch campaign + flow metrics and upsert to cache tables.

        Returns:
            Dict with counts of synced campaigns and flows.
        """
        real_org_id = self._resolve_org_id(org_id, brand_id)
        synced = {"campaigns": 0, "flows": 0}

        # Sync campaigns
        try:
            campaigns = self.get_campaigns(brand_id, org_id)
            if campaigns:
                campaign_ids = [c["id"] for c in campaigns if c.get("id")]
                if campaign_ids:
                    metrics = self.get_campaign_metrics(brand_id, org_id, campaign_ids)
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    for m in metrics:
                        stats = m.get("statistics", m)
                        campaign_id = m.get("id", "")
                        campaign_name = ""
                        for c in campaigns:
                            if c.get("id") == campaign_id:
                                campaign_name = c.get("name", "")
                                break
                        row = {
                            "brand_id": brand_id,
                            "organization_id": real_org_id,
                            "klaviyo_campaign_id": campaign_id,
                            "campaign_name": campaign_name,
                            "date": today,
                            "opens": stats.get("opens", 0),
                            "unique_opens": stats.get("unique_opens", 0),
                            "clicks": stats.get("clicks", 0),
                            "unique_clicks": stats.get("unique_clicks", 0),
                            "bounces": stats.get("bounces", 0),
                            "unsubscribes": stats.get("unsubscribes", 0),
                            "conversions": stats.get("conversions", 0),
                            "revenue": stats.get("revenue", 0),
                            "recipients": stats.get("recipients", 0),
                            "synced_at": datetime.now(timezone.utc).isoformat(),
                        }
                        self.supabase.table("klaviyo_campaign_metrics").upsert(
                            row, on_conflict="brand_id,klaviyo_campaign_id,date"
                        ).execute()
                        synced["campaigns"] += 1
        except Exception as e:
            logger.error(f"Campaign metrics sync error: {e}")

        # Sync flows
        try:
            flows = self.get_flows(brand_id, org_id)
            if flows:
                flow_ids = [f["id"] for f in flows if f.get("id")]
                if flow_ids:
                    metrics = self.get_flow_metrics(brand_id, org_id, flow_ids)
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    for m in metrics:
                        stats = m.get("statistics", m)
                        flow_id = m.get("id", "")
                        flow_name = ""
                        for f in flows:
                            if f.get("id") == flow_id:
                                flow_name = f.get("name", "")
                                break
                        row = {
                            "brand_id": brand_id,
                            "organization_id": real_org_id,
                            "klaviyo_flow_id": flow_id,
                            "flow_name": flow_name,
                            "date": today,
                            "opens": stats.get("opens", 0),
                            "unique_opens": stats.get("unique_opens", 0),
                            "clicks": stats.get("clicks", 0),
                            "unique_clicks": stats.get("unique_clicks", 0),
                            "bounces": stats.get("bounces", 0),
                            "unsubscribes": stats.get("unsubscribes", 0),
                            "conversions": stats.get("conversions", 0),
                            "revenue": stats.get("revenue", 0),
                            "recipients": stats.get("recipients", 0),
                            "synced_at": datetime.now(timezone.utc).isoformat(),
                        }
                        self.supabase.table("klaviyo_flow_metrics").upsert(
                            row, on_conflict="brand_id,klaviyo_flow_id,date"
                        ).execute()
                        synced["flows"] += 1
        except Exception as e:
            logger.error(f"Flow metrics sync error: {e}")

        return synced
