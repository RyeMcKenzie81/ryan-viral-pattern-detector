"""
Klaviyo Flows & Analytics - Manage automation flows and view performance metrics.

Uses st.tabs() for sub-views: Active Flows, Flow Templates, Analytics.
"""

import logging
from datetime import datetime, timezone

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Klaviyo Flows", page_icon="🔄", layout="wide")
require_auth()

from viraltracker.ui.utils import require_feature, render_brand_selector

require_feature("klaviyo_flows", "Klaviyo Flows")

logger = logging.getLogger(__name__)


def _get_klaviyo_service():
    from viraltracker.services.klaviyo_service import KlaviyoService
    return KlaviyoService()


st.title("🔄 Klaviyo Flows & Analytics")

brand_id = render_brand_selector(key="klaviyo_flows_brand")
if not brand_id:
    st.stop()

org_id = st.session_state.get("current_organization_id", "all")
svc = _get_klaviyo_service()

if not svc.is_connected(brand_id, org_id):
    st.warning("Klaviyo is not connected for this brand. Please connect on the Klaviyo Dashboard page.")
    st.stop()


tab_flows, tab_templates, tab_analytics = st.tabs(["Active Flows", "Flow Templates", "Analytics"])


# =============================================================================
# TAB 1: ACTIVE FLOWS
# =============================================================================

with tab_flows:
    st.subheader("Active Flows")

    # Daily quota display
    usage = svc.get_daily_flow_usage(brand_id)
    if usage["used"] > 0:
        st.caption(f"Flow API usage today: {usage['used']}/{usage['limit']}")

    try:
        flows = svc.get_flows(brand_id, org_id)
        if flows:
            import pandas as pd

            rows = []
            for f in flows:
                rows.append({
                    "Name": f.get("name", ""),
                    "Status": f.get("status", ""),
                    "Trigger": f.get("trigger_type", ""),
                    "Created": f.get("created", ""),
                    "ID": f.get("id", ""),
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Status toggle controls
            st.divider()
            st.markdown("**Change Flow Status**")
            flow_names = {f.get("name", f.get("id", "")): f.get("id", "") for f in flows}
            selected_flow_name = st.selectbox("Select flow", list(flow_names.keys()), key="flow_status_select")
            selected_flow_id = flow_names.get(selected_flow_name, "")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Set Draft", key="flow_draft"):
                    try:
                        svc.update_flow_status(brand_id, org_id, selected_flow_id, "draft")
                        st.success(f"Flow set to draft.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            with col2:
                if st.button("Set Manual", key="flow_manual"):
                    try:
                        svc.update_flow_status(brand_id, org_id, selected_flow_id, "manual")
                        st.success(f"Flow set to manual.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            with col3:
                if st.button("Set Live", type="primary", key="flow_live"):
                    try:
                        svc.update_flow_status(brand_id, org_id, selected_flow_id, "live")
                        st.success(f"Flow is now live!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
        else:
            st.info("No flows found. Use the Flow Templates tab to create your first automation.")
    except Exception as e:
        st.error(f"Could not load flows: {e}")


# =============================================================================
# TAB 2: FLOW TEMPLATES
# =============================================================================

with tab_templates:
    st.subheader("Flow Templates")
    st.caption("Pre-built automation patterns. Creates as draft in Klaviyo — customize in their UI.")

    FLOW_TEMPLATES = {
        "post_purchase": {
            "title": "Post-Purchase Sequence",
            "description": "Thank you, product tips, review request, and loyalty/reorder emails.",
            "icon": "🛍️",
            "default_delays": [0, 3, 7, 14],
            "delay_unit": "days",
            "email_labels": ["Thank You", "Product Tips", "Review Request", "Loyalty Prompt"],
        },
        "welcome_series": {
            "title": "Welcome Series",
            "description": "Onboard new subscribers with a warm introduction sequence.",
            "icon": "👋",
            "default_delays": [0, 1, 3, 7],
            "delay_unit": "days",
            "email_labels": ["Welcome", "Brand Story", "Best Sellers", "First Purchase CTA"],
        },
        "abandoned_cart": {
            "title": "Abandoned Cart",
            "description": "Recover lost sales with timely cart reminders.",
            "icon": "🛒",
            "default_delays": [1, 4, 24],
            "delay_unit": "hours",
            "email_labels": ["Cart Reminder", "Urgency", "Final Chance"],
        },
        "winback": {
            "title": "Win-Back",
            "description": "Re-engage lapsed customers with escalating offers.",
            "icon": "🔄",
            "default_delays": [30, 45, 60, 90],
            "delay_unit": "days",
            "email_labels": ["We Miss You", "Special Offer", "Last Chance", "Final Goodbye"],
        },
    }

    # Load templates for selection
    try:
        templates = svc.get_templates(brand_id, org_id)
        template_options = {t.get("name", t.get("id", "")): t.get("id", "") for t in templates}
    except Exception:
        template_options = {}

    if not template_options:
        st.warning("No email templates found in Klaviyo. Create templates in Klaviyo first.")

    for tmpl_key, tmpl_info in FLOW_TEMPLATES.items():
        with st.expander(f"{tmpl_info['icon']} {tmpl_info['title']}"):
            st.write(tmpl_info["description"])

            if not template_options:
                st.caption("Templates required to create this flow.")
                continue

            with st.form(f"flow_template_{tmpl_key}"):
                flow_name = st.text_input(
                    "Flow Name",
                    value=f"{tmpl_info['title']}",
                    key=f"fn_{tmpl_key}",
                )

                selected_templates = []
                delays = []
                for i, label in enumerate(tmpl_info["email_labels"]):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        t = st.selectbox(
                            f"Email {i+1}: {label}",
                            list(template_options.keys()),
                            key=f"tmpl_{tmpl_key}_{i}",
                        )
                        selected_templates.append(template_options.get(t, ""))
                    with col2:
                        d = st.number_input(
                            f"Delay ({tmpl_info['delay_unit']})",
                            value=tmpl_info["default_delays"][i],
                            min_value=0,
                            key=f"delay_{tmpl_key}_{i}",
                        )
                        delays.append(d)

                brand_name = st.text_input(
                    "Brand Name (for personalization)",
                    key=f"bn_{tmpl_key}",
                )

                create_btn = st.form_submit_button(f"Create {tmpl_info['title']}", type="primary")

            if create_btn:
                try:
                    config = {
                        "template_ids": selected_templates,
                        "delays": delays,
                        "brand_name": brand_name,
                        "flow_name": flow_name,
                    }
                    result = svc.create_flow_from_template(brand_id, org_id, tmpl_key, config)
                    flow_id = result.get("id", "")
                    st.success(f"Flow **{flow_name}** created as draft! (ID: {flow_id})")
                    st.caption("Fine-tune the flow in the Klaviyo UI, then set it live from the Active Flows tab.")
                except Exception as e:
                    st.error(f"Flow creation failed: {e}")


# =============================================================================
# TAB 3: ANALYTICS
# =============================================================================

with tab_analytics:
    st.subheader("Email Marketing Analytics")

    # Date range selector
    timeframe = st.selectbox(
        "Time Range",
        ["last_7_days", "last_14_days", "last_30_days", "last_90_days"],
        index=2,
        format_func=lambda x: x.replace("_", " ").title(),
        key="klaviyo_analytics_timeframe",
    )

    # Sync button
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("Sync Now", key="klaviyo_sync"):
            with st.spinner("Syncing metrics from Klaviyo..."):
                try:
                    result = svc.sync_metrics_to_cache(brand_id, org_id)
                    st.success(f"Synced {result['campaigns']} campaign(s) and {result['flows']} flow(s).")
                except Exception as e:
                    st.error(f"Sync failed: {e}")

    # --- Campaign Metrics ---
    st.divider()
    st.markdown("### Campaign Performance")

    try:
        campaigns = svc.get_campaigns(brand_id, org_id)
        if campaigns:
            campaign_ids = [c["id"] for c in campaigns if c.get("id")]
            if campaign_ids:
                metrics = svc.get_campaign_metrics(brand_id, org_id, campaign_ids, timeframe)
                if metrics:
                    # KPI cards
                    total_opens = sum(m.get("unique_opens", m.get("statistics", {}).get("unique_opens", 0)) for m in metrics)
                    total_clicks = sum(m.get("unique_clicks", m.get("statistics", {}).get("unique_clicks", 0)) for m in metrics)
                    total_revenue = sum(m.get("revenue", m.get("statistics", {}).get("revenue", 0)) for m in metrics)
                    total_recipients = sum(m.get("recipients", m.get("statistics", {}).get("recipients", 0)) for m in metrics)

                    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                    with kpi1:
                        st.metric("Total Recipients", f"{total_recipients:,}")
                    with kpi2:
                        st.metric("Unique Opens", f"{total_opens:,}")
                    with kpi3:
                        st.metric("Unique Clicks", f"{total_clicks:,}")
                    with kpi4:
                        st.metric("Revenue", f"${total_revenue:,.2f}")

                    # Campaign detail table
                    import pandas as pd
                    rows = []
                    for m in metrics:
                        stats = m.get("statistics", m)
                        campaign_id = m.get("id", "")
                        name = ""
                        for c in campaigns:
                            if c.get("id") == campaign_id:
                                name = c.get("name", "")
                                break
                        recipients = stats.get("recipients", 0)
                        unique_opens = stats.get("unique_opens", 0)
                        unique_clicks = stats.get("unique_clicks", 0)
                        open_rate = (unique_opens / recipients * 100) if recipients else 0
                        click_rate = (unique_clicks / recipients * 100) if recipients else 0
                        rows.append({
                            "Campaign": name or campaign_id,
                            "Recipients": recipients,
                            "Opens": unique_opens,
                            "Open Rate": f"{open_rate:.1f}%",
                            "Clicks": unique_clicks,
                            "Click Rate": f"{click_rate:.1f}%",
                            "Revenue": f"${stats.get('revenue', 0):,.2f}",
                            "Bounces": stats.get("bounces", 0),
                            "Unsubs": stats.get("unsubscribes", 0),
                        })
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No campaign metrics available. Click 'Sync Now' to fetch data.")
            else:
                st.info("No campaigns with IDs found.")
        else:
            st.info("No campaigns found.")
    except Exception as e:
        st.warning(f"Could not load campaign metrics: {e}")

    # --- Flow Metrics ---
    st.divider()
    st.markdown("### Flow Performance")

    try:
        flows = svc.get_flows(brand_id, org_id)
        if flows:
            flow_ids = [f["id"] for f in flows if f.get("id")]
            if flow_ids:
                flow_metrics = svc.get_flow_metrics(brand_id, org_id, flow_ids, timeframe)
                if flow_metrics:
                    import pandas as pd
                    rows = []
                    for m in flow_metrics:
                        stats = m.get("statistics", m)
                        flow_id = m.get("id", "")
                        name = ""
                        for f in flows:
                            if f.get("id") == flow_id:
                                name = f.get("name", "")
                                break
                        recipients = stats.get("recipients", 0)
                        unique_opens = stats.get("unique_opens", 0)
                        unique_clicks = stats.get("unique_clicks", 0)
                        open_rate = (unique_opens / recipients * 100) if recipients else 0
                        click_rate = (unique_clicks / recipients * 100) if recipients else 0
                        rows.append({
                            "Flow": name or flow_id,
                            "Recipients": recipients,
                            "Opens": unique_opens,
                            "Open Rate": f"{open_rate:.1f}%",
                            "Clicks": unique_clicks,
                            "Click Rate": f"{click_rate:.1f}%",
                            "Revenue": f"${stats.get('revenue', 0):,.2f}",
                        })
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No flow metrics available. Click 'Sync Now' to fetch data.")
        else:
            st.info("No flows found.")
    except Exception as e:
        st.warning(f"Could not load flow metrics: {e}")
