"""
Klaviyo Campaigns - Create, schedule, and manage email campaigns.

Single-page form with numbered sections (not a multi-step wizard).
"""

import logging

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Klaviyo Campaigns", page_icon="📨", layout="wide")
require_auth()

from viraltracker.ui.utils import require_feature, render_brand_selector

require_feature("klaviyo_campaigns", "Klaviyo Campaigns")

logger = logging.getLogger(__name__)


def _get_klaviyo_service():
    from viraltracker.services.klaviyo_service import KlaviyoService
    return KlaviyoService()


st.title("📨 Klaviyo Campaigns")

brand_id = render_brand_selector(key="klaviyo_campaigns_brand")
if not brand_id:
    st.stop()

org_id = st.session_state.get("current_organization_id", "all")
svc = _get_klaviyo_service()

if not svc.is_connected(brand_id, org_id):
    st.warning("Klaviyo is not connected for this brand. Please connect on the Klaviyo Dashboard page.")
    st.stop()

# =============================================================================
# EXISTING CAMPAIGNS
# =============================================================================

st.subheader("Existing Campaigns")

try:
    campaigns = svc.get_campaigns(brand_id, org_id)
    if campaigns:
        import pandas as pd
        rows = []
        for c in campaigns:
            rows.append({
                "Name": c.get("name", ""),
                "Status": c.get("status", ""),
                "Channel": c.get("channel", ""),
                "Created": c.get("created_datetime", c.get("created", "")),
                "Send Time": c.get("send_time", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No campaigns yet. Create your first email campaign below.")
except Exception as e:
    st.error(f"Could not load campaigns: {e}")

st.divider()

# =============================================================================
# CREATE CAMPAIGN FORM
# =============================================================================

st.subheader("Create New Campaign")

# Load lists, segments, and templates for selectors
try:
    lists = svc.get_lists(brand_id, org_id)
    segments = svc.get_segments(brand_id, org_id)
    templates = svc.get_templates(brand_id, org_id)
except Exception as e:
    st.error(f"Could not load Klaviyo data: {e}")
    st.stop()

list_options = {l.get("name", l.get("id", "")): l.get("id", "") for l in lists}
segment_options = {s.get("name", s.get("id", "")): s.get("id", "") for s in segments}
template_options = {"(None)": ""} | {t.get("name", t.get("id", "")): t.get("id", "") for t in templates}

with st.form("create_campaign_form"):
    # --- 1. Campaign Details ---
    st.markdown("**1. Campaign Details**")
    campaign_name = st.text_input("Campaign Name", placeholder="e.g., Spring Sale 2026")

    audience_type = st.radio("Audience Type", ["List", "Segment"], horizontal=True)
    if audience_type == "List":
        audience_name = st.selectbox("Select List", list(list_options.keys())) if list_options else None
        if not list_options:
            st.caption("No lists found in Klaviyo.")
    else:
        audience_name = st.selectbox("Select Segment", list(segment_options.keys())) if segment_options else None
        if not segment_options:
            st.caption("No segments found in Klaviyo.")

    # --- 2. Email Content ---
    st.markdown("**2. Email Content**")
    template_name = st.selectbox("Template", list(template_options.keys()))
    subject_line = st.text_input("Subject Line", placeholder="e.g., Don't miss our spring sale!")
    from_name = st.text_input("From Name", placeholder="e.g., Savage")
    from_email = st.text_input("From Email", placeholder="e.g., hello@yourbrand.com")

    # --- 3. Schedule ---
    st.markdown("**3. Schedule**")
    send_option = st.radio(
        "When to send",
        ["Send immediately", "Schedule for later", "Smart send time"],
        horizontal=True,
    )
    scheduled_date = None
    scheduled_time = None
    if send_option == "Schedule for later":
        col1, col2 = st.columns(2)
        with col1:
            import datetime
            scheduled_date = st.date_input("Send Date", min_value=datetime.date.today())
        with col2:
            scheduled_time = st.time_input("Send Time")

    submitted = st.form_submit_button("Create Campaign", type="primary")

if submitted:
    if not campaign_name:
        st.error("Campaign name is required.")
    elif not audience_name:
        st.error("Please select an audience.")
    else:
        try:
            # Build audiences payload
            if audience_type == "List":
                audience_id = list_options[audience_name]
                audiences = {"included": [{"type": "list", "id": audience_id}]}
            else:
                audience_id = segment_options[audience_name]
                audiences = {"included": [{"type": "segment", "id": audience_id}]}

            # Create campaign
            campaign = svc.create_campaign(brand_id, org_id, campaign_name, audiences)
            campaign_id = campaign.get("id")

            if not campaign_id:
                st.error("Campaign creation failed — no ID returned.")
                st.stop()

            st.success(f"Campaign **{campaign_name}** created (ID: {campaign_id})")

            # Update message if template/subject provided
            template_id = template_options.get(template_name, "")
            if template_id or subject_line or from_email or from_name:
                # Get the campaign's message ID
                relationships = campaign.get("relationships", {})
                messages = relationships.get("campaign-messages", {}).get("data", [])
                if messages:
                    message_id = messages[0].get("id", "")
                    if message_id:
                        svc.update_campaign_message(
                            brand_id, org_id, message_id,
                            template_id=template_id if template_id else None,
                            subject=subject_line if subject_line else None,
                            from_email=from_email if from_email else None,
                            from_name=from_name if from_name else None,
                        )

            # Store in session for send confirmation
            st.session_state["_klaviyo_pending_campaign"] = {
                "id": campaign_id,
                "name": campaign_name,
                "send_option": send_option,
                "scheduled_date": str(scheduled_date) if scheduled_date else None,
                "scheduled_time": str(scheduled_time) if scheduled_time else None,
            }
            st.rerun()

        except Exception as e:
            st.error(f"Campaign creation failed: {e}")

# =============================================================================
# SEND CONFIRMATION
# =============================================================================

pending = st.session_state.get("_klaviyo_pending_campaign")
if pending:
    st.divider()
    with st.container(border=True):
        st.markdown(f"### Ready to Send: **{pending['name']}**")
        st.caption(f"Campaign ID: {pending['id']}")

        if pending["send_option"] == "Schedule for later" and pending.get("scheduled_date"):
            st.info(f"Scheduled for {pending['scheduled_date']} at {pending.get('scheduled_time', 'N/A')}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve & Send", type="primary", key="approve_send"):
                try:
                    scheduled_at = None
                    send_strategy = None

                    if pending["send_option"] == "Schedule for later" and pending.get("scheduled_date"):
                        scheduled_at = f"{pending['scheduled_date']}T{pending.get('scheduled_time', '09:00:00')}"
                    elif pending["send_option"] == "Smart send time":
                        send_strategy = {"method": "smart_send_time"}

                    result = svc.send_campaign(
                        brand_id, org_id, pending["id"],
                        send_strategy=send_strategy,
                        scheduled_at=scheduled_at,
                    )
                    job_id = result.get("id")
                    st.success(f"Campaign sent! Job ID: {job_id}")
                    del st.session_state["_klaviyo_pending_campaign"]
                except Exception as e:
                    st.error(f"Send failed: {e}")

        with col2:
            if st.button("Cancel", key="cancel_send"):
                del st.session_state["_klaviyo_pending_campaign"]
                st.rerun()
