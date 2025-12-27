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

# Session state for filtering (Facebook-style)
if "ad_perf_selected_campaign" not in st.session_state:
    st.session_state.ad_perf_selected_campaign = None  # (id, name) tuple
if "ad_perf_selected_adset" not in st.session_state:
    st.session_state.ad_perf_selected_adset = None  # (id, name) tuple
if "ad_perf_active_tab" not in st.session_state:
    st.session_state.ad_perf_active_tab = 0  # 0=Campaigns, 1=Ad Sets, 2=Ads, 3=Linked, 4=Manual Analysis

# Analysis State
if "ad_analysis_result" not in st.session_state:
    st.session_state.ad_analysis_result = None
if "analyzing_ad" not in st.session_state:
    st.session_state.analyzing_ad = False


# Session state for linking
if "ad_perf_match_suggestions" not in st.session_state:
    st.session_state.ad_perf_match_suggestions = None  # List of match suggestions
if "ad_perf_linking_ad" not in st.session_state:
    st.session_state.ad_perf_linking_ad = None  # Meta ad being manually linked



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


def get_brand_research_service():
    """Get BrandResearchService instance."""
    from viraltracker.services.brand_research_service import BrandResearchService
    return BrandResearchService()


def fetch_real_ad_copy(meta_ad_id: str) -> Optional[str]:
    """
    Try to fetch the real ad body text from the facebook_ads table.
    
    Args:
        meta_ad_id: The Meta Ad ID string
        
    Returns:
        The body text if found, else None
    """
    try:
        db = get_supabase_client()
        # Look up by id (which corresponds to meta_ad_id in our schema usually, 
        # or we check if facebook_ads.id is the meta_id. 
        # In this project, facebook_ads.id seems to be the UUID, and it has a 'ad_id' column for Meta ID?
        # Let's check schema assumption. Usually 'id' is UUID.
        # But 'meta_ads_performance' joins on 'meta_ad_id'. 
        # Let's query based on 'ad_id' column in facebook_ads which usually holds the platform ID.
        
        result = db.table("facebook_ads").select("snapshot").eq("ad_id", meta_ad_id).limit(1).execute()
        
        if result.data:
            snapshot = result.data[0].get("snapshot")
            if isinstance(snapshot, str):
                import json
                snapshot = json.loads(snapshot)
            
            # Extract body text
            if isinstance(snapshot, dict):
                body = snapshot.get("body", {})
                if isinstance(body, dict):
                    return body.get("text")
                elif isinstance(body, str):
                    return body
                    
        return None
    except Exception as e:
        # Fail silently and fall back to ad name
        return None






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
            "*, generated_ads(id, storage_path, hook_text, final_status)"
        ).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch linked ads: {e}")
        return []


def get_linked_meta_ad_ids() -> set:
    """Get set of Meta ad IDs that are already linked."""
    try:
        db = get_supabase_client()
        result = db.table("meta_ad_mapping").select("meta_ad_id").execute()
        return set(r["meta_ad_id"] for r in (result.data or []))
    except Exception:
        return set()


def get_generated_ads_for_linking(brand_id: str, limit: int = 100) -> List[Dict]:
    """Get generated ads for manual linking picker."""
    try:
        db = get_supabase_client()
        # Get ads through ad_runs -> products -> brand
        result = db.table("generated_ads").select(
            "id, storage_path, hook_text, final_status, created_at, "
            "ad_runs(id, product_id, products(id, name, brand_id))"
        ).eq("final_status", "approved").order(
            "created_at", desc=True
        ).limit(limit).execute()

        # Filter to only ads for this brand
        ads = []
        for ad in (result.data or []):
            ad_run = ad.get("ad_runs") or {}
            product = ad_run.get("products") or {}
            if str(product.get("brand_id")) == brand_id:
                ads.append({
                    "id": ad["id"],
                    "storage_path": ad.get("storage_path"),
                    "hook_text": ad.get("hook_text", "")[:50],
                    "product_name": product.get("name", "Unknown"),
                    "created_at": ad.get("created_at", "")[:10],
                })
        return ads
    except Exception as e:
        st.error(f"Failed to fetch generated ads: {e}")
        return []


async def find_auto_matches(brand_id: str) -> List[Dict]:
    """Find auto-match suggestions using MetaAdsService."""
    service = get_meta_ads_service()
    return await service.auto_match_ads(brand_id=UUID(brand_id))


async def fetch_missing_thumbnails(brand_id: str) -> int:
    """Fetch thumbnails for ads that don't have them."""
    service = get_meta_ads_service()
    return await service.update_missing_thumbnails(brand_id=UUID(brand_id), limit=50)


def create_ad_link(
    generated_ad_id: str,
    meta_ad_id: str,
    meta_campaign_id: str,
    meta_ad_account_id: str,
    linked_by: str = "manual"
) -> bool:
    """Create a link between generated ad and Meta ad."""
    try:
        db = get_supabase_client()
        db.table("meta_ad_mapping").insert({
            "generated_ad_id": generated_ad_id,
            "meta_ad_id": meta_ad_id,
            "meta_campaign_id": meta_campaign_id,
            "meta_ad_account_id": meta_ad_account_id,
            "linked_by": linked_by,
        }).execute()
        return True
    except Exception as e:
        error_str = str(e)
        if "duplicate key" in error_str or "23505" in error_str:
            st.warning("This ad is already linked!")
            return True  # Return True so we still remove it from suggestions
        st.error(f"Failed to create link: {e}")
        return False


def delete_ad_link(meta_ad_id: str) -> bool:
    """Remove a link between generated ad and Meta ad."""
    try:
        db = get_supabase_client()
        db.table("meta_ad_mapping").delete().eq("meta_ad_id", meta_ad_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to remove link: {e}")
        return False


def get_legacy_unmatched_ads(brand_id: str, campaign_name: str) -> List[Dict]:
    """
    Get Meta ads from a specific campaign that don't have ID patterns in their names
    and are not yet linked to generated ads.
    """
    try:
        db = get_supabase_client()
        service = get_meta_ads_service()

        # Get all linked meta_ad_ids
        linked_result = db.table("meta_ad_mapping").select("meta_ad_id").execute()
        linked_ids = set(r["meta_ad_id"] for r in (linked_result.data or []))

        # Get ads from the specific campaign
        result = db.table("meta_ads_performance").select(
            "meta_ad_id, ad_name, campaign_name, thumbnail_url, spend, impressions"
        ).eq("brand_id", brand_id).ilike("campaign_name", f"%{campaign_name}%").execute()

        # Filter to unlinked ads without ID patterns
        unmatched = []
        seen_ids = set()
        for ad in (result.data or []):
            meta_ad_id = ad.get("meta_ad_id")
            ad_name = ad.get("ad_name", "")

            # Skip if already linked or already seen
            if meta_ad_id in linked_ids or meta_ad_id in seen_ids:
                continue
            seen_ids.add(meta_ad_id)

            # Check if the ad name has an ID pattern (if so, auto-match should handle it)
            extracted_id = service.find_matching_generated_ad_id(ad_name)
            if not extracted_id:
                # No ID pattern found - this is a legacy ad
                unmatched.append(ad)

        # Sort by spend descending (highest spend first)
        unmatched.sort(key=lambda x: float(x.get("spend") or 0), reverse=True)
        return unmatched
    except Exception as e:
        st.error(f"Failed to get legacy ads: {e}")
        return []


def get_signed_url(storage_path: str, expires_in: int = 3600) -> Optional[str]:
    """Get a signed URL for a storage path."""
    if not storage_path:
        return None
    try:
        db = get_supabase_client()
        # Parse bucket and path from storage_path
        # Format could be "generated-ads/path/to/file.png" or just "path/to/file.png"
        if storage_path.startswith("generated-ads/"):
            bucket = "generated-ads"
            path = storage_path[len("generated-ads/"):]
        else:
            bucket = "generated-ads"
            path = storage_path

        result = db.storage.from_(bucket).create_signed_url(path, expires_in)
        return result.get("signedURL")
    except Exception:
        return None


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


def aggregate_time_series(data: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Aggregate performance data by date for time-series charts.

    Returns dict with keys: dates, spend, roas, ctr, cpc, impressions, clicks
    """
    from collections import defaultdict

    daily = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "purchases": 0, "purchase_value": 0
    })

    for d in data:
        date = d.get("date")
        if not date:
            continue
        day = daily[date]
        day["spend"] += float(d.get("spend") or 0)
        day["impressions"] += int(d.get("impressions") or 0)
        day["link_clicks"] += int(d.get("link_clicks") or 0)
        day["purchases"] += int(d.get("purchases") or 0)
        day["purchase_value"] += float(d.get("purchase_value") or 0)

    # Sort by date and build lists
    sorted_dates = sorted(daily.keys())

    result = {
        "dates": sorted_dates,
        "spend": [],
        "impressions": [],
        "clicks": [],
        "ctr": [],
        "cpc": [],
        "roas": [],
    }

    for date in sorted_dates:
        d = daily[date]
        result["spend"].append(d["spend"])
        result["impressions"].append(d["impressions"])
        result["clicks"].append(d["link_clicks"])

        # Calculate rates
        ctr = (d["link_clicks"] / d["impressions"] * 100) if d["impressions"] > 0 else 0
        cpc = (d["spend"] / d["link_clicks"]) if d["link_clicks"] > 0 else 0
        roas = (d["purchase_value"] / d["spend"]) if d["spend"] > 0 else 0

        result["ctr"].append(round(ctr, 2))
        result["cpc"].append(round(cpc, 2))
        result["roas"].append(round(roas, 2))

    return result


def get_top_performers(data: List[Dict], metric: str = "roas", top_n: int = 5) -> List[Dict]:
    """
    Get top N performing ads by a specified metric.

    Args:
        data: Performance data list
        metric: Metric to sort by (roas, ctr, spend, purchases)
        top_n: Number of top performers to return
    """
    ads = aggregate_by_ad(data)

    # Sort by metric (descending)
    if metric == "roas":
        sorted_ads = sorted(ads, key=lambda x: x.get("roas", 0), reverse=True)
    elif metric == "ctr":
        sorted_ads = sorted(ads, key=lambda x: x.get("ctr", 0), reverse=True)
    elif metric == "spend":
        sorted_ads = sorted(ads, key=lambda x: x.get("spend", 0), reverse=True)
    elif metric == "purchases":
        sorted_ads = sorted(ads, key=lambda x: x.get("purchases", 0), reverse=True)
    else:
        sorted_ads = ads

    return sorted_ads[:top_n]


def get_worst_performers(data: List[Dict], metric: str = "roas", bottom_n: int = 5, min_spend: float = 10.0) -> List[Dict]:
    """
    Get bottom N performing ads by a specified metric.

    Args:
        data: Performance data list
        metric: Metric to sort by (roas, ctr)
        bottom_n: Number of worst performers to return
        min_spend: Minimum spend threshold to be included
    """
    ads = aggregate_by_ad(data)

    # Filter by minimum spend
    ads_with_spend = [a for a in ads if a.get("spend", 0) >= min_spend]

    # Sort by metric (ascending for worst)
    if metric == "roas":
        sorted_ads = sorted(ads_with_spend, key=lambda x: x.get("roas", 0))
    elif metric == "ctr":
        sorted_ads = sorted(ads_with_spend, key=lambda x: x.get("ctr", 0))
    else:
        sorted_ads = ads_with_spend

    return sorted_ads[:bottom_n]


def export_to_csv(data: List[Dict]) -> str:
    """
    Export performance data to CSV format string.

    Returns CSV content as string.
    """
    import io
    import csv

    if not data:
        return ""

    # Aggregate by ad
    ads = aggregate_by_ad(data)

    # Define columns
    columns = [
        "Ad Name", "Campaign", "Ad Set", "Status",
        "Spend", "Impressions", "CPM", "Clicks", "CTR",
        "CPC", "Add to Carts", "Purchases", "ROAS"
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)

    for ad in ads:
        writer.writerow([
            ad.get("ad_name", "Unknown"),
            ad.get("campaign_name", ""),
            ad.get("adset_name", ""),
            ad.get("ad_status", ""),
            f"{ad.get('spend', 0):.2f}",
            ad.get("impressions", 0),
            f"{ad.get('cpm', 0):.2f}",
            ad.get("link_clicks", 0),
            f"{ad.get('ctr', 0):.2f}%",
            f"{ad.get('cpc', 0):.2f}",
            ad.get("add_to_carts", 0),
            ad.get("purchases", 0),
            f"{ad.get('roas', 0):.2f}",
        ])

    return output.getvalue()


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


async def analyze_ad_creative(
    creative_file: Optional[Any] = None,
    creative_url: Optional[str] = None,
    creative_type: str = "image",  # image or video
    ad_copy: str = "",
    headline: str = "",
    ad_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Analyze ad creative and copy to extract strategy.
    
    Args:
        creative_file: UploadedFile object or bytes
        creative_url: URL to creative (if file not provided)
        creative_type: 'image' or 'video'
        ad_copy: Primary text
        headline: Ad headline
        ad_id: Optional UUID of the ad for tracking
        
    Returns:
        Dict with analysis results (angle, belief, hooks, etc.)
    """
    service = get_brand_research_service()
    
    # 1. Analyze Creative (Vision)
    vision_analysis = {}
    if creative_file or creative_url:
        st.write(f"DEBUG: Starting visual analysis. URL: {creative_url}, ID: {ad_id}")
        if creative_type == "video":
            # For video, we need bytes or URL
            if creative_file:
                # If it's a Streamlit UploadedFile, get bytes
                video_bytes = creative_file.getvalue() if hasattr(creative_file, "getvalue") else creative_file
                vision_analysis = await service.analyze_video(video_bytes=video_bytes)
            elif creative_url:
                # Use the new analyze_video_from_url for direct handling
                vision_analysis = await service.analyze_video_from_url(video_url=creative_url)
        else:
            # Image
            if creative_file:
                img_bytes = creative_file.getvalue() if hasattr(creative_file, "getvalue") else creative_file
                vision_analysis = await service.analyze_image(image_bytes=img_bytes)
            elif creative_url:
                # Download image from URL to bytes
                import httpx
                import traceback
                try:
                    st.write("DEBUG: [1] Initializing httpx client...")
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        st.write(f"DEBUG: [2] Fetching URL: {creative_url}")
                        resp = await client.get(creative_url)
                        st.write(f"DEBUG: [3] Response status: {resp.status_code}")
                        
                        if resp.status_code == 200:
                            img_bytes = resp.content
                            st.write(f"DEBUG: [4] Got {len(img_bytes)} bytes. Calling analyze_image...")
                            vision_analysis = await service.analyze_image(image_bytes=img_bytes, skip_save=True)
                            st.write("DEBUG: [5] analyze_image returned.")
                        else:
                            st.warning(f"Failed to download image: {resp.status_code}")
                except Exception as e:
                    st.error(f"Image download failed: {e}")
                    st.code(traceback.format_exc())

    
    # 2. Analyze Copy
    copy_analysis = {}
    if ad_copy or headline:
        full_text = f"{headline}\n\n{ad_copy}"
        # Refactored: service now supports optional ad_id for manual analysis
        copy_analysis = await service.analyze_copy(ad_copy=full_text, ad_id=ad_id)


        
    # 3. Merge/Synthesize (Smarter merge)
    def resolve_best(key_copy, key_vision, invalid_values=None):
        invalid = invalid_values or ["None", "Unknown", "null", "Error", None, ""]
        val_c = copy_analysis.get(key_copy)
        val_v = vision_analysis.get(key_vision)
        
        # Check validity (simple check: valid if not in invalid list and doesn't start with Error)
        def is_valid(v):
            if v in invalid: return False
            if isinstance(v, str) and (v.startswith("Error:") or v.startswith("[image]")): return False
            return True
            
        if is_valid(val_v): return val_v
        if is_valid(val_c): return val_c
        return val_v or val_c # Fallback

    result = {
        "angle": resolve_best("advertising_angle", "advertising_angle"),
        "belief": resolve_best("belief_statement", "key_belief"),
        "hooks": copy_analysis.get("hooks", []) + vision_analysis.get("hooks", []),
        "awareness_level": resolve_best("awareness_level", "awareness_level"),
        "raw_copy": copy_analysis,
        "raw_vision": vision_analysis
    }
    return result



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


def render_time_series_charts(data: List[Dict]):
    """Render time-series charts for key metrics."""
    import pandas as pd

    if not data:
        st.info("No data available for charts.")
        return

    ts_data = aggregate_time_series(data)

    if not ts_data["dates"]:
        st.info("No time-series data available.")
        return

    # Create DataFrame
    df = pd.DataFrame({
        "Date": ts_data["dates"],
        "Spend ($)": ts_data["spend"],
        "ROAS": ts_data["roas"],
        "CTR (%)": ts_data["ctr"],
        "CPC ($)": ts_data["cpc"],
        "Impressions": ts_data["impressions"],
        "Clicks": ts_data["clicks"],
    })

    # Metric selector
    metric_options = ["Spend ($)", "ROAS", "CTR (%)", "CPC ($)", "Impressions", "Clicks"]
    selected_metrics = st.multiselect(
        "Select metrics to display",
        metric_options,
        default=["Spend ($)", "ROAS"],
        key="ts_chart_metrics"
    )

    if not selected_metrics:
        st.info("Select at least one metric to display.")
        return

    # Render charts
    for metric in selected_metrics:
        chart_df = df[["Date", metric]].copy()
        chart_df = chart_df.set_index("Date")

        st.subheader(f"{metric} Over Time")
        st.line_chart(chart_df, height=250)


def render_analysis_result(result: Dict):
    """Render the ad analysis result with 'Create Plan' action."""
    if not result:
        return

    st.success("✅ Analysis Complete! Strategy Extracted.")
    
    angle = result.get("angle", "Unknown Angle")
    belief = result.get("belief", "No belief detected")
    hooks = result.get("hooks", [])
    
    with st.container():
        # styled card
        st.markdown(f"""
        <div style="padding: 20px; border-radius: 10px; background-color: #f0f2f6; border: 1px solid #d0d7de;">
            <h3 style="margin-top:0;">🏹 Detected Angle: {angle}</h3>
            <p style="font-size: 1.1em;"><strong>Core Belief:</strong> <em>"{belief}"</em></p>
        </div>
        """, unsafe_allow_html=True)
        
        st.write("") # Spacer
        
        col_act1, col_act2 = st.columns([1, 2])
        with col_act1:
            if st.button("✨ Create Plan from this Angle", type="primary", use_container_width=True):
                # BRIDGE LOGIC
                st.session_state.injected_angle_data = {
                    "name": angle,
                    "belief": belief,
                    "explanation": f"Extracted from winning ad analysis. Hooks found: {', '.join([h.get('text','') for h in hooks[:3]])}"
                }
                # Redirect
                st.switch_page("pages/25_📋_Ad_Planning.py")
        
        with col_act2:
            st.info("👆 Click to instantly start a 30-ad test campaign based on this winning angle.")
            
    # Check for low quality analysis due to missing text
    if angle in ["Unknown Angle", "None"] or belief in ["No belief detected", "None"]:
        st.warning("⚠️ Analysis yielded limited results. This often happens when analyzing based only on the Ad Name.")
        st.markdown("""
        **Try this instead:**
        1. Copy the actual **Primary Text** from this ad in Ads Manager.
        2. Go to the **🧪 Manual Analysis** tab above.
        3. Paste the text there for a deep analysis.
        """)

    # Use checkbox instead of expander to avoid "nested expander" errors
    # (Since this component is often rendered inside the 'Charts & Analysis' expander)
    if st.checkbox("View Detailed Insights"):
        st.markdown(f"**Awareness Level:** {result.get('awareness_level', 'Unknown')}")
        
        st.markdown("**Identified Hooks:**")
        for hook in hooks:
            st.write(f"- {hook.get('type', 'Hook')}: *{hook.get('text', '')}*")
            
        st.json(result)




def render_top_performers(data: List[Dict]):
    """Render top and worst performers section."""
    import pandas as pd

    if not data:
        return

    # Filter option - default to active only
    include_inactive = st.checkbox(
        "Include inactive ads",
        value=False,
        key="performers_include_inactive",
        help="Show paused/deleted ads in rankings"
    )

    # Filter data to active ads only if checkbox not checked
    if not include_inactive:
        # Get the most recent date in the data to determine "recent" activity
        from datetime import datetime, timedelta
        all_dates = [d.get("date") for d in data if d.get("date")]
        if all_dates:
            max_date = max(all_dates)
            try:
                max_date_dt = datetime.strptime(max_date, "%Y-%m-%d")
                recent_cutoff = (max_date_dt - timedelta(days=3)).strftime("%Y-%m-%d")
            except:
                recent_cutoff = None
        else:
            recent_cutoff = None

        # Filter to ads that are both ACTIVE status AND have recent data
        # This excludes ads in ended campaigns that still show status=ACTIVE
        if recent_cutoff:
            recent_ad_ids = set(
                d.get("meta_ad_id") for d in data
                if d.get("date") and d.get("date") >= recent_cutoff
            )
            filtered_data = [
                d for d in data
                if d.get("ad_status", "").upper() == "ACTIVE"
                and d.get("meta_ad_id") in recent_ad_ids
            ]
        else:
            filtered_data = [d for d in data if d.get("ad_status", "").upper() == "ACTIVE"]

        if not filtered_data:
            st.info("No currently active ads found. Check 'Include inactive ads' to see all ads.")
            return
    else:
        filtered_data = data

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🏆 Top Performers (by ROAS)")
        top_ads = get_top_performers(filtered_data, metric="roas", top_n=5)

        if top_ads:
            for i, ad in enumerate(top_ads, 1):
                roas = ad.get("roas", 0)
                spend = ad.get("spend", 0)
                name = (ad.get("ad_name") or "Unknown")[:40]
                campaign = (ad.get("campaign_name") or "")[:30]
                adset = (ad.get("adset_name") or "")[:25]
                status = ad.get("ad_status", "")
                status_emoji = get_status_emoji(status) if status else ""

                if roas > 0:
                    st.markdown(f"**{i}. {status_emoji} {name}**")
                    st.caption(f"📁 {campaign} › {adset}")
                    st.caption(f"ROAS: **{roas:.2f}x** · Spend: ${spend:,.2f} · Purchases: {ad.get('purchases', 0)}")
        else:
            st.info("No data for top performers")

        # Integrated Analysis Action
        if top_ads:
            st.markdown("---")
            st.caption("Select an ad to analyze its strategy:")
            
            # Create a selection map
            options = {f"{ad.get('ad_name', 'Unknown')} (ROAS: {ad.get('roas', 0):.2f})": ad for ad in top_ads}
            selected_label = st.selectbox("Select Winner", options=list(options.keys()), key="top_perf_select")
            
            if selected_label:
                target_ad = options[selected_label]
                st.write(f"DEBUG: Target Ad Keys: {list(target_ad.keys())}")
                st.write(f"DEBUG: Target Ad Data (Sample): {str(target_ad)[:500]}")
                if st.button(f"🔍 Analyze Strategy: {target_ad.get('ad_name')}"):
                    # In a real scenario, we would stream the creative URL from the ad data.
                    # Since existing data might not have the full creative bytes/url ready for immediate download without token,
                    # We might need to ask user to confirm/provide if missing.
                    # For this implementation, we will assume we scrape/fetch on the fly or just analyze COPY for now if creative missing.
                    
                    with st.spinner("Analyzing ad strategy..."):
                        # Dummy call for MVP integration if URL missing, or use Ad Copy if available
                        # In production this would fetch the actual creative.
                         try:
                             # Try to fetch real body text from DB first
                             meta_ad_id = target_ad.get("meta_ad_id") or target_ad.get("ad_id")
                             body_text = fetch_real_ad_copy(str(meta_ad_id)) if meta_ad_id else None
                             
                             # Fallback to ad name if body text not found
                             final_copy = body_text if body_text else target_ad.get("ad_name", "")
                             
                             # Get Creative URL from ad data (image_url or thumbnail_url)
                             creative_url = target_ad.get("image_url") or target_ad.get("thumbnail_url")
                             
                             # If missing, try to fetch on-the-fly
                             if not creative_url:
                                 st.info("Fetching ad creative from Meta...")
                                 try:
                                     from viraltracker.services.meta_ads_service import MetaAdsService
                                     meta_service = MetaAdsService()
                                     # Assuming we have meta_ad_id
                                     aid = target_ad.get("meta_ad_id")
                                     if aid:
                                         thumbs = asyncio.run(meta_service.fetch_ad_thumbnails([aid]))
                                         creative_url = thumbs.get(aid)
                                         if creative_url:
                                             st.success("Fetched creative URL from Meta")
                                 except Exception as e:
                                     st.warning(f"Could not fetch creative from Meta: {e}")

                             # If not http, assume storage path (unless empty)
                             if creative_url and not creative_url.startswith("http"):
                                 signed = get_signed_url(creative_url)
                                 if signed: 
                                     st.write(f"DEBUG: Signed storage path '{creative_url}' -> '{signed[:20]}...'")
                                     creative_url = signed
                                 else:
                                     st.warning(f"Could not sign URL for path: {creative_url}")
                             
                             st.write(f"DEBUG: Final Analysis URL: {creative_url}") # Debug for user

                             # Try to convert ID to UUID for tracking, otherwise None
                             from uuid import UUID as PyUUID
                             ad_uuid = None
                             try:
                                 if meta_ad_id:
                                     ad_uuid = PyUUID(str(meta_ad_id))
                             except:
                                 pass # Not a UUID (likely a Meta numeric ID)

                             res = asyncio.run(analyze_ad_creative(
                                 ad_copy=final_copy,
                                 headline=target_ad.get("headline", ""),
                                 creative_url=creative_url,
                                 creative_type="image", # Default to image for now unless we detect video
                                 ad_id=ad_uuid
                             ))
                             st.session_state.ad_analysis_result = res
                         except Exception as e:
                             st.error(f"Analysis failed: {e}")

                if st.session_state.ad_analysis_result:
                    render_analysis_result(st.session_state.ad_analysis_result)

    with col2:

        st.subheader("⚠️ Needs Attention (low ROAS)")
        worst_ads = get_worst_performers(filtered_data, metric="roas", bottom_n=5, min_spend=10.0)

        if worst_ads:
            for i, ad in enumerate(worst_ads, 1):
                roas = ad.get("roas", 0)
                spend = ad.get("spend", 0)
                name = (ad.get("ad_name") or "Unknown")[:40]
                campaign = (ad.get("campaign_name") or "")[:30]
                adset = (ad.get("adset_name") or "")[:25]
                status = ad.get("ad_status", "")
                status_emoji = get_status_emoji(status) if status else ""

                st.markdown(f"**{i}. {status_emoji} {name}**")
                st.caption(f"📁 {campaign} › {adset}")
                st.caption(f"ROAS: **{roas:.2f}x** · Spend: ${spend:,.2f} · CTR: {ad.get('ctr', 0):.2f}%")
        else:
            st.info("No underperforming ads (or none with min $10 spend)")


def render_csv_export(data: List[Dict]):
    """Render CSV export button."""
    if not data:
        return

    csv_content = export_to_csv(data)

    if csv_content:
        st.download_button(
            label="📥 Export to CSV",
            data=csv_content,
            file_name=f"meta_ads_performance_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            help="Download performance data as CSV"
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
        
        # Capture creative details (first non-empty value wins or overwrite)
        if d.get("image_url"): a["image_url"] = d.get("image_url")
        if d.get("thumbnail_url"): a["thumbnail_url"] = d.get("thumbnail_url")
        if d.get("headline"): a["headline"] = d.get("headline")
        if d.get("body"): a["body"] = d.get("body")

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
            "image_url": a.get("image_url"),
            "thumbnail_url": a.get("thumbnail_url"),
            "headline": a.get("headline"),
            "body": a.get("body"),
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


def derive_delivery_status(ad_statuses: set) -> str:
    """
    Derive delivery status from a set of ad statuses.

    Returns: 'Active', 'Paused', 'Off', or status if only one type.
    """
    if not ad_statuses:
        return ""

    # Normalize statuses
    normalized = set()
    for s in ad_statuses:
        if s:
            normalized.add(s.upper())

    if not normalized:
        return ""

    # Only "ACTIVE" counts as active - not COMPLETED, WITH_ISSUES, etc.
    if "ACTIVE" in normalized:
        return "Active"

    # If all are PAUSED
    if normalized == {"PAUSED"}:
        return "Paused"

    # Campaign ended statuses
    if "CAMPAIGN_PAUSED" in normalized or "ADSET_PAUSED" in normalized:
        return "Paused"

    # If all are same status
    if len(normalized) == 1:
        status = list(normalized)[0]
        # Map common statuses
        status_map = {
            "COMPLETED": "Completed",
            "WITH_ISSUES": "Issues",
            "IN_PROCESS": "Processing",
            "PENDING_REVIEW": "Pending",
            "DISAPPROVED": "Disapproved",
            "DELETED": "Deleted",
            "ARCHIVED": "Archived",
        }
        return status_map.get(status, status.replace("_", " ").title())

    # Mixed - show most relevant
    for check in ["PENDING_REVIEW", "WITH_ISSUES", "PAUSED", "COMPLETED", "ARCHIVED", "DELETED"]:
        if check in normalized:
            return check.replace("_", " ").title()

    return "Off"


def aggregate_by_campaign(data: List[Dict]) -> List[Dict]:
    """Aggregate performance data by campaign."""
    from collections import defaultdict
    from datetime import datetime, timedelta

    campaigns = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
        "ad_count": 0, "adset_ids": set(), "ad_ids": set(),
        "ad_statuses": set(), "max_date": None
    })

    # Find the global max date to determine "recent"
    all_dates = [d.get("date") for d in data if d.get("date")]
    global_max_date = max(all_dates) if all_dates else None

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
        if d.get("ad_status"):
            c["ad_statuses"].add(d.get("ad_status"))
        # Track most recent date for this campaign
        date = d.get("date")
        if date and (c["max_date"] is None or date > c["max_date"]):
            c["max_date"] = date

    # Calculate recency cutoff (3 days before most recent data)
    recent_cutoff = None
    if global_max_date:
        try:
            max_dt = datetime.strptime(global_max_date, "%Y-%m-%d")
            recent_cutoff = (max_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        except:
            pass

    result = []
    for cid, c in campaigns.items():
        ctr = (c["link_clicks"] / c["impressions"] * 100) if c["impressions"] > 0 else 0
        cpm = (c["spend"] / c["impressions"] * 1000) if c["impressions"] > 0 else 0
        roas = (c["purchase_value"] / c["spend"]) if c["spend"] > 0 else 0

        # Determine delivery - check if campaign has recent activity
        has_recent_activity = (
            recent_cutoff and c["max_date"] and c["max_date"] >= recent_cutoff
        )
        delivery = derive_delivery_status(c["ad_statuses"])

        # If no recent activity but shows as Active, mark as Ended
        if delivery == "Active" and not has_recent_activity:
            delivery = "Ended"

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
            "delivery": delivery,
        })

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def aggregate_by_adset(data: List[Dict]) -> List[Dict]:
    """Aggregate performance data by ad set."""
    from collections import defaultdict
    from datetime import datetime, timedelta

    adsets = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
        "ad_ids": set(), "ad_statuses": set(), "max_date": None
    })

    # Find the global max date to determine "recent"
    all_dates = [d.get("date") for d in data if d.get("date")]
    global_max_date = max(all_dates) if all_dates else None

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
        if d.get("ad_status"):
            a["ad_statuses"].add(d.get("ad_status"))
        # Track most recent date for this adset
        date = d.get("date")
        if date and (a["max_date"] is None or date > a["max_date"]):
            a["max_date"] = date

    # Calculate recency cutoff (3 days before most recent data)
    recent_cutoff = None
    if global_max_date:
        try:
            max_dt = datetime.strptime(global_max_date, "%Y-%m-%d")
            recent_cutoff = (max_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        except:
            pass

    result = []
    for asid, a in adsets.items():
        ctr = (a["link_clicks"] / a["impressions"] * 100) if a["impressions"] > 0 else 0
        cpm = (a["spend"] / a["impressions"] * 1000) if a["impressions"] > 0 else 0
        roas = (a["purchase_value"] / a["spend"]) if a["spend"] > 0 else 0

        # Determine delivery - check if adset has recent activity
        has_recent_activity = (
            recent_cutoff and a["max_date"] and a["max_date"] >= recent_cutoff
        )
        delivery = derive_delivery_status(a["ad_statuses"])

        # If no recent activity but shows as Active, mark as Ended
        if delivery == "Active" and not has_recent_activity:
            delivery = "Ended"

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
            "delivery": delivery,
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


def render_filter_bar():
    """Render filter bar showing active filters with clear buttons."""
    selected_campaign = st.session_state.ad_perf_selected_campaign
    selected_adset = st.session_state.ad_perf_selected_adset

    if not selected_campaign and not selected_adset:
        return

    cols = st.columns([6, 1])
    with cols[0]:
        filters = []
        if selected_campaign:
            filters.append(f"Campaign: **{selected_campaign[1]}**")
        if selected_adset:
            filters.append(f"Ad Set: **{selected_adset[1]}**")
        st.markdown("Filtered by: " + " → ".join(filters))

    with cols[1]:
        if st.button("✕ Clear Filters", use_container_width=True):
            st.session_state.ad_perf_selected_campaign = None
            st.session_state.ad_perf_selected_adset = None
            st.rerun()


def render_campaigns_table_fb(data: List[Dict]):
    """Render campaigns table with clickable names using AG Grid."""
    import pandas as pd
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
        use_aggrid = True
    except ImportError:
        use_aggrid = False

    campaigns = aggregate_by_campaign(data)

    if not campaigns:
        st.info("No campaign data available.")
        return

    # Build dataframe with IDs
    rows = []
    for c in campaigns:
        delivery = c.get("delivery", "")
        # Add emoji to delivery text
        if delivery == "Active":
            delivery_display = "🟢 Active"
        elif delivery == "Paused":
            delivery_display = "⚪ Paused"
        elif delivery == "Ended":
            delivery_display = "⏹️ Ended"
        elif delivery == "Completed":
            delivery_display = "✅ Completed"
        elif delivery in ["Pending", "Pending Review"]:
            delivery_display = "🟡 Pending"
        elif delivery:
            delivery_display = f"⚪ {delivery}"
        else:
            delivery_display = ""

        rows.append({
            "id": c["meta_campaign_id"],
            "Campaign": (c["campaign_name"] or "Unknown")[:45],
            "Delivery": delivery_display,
            "Spend": c["spend"],
            "Impr": c["impressions"],
            "CPM": c["cpm"],
            "Clicks": c["link_clicks"],
            "CTR": c["ctr"],
            "ATC": c["add_to_carts"],
            "Purch": c["purchases"],
            "ROAS": c["roas"],
            "Sets": c["adset_count"],
        })

    df = pd.DataFrame(rows)

    if use_aggrid:
        # Configure AG Grid
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_column("id", hide=True)
        gb.configure_column("Campaign",
            cellStyle={'color': '#1a73e8', 'cursor': 'pointer', 'textDecoration': 'underline'},
            width=220
        )
        gb.configure_column("Delivery", width=110)
        gb.configure_column("Spend", valueFormatter="'$' + value.toLocaleString(undefined, {minimumFractionDigits: 2})", width=100)
        gb.configure_column("Impr", valueFormatter="value.toLocaleString()", width=90)
        gb.configure_column("CPM", valueFormatter="'$' + value.toFixed(2)", width=70)
        gb.configure_column("Clicks", valueFormatter="value.toLocaleString()", width=70)
        gb.configure_column("CTR", valueFormatter="value.toFixed(2) + '%'", width=60)
        gb.configure_column("ROAS", valueFormatter="value > 0 ? value.toFixed(2) + 'x' : '-'", width=60)
        gb.configure_selection(selection_mode="single", use_checkbox=False)
        gb.configure_grid_options(domLayout='autoHeight')

        grid_options = gb.build()

        # Display grid
        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            theme="streamlit",
            key="campaigns_grid",
            allow_unsafe_jscode=True
        )

        # Handle row selection
        selected_rows = grid_response.get("selected_rows", None)
        if selected_rows is not None and len(selected_rows) > 0:
            selected_row = selected_rows.iloc[0] if hasattr(selected_rows, 'iloc') else selected_rows[0]
            campaign_id = selected_row.get("id") or selected_row.get("_selectedRowNodeInfo", {}).get("nodeRowIndex")
            campaign_name = selected_row.get("Campaign", "Unknown")
            if campaign_id:
                st.session_state.ad_perf_selected_campaign = (str(campaign_id), campaign_name)
                st.session_state.ad_perf_selected_adset = None
                st.session_state.ad_perf_active_tab = 1
                st.rerun()
    else:
        # Fallback to regular dataframe
        display_df = df.drop(columns=["id"]).copy()
        display_df["Spend"] = display_df["Spend"].apply(lambda x: f"${x:,.2f}")
        display_df["Impr"] = display_df["Impr"].apply(lambda x: f"{x:,}")
        display_df["CPM"] = display_df["CPM"].apply(lambda x: f"${x:.2f}")
        display_df["CTR"] = display_df["CTR"].apply(lambda x: f"{x:.2f}%")
        display_df["ROAS"] = display_df["ROAS"].apply(lambda x: f"{x:.2f}x" if x > 0 else "-")
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.info("Install `streamlit-aggrid` for clickable campaign names")

    # Totals
    total_spend = sum(c["spend"] for c in campaigns)
    total_impr = sum(c["impressions"] for c in campaigns)
    total_clicks = sum(c["link_clicks"] for c in campaigns)
    total_atc = sum(c["add_to_carts"] for c in campaigns)
    total_purch = sum(c["purchases"] for c in campaigns)
    total_ctr = (total_clicks / total_impr * 100) if total_impr > 0 else 0

    st.markdown(f"""
    **Totals ({len(campaigns)}):** Spend **${total_spend:,.2f}** · Impr **{total_impr:,}** ·
    Clicks **{total_clicks:,}** · CTR **{total_ctr:.1f}%** · ATC **{total_atc:,}** · Purchases **{total_purch:,}**
    """)


def render_adsets_table_fb(data: List[Dict]):
    """Render ad sets table with clickable names using AG Grid."""
    import pandas as pd
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
        use_aggrid = True
    except ImportError:
        use_aggrid = False

    # Apply campaign filter if set
    selected_campaign = st.session_state.ad_perf_selected_campaign
    if selected_campaign:
        data = [d for d in data if d.get("meta_campaign_id") == selected_campaign[0]]

    adsets = aggregate_by_adset(data)

    if not adsets:
        st.info("No ad set data available." + (" Try clearing filters." if selected_campaign else ""))
        return

    # Build dataframe with IDs
    rows = []
    for a in adsets:
        delivery = a.get("delivery", "")
        # Add emoji to delivery text
        if delivery == "Active":
            delivery_display = "🟢 Active"
        elif delivery == "Paused":
            delivery_display = "⚪ Paused"
        elif delivery == "Ended":
            delivery_display = "⏹️ Ended"
        elif delivery == "Completed":
            delivery_display = "✅ Completed"
        elif delivery in ["Pending", "Pending Review"]:
            delivery_display = "🟡 Pending"
        elif delivery:
            delivery_display = f"⚪ {delivery}"
        else:
            delivery_display = ""

        rows.append({
            "id": a["meta_adset_id"],
            "Ad Set": (a["adset_name"] or "Unknown")[:40],
            "Delivery": delivery_display,
            "Campaign": (a["campaign_name"] or "")[:25],
            "Spend": a["spend"],
            "Impr": a["impressions"],
            "CPM": a["cpm"],
            "Clicks": a["link_clicks"],
            "CTR": a["ctr"],
            "ATC": a["add_to_carts"],
            "Purch": a["purchases"],
            "ROAS": a["roas"],
            "Ads": a["ad_count"],
        })

    df = pd.DataFrame(rows)

    if use_aggrid:
        # Configure AG Grid
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_column("id", hide=True)
        gb.configure_column("Ad Set",
            cellStyle={'color': '#1a73e8', 'cursor': 'pointer', 'textDecoration': 'underline'},
            width=200
        )
        gb.configure_column("Delivery", width=110)
        gb.configure_column("Campaign", width=130)
        gb.configure_column("Spend", valueFormatter="'$' + value.toLocaleString(undefined, {minimumFractionDigits: 2})", width=90)
        gb.configure_column("Impr", valueFormatter="value.toLocaleString()", width=80)
        gb.configure_column("CPM", valueFormatter="'$' + value.toFixed(2)", width=60)
        gb.configure_column("Clicks", valueFormatter="value.toLocaleString()", width=60)
        gb.configure_column("CTR", valueFormatter="value.toFixed(2) + '%'", width=55)
        gb.configure_column("ROAS", valueFormatter="value > 0 ? value.toFixed(2) + 'x' : '-'", width=55)
        gb.configure_selection(selection_mode="single", use_checkbox=False)
        gb.configure_grid_options(domLayout='autoHeight')

        grid_options = gb.build()

        # Display grid
        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            theme="streamlit",
            key="adsets_grid",
            allow_unsafe_jscode=True
        )

        # Handle row selection
        selected_rows = grid_response.get("selected_rows", None)
        if selected_rows is not None and len(selected_rows) > 0:
            selected_row = selected_rows.iloc[0] if hasattr(selected_rows, 'iloc') else selected_rows[0]
            adset_id = selected_row.get("id")
            adset_name = selected_row.get("Ad Set", "Unknown")
            if adset_id:
                st.session_state.ad_perf_selected_adset = (str(adset_id), adset_name)
                st.session_state.ad_perf_active_tab = 2
                st.rerun()
    else:
        # Fallback to regular dataframe
        display_df = df.drop(columns=["id"]).copy()
        display_df["Spend"] = display_df["Spend"].apply(lambda x: f"${x:,.2f}")
        display_df["Impr"] = display_df["Impr"].apply(lambda x: f"{x:,}")
        display_df["CPM"] = display_df["CPM"].apply(lambda x: f"${x:.2f}")
        display_df["CTR"] = display_df["CTR"].apply(lambda x: f"{x:.2f}%")
        display_df["ROAS"] = display_df["ROAS"].apply(lambda x: f"{x:.2f}x" if x > 0 else "-")
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.info("Install `streamlit-aggrid` for clickable ad set names")

    # Totals
    total_spend = sum(a["spend"] for a in adsets)
    total_impr = sum(a["impressions"] for a in adsets)
    total_clicks = sum(a["link_clicks"] for a in adsets)
    total_atc = sum(a["add_to_carts"] for a in adsets)
    total_purch = sum(a["purchases"] for a in adsets)
    total_ctr = (total_clicks / total_impr * 100) if total_impr > 0 else 0

    st.markdown(f"""
    **Totals ({len(adsets)}):** Spend **${total_spend:,.2f}** · Impr **{total_impr:,}** ·
    Clicks **{total_clicks:,}** · CTR **{total_ctr:.1f}%** · ATC **{total_atc:,}** · Purchases **{total_purch:,}**
    """)


def render_ads_table_fb(data: List[Dict]):
    """Render ads table Facebook-style with totals."""
    import pandas as pd

    # Apply filters
    selected_campaign = st.session_state.ad_perf_selected_campaign
    selected_adset = st.session_state.ad_perf_selected_adset

    if selected_campaign:
        data = [d for d in data if d.get("meta_campaign_id") == selected_campaign[0]]
    if selected_adset:
        data = [d for d in data if d.get("meta_adset_id") == selected_adset[0]]

    if not data:
        st.info("No ad data available." + (" Try clearing filters." if selected_campaign or selected_adset else ""))
        return

    # Aggregate by ad
    ads = aggregate_by_ad(data)

    # Build dataframe
    rows = []
    for a in ads:
        status = a.get("ad_status", "")
        status_display = f"{get_status_emoji(status)} {status}" if status else "-"
        rows.append({
            "Status": status_display,
            "Ad Name": (a["ad_name"] or "Unknown")[:45],
            "Ad Set": (a.get("adset_name") or "")[:20],
            "Spend": a["spend"],
            "Impressions": a["impressions"],
            "CPM": a["cpm"],
            "Clicks": a["link_clicks"],
            "CTR %": a["ctr"],
            "CPC": a["cpc"],
            "ATC": a["add_to_carts"],
            "Purchases": a["purchases"],
            "ROAS": a["roas"],
        })

    df = pd.DataFrame(rows)

    # Calculate totals
    total_spend = df["Spend"].sum()
    total_impr = df["Impressions"].sum()
    total_clicks = df["Clicks"].sum()
    totals = {
        "Spend": total_spend,
        "Impressions": total_impr,
        "Clicks": total_clicks,
        "CTR %": (total_clicks / total_impr * 100) if total_impr > 0 else 0,
        "ATC": df["ATC"].sum(),
        "Purchases": df["Purchases"].sum(),
    }

    # Format for display
    display_df = df.copy()
    display_df["Spend"] = display_df["Spend"].apply(lambda x: f"${x:,.2f}")
    display_df["Impressions"] = display_df["Impressions"].apply(lambda x: f"{x:,}")
    display_df["CPM"] = display_df["CPM"].apply(lambda x: f"${x:.2f}")
    display_df["CTR %"] = display_df["CTR %"].apply(lambda x: f"{x:.2f}%")
    display_df["CPC"] = display_df["CPC"].apply(lambda x: f"${x:.2f}")
    display_df["ROAS"] = display_df["ROAS"].apply(lambda x: f"{x:.2f}x" if x > 0 else "-")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Totals row
    st.markdown(f"""
    **Totals ({len(ads)} ads):** Spend: **${totals['Spend']:,.2f}** · Impressions: **{totals['Impressions']:,}** ·
    Clicks: **{totals['Clicks']:,}** · CTR: **{totals['CTR %']:.2f}%** ·
    ATC: **{totals['ATC']:,}** · Purchases: **{totals['Purchases']:,}**
    """)


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

    # Scheduling section
    render_sync_scheduling(brand_id)


def render_sync_scheduling(brand_id: str):
    """Render the automated sync scheduling UI."""
    import pytz

    st.divider()
    st.markdown("**⏰ Automated Sync Schedule**")

    db = get_supabase_client()

    # Check for existing meta_sync job for this brand
    existing_job = None
    try:
        result = db.table("scheduled_jobs").select("*").eq(
            "brand_id", brand_id
        ).eq("job_type", "meta_sync").eq("status", "active").limit(1).execute()
        existing_job = result.data[0] if result.data else None
    except Exception:
        pass

    if existing_job:
        # Show existing schedule
        st.info(f"**Active Schedule:** {existing_job['name']}")
        params = existing_job.get('parameters', {})
        cron = existing_job.get('cron_expression', '')

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.caption(f"Syncs last **{params.get('days_back', 7)} days** of data")
        with col2:
            if cron:
                # Parse cron to display time
                parts = cron.split()
                if len(parts) >= 2:
                    hour = int(parts[1])
                    st.caption(f"Runs daily at **{hour}:00 PST**")
        with col3:
            if st.button("🗑️ Remove", key="remove_sync_schedule"):
                try:
                    db.table("scheduled_jobs").update({
                        "status": "completed"
                    }).eq("id", existing_job['id']).execute()
                    st.success("Schedule removed!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

        # Show last run info
        try:
            runs = db.table("scheduled_job_runs").select(
                "status, started_at, completed_at, logs"
            ).eq("scheduled_job_id", existing_job['id']).order(
                "started_at", desc=True
            ).limit(1).execute()

            if runs.data:
                last_run = runs.data[0]
                status_emoji = "✅" if last_run['status'] == 'completed' else "❌"
                st.caption(f"Last run: {status_emoji} {last_run['status']} at {last_run.get('started_at', 'N/A')[:16]}")
        except Exception:
            pass

    else:
        # Create new schedule form
        st.markdown("Set up automatic daily sync of your Meta Ads performance data.")

        col1, col2 = st.columns(2)

        with col1:
            sync_hour = st.selectbox(
                "Run at (PST)",
                options=list(range(24)),
                index=6,  # Default 6 AM
                format_func=lambda x: f"{x}:00 {'AM' if x < 12 else 'PM'}" if x != 12 else "12:00 PM",
                key="sync_schedule_hour"
            )

        with col2:
            days_back = st.selectbox(
                "Days to sync",
                options=[3, 7, 14, 30],
                index=1,  # Default 7 days
                key="sync_days_back"
            )

        if st.button("📅 Enable Daily Sync", type="primary"):
            try:
                PST = pytz.timezone('America/Los_Angeles')
                now = datetime.now(PST)

                # Calculate next run time
                next_run = now.replace(hour=sync_hour, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run = next_run + timedelta(days=1)

                # Create cron expression (minute hour * * *)
                cron_expr = f"0 {sync_hour} * * *"

                # Insert job
                db.table("scheduled_jobs").insert({
                    "brand_id": brand_id,
                    "product_id": None,  # Not needed for meta_sync
                    "name": "Daily Meta Ads Sync",
                    "job_type": "meta_sync",
                    "schedule_type": "recurring",
                    "cron_expression": cron_expr,
                    "next_run_at": next_run.isoformat(),
                    "template_mode": None,  # Not needed for meta_sync
                    "parameters": {
                        "days_back": days_back
                    }
                }).execute()

                st.success(f"Daily sync scheduled for {sync_hour}:00 PST!")
                st.rerun()

            except Exception as e:
                st.error(f"Failed to create schedule: {e}")


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
# Linking UI Components
# =============================================================================

def render_match_suggestions(suggestions: List[Dict], ad_account_id: str):
    """Render auto-match suggestions with thumbnails and confirm/reject buttons."""
    if not suggestions:
        st.info("No matches found. Try naming your Meta ads with the 8-character ID from the filename.")
        return

    st.subheader(f"🔍 Found {len(suggestions)} Potential Matches")
    st.caption("Compare Meta ad thumbnail with generated ad to verify the match")

    for i, match in enumerate(suggestions):
        meta_ad = match.get("meta_ad", {})
        suggested = match.get("suggested_match")
        matched_id = match.get("matched_id", "")
        confidence = match.get("confidence", "low")

        with st.container():
            # Layout: [Meta Ad Thumbnail + Info] [Arrow] [Generated Ad Thumbnail] [Actions]
            cols = st.columns([2.5, 0.5, 2.5, 1.5])

            with cols[0]:
                st.markdown("**Meta Ad**")
                # Show Meta ad thumbnail if available
                meta_thumbnail = meta_ad.get("thumbnail_url")
                if meta_thumbnail:
                    st.image(meta_thumbnail, width=120)
                else:
                    # Show why thumbnail is missing
                    meta_ad_id = meta_ad.get("meta_ad_id", "unknown")
                    st.caption(f"📷 No thumbnail")
                    st.caption(f"Ad ID: `{meta_ad_id[:15]}...`")
                st.caption(f"`{meta_ad.get('ad_name', 'Unknown')[:40]}`")
                st.caption(f"Matched ID: `{matched_id}`")

            with cols[1]:
                st.markdown("")
                st.markdown("")
                st.markdown("**↔**")

            with cols[2]:
                st.markdown("**Generated Ad**")
                if suggested:
                    # Show generated ad thumbnail
                    storage_path = suggested.get("storage_path")
                    if storage_path:
                        signed_url = get_signed_url(storage_path)
                        if signed_url:
                            st.image(signed_url, width=120)
                        else:
                            st.caption("📷 (unavailable)")
                    st.caption(f"ID: `{suggested['id'][:8]}...`")
                    hook = suggested.get("hook_text", "")
                    if hook:
                        st.caption(f"{hook[:35]}...")
                else:
                    st.warning("No match found")
                    st.caption("ID detected but no generated ad")

            with cols[3]:
                st.markdown("")
                if confidence == "high":
                    st.success("✓ High")
                else:
                    st.warning("? Low")

                if suggested:
                    if st.button("✓ Link", key=f"confirm_match_{i}", type="primary", use_container_width=True):
                        success = create_ad_link(
                            generated_ad_id=suggested["id"],
                            meta_ad_id=meta_ad.get("meta_ad_id"),
                            meta_campaign_id=meta_ad.get("meta_campaign_id", ""),
                            meta_ad_account_id=ad_account_id,
                            linked_by="auto_filename"
                        )
                        if success:
                            # Remove this suggestion from the list
                            if st.session_state.ad_perf_match_suggestions:
                                st.session_state.ad_perf_match_suggestions = [
                                    s for s in st.session_state.ad_perf_match_suggestions
                                    if s.get("meta_ad", {}).get("meta_ad_id") != meta_ad.get("meta_ad_id")
                                ]
                            st.success("Linked!")
                            st.rerun()
                    if st.button("✗ Skip", key=f"skip_match_{i}", use_container_width=True):
                        # Remove from suggestions without linking
                        if st.session_state.ad_perf_match_suggestions:
                            st.session_state.ad_perf_match_suggestions = [
                                s for s in st.session_state.ad_perf_match_suggestions
                                if s.get("meta_ad", {}).get("meta_ad_id") != meta_ad.get("meta_ad_id")
                            ]
                        st.rerun()

            st.divider()


def render_manual_link_modal(meta_ad: Dict, brand_id: str, ad_account_id: str):
    """Render modal for manually linking a Meta ad to a generated ad."""
    st.subheader("🔗 Link to Generated Ad")

    st.markdown(f"**Meta Ad:** {meta_ad.get('ad_name', 'Unknown')}")
    st.caption(f"Campaign: {meta_ad.get('campaign_name', 'Unknown')}")

    # Get generated ads for this brand
    generated_ads = get_generated_ads_for_linking(brand_id)

    if not generated_ads:
        st.warning("No approved generated ads found for this brand.")
        if st.button("Cancel"):
            st.session_state.ad_perf_linking_ad = None
            st.rerun()
        return

    # Create options for selectbox
    options = ["-- Select a generated ad --"]
    for ad in generated_ads:
        label = f"{ad['id'][:8]}... | {ad['product_name']} | {ad['hook_text']}"
        options.append(label)

    selected = st.selectbox(
        "Choose generated ad to link",
        options,
        key="manual_link_select"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Cancel", use_container_width=True):
            st.session_state.ad_perf_linking_ad = None
            st.rerun()

    with col2:
        link_disabled = selected == options[0]
        if st.button("🔗 Create Link", type="primary", use_container_width=True, disabled=link_disabled):
            # Find the selected ad
            selected_idx = options.index(selected) - 1  # -1 for the placeholder
            selected_ad = generated_ads[selected_idx]

            success = create_ad_link(
                generated_ad_id=selected_ad["id"],
                meta_ad_id=meta_ad.get("meta_ad_id"),
                meta_campaign_id=meta_ad.get("meta_campaign_id", ""),
                meta_ad_account_id=ad_account_id,
                linked_by="manual"
            )
            if success:
                st.success("✓ Ad linked successfully!")
                st.session_state.ad_perf_linking_ad = None
                st.rerun()


def render_linked_ads_table(perf_data: List[Dict], linked_ads: List[Dict]):
    """Render the Linked ads tab with performance data."""
    import pandas as pd

    if not linked_ads:
        st.info("No ads linked yet.")
        st.markdown("""
        **How to link ads:**
        1. **Auto-match**: Click "Find Matches" to scan Meta ad names for IDs
        2. **Manual**: Click the 🔗 button on any ad in the Ads tab
        """)
        return

    # Build a map of meta_ad_id -> generated_ad info
    link_map = {}
    for link in linked_ads:
        meta_id = link.get("meta_ad_id")
        gen_ad = link.get("generated_ads") or {}
        link_map[meta_id] = {
            "generated_ad_id": gen_ad.get("id", "")[:8] if gen_ad.get("id") else "",
            "hook_text": gen_ad.get("hook_text", "")[:30],
            "linked_by": link.get("linked_by", "manual"),
        }

    # Filter performance data to linked ads only
    linked_meta_ids = set(link_map.keys())
    linked_perf = [d for d in perf_data if d.get("meta_ad_id") in linked_meta_ids]

    if not linked_perf:
        st.warning("Linked ads found but no performance data in selected date range.")
        st.caption(f"{len(linked_ads)} ads are linked. Sync data to see their performance.")
        return

    # Aggregate by ad
    ads = aggregate_by_ad(linked_perf)

    # Build table with link info
    rows = []
    for a in ads:
        meta_id = a.get("meta_ad_id", "")
        link_info = link_map.get(meta_id, {})
        link_type = "🤖" if link_info.get("linked_by") == "auto_filename" else "👤"

        rows.append({
            "Link": link_type,
            "Generated ID": link_info.get("generated_ad_id", "-"),
            "Meta Ad": (a["ad_name"] or "Unknown")[:35],
            "Spend": f"${a['spend']:,.2f}",
            "Impr": f"{a['impressions']:,}",
            "Clicks": a["link_clicks"],
            "CTR": f"{a['ctr']:.2f}%",
            "Purchases": a["purchases"],
            "ROAS": f"{a['roas']:.2f}x" if a["roas"] else "-",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Summary
    total_spend = sum(a["spend"] for a in ads)
    total_purchases = sum(a["purchases"] for a in ads)
    st.markdown(f"**{len(ads)} linked ads** · Spend: **${total_spend:,.2f}** · Purchases: **{total_purchases:,}**")


def render_ads_table_with_linking(data: List[Dict], brand_id: str, ad_account_id: str):
    """Render ads table with link/unlink buttons."""
    import pandas as pd

    # Apply filters
    selected_campaign = st.session_state.ad_perf_selected_campaign
    selected_adset = st.session_state.ad_perf_selected_adset

    if selected_campaign:
        data = [d for d in data if d.get("meta_campaign_id") == selected_campaign[0]]
    if selected_adset:
        data = [d for d in data if d.get("meta_adset_id") == selected_adset[0]]

    if not data:
        st.info("No ad data available." + (" Try clearing filters." if selected_campaign or selected_adset else ""))
        return

    # Get linked ad IDs
    linked_ids = get_linked_meta_ad_ids()

    # Aggregate by ad
    ads = aggregate_by_ad(data)

    # Sort: Active ads first when no filter applied, then by spend
    if not selected_campaign and not selected_adset:
        # Active first, then by spend
        ads = sorted(ads, key=lambda x: (
            0 if x.get("ad_status", "").upper() == "ACTIVE" else 1,
            -x.get("spend", 0)
        ))

    # Header row
    header_cols = st.columns([0.5, 2.5, 1, 1, 1, 1, 1, 1, 1, 1])
    with header_cols[0]:
        st.caption("🔗")
    with header_cols[1]:
        st.caption("**Ad**")
    with header_cols[2]:
        st.caption("**Delivery**")
    with header_cols[3]:
        st.caption("**Spend**")
    with header_cols[4]:
        st.caption("**Impr**")
    with header_cols[5]:
        st.caption("**CTR**")
    with header_cols[6]:
        st.caption("**CPC**")
    with header_cols[7]:
        st.caption("**ATC**")
    with header_cols[8]:
        st.caption("**Purch**")
    with header_cols[9]:
        st.caption("**ROAS**")

    # Display ads with link status
    for i, a in enumerate(ads):
        meta_id = a.get("meta_ad_id", "")
        is_linked = meta_id in linked_ids
        status = a.get("ad_status", "")

        # Delivery display with color
        if status:
            status_upper = status.upper()
            if status_upper == "ACTIVE":
                delivery_html = "<span style='color:#28a745'>● Active</span>"
            elif status_upper == "PAUSED":
                delivery_html = "<span style='color:#6c757d'>● Paused</span>"
            elif status_upper == "PENDING_REVIEW":
                delivery_html = "<span style='color:#ffc107'>● Pending</span>"
            else:
                delivery_html = f"<span style='color:#6c757d'>● {status.title()}</span>"
        else:
            delivery_html = ""

        cols = st.columns([0.5, 2.5, 1, 1, 1, 1, 1, 1, 1, 1])

        with cols[0]:
            if is_linked:
                if st.button("🔗", key=f"unlink_{i}", help="Click to unlink"):
                    if delete_ad_link(meta_id):
                        st.rerun()
            else:
                if st.button("○", key=f"link_{i}", help="Click to link"):
                    st.session_state.ad_perf_linking_ad = {
                        "meta_ad_id": meta_id,
                        "ad_name": a.get("ad_name", "Unknown"),
                        "campaign_name": a.get("campaign_name", ""),
                        "meta_campaign_id": a.get("meta_campaign_id", ""),
                    }
                    st.rerun()

        with cols[1]:
            st.markdown(f"**{(a['ad_name'] or 'Unknown')[:35]}**")

        with cols[2]:
            st.markdown(delivery_html, unsafe_allow_html=True)

        with cols[3]:
            st.caption(f"${a['spend']:,.0f}")

        with cols[4]:
            st.caption(f"{a['impressions']:,}")

        with cols[5]:
            st.caption(f"{a['ctr']:.1f}%")

        with cols[6]:
            st.caption(f"${a['cpc']:.2f}")

        with cols[7]:
            st.caption(f"{a['add_to_carts']}")

        with cols[8]:
            st.caption(f"{a['purchases']}")

        with cols[9]:
            st.caption(f"{a['roas']:.1f}x" if a['roas'] else "-")

    # Totals
    total_spend = sum(a["spend"] for a in ads)
    total_impr = sum(a["impressions"] for a in ads)
    total_clicks = sum(a["link_clicks"] for a in ads)
    active_count = sum(1 for a in ads if a.get("ad_status", "").upper() == "ACTIVE")
    st.markdown(f"**{len(ads)} ads** ({active_count} active) · Spend: **${total_spend:,.2f}** · Impr: **{total_impr:,}** · Clicks: **{total_clicks:,}**")


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

# Export button below metrics
render_csv_export(perf_data)

st.divider()

# Enhanced Views - Charts and Analysis (collapsible)
with st.expander("📊 Charts & Analysis", expanded=False):
    # Tabs for different views
    chart_tab, performers_tab = st.tabs(["📈 Time Series", "🏆 Top/Bottom Performers"])

    with chart_tab:
        render_time_series_charts(perf_data)

    with performers_tab:
        render_top_performers(perf_data)

st.divider()

# Hierarchy count display
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"📁 {metrics.get('campaign_count', 0)} Campaigns")
with col2:
    st.caption(f"📂 {metrics.get('adset_count', 0)} Ad Sets")
with col3:
    st.caption(f"📄 {metrics.get('ad_count', 0)} Ads")

# Filter bar (shows active filters)
render_filter_bar()

# Tab selection (controllable via session state)
tab_options = ["📁 Campaigns", "📂 Ad Sets", "📄 Ads", "🔗 Linked"]
active_tab = st.session_state.ad_perf_active_tab

selected_tab = st.radio(
    "View",
    tab_options,
    index=active_tab,
    horizontal=True,
    key="ad_perf_tab_radio",
    label_visibility="collapsed"
)

# Update session state if user clicked a different tab
new_tab_index = tab_options.index(selected_tab)
if new_tab_index != st.session_state.ad_perf_active_tab:
    st.session_state.ad_perf_active_tab = new_tab_index

st.divider()

# Check if manual linking modal should be shown
if st.session_state.ad_perf_linking_ad:
    render_manual_link_modal(
        st.session_state.ad_perf_linking_ad,
        brand_id,
        ad_account['meta_ad_account_id']
    )
    st.stop()

# Check if match suggestions should be shown
if st.session_state.ad_perf_match_suggestions is not None:
    render_match_suggestions(
        st.session_state.ad_perf_match_suggestions,
        ad_account['meta_ad_account_id']
    )
    if st.button("← Back to Ads"):
        st.session_state.ad_perf_match_suggestions = None
        st.rerun()
    st.stop()

# Render content based on selected tab
if selected_tab == "📁 Campaigns":
    render_campaigns_table_fb(perf_data)

elif selected_tab == "📂 Ad Sets":
    render_adsets_table_fb(perf_data)

elif selected_tab == "📄 Ads":
    # Add header row
    st.caption("○ = Unlinked · 🔗 = Linked (click to change)")
    cols = st.columns([0.5, 3, 1, 1, 1, 1, 1, 1, 1])
    with cols[0]:
        st.caption("")
    with cols[1]:
        st.caption("**Ad Name**")
    with cols[2]:
        st.caption("**Spend**")
    with cols[3]:
        st.caption("**Impr**")
    with cols[4]:
        st.caption("**CTR**")
    with cols[5]:
        st.caption("**CPC**")
    with cols[6]:
        st.caption("**ATC**")
    with cols[7]:
        st.caption("**Purch**")
    with cols[8]:
        st.caption("**ROAS**")

    render_ads_table_with_linking(perf_data, brand_id, ad_account['meta_ad_account_id'])

elif selected_tab == "🔗 Linked":
    st.subheader("Linked Ads (ViralTracker ↔ Meta)")

    # Find Matches button

    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        if st.button("🔍 Find Matches", type="primary", use_container_width=True):
            with st.spinner("Fetching thumbnails and scanning for matches..."):
                try:
                    # Fetch ALL missing thumbnails (loop until no more updated)
                    total_thumbs = 0
                    max_iterations = 20  # Safety limit
                    for _ in range(max_iterations):
                        batch_count = asyncio.run(fetch_missing_thumbnails(brand_id))
                        total_thumbs += batch_count
                        if batch_count == 0:  # No more to fetch
                            break
                    # Store result for display
                    st.session_state.ad_perf_last_thumb_count = total_thumbs
                    # Then find matches
                    matches = asyncio.run(find_auto_matches(brand_id))
                    st.session_state.ad_perf_match_suggestions = matches
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to find matches: {e}")

    with col2:
        if st.button("🔧 Debug Thumbnails", use_container_width=True):
            st.session_state.ad_perf_debug_thumbs = True
            st.rerun()

    with col3:
        # Show last fetch result
        if "ad_perf_last_thumb_count" in st.session_state:
            st.caption(f"Last fetch: {st.session_state.ad_perf_last_thumb_count} thumbnails")

    # Debug panel
    if st.session_state.get("ad_perf_debug_thumbs"):
        st.markdown("### 🔧 Thumbnail Debug")
        with st.spinner("Checking thumbnail status..."):
            try:
                db = get_supabase_client()
                # Count ads by thumbnail status
                all_ads = db.table("meta_ads_performance").select(
                    "meta_ad_id, thumbnail_url, ad_name"
                ).eq("brand_id", brand_id).execute()

                total = len(all_ads.data) if all_ads.data else 0
                with_thumb = sum(1 for a in (all_ads.data or []) if a.get("thumbnail_url"))
                without_thumb = total - with_thumb

                st.write(f"**Total ads:** {total}")
                st.write(f"**With thumbnail:** {with_thumb}")
                st.write(f"**Without thumbnail:** {without_thumb}")

                if without_thumb > 0:
                    st.markdown("**Sample ads missing thumbnails:**")
                    missing = [a for a in (all_ads.data or []) if not a.get("thumbnail_url")][:5]
                    for a in missing:
                        st.code(f"ID: {a.get('meta_ad_id')}\nName: {a.get('ad_name', 'Unknown')[:50]}")

                # Test single ad fetch
                st.markdown("---")
                st.markdown("**Test single ad thumbnail fetch:**")
                test_ad_id = st.text_input("Enter Meta Ad ID to test:", value="120235403371890742")

                col_test1, col_test2 = st.columns(2)
                with col_test1:
                    if st.button("🧪 Test Fetch from Meta"):
                        with st.spinner("Fetching from Meta API..."):
                            try:
                                from facebook_business.api import FacebookAdsApi
                                from facebook_business.adobjects.ad import Ad
                                from facebook_business.adobjects.adcreative import AdCreative
                                from viraltracker.core.config import Config

                                # Initialize API
                                FacebookAdsApi.init(access_token=Config.META_GRAPH_API_TOKEN)

                                st.write(f"**Step 1:** Fetching ad {test_ad_id}...")
                                ad = Ad(test_ad_id)
                                ad_data = ad.api_get(fields=["id", "name", "creative", "status"])
                                st.json(dict(ad_data))

                                creative_data = ad_data.get("creative")
                                if creative_data:
                                    creative_id = creative_data.get("id")
                                    st.write(f"**Step 2:** Fetching creative {creative_id}...")
                                    creative = AdCreative(creative_id)
                                    creative_info = creative.api_get(fields=[
                                        "id", "name", "thumbnail_url", "image_url",
                                        "image_hash", "video_id", "object_type",
                                        "object_story_spec"
                                    ])
                                    st.json(dict(creative_info))

                                    # Try to find image
                                    thumb = creative_info.get("thumbnail_url")
                                    img = creative_info.get("image_url")
                                    st.write(f"**thumbnail_url:** {thumb}")
                                    st.write(f"**image_url:** {img}")

                                    if thumb:
                                        st.image(thumb, caption="Thumbnail", width=150)
                                    if img:
                                        st.image(img, caption="Image URL", width=150)

                                    # Store for update button
                                    st.session_state.debug_fetched_url = img or thumb
                                else:
                                    st.warning("No creative found on this ad")

                            except Exception as e:
                                st.error(f"Test failed: {e}")

                with col_test2:
                    if st.button("📋 Check Database Value"):
                        try:
                            db_result = db.table("meta_ads_performance").select(
                                "meta_ad_id, ad_name, thumbnail_url"
                            ).eq("meta_ad_id", test_ad_id).limit(1).execute()

                            if db_result.data:
                                db_ad = db_result.data[0]
                                st.write(f"**Ad Name:** {db_ad.get('ad_name', 'N/A')[:50]}")
                                db_thumb = db_ad.get('thumbnail_url')
                                st.write(f"**Stored thumbnail_url:** {db_thumb or '(NULL/empty)'}")
                                if db_thumb:
                                    st.image(db_thumb, caption="Current stored image", width=150)
                            else:
                                st.warning(f"Ad {test_ad_id} not found in database")
                        except Exception as e:
                            st.error(f"Database check failed: {e}")

                # Update button if we have a fetched URL
                if st.session_state.get("debug_fetched_url"):
                    fetched_url = st.session_state.debug_fetched_url
                    st.write(f"**Fetched URL:** {fetched_url[:80]}...")
                    if st.button("💾 Save this URL to Database"):
                        try:
                            db.table("meta_ads_performance").update({
                                "thumbnail_url": fetched_url
                            }).eq("meta_ad_id", test_ad_id).execute()
                            st.success(f"Updated thumbnail for {test_ad_id}")
                            st.session_state.debug_fetched_url = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Update failed: {e}")

                if st.button("Close Debug"):
                    st.session_state.ad_perf_debug_thumbs = False
                    st.rerun()

            except Exception as e:
                st.error(f"Debug error: {e}")

        st.divider()

    st.divider()

    # Show linked ads table
    linked = get_linked_ads(brand_id)
    render_linked_ads_table(perf_data, linked)

    # Legacy Ads Section - Auto-match by filename
    st.divider()
    with st.expander("📦 Legacy Ads (Filename Matching)", expanded=False):
        st.caption("Match Meta ads to generated ads by filename (e.g., '1.png' in ad name matches generated ad with '1.png' in path)")

        # Campaign filter for legacy ads
        legacy_campaign = st.text_input(
            "Campaign name to search:",
            value="M5 - Collagen - ADV+ - Reboot - Dec 5",
            help="Enter part of the campaign name to filter legacy ads"
        )

        if st.button("🔍 Find Filename Matches", key="find_legacy"):
            with st.spinner("Searching for filename matches..."):
                # Get legacy ads
                legacy_ads = get_legacy_unmatched_ads(brand_id, legacy_campaign)

                # Get all generated ads with storage paths
                db = get_supabase_client()
                gen_result = db.table("generated_ads").select(
                    "id, storage_path, hook_text"
                ).execute()
                generated_ads = gen_result.data or []

                # Build lookup by filename
                gen_ads_by_filename = {}
                for ad in generated_ads:
                    path = ad.get("storage_path", "")
                    if path:
                        # Extract filename from path (e.g., "brand/run/1.png" -> "1.png")
                        filename = path.split("/")[-1].lower()
                        # Also try without extension
                        name_no_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
                        gen_ads_by_filename[filename] = ad
                        gen_ads_by_filename[name_no_ext] = ad

                # Find matches
                matches = []
                import re
                for meta_ad in legacy_ads:
                    ad_name = meta_ad.get("ad_name", "")
                    filename_patterns = []

                    # Pattern 1: [m5-system]_X.png format (e.g., "[image][m5-system]_3.png-12_December")
                    m5_match = re.search(r'\[m5-system\]_(\d+)\.png', ad_name, re.IGNORECASE)
                    if m5_match:
                        num = m5_match.group(1)
                        filename_patterns.append(f"{num}.png")
                        filename_patterns.append(num)

                    # Pattern 2: General filename patterns like "1.png", "2.jpg"
                    filename_patterns.extend(re.findall(r'(\d+\.png|\d+\.jpg|\d+\.jpeg)', ad_name.lower()))

                    # Pattern 3: Standalone numbers
                    standalone_nums = re.findall(r'^(\d+)$|[^\w](\d+)[^\w]|^(\d+)[^\w]|[^\w](\d+)$', ad_name)
                    for match_tuple in standalone_nums:
                        for num in match_tuple:
                            if num:
                                filename_patterns.append(num)
                                filename_patterns.append(f"{num}.png")

                    matched_gen_ad = None
                    matched_filename = None
                    for pattern in filename_patterns:
                        if pattern in gen_ads_by_filename:
                            matched_gen_ad = gen_ads_by_filename[pattern]
                            matched_filename = pattern
                            break
                        # Try without extension
                        name_no_ext = pattern.rsplit(".", 1)[0] if "." in pattern else pattern
                        if name_no_ext in gen_ads_by_filename:
                            matched_gen_ad = gen_ads_by_filename[name_no_ext]
                            matched_filename = pattern
                            break

                    if matched_gen_ad:
                        matches.append({
                            "meta_ad": meta_ad,
                            "suggested_match": matched_gen_ad,
                            "matched_filename": matched_filename,
                            "confidence": "medium"
                        })

                st.session_state.ad_perf_legacy_matches = matches

                # Find simple numeric filenames for debug
                simple_filenames = [k for k in gen_ads_by_filename.keys() if re.match(r'^\d+$', k) or re.match(r'^\d+\.png$', k)]

                # Debug: show what patterns were extracted from first few ads
                extraction_debug = []
                for ad in legacy_ads[:5]:
                    ad_name = ad.get("ad_name", "")
                    patterns = []
                    m5_match = re.search(r'\[m5-system\]_(\d+)\.png', ad_name, re.IGNORECASE)
                    if m5_match:
                        patterns.append(f"{m5_match.group(1)}.png")
                        patterns.append(m5_match.group(1))
                    extraction_debug.append({
                        "ad_name": ad_name[:60],
                        "extracted": patterns,
                        "in_lookup": [p for p in patterns if p in gen_ads_by_filename]
                    })

                st.session_state.ad_perf_legacy_debug = {
                    "legacy_count": len(legacy_ads),
                    "gen_count": len(generated_ads),
                    "match_count": len(matches),
                    "sample_legacy": [a.get("ad_name", "")[:60] for a in legacy_ads[:5]],
                    "sample_gen": [a.get("storage_path", "").split("/")[-1] for a in list(generated_ads)[:5]],
                    "simple_numeric_filenames": simple_filenames[:20],
                    "lookup_keys_sample": list(gen_ads_by_filename.keys())[:30],
                    "extraction_debug": extraction_debug
                }

        # Always show debug info if available
        debug = st.session_state.get("ad_perf_legacy_debug")
        if debug:
            st.info(f"📊 **Search Results**: Found {debug['legacy_count']} legacy ads, {debug['gen_count']} generated ads, **{debug['match_count']} matches**")

            if debug['match_count'] == 0:
                st.markdown("---")
                st.markdown("**🔍 Debug: Why no matches?**")

                st.write("**Pattern Extraction Test (first 5 ads):**")
                for item in debug.get('extraction_debug', []):
                    extracted = item.get('extracted', [])
                    in_lookup = item.get('in_lookup', [])
                    if extracted:
                        status = "✅ Found in DB" if in_lookup else "❌ NOT in DB"
                        st.code(f"{item['ad_name']}\n  → Extracted: {extracted}\n  → {status}")
                    else:
                        st.code(f"{item['ad_name']}\n  → ❌ No pattern extracted!")

                st.write("**Simple Numeric Filenames in Generated Ads:**")
                simple = debug.get('simple_numeric_filenames', [])
                if simple:
                    st.code(", ".join(simple[:20]))
                else:
                    st.warning("No simple numeric filenames (like '1', '1.png') found in generated_ads!")

                st.caption("Pattern looks for `[m5-system]_X.png` where X is a number.")

        # Show matches
        if st.session_state.get("ad_perf_legacy_matches"):
            matches = st.session_state.ad_perf_legacy_matches
            st.write(f"**Found {len(matches)} filename matches**")

            for i, match in enumerate(matches):
                meta_ad = match["meta_ad"]
                gen_ad = match["suggested_match"]
                matched_filename = match["matched_filename"]

                st.markdown("---")
                cols = st.columns([1.5, 0.5, 1.5, 1])

                with cols[0]:
                    st.markdown("**Meta Ad**")
                    thumb = meta_ad.get("thumbnail_url")
                    if thumb:
                        st.image(thumb, width=120)
                    else:
                        st.caption("📷 No thumbnail")
                    st.caption(f"`{meta_ad.get('ad_name', 'Unknown')[:50]}`")
                    st.caption(f"Matched: **{matched_filename}**")

                with cols[1]:
                    st.markdown("")
                    st.markdown("")
                    st.markdown("↔️")

                with cols[2]:
                    st.markdown("**Generated Ad**")
                    signed_url = get_signed_url(gen_ad.get("storage_path"))
                    if signed_url:
                        st.image(signed_url, width=120)
                    else:
                        st.caption("📷 No image")
                    st.caption(f"ID: `{str(gen_ad['id'])[:8]}...`")
                    hook = gen_ad.get("hook_text", "")
                    if hook:
                        st.caption(f"{hook[:40]}...")

                with cols[3]:
                    if st.button("✓ Link", key=f"legacy_link_{meta_ad.get('meta_ad_id')}", type="primary"):
                        perf_record = next(
                            (p for p in perf_data if p.get("meta_ad_id") == meta_ad.get("meta_ad_id")),
                            {}
                        )
                        success = create_ad_link(
                            generated_ad_id=str(gen_ad["id"]),
                            meta_ad_id=meta_ad.get("meta_ad_id"),
                            meta_campaign_id=perf_record.get("meta_campaign_id", "unknown"),
                            meta_ad_account_id=ad_account['meta_ad_account_id'],
                            linked_by="filename_match"
                        )
                        if success:
                            st.success("Linked!")
                            st.session_state.ad_perf_legacy_matches = [
                                m for m in matches
                                if m["meta_ad"].get("meta_ad_id") != meta_ad.get("meta_ad_id")
                            ]
                            st.rerun()
                    if st.button("✗ Skip", key=f"legacy_skip_{meta_ad.get('meta_ad_id')}"):
                        st.session_state.ad_perf_legacy_matches = [
                            m for m in matches
                            if m["meta_ad"].get("meta_ad_id") != meta_ad.get("meta_ad_id")
                        ]
                        st.rerun()

        # Manual Linking Section - show unlinked ads with spend
        st.markdown("---")
        st.markdown("### 🔗 Manual Linking")
        st.caption("Link Meta ads manually by selecting the matching generated ad")

        # Get unlinked legacy ads (reuse from above or fetch fresh)
        if 'legacy_ads' not in dir() or not legacy_ads:
            legacy_ads = get_legacy_unmatched_ads(brand_id, legacy_campaign)

        if legacy_ads:
            # Show top spending unlinked ads
            st.write(f"**{len(legacy_ads)} unlinked ads** (sorted by spend)")

            for idx, meta_ad in enumerate(legacy_ads[:10]):  # Show top 10 by spend
                spend = float(meta_ad.get("spend") or 0)
                ad_name = meta_ad.get("ad_name", "Unknown")
                meta_ad_id = meta_ad.get("meta_ad_id")

                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    thumb = meta_ad.get("thumbnail_url")
                    if thumb:
                        st.image(thumb, width=80)
                    st.caption(f"`{ad_name[:50]}`")

                with col2:
                    st.metric("Spend", f"${spend:.2f}")

                with col3:
                    # Manual link button - opens a selectbox
                    link_key = f"manual_link_select_{meta_ad_id}"
                    if st.button("🔗 Link", key=f"manual_link_btn_{idx}"):
                        st.session_state[f"show_link_for_{meta_ad_id}"] = True

                # Show generated ad selector if button was clicked
                if st.session_state.get(f"show_link_for_{meta_ad_id}"):
                    st.markdown("**Select generated ad to link (legacy ads with numeric filenames):**")

                    # Get generated ads for selection
                    db = get_supabase_client()
                    gen_result = db.table("generated_ads").select(
                        "id, storage_path, hook_text, created_at"
                    ).order("created_at", desc=True).limit(500).execute()
                    all_gen_ads = gen_result.data or []

                    # Filter to only legacy ads (simple numeric filenames like 1.png, 2.png)
                    # and filter by brand (check if storage_path contains brand name)
                    import re
                    gen_ads_list = []
                    for ga in all_gen_ads:
                        path = ga.get("storage_path", "")
                        filename = path.split("/")[-1].lower() if path else ""
                        # Check if it's a simple numeric filename (1.png, 2.png, etc.)
                        if re.match(r'^\d+\.png$', filename) or re.match(r'^\d+\.jpg$', filename):
                            # Also try to filter by brand - check if path contains brand-related terms
                            # Wonder Paws brand might have "wonderpaws", "wonder-paws", "wp" in path
                            path_lower = path.lower()
                            if "wonderpaws" in path_lower or "wonder" in path_lower or "wp" in path_lower or "paws" in path_lower:
                                gen_ads_list.append(ga)

                    # If no brand-filtered results, show all numeric filename ads
                    if not gen_ads_list:
                        for ga in all_gen_ads:
                            path = ga.get("storage_path", "")
                            filename = path.split("/")[-1].lower() if path else ""
                            if re.match(r'^\d+\.png$', filename) or re.match(r'^\d+\.jpg$', filename):
                                gen_ads_list.append(ga)

                    if not gen_ads_list:
                        st.warning("No legacy ads (1.png, 2.png, etc.) found in generated_ads")
                    else:
                        st.caption(f"Found {len(gen_ads_list)} legacy ads with numeric filenames")

                        # Pagination
                        page_size = 30
                        page_key = f"page_{meta_ad_id}"
                        if page_key not in st.session_state:
                            st.session_state[page_key] = 0

                        total_pages = (len(gen_ads_list) + page_size - 1) // page_size
                        current_page = st.session_state[page_key]

                        # Page navigation
                        if total_pages > 1:
                            nav_cols = st.columns([1, 2, 1])
                            with nav_cols[0]:
                                if current_page > 0:
                                    if st.button("← Prev", key=f"prev_{meta_ad_id}"):
                                        st.session_state[page_key] -= 1
                                        st.rerun()
                            with nav_cols[1]:
                                st.caption(f"Page {current_page + 1} of {total_pages}")
                            with nav_cols[2]:
                                if current_page < total_pages - 1:
                                    if st.button("Next →", key=f"next_{meta_ad_id}"):
                                        st.session_state[page_key] += 1
                                        st.rerun()

                        # Get ads for current page
                        start_idx = current_page * page_size
                        end_idx = min(start_idx + page_size, len(gen_ads_list))
                        page_ads = gen_ads_list[start_idx:end_idx]

                    # Show as visual grid - 5 columns
                    if gen_ads_list:
                        cols_per_row = 5
                        for row_start in range(0, len(page_ads), cols_per_row):
                            cols = st.columns(cols_per_row)
                            for col_idx, col in enumerate(cols):
                                ad_idx = row_start + col_idx
                                if ad_idx < len(page_ads):
                                    ga = page_ads[ad_idx]
                                    global_idx = start_idx + ad_idx  # For unique key
                                    with col:
                                        signed_url = get_signed_url(ga.get("storage_path"))
                                        if signed_url:
                                            st.image(signed_url, width=100)
                                        else:
                                            st.caption("📷")

                                        # Show filename
                                        filename = ga.get("storage_path", "").split("/")[-1][:15]
                                        st.caption(f"`{filename}`")

                                        # Link button for this ad
                                        if st.button("Select", key=f"sel_{meta_ad_id}_{global_idx}", type="secondary"):
                                            success = create_ad_link(
                                                generated_ad_id=str(ga["id"]),
                                                meta_ad_id=meta_ad_id,
                                                meta_campaign_id="unknown",
                                                meta_ad_account_id=ad_account['meta_ad_account_id'],
                                                linked_by="manual"
                                            )
                                            if success:
                                                st.success("Linked!")
                                                del st.session_state[f"show_link_for_{meta_ad_id}"]
                                                st.rerun()

                    if st.button("Cancel", key=f"cancel_{meta_ad_id}"):
                        del st.session_state[f"show_link_for_{meta_ad_id}"]
                        st.rerun()

                st.markdown("---")
        else:
            st.success("✅ All legacy ads are linked!")


elif selected_tab == "🧪 Manual Analysis":
    render_manual_analysis_tab()


# Footer with data info
if perf_data:
    st.divider()
    latest = max(d.get("fetched_at", "") for d in perf_data if d.get("fetched_at"))
    if latest:
        st.caption(f"Data last synced: {latest[:19]}")
