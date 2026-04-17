"""
Klaviyo Dashboard - Connection management, account overview, and quick stats.

Handles OAuth callback with PKCE (code_verifier stored in DB for cross-tab safety).
"""

import logging
import os
import secrets

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Klaviyo Dashboard", page_icon="📧", layout="wide")

logger = logging.getLogger(__name__)


# =============================================================================
# OAUTH CALLBACK HANDLING (BEFORE require_auth — cookie iframe hasn't
# initialized yet after cross-domain redirect from klaviyo.com)
# =============================================================================

def _get_oauth_redirect_uri() -> str:
    base = os.environ.get("APP_BASE_URL", "http://localhost:8501")
    return f"{base.rstrip('/')}/klaviyo-dashboard"


def _get_klaviyo_service():
    from viraltracker.services.klaviyo_service import KlaviyoService
    return KlaviyoService()


if "code" in st.query_params and "state" in st.query_params:
    try:
        from viraltracker.services.klaviyo_oauth_utils import decode_oauth_state, exchange_klaviyo_code

        state_data = decode_oauth_state(st.query_params["state"])
        brand_id = state_data["brand_id"]
        org_id = state_data["org_id"]
        nonce = state_data["nonce"]

        svc = _get_klaviyo_service()

        # Look up code_verifier from DB (cross-tab safe)
        code_verifier = svc.get_pending_oauth(brand_id, org_id, nonce)
        if not code_verifier:
            st.error("OAuth state expired or invalid. Please try connecting again.")
            st.query_params.clear()
            st.stop()

        redirect_uri = _get_oauth_redirect_uri()
        tokens = exchange_klaviyo_code(
            st.query_params["code"], redirect_uri, code_verifier
        )

        # Fetch account info to store with integration
        account_id = ""
        account_name = ""
        try:
            # Temporarily save so we can use _make_request
            svc.save_integration(brand_id, org_id, tokens)
            info = svc.get_account_info(brand_id, org_id)
            account_id = info.get("id", "")
            account_name = info.get("company_name", info.get("contact_information", {}).get("organization_name", ""))
        except Exception as e:
            logger.warning(f"Could not fetch account info: {e}")

        # Save final integration with account details
        svc.save_integration(brand_id, org_id, tokens, account_id, account_name)
        svc.delete_pending_oauth(brand_id, org_id)
        st.session_state["_oauth_return"] = True  # Signal auth to wait for cookie iframe

        st.query_params.clear()
        st.rerun()
    except Exception as e:
        logger.error(f"Klaviyo OAuth callback failed: {e}")
        st.error(f"OAuth callback failed: {e}")
        st.query_params.clear()
        st.session_state["_oauth_return"] = True  # Even on error, we came from OAuth

# Auth check AFTER OAuth callback — cookie iframe needs extra cycles after redirect
require_auth()

from viraltracker.ui.utils import require_feature, render_brand_selector

require_feature("klaviyo_dashboard", "Klaviyo Dashboard")

# =============================================================================
# PAGE UI
# =============================================================================

st.title("📧 Klaviyo Dashboard")

brand_id = render_brand_selector(key="klaviyo_dashboard_brand")
if not brand_id:
    st.stop()

org_id = st.session_state.get("current_organization_id", "all")
svc = _get_klaviyo_service()

# --- Connection Status ---

if svc.is_connected(brand_id, org_id):
    # Connected state
    try:
        account_info = svc.get_account_info(brand_id, org_id)
    except Exception as e:
        account_info = {}
        st.warning(f"Could not fetch account info: {e}")

    col1, col2 = st.columns([3, 1])
    with col1:
        account_name = account_info.get("company_name", account_info.get("contact_information", {}).get("organization_name", "Connected"))
        st.success(f"Connected to Klaviyo: **{account_name}**")

        timezone = account_info.get("timezone", "")
        if timezone:
            st.caption(f"Timezone: {timezone}")

    with col2:
        if st.button("Disconnect", type="secondary", key="klaviyo_disconnect"):
            result = svc.disconnect(brand_id, org_id)
            if result.get("warning"):
                st.warning(result["message"])
                if st.button("Force Disconnect", type="primary", key="klaviyo_force_disconnect"):
                    svc.disconnect(brand_id, org_id, force=True)
                    st.rerun()
            else:
                st.rerun()

    # --- Refresh Token Health ---
    try:
        _, config = svc._get_credentials(brand_id, org_id)
        last_refresh = config.get("last_token_refresh_at", "")
        if last_refresh:
            from datetime import datetime, timezone as tz
            last_dt = datetime.fromisoformat(last_refresh)
            days_since = (datetime.now(tz.utc) - last_dt).days
            if days_since > 75:
                st.warning(
                    f"Refresh token last used {days_since} days ago. "
                    "Klaviyo refresh tokens expire after 90 days of inactivity. "
                    "Consider reconnecting soon."
                )
    except Exception:
        pass

    # --- Quick Stats ---
    st.divider()
    st.subheader("Quick Stats")

    col1, col2, col3 = st.columns(3)
    with col1:
        try:
            lists = svc.get_lists(brand_id, org_id)
            st.metric("Lists", len(lists))
        except Exception:
            st.metric("Lists", "—")

    with col2:
        try:
            segments = svc.get_segments(brand_id, org_id)
            st.metric("Segments", len(segments))
        except Exception:
            st.metric("Segments", "—")

    with col3:
        try:
            campaigns = svc.get_campaigns(brand_id, org_id)
            st.metric("Campaigns", len(campaigns))
        except Exception:
            st.metric("Campaigns", "—")

    # --- Recent Campaigns ---
    st.divider()
    st.subheader("Recent Campaigns")
    try:
        campaigns = svc.get_campaigns(brand_id, org_id)
        if campaigns:
            import pandas as pd
            rows = []
            for c in campaigns[:10]:
                rows.append({
                    "Name": c.get("name", ""),
                    "Status": c.get("status", ""),
                    "Channel": c.get("channel", ""),
                    "Created": c.get("created_datetime", c.get("created", "")),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No campaigns found. Create your first campaign in the Campaigns page.")
    except Exception as e:
        st.warning(f"Could not load campaigns: {e}")

else:
    # Not connected state
    st.info("Connect your Klaviyo account to manage email marketing campaigns and flows.")

    if st.button("Connect Klaviyo", type="primary", key="klaviyo_connect"):
        from viraltracker.services.klaviyo_oauth_utils import (
            generate_pkce_pair,
            get_klaviyo_authorization_url,
            encode_oauth_state,
        )

        nonce = secrets.token_urlsafe(32)
        code_verifier, code_challenge = generate_pkce_pair()

        # Store code_verifier in DB for cross-tab safety
        svc.save_pending_oauth(brand_id, org_id, nonce, code_verifier)

        state = encode_oauth_state(brand_id, org_id, nonce)
        redirect_uri = _get_oauth_redirect_uri()
        auth_url = get_klaviyo_authorization_url(redirect_uri, state, code_challenge)

        st.markdown(f"[Click here to authorize Klaviyo]({auth_url})")
