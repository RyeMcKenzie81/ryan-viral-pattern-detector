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
            "total_purchases": 0,
            "total_revenue": 0,
            "avg_roas": 0,
            "total_add_to_carts": 0,
            "ad_count": 0
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
    avg_roas = (total_revenue / total_spend) if total_spend > 0 else 0

    # Count unique ads
    unique_ads = set(d.get("meta_ad_id") for d in data if d.get("meta_ad_id"))

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "avg_ctr": avg_ctr,
        "avg_cpc": avg_cpc,
        "total_purchases": total_purchases,
        "total_revenue": total_revenue,
        "avg_roas": avg_roas,
        "total_add_to_carts": total_add_to_carts,
        "ad_count": len(unique_ads)
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
    col1, col2, col3, col4 = st.columns(4)

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

    # Second row
    col5, col6, col7, col8 = st.columns(4)

    with col5:
        st.metric(
            "Impressions",
            f"{metrics['total_impressions']:,}",
            help="Total ad impressions"
        )

    with col6:
        st.metric(
            "Link Clicks",
            f"{metrics['total_clicks']:,}",
            help="Total link clicks"
        )

    with col7:
        st.metric(
            "Add to Carts",
            f"{metrics['total_add_to_carts']:,}",
            help="Total add to cart events"
        )

    with col8:
        st.metric(
            "Purchases",
            f"{metrics['total_purchases']:,}",
            help="Total purchase events"
        )


def render_ads_table(data: List[Dict], show_link_button: bool = False):
    """Render ads performance table."""
    import pandas as pd

    if not data:
        st.info("No ad data available for selected period.")
        return

    # Prepare data for display
    rows = []
    for d in data:
        rows.append({
            "Date": d.get("date", ""),
            "Ad Name": d.get("ad_name", "Unknown")[:50],
            "Spend": f"${float(d.get('spend') or 0):,.2f}",
            "Impr.": f"{int(d.get('impressions') or 0):,}",
            "Clicks": int(d.get("link_clicks") or 0),
            "CTR": f"{float(d.get('link_ctr') or 0):.2f}%",
            "CPC": f"${float(d.get('link_cpc') or 0):.2f}",
            "ATC": int(d.get("add_to_carts") or 0),
            "Purchases": int(d.get("purchases") or 0),
            "ROAS": f"{float(d.get('roas') or 0):.2f}x" if d.get("roas") else "-",
            "Meta Ad ID": d.get("meta_ad_id", "")[:15] + "..."
        })

    df = pd.DataFrame(rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ad Name": st.column_config.TextColumn("Ad Name", width="medium"),
            "Spend": st.column_config.TextColumn("Spend", width="small"),
            "CTR": st.column_config.TextColumn("CTR", width="small"),
            "ROAS": st.column_config.TextColumn("ROAS", width="small"),
        }
    )


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

# Tabs for different views
tab1, tab2 = st.tabs(["📊 All Meta Ads", "🔗 Linked Ads"])

with tab1:
    st.subheader(f"All Ads ({metrics['ad_count']} unique ads)")
    render_ads_table(perf_data)

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
