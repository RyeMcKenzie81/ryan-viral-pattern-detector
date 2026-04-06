"""
Meta (Facebook) OAuth2 utilities — authorization URL, code exchange, token extension.

Handles the full OAuth lifecycle for per-brand Meta ad account connections:
1. Build authorization URL for Facebook Login dialog
2. Exchange authorization code for short-lived token
3. Exchange short-lived token for long-lived token (~60 days)
4. Extend long-lived token before expiry (auto-renewal)

Meta does NOT have refresh tokens. Long-lived tokens can be exchanged for
new long-lived tokens before they expire (must be >24h old). If a token
expires or the user revokes access, they must re-authenticate via OAuth.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from viraltracker.services.google_oauth_utils import encode_oauth_state, decode_oauth_state  # noqa: F401

logger = logging.getLogger(__name__)

META_GRAPH_API_VERSION = "v25.0"
META_AUTH_URL = f"https://www.facebook.com/{META_GRAPH_API_VERSION}/dialog/oauth"
META_TOKEN_URL = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/oauth/access_token"
META_GRAPH_URL = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"

# Minimum scope needed for ad performance data
META_OAUTH_SCOPE = "ads_read"


def _get_app_credentials() -> tuple[str, str]:
    """Get Meta App ID and Secret from environment."""
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")
    return app_id, app_secret


def get_meta_authorization_url(redirect_uri: str, state: str) -> str:
    """
    Build the Meta OAuth2 authorization URL.

    Args:
        redirect_uri: URL to redirect back to after authorization
        state: Encoded state parameter (brand_id, org_id, nonce)

    Returns:
        Full authorization URL to redirect the user to
    """
    app_id, _ = _get_app_credentials()
    if not app_id:
        raise ValueError("META_APP_ID environment variable not set")

    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": META_OAUTH_SCOPE,
        "response_type": "code",
    }
    return f"{META_AUTH_URL}?{urlencode(params)}"


def exchange_meta_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """
    Exchange an authorization code for a short-lived access token.

    Args:
        code: Authorization code from OAuth callback
        redirect_uri: Must match the redirect_uri used in the authorization URL

    Returns:
        Dict with access_token, token_type, expires_in
    """
    app_id, app_secret = _get_app_credentials()
    if not app_id or not app_secret:
        raise ValueError("META_APP_ID and META_APP_SECRET must be set")

    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            META_TOKEN_URL,
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )

    if response.status_code != 200:
        logger.error(f"Meta code exchange failed: {response.status_code} {response.text}")
        raise ValueError(f"Meta code exchange failed: {response.text}")

    data = response.json()
    logger.info("Meta authorization code exchanged for short-lived token")
    return data


def exchange_for_long_lived_token(short_lived_token: str) -> Dict[str, Any]:
    """
    Exchange a short-lived token for a long-lived token (~60 days).

    Args:
        short_lived_token: Short-lived access token from code exchange

    Returns:
        Dict with access_token, token_type, expires_in (~5184000 seconds)
    """
    app_id, app_secret = _get_app_credentials()
    if not app_id or not app_secret:
        raise ValueError("META_APP_ID and META_APP_SECRET must be set")

    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            META_TOKEN_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_lived_token,
            },
        )

    if response.status_code != 200:
        logger.error(f"Meta long-lived token exchange failed: {response.status_code} {response.text}")
        raise ValueError(f"Meta long-lived token exchange failed: {response.text}")

    data = response.json()
    logger.info(f"Meta long-lived token obtained (expires_in={data.get('expires_in', 'unknown')}s)")
    return data


def extend_token(existing_long_lived_token: str) -> Optional[Dict[str, Any]]:
    """
    Exchange a valid long-lived token for a fresh long-lived token.

    Uses the same fb_exchange_token endpoint. The existing token must be
    >24h old and not expired. Returns None on failure (token expired,
    user revoked access, etc.).

    Args:
        existing_long_lived_token: Current long-lived access token

    Returns:
        Dict with access_token, token_type, expires_in on success; None on failure
    """
    app_id, app_secret = _get_app_credentials()
    if not app_id or not app_secret:
        logger.warning("META_APP_ID/SECRET not set, can't extend token")
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                META_TOKEN_URL,
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": existing_long_lived_token,
                },
            )

        if response.status_code != 200:
            logger.warning(f"Meta token extension failed: {response.status_code} {response.text}")
            return None

        data = response.json()
        logger.info(f"Meta token extended (expires_in={data.get('expires_in', 'unknown')}s)")
        return data

    except Exception as e:
        logger.error(f"Meta token extension error: {e}")
        return None


def get_token_user_info(access_token: str) -> Dict[str, Any]:
    """
    Get the Facebook user info for the token owner.

    Args:
        access_token: Valid access token

    Returns:
        Dict with id, name
    """
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            f"{META_GRAPH_URL}/me",
            params={"access_token": access_token, "fields": "id,name"},
        )

    if response.status_code != 200:
        logger.error(f"Meta user info failed: {response.status_code}")
        return {}

    return response.json()


def get_user_ad_accounts(access_token: str) -> List[Dict[str, Any]]:
    """
    Get all ad accounts the authenticated user has access to.

    Args:
        access_token: Valid access token with ads_read scope

    Returns:
        List of dicts with id (e.g., "act_123"), name, account_status
    """
    accounts = []
    url = f"{META_GRAPH_URL}/me/adaccounts"
    params = {
        "access_token": access_token,
        "fields": "id,name,account_status",
        "limit": 100,
    }

    max_pages = 50
    with httpx.Client(timeout=30.0) as client:
        page = 0
        while url and page < max_pages:
            response = client.get(url, params=params)
            if response.status_code != 200:
                logger.error(f"Meta ad accounts fetch failed: {response.status_code}")
                break

            data = response.json()
            accounts.extend(data.get("data", []))

            # Handle pagination
            paging = data.get("paging", {})
            url = paging.get("next")
            params = {}  # Next URL already has params
            page += 1

    logger.info(f"Found {len(accounts)} Meta ad accounts for user")
    return accounts
