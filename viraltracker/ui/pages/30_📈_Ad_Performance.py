"""
Ad Performance - Meta Ads performance feedback loop.

This page allows users to:
- Sync ad performance data from Meta Ads API
- View performance metrics (spend, ROAS, CTR, etc.)
- See both linked ads and all Meta ads
- Link generated ads to Meta ads
"""

import streamlit as st
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

# Page config (must be first)
st.set_page_config(
    page_title="Ad Performance",
    page_icon="📈",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Session state for drill-down navigation
if "ad_perf_campaign_id" not in st.session_state:
    st.session_state.ad_perf_campaign_id = None
if "ad_perf_campaign_name" not in st.session_state:
    st.session_state.ad_perf_campaign_name = None
if "ad_perf_adset_id" not in st.session_state:
    st.session_state.ad_perf_adset_id = None
if "ad_perf_adset_name" not in st.session_state:
    st.session_state.ad_perf_adset_name = None


# =============================================================================
# Helper Functions
# =============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_meta_ads_service():
    """Get MetaAdsService instance (lazy import to avoid init issues)."""
    from viraltracker.services.meta_ads_service import MetaAdsService
    return MetaAdsService()


def get_brand_ad_account(brand_id: str) -> Optional[Dict]:
    """Get the Meta ad account linked to a brand."""
    try:
        db = get_supabase_client()
        result = db.table("brand_ad_accounts").select(
            "id, meta_ad_account_id, account_name, is_primary"
        ).eq("brand_id", brand_id).eq("is_primary", True).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Failed to fetch ad account: {e}")
        return None


def get_performance_data(
    brand_id: str,
    date_start: str,
    date_end: str,
    meta_ad_account_id: Optional[str] = None
) -> List[Dict]:
    """Fetch performance data from database."""
    try:
        db = get_supabase_client()
        query = db.table("meta_ads_performance").select("*")

        if meta_ad_account_id:
            query = query.eq("meta_ad_account_id", meta_ad_account_id)

        if brand_id:
            query = query.eq("brand_id", brand_id)

        query = query.gte("date", date_start).lte("date", date_end)
        query = query.order("date", desc=True).order("spend", desc=True)

        result = query.execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch performance data: {e}")
        return []


def get_linked_ads(brand_id: str) -> List[Dict]:
    """Get ads that are linked between ViralTracker and Meta."""
    try:
        db = get_supabase_client()
        result = db.table("meta_ad_mapping").select(
            "*, generated_ads(id, storage_path, status)"
        ).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch linked ads: {e}")
        return []


def aggregate_metrics(data: List[Dict]) -> Dict[str, Any]:
    """Aggregate performance metrics across all ads."""
    if not data:
        return {
            "total_spend": 0,
            "total_impressions": 0,
            "total_clicks": 0,
            "avg_ctr": 0,
            "avg_cpc": 0,
            "avg_cpm": 0,
            "total_purchases": 0,
            "total_revenue": 0,
            "avg_roas": 0,
            "total_add_to_carts": 0,
            "ad_count": 0,
            "campaign_count": 0,
            "adset_count": 0
        }

    total_spend = sum(float(d.get("spend") or 0) for d in data)
    total_impressions = sum(int(d.get("impressions") or 0) for d in data)
    total_clicks = sum(int(d.get("link_clicks") or 0) for d in data)
    total_purchases = sum(int(d.get("purchases") or 0) for d in data)
    total_revenue = sum(float(d.get("purchase_value") or 0) for d in data)
    total_add_to_carts = sum(int(d.get("add_to_carts") or 0) for d in data)

    # Calculate averages
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    avg_cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
    avg_cpm = (total_spend / total_impressions * 1000) if total_impressions > 0 else 0
    avg_roas = (total_revenue / total_spend) if total_spend > 0 else 0

    # Count unique entities
    unique_ads = set(d.get("meta_ad_id") for d in data if d.get("meta_ad_id"))
    unique_campaigns = set(d.get("meta_campaign_id") for d in data if d.get("meta_campaign_id"))
    unique_adsets = set(d.get("meta_adset_id") for d in data if d.get("meta_adset_id"))

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "avg_ctr": avg_ctr,
        "avg_cpc": avg_cpc,
        "avg_cpm": avg_cpm,
        "total_purchases": total_purchases,
        "total_revenue": total_revenue,
        "avg_roas": avg_roas,
        "total_add_to_carts": total_add_to_carts,
        "ad_count": len(unique_ads),
        "campaign_count": len(unique_campaigns),
        "adset_count": len(unique_adsets)
    }


async def sync_ads_from_meta(
    brand_id: str,
    ad_account_id: str,
    date_start: str,
    date_end: str
) -> int:
    """Sync ads from Meta API to database."""
    service = get_meta_ads_service()

    # Fetch insights from Meta
    insights = await service.get_ad_insights(
        ad_account_id=ad_account_id,
        date_start=date_start,
        date_end=date_end
    )

    if not insights:
        return 0

    # Save to database
    count = await service.sync_performance_to_db(
        insights=insights,
        brand_id=UUID(brand_id)
    )

    return count


# =============================================================================
# UI Components
# =============================================================================

def render_metric_cards(metrics: Dict[str, Any]):
    """Render metric summary cards."""
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "Total Spend",
            f"${metrics['total_spend']:,.2f}",
            help="Total ad spend in selected period"
        )

    with col2:
        st.metric(
            "ROAS",
            f"{metrics['avg_roas']:.2f}x",
            help="Return on Ad Spend (Revenue / Spend)"
        )

    with col3:
        st.metric(
            "Link CTR",
            f"{metrics['avg_ctr']:.2f}%",
            help="Link Click-Through Rate"
        )

    with col4:
        st.metric(
            "CPC",
            f"${metrics['avg_cpc']:.2f}",
            help="Cost Per Click"
        )

    with col5:
        st.metric(
            "CPM",
            f"${metrics.get('avg_cpm', 0):.2f}",
            help="Cost Per 1000 Impressions"
        )

    # Second row
    col6, col7, col8, col9, col10 = st.columns(5)

    with col6:
        st.metric(
            "Impressions",
            f"{metrics['total_impressions']:,}",
            help="Total ad impressions"
        )

    with col7:
        st.metric(
            "Link Clicks",
            f"{metrics['total_clicks']:,}",
            help="Total link clicks"
        )

    with col8:
        st.metric(
            "Add to Carts",
            f"{metrics['total_add_to_carts']:,}",
            help="Total add to cart events"
        )

    with col9:
        st.metric(
            "Purchases",
            f"{metrics['total_purchases']:,}",
            help="Total purchase events"
        )

    with col10:
        st.metric(
            "Revenue",
            f"${metrics['total_revenue']:,.2f}",
            help="Total purchase revenue"
        )


def get_status_emoji(status: str) -> str:
    """Get emoji for ad status."""
    status_map = {
        "ACTIVE": "🟢",
        "PAUSED": "⚪",
        "DELETED": "🔴",
        "ARCHIVED": "📦",
        "PENDING_REVIEW": "🟡",
        "DISAPPROVED": "❌",
    }
    return status_map.get(status.upper() if status else "", "⚫")


def aggregate_by_ad(data: List[Dict]) -> List[Dict]:
    """Aggregate performance data by ad (across all dates in range)."""
    from collections import defaultdict
    ads = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
    })

    for d in data:
        aid = d.get("meta_ad_id")
        if not aid:
            continue
        a = ads[aid]
        a["ad_name"] = d.get("ad_name", "Unknown")
        a["ad_status"] = d.get("ad_status", "")
        a["adset_name"] = d.get("adset_name", "")
        a["campaign_name"] = d.get("campaign_name", "")
        a["meta_adset_id"] = d.get("meta_adset_id", "")
        a["meta_campaign_id"] = d.get("meta_campaign_id", "")
        a["spend"] += float(d.get("spend") or 0)
        a["impressions"] += int(d.get("impressions") or 0)
        a["link_clicks"] += int(d.get("link_clicks") or 0)
        a["add_to_carts"] += int(d.get("add_to_carts") or 0)
        a["purchases"] += int(d.get("purchases") or 0)
        a["purchase_value"] += float(d.get("purchase_value") or 0)

    result = []
    for aid, a in ads.items():
        ctr = (a["link_clicks"] / a["impressions"] * 100) if a["impressions"] > 0 else 0
        cpm = (a["spend"] / a["impressions"] * 1000) if a["impressions"] > 0 else 0
        cpc = (a["spend"] / a["link_clicks"]) if a["link_clicks"] > 0 else 0
        roas = (a["purchase_value"] / a["spend"]) if a["spend"] > 0 else 0
        result.append({
            "meta_ad_id": aid,
            "ad_name": a["ad_name"],
            "ad_status": a["ad_status"],
            "adset_name": a["adset_name"],
            "campaign_name": a["campaign_name"],
            "meta_adset_id": a["meta_adset_id"],
            "meta_campaign_id": a["meta_campaign_id"],
            "spend": a["spend"],
            "impressions": a["impressions"],
            "link_clicks": a["link_clicks"],
            "ctr": ctr,
            "cpm": cpm,
            "cpc": cpc,
            "add_to_carts": a["add_to_carts"],
            "purchases": a["purchases"],
            "roas": roas,
        })

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def render_ads_table(data: List[Dict], show_link_button: bool = False):
    """Render ads performance table with aggregated data."""
    import pandas as pd

    if not data:
        st.info("No ad data available for selected period.")
        return

    # Aggregate by ad across all dates
    ads = aggregate_by_ad(data)

    # Prepare data for display
    rows = []
    for a in ads:
        status = a.get("ad_status", "")
        status_display = f"{get_status_emoji(status)} {status}" if status else "-"
        rows.append({
            "Status": status_display,
            "Ad Name": a.get("ad_name", "Unknown")[:50],
            "Spend": f"${a['spend']:,.2f}",
            "Impr.": f"{a['impressions']:,}",
            "CPM": f"${a['cpm']:.2f}",
            "Clicks": a["link_clicks"],
            "CTR": f"{a['ctr']:.2f}%",
            "CPC": f"${a['cpc']:.2f}",
            "ATC": a["add_to_carts"],
            "Purchases": a["purchases"],
            "ROAS": f"{a['roas']:.2f}x" if a["roas"] else "-",
        })

    df = pd.DataFrame(rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Ad Name": st.column_config.TextColumn("Ad Name", width="medium"),
            "Spend": st.column_config.TextColumn("Spend", width="small"),
            "CPM": st.column_config.TextColumn("CPM", width="small"),
            "CTR": st.column_config.TextColumn("CTR", width="small"),
            "ROAS": st.column_config.TextColumn("ROAS", width="small"),
        }
    )


def aggregate_by_campaign(data: List[Dict]) -> List[Dict]:
    """Aggregate performance data by campaign."""
    from collections import defaultdict
    campaigns = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
        "ad_count": 0, "adset_ids": set(), "ad_ids": set()
    })

    for d in data:
        cid = d.get("meta_campaign_id")
        if not cid:
            continue
        c = campaigns[cid]
        c["campaign_name"] = d.get("campaign_name", "Unknown")
        c["spend"] += float(d.get("spend") or 0)
        c["impressions"] += int(d.get("impressions") or 0)
        c["link_clicks"] += int(d.get("link_clicks") or 0)
        c["add_to_carts"] += int(d.get("add_to_carts") or 0)
        c["purchases"] += int(d.get("purchases") or 0)
        c["purchase_value"] += float(d.get("purchase_value") or 0)
        if d.get("meta_adset_id"):
            c["adset_ids"].add(d.get("meta_adset_id"))
        if d.get("meta_ad_id"):
            c["ad_ids"].add(d.get("meta_ad_id"))

    result = []
    for cid, c in campaigns.items():
        ctr = (c["link_clicks"] / c["impressions"] * 100) if c["impressions"] > 0 else 0
        cpm = (c["spend"] / c["impressions"] * 1000) if c["impressions"] > 0 else 0
        roas = (c["purchase_value"] / c["spend"]) if c["spend"] > 0 else 0
        result.append({
            "meta_campaign_id": cid,
            "campaign_name": c["campaign_name"],
            "spend": c["spend"],
            "impressions": c["impressions"],
            "link_clicks": c["link_clicks"],
            "ctr": ctr,
            "cpm": cpm,
            "add_to_carts": c["add_to_carts"],
            "purchases": c["purchases"],
            "roas": roas,
            "adset_count": len(c["adset_ids"]),
            "ad_count": len(c["ad_ids"]),
        })

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def aggregate_by_adset(data: List[Dict]) -> List[Dict]:
    """Aggregate performance data by ad set."""
    from collections import defaultdict
    adsets = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
        "ad_ids": set()
    })

    for d in data:
        asid = d.get("meta_adset_id")
        if not asid:
            continue
        a = adsets[asid]
        a["adset_name"] = d.get("adset_name", "Unknown")
        a["campaign_name"] = d.get("campaign_name", "")
        a["meta_campaign_id"] = d.get("meta_campaign_id", "")
        a["spend"] += float(d.get("spend") or 0)
        a["impressions"] += int(d.get("impressions") or 0)
        a["link_clicks"] += int(d.get("link_clicks") or 0)
        a["add_to_carts"] += int(d.get("add_to_carts") or 0)
        a["purchases"] += int(d.get("purchases") or 0)
        a["purchase_value"] += float(d.get("purchase_value") or 0)
        if d.get("meta_ad_id"):
            a["ad_ids"].add(d.get("meta_ad_id"))

    result = []
    for asid, a in adsets.items():
        ctr = (a["link_clicks"] / a["impressions"] * 100) if a["impressions"] > 0 else 0
        cpm = (a["spend"] / a["impressions"] * 1000) if a["impressions"] > 0 else 0
        roas = (a["purchase_value"] / a["spend"]) if a["spend"] > 0 else 0
        result.append({
            "meta_adset_id": asid,
            "adset_name": a["adset_name"],
            "campaign_name": a["campaign_name"],
            "meta_campaign_id": a["meta_campaign_id"],
            "spend": a["spend"],
            "impressions": a["impressions"],
            "link_clicks": a["link_clicks"],
            "ctr": ctr,
            "cpm": cpm,
            "add_to_carts": a["add_to_carts"],
            "purchases": a["purchases"],
            "roas": roas,
            "ad_count": len(a["ad_ids"]),
        })

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def render_campaigns_table(data: List[Dict]):
    """Render campaigns summary table."""
    import pandas as pd

    if not data:
        st.info("No campaign data available.")
        return

    campaigns = aggregate_by_campaign(data)
    rows = []
    for c in campaigns:
        rows.append({
            "Campaign": (c["campaign_name"] or "Unknown")[:40],
            "Spend": f"${c['spend']:,.2f}",
            "Impr.": f"{c['impressions']:,}",
            "CPM": f"${c['cpm']:.2f}",
            "Clicks": c["link_clicks"],
            "CTR": f"{c['ctr']:.2f}%",
            "ATC": c["add_to_carts"],
            "Purchases": c["purchases"],
            "ROAS": f"{c['roas']:.2f}x",
            "Ad Sets": c["adset_count"],
            "Ads": c["ad_count"],
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_adsets_table(data: List[Dict]):
    """Render ad sets summary table."""
    import pandas as pd

    if not data:
        st.info("No ad set data available.")
        return

    adsets = aggregate_by_adset(data)
    rows = []
    for a in adsets:
        rows.append({
            "Ad Set": (a["adset_name"] or "Unknown")[:35],
            "Campaign": (a["campaign_name"] or "Unknown")[:25],
            "Spend": f"${a['spend']:,.2f}",
            "Impr.": f"{a['impressions']:,}",
            "CPM": f"${a['cpm']:.2f}",
            "Clicks": a["link_clicks"],
            "CTR": f"{a['ctr']:.2f}%",
            "ATC": a["add_to_carts"],
            "Purchases": a["purchases"],
            "ROAS": f"{a['roas']:.2f}x",
            "Ads": a["ad_count"],
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_breadcrumbs():
    """Render breadcrumb navigation for drill-down."""
    campaign_id = st.session_state.ad_perf_campaign_id
    campaign_name = st.session_state.ad_perf_campaign_name
    adset_id = st.session_state.ad_perf_adset_id
    adset_name = st.session_state.ad_perf_adset_name

    cols = st.columns([1, 1, 1, 6])

    with cols[0]:
        if st.button("📁 All Campaigns", use_container_width=True):
            st.session_state.ad_perf_campaign_id = None
            st.session_state.ad_perf_campaign_name = None
            st.session_state.ad_perf_adset_id = None
            st.session_state.ad_perf_adset_name = None
            st.rerun()

    if campaign_id:
        with cols[1]:
            label = f"📂 {(campaign_name or 'Campaign')[:20]}"
            if st.button(label, use_container_width=True):
                st.session_state.ad_perf_adset_id = None
                st.session_state.ad_perf_adset_name = None
                st.rerun()

    if adset_id:
        with cols[2]:
            label = f"📄 {(adset_name or 'Ad Set')[:20]}"
            st.button(label, use_container_width=True, disabled=True)


def render_drilldown_campaigns(data: List[Dict]):
    """Render campaigns table with clickable rows for drill-down."""
    import pandas as pd

    campaigns = aggregate_by_campaign(data)

    if not campaigns:
        st.info("No campaign data available.")
        return

    st.caption(f"Click a campaign to view its ad sets")

    for c in campaigns:
        campaign_name = c["campaign_name"] or "Unknown"
        campaign_id = c["meta_campaign_id"]

        with st.container():
            cols = st.columns([3, 1, 1, 1, 1, 1, 1, 1])

            with cols[0]:
                if st.button(f"📁 {campaign_name[:35]}", key=f"camp_{campaign_id}", use_container_width=True):
                    st.session_state.ad_perf_campaign_id = campaign_id
                    st.session_state.ad_perf_campaign_name = campaign_name
                    st.rerun()

            with cols[1]:
                st.metric("Spend", f"${c['spend']:,.0f}", label_visibility="collapsed")
            with cols[2]:
                st.metric("Impr", f"{c['impressions']:,}", label_visibility="collapsed")
            with cols[3]:
                st.metric("CTR", f"{c['ctr']:.1f}%", label_visibility="collapsed")
            with cols[4]:
                st.metric("ROAS", f"{c['roas']:.1f}x", label_visibility="collapsed")
            with cols[5]:
                st.metric("ATC", f"{c['add_to_carts']}", label_visibility="collapsed")
            with cols[6]:
                st.metric("Purch", f"{c['purchases']}", label_visibility="collapsed")
            with cols[7]:
                st.caption(f"{c['adset_count']} sets · {c['ad_count']} ads")


def render_drilldown_adsets(data: List[Dict], campaign_id: str):
    """Render ad sets for a specific campaign with clickable rows."""
    import pandas as pd

    # Filter data to selected campaign
    filtered = [d for d in data if d.get("meta_campaign_id") == campaign_id]
    adsets = aggregate_by_adset(filtered)

    if not adsets:
        st.info("No ad sets found for this campaign.")
        return

    st.caption(f"Click an ad set to view its ads")

    for a in adsets:
        adset_name = a["adset_name"] or "Unknown"
        adset_id = a["meta_adset_id"]

        with st.container():
            cols = st.columns([3, 1, 1, 1, 1, 1, 1, 1])

            with cols[0]:
                if st.button(f"📂 {adset_name[:35]}", key=f"adset_{adset_id}", use_container_width=True):
                    st.session_state.ad_perf_adset_id = adset_id
                    st.session_state.ad_perf_adset_name = adset_name
                    st.rerun()

            with cols[1]:
                st.metric("Spend", f"${a['spend']:,.0f}", label_visibility="collapsed")
            with cols[2]:
                st.metric("Impr", f"{a['impressions']:,}", label_visibility="collapsed")
            with cols[3]:
                st.metric("CTR", f"{a['ctr']:.1f}%", label_visibility="collapsed")
            with cols[4]:
                st.metric("ROAS", f"{a['roas']:.1f}x", label_visibility="collapsed")
            with cols[5]:
                st.metric("ATC", f"{a['add_to_carts']}", label_visibility="collapsed")
            with cols[6]:
                st.metric("Purch", f"{a['purchases']}", label_visibility="collapsed")
            with cols[7]:
                st.caption(f"{a['ad_count']} ads")


def render_drilldown_ads(data: List[Dict], adset_id: str):
    """Render ads for a specific ad set."""
    # Filter data to selected ad set
    filtered = [d for d in data if d.get("meta_adset_id") == adset_id]
    render_ads_table(filtered)


def render_drilldown_view(data: List[Dict]):
    """Render the appropriate drill-down level based on session state."""
    campaign_id = st.session_state.ad_perf_campaign_id
    adset_id = st.session_state.ad_perf_adset_id

    # Render breadcrumbs
    render_breadcrumbs()
    st.divider()

    if adset_id:
        # Level 3: Show ads for selected ad set
        st.subheader(f"📄 Ads in {st.session_state.ad_perf_adset_name or 'Ad Set'}")
        render_drilldown_ads(data, adset_id)
    elif campaign_id:
        # Level 2: Show ad sets for selected campaign
        st.subheader(f"📂 Ad Sets in {st.session_state.ad_perf_campaign_name or 'Campaign'}")
        render_drilldown_adsets(data, campaign_id)
    else:
        # Level 1: Show all campaigns
        st.subheader("📁 Campaigns")
        render_drilldown_campaigns(data)


def render_sync_section(brand_id: str, ad_account: Dict):
    """Render the sync controls section."""
    st.subheader("Sync Data from Meta")

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        sync_start = st.date_input(
            "Start Date",
            value=datetime.now() - timedelta(days=30),
            key="sync_start_date"
        )

    with col2:
        sync_end = st.date_input(
            "End Date",
            value=datetime.now(),
            key="sync_end_date"
        )

    with col3:
        st.write("")  # Spacer
        st.write("")  # Spacer
        sync_clicked = st.button("🔄 Sync Ads", type="primary", use_container_width=True)

    if sync_clicked:
        with st.spinner(f"Syncing ads from {ad_account['meta_ad_account_id']}..."):
            try:
                count = asyncio.run(sync_ads_from_meta(
                    brand_id=brand_id,
                    ad_account_id=ad_account['meta_ad_account_id'],
                    date_start=sync_start.strftime("%Y-%m-%d"),
                    date_end=sync_end.strftime("%Y-%m-%d")
                ))
                st.success(f"Synced {count} ad performance records!")
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")


def render_setup_instructions():
    """Render setup instructions when no ad account is linked."""
    st.warning("No Meta Ad Account linked to this brand.")

    with st.expander("How to set up Meta Ads integration"):
        st.markdown("""
        ### Step 1: Get your Ad Account ID

        1. Go to [Meta Ads Manager](https://adsmanager.facebook.com/)
        2. Click on your account name in the top left
        3. Your Ad Account ID is shown (format: `act_123456789`)

        ### Step 2: Link your account

        Run this SQL in Supabase to link your ad account:

        ```sql
        INSERT INTO brand_ad_accounts (brand_id, meta_ad_account_id, account_name, is_primary)
        VALUES (
            'YOUR_BRAND_UUID',
            'act_123456789',
            'My Ad Account',
            true
        );
        ```

        ### Step 3: Set up API token

        Add to your environment variables:
        ```
        META_GRAPH_API_TOKEN=your_token_here
        ```

        Get a token from [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
        """)


# =============================================================================
# Main Page
# =============================================================================

st.title("📈 Ad Performance")
st.markdown("Track Meta Ads performance and close the feedback loop.")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="ad_performance_brand")

if not brand_id:
    st.stop()

# Check for linked ad account
ad_account = get_brand_ad_account(brand_id)

if not ad_account:
    render_setup_instructions()
    st.stop()

st.caption(f"Connected: **{ad_account.get('account_name', ad_account['meta_ad_account_id'])}**")

st.divider()

# Date range selector
col1, col2 = st.columns(2)
with col1:
    date_start = st.date_input(
        "From",
        value=datetime.now() - timedelta(days=30),
        key="perf_date_start"
    )
with col2:
    date_end = st.date_input(
        "To",
        value=datetime.now(),
        key="perf_date_end"
    )

# Sync section
with st.expander("🔄 Sync from Meta", expanded=False):
    render_sync_section(brand_id, ad_account)

st.divider()

# Fetch performance data
perf_data = get_performance_data(
    brand_id=brand_id,
    date_start=date_start.strftime("%Y-%m-%d"),
    date_end=date_end.strftime("%Y-%m-%d"),
    meta_ad_account_id=ad_account['meta_ad_account_id']
)

# Aggregate metrics
metrics = aggregate_metrics(perf_data)

# Metric cards
render_metric_cards(metrics)

st.divider()

# Hierarchy count display
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"📁 {metrics.get('campaign_count', 0)} Campaigns")
with col2:
    st.caption(f"📂 {metrics.get('adset_count', 0)} Ad Sets")
with col3:
    st.caption(f"📄 {metrics.get('ad_count', 0)} Ads")

# Tabs: Drill-down hierarchy vs Linked ads
tab1, tab2 = st.tabs(["📊 Performance", "🔗 Linked Ads"])

with tab1:
    # Drill-down navigation: Campaigns → Ad Sets → Ads
    render_drilldown_view(perf_data)

with tab2:
    st.subheader("Linked Ads (ViralTracker ↔ Meta)")
    linked = get_linked_ads(brand_id)

    if linked:
        st.info(f"{len(linked)} ads linked to ViralTracker generated ads")
        # Filter performance data to only linked ads
        linked_ad_ids = set(l.get("meta_ad_id") for l in linked)
        linked_perf = [d for d in perf_data if d.get("meta_ad_id") in linked_ad_ids]
        render_ads_table(linked_perf)
    else:
        st.info("No ads linked yet. Use the auto-match feature to link Meta ads to your generated ads.")
        st.markdown("""
        **How linking works:**
        1. When you create ads in ViralTracker, the filename starts with an 8-character ID
        2. Copy this ID to your Meta ad name when uploading
        3. Use the auto-match feature to automatically link them
        """)


# Footer with data info
if perf_data:
    st.divider()
    latest = max(d.get("fetched_at", "") for d in perf_data if d.get("fetched_at"))
    if latest:
        st.caption(f"Data last synced: {latest[:19]}")
