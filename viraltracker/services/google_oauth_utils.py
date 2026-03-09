"""
Shared Google OAuth2 utilities — state encoding, token refresh.

Extracted from GSCService to enable reuse across Google integrations
(Search Console, Drive, etc.).
"""

import json
import logging
import os
import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def encode_oauth_state(brand_id: str, org_id: str, nonce: str, **extra) -> str:
    """Encode brand_id + org_id + nonce (+ optional extra fields) into OAuth state param."""
    data = {"brand_id": brand_id, "org_id": org_id, "nonce": nonce, **extra}
    payload = json.dumps(data)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_oauth_state(state: str) -> Dict[str, str]:
    """Decode OAuth state param back to brand_id, org_id, nonce."""
    payload = base64.urlsafe_b64decode(state.encode()).decode()
    return json.loads(payload)


def refresh_google_token(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Check token expiry and refresh if needed.

    Returns updated config with fresh access_token, or None if revoked/failed.
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
        logger.warning("No refresh_token available for Google token refresh")
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
            logger.error(f"Google token refresh failed: {response.status_code}")
            return None

        data = response.json()
        config["access_token"] = data["access_token"]
        config["token_expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        ).isoformat()

        logger.info("Google access token refreshed")
        return config

    except Exception as e:
        logger.error(f"Google token refresh error: {e}")
        return None
