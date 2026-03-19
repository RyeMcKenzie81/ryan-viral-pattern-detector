"""
Klaviyo OAuth2 + PKCE utilities.

Handles authorization URL generation, code exchange, and token refresh
for Klaviyo's OAuth 2.0 flow with PKCE.

PKCE code_verifier is stored in the DB (brand_integrations with
platform='klaviyo_pending') keyed by the state nonce to survive
cross-tab OAuth callbacks.
"""

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx

from viraltracker.services.google_oauth_utils import encode_oauth_state, decode_oauth_state  # noqa: F401

logger = logging.getLogger(__name__)

KLAVIYO_AUTH_URL = "https://www.klaviyo.com/oauth/authorize"
KLAVIYO_TOKEN_URL = "https://a.klaviyo.com/oauth/token"


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge)
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_klaviyo_authorization_url(
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: str = "accounts:read campaigns:read campaigns:write flows:read flows:write lists:read segments:read templates:read templates:write metrics:read",
) -> str:
    """Build the Klaviyo OAuth2 authorization URL.

    Args:
        redirect_uri: Where Klaviyo redirects after user consent.
        state: Opaque state param (encoded brand_id + org_id + nonce).
        code_challenge: S256 PKCE challenge derived from code_verifier.
        scopes: Space-separated OAuth scopes.

    Returns:
        Full authorization URL string.
    """
    client_id = os.environ.get("KLAVIYO_CLIENT_ID", "")
    if not client_id:
        raise ValueError("KLAVIYO_CLIENT_ID env var not set")

    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{KLAVIYO_AUTH_URL}?{params}"


def exchange_klaviyo_code(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> Dict[str, Any]:
    """Exchange an authorization code for tokens using PKCE.

    Args:
        code: Authorization code from the callback.
        redirect_uri: Must match the one used in the authorization URL.
        code_verifier: The original PKCE verifier stored during auth start.

    Returns:
        Token response dict with access_token, refresh_token, expires_in, etc.

    Raises:
        Exception: On HTTP or Klaviyo error.
    """
    client_id = os.environ.get("KLAVIYO_CLIENT_ID", "")
    client_secret = os.environ.get("KLAVIYO_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise ValueError("KLAVIYO_CLIENT_ID/SECRET env vars not set")

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            KLAVIYO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )

    if response.status_code != 200:
        raise Exception(
            f"Klaviyo token exchange failed: {response.status_code} — {response.text[:300]}"
        )

    return response.json()


def refresh_klaviyo_token(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check token expiry and refresh if needed.

    Args:
        config: Integration config dict from brand_integrations.config JSONB.

    Returns:
        Updated config with fresh access_token, or None if refresh failed.
    """
    token_expiry = config.get("token_expiry", "")
    if token_expiry:
        try:
            expiry = datetime.fromisoformat(token_expiry)
            if expiry > datetime.now(timezone.utc):
                return config  # Token still valid
        except (ValueError, TypeError):
            pass

    refresh_token = config.get("refresh_token")
    if not refresh_token:
        logger.warning("No refresh_token available for Klaviyo token refresh")
        return None

    client_id = os.environ.get("KLAVIYO_CLIENT_ID", "")
    client_secret = os.environ.get("KLAVIYO_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        logger.warning("KLAVIYO_CLIENT_ID/SECRET not set, can't refresh")
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                KLAVIYO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )

        if response.status_code != 200:
            logger.error(f"Klaviyo token refresh failed: {response.status_code}")
            return None

        data = response.json()
        config["access_token"] = data["access_token"]
        if data.get("refresh_token"):
            config["refresh_token"] = data["refresh_token"]
        config["token_expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        ).isoformat()
        config["last_token_refresh_at"] = datetime.now(timezone.utc).isoformat()

        logger.info("Klaviyo access token refreshed")
        return config

    except Exception as e:
        logger.error(f"Klaviyo token refresh error: {e}")
        return None
