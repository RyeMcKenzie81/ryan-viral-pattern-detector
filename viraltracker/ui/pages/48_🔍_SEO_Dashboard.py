"""
SEO Dashboard Page - Overview, KPIs, articles table, analytics, and link management.

Provides UI for:
- Brand-level overview (all projects aggregated)
- Project-level KPIs (article counts, keyword counts, link stats)
- Articles table with status and actions
- Analytics settings (GSC, GA4, Shopify) with OAuth callback handling
- External analytics display (search performance, traffic, conversions)
- Internal link management (suggest, auto-link, bidirectional)
"""

import datetime
import logging

import altair as alt
import pandas as pd
import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="SEO Dashboard", page_icon="🔍", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# OAUTH CALLBACK HANDLING (must be before UI renders)
# =============================================================================

def _get_oauth_redirect_uri() -> str:
    """Get OAuth redirect URI from env var, with localhost fallback."""
    import os
    base = os.environ.get("APP_BASE_URL", "http://localhost:8501")
    return f"{base.rstrip('/')}/SEO_Dashboard"


if "code" in st.query_params and "state" in st.query_params:
    try:
        from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
        gsc = GSCService()
        state_data = gsc.decode_oauth_state(st.query_params["state"])
        redirect_uri = _get_oauth_redirect_uri()
        tokens = gsc.exchange_code_for_tokens(st.query_params["code"], redirect_uri)

        # Fetch available properties so user can pick the right one
        sites = gsc.list_sites(tokens["access_token"])

        # Store tokens + state in session for property selection step
        st.session_state["_gsc_pending_tokens"] = tokens
        st.session_state["_gsc_pending_state"] = state_data
        st.session_state["_gsc_pending_sites"] = sites

        st.query_params.clear()
        st.rerun()
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        st.error(f"OAuth callback failed: {e}")
        st.query_params.clear()


# =============================================================================
# HELPERS
# =============================================================================

def get_project_service():
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
    return SEOProjectService()


def get_analytics_service():
    from viraltracker.services.seo_pipeline.services.seo_analytics_service import SEOAnalyticsService
    return SEOAnalyticsService()


def get_tracking_service():
    from viraltracker.services.seo_pipeline.services.article_tracking_service import ArticleTrackingService
    return ArticleTrackingService()


def get_interlinking_service():
    from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
    return InterlinkingService()


ALL_PROJECTS_SENTINEL = "__all__"


def _resolve_org_id_for_brand(brand_id: str, org_id: str) -> str:
    """Resolve actual UUID org_id from brand when superuser has org_id='all'."""
    if org_id != "all":
        return org_id
    from viraltracker.core.database import get_supabase_client
    row = get_supabase_client().table("brands").select("organization_id").eq("id", brand_id).execute()
    if row.data:
        return row.data[0]["organization_id"]
    return org_id  # fallback


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("🔍 SEO Dashboard")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_dashboard_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()
# Real UUID org_id for DB writes (superuser has org_id="all" which can't be inserted into UUID columns)
_real_org_id = _resolve_org_id_for_brand(brand_id, org_id)

# Project selector — "All Projects" as default
project_service = get_project_service()
projects = project_service.list_projects(org_id, brand_id=brand_id)

project_options = {ALL_PROJECTS_SENTINEL: "All Projects"}
for p in projects:
    project_options[p["id"]] = p["name"]

selected_project_id = st.selectbox(
    "SEO Project",
    options=list(project_options.keys()),
    format_func=lambda x: project_options[x],
    key="seo_dash_project_selector",
)

is_brand_view = selected_project_id == ALL_PROJECTS_SENTINEL


# =============================================================================
# KPIs
# =============================================================================

analytics = get_analytics_service()

if is_brand_view:
    if not projects:
        # Zero state — no projects at all
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Articles", 0)
        with col2:
            st.metric("Published", 0)
        with col3:
            st.metric("Keywords", 0)
        with col4:
            st.metric("Projects", 0)

        st.divider()
        st.info("No SEO projects yet. Get started by creating your first project.")
        if st.button("Create Your First SEO Project", type="primary"):
            st.switch_page("pages/49_🔑_Keyword_Research.py")

    if projects:
        with st.spinner("Loading brand overview..."):
            dashboard = analytics.get_brand_dashboard(brand_id, org_id)

        articles_data = dashboard["articles"]
        keywords_data = dashboard["keywords"]
        projects_data = dashboard["projects"]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Articles", articles_data["total"])
        with col2:
            st.metric("Published", articles_data["published"])
        with col3:
            st.metric("Keywords", keywords_data["total"])
        with col4:
            st.metric("Projects", projects_data["total"])
    else:
        articles_data = {"status_counts": {}}
else:
    dashboard = analytics.get_project_dashboard(selected_project_id, org_id)

    articles_data = dashboard["articles"]
    keywords_data = dashboard["keywords"]
    links_data = dashboard["links"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Articles", articles_data["total"])
    with col2:
        st.metric("Published", articles_data["published"])
    with col3:
        st.metric("Keywords", keywords_data["total"])
    with col4:
        st.metric("Internal Links", links_data["total"])


# =============================================================================
# ARTICLE STATUS BREAKDOWN
# =============================================================================

if articles_data["status_counts"]:
    st.subheader("Article Status")
    status_cols = st.columns(min(len(articles_data["status_counts"]), 5))
    for i, (status, count) in enumerate(sorted(articles_data["status_counts"].items())):
        with status_cols[i % len(status_cols)]:
            st.metric(status.replace("_", " ").title(), count)


# =============================================================================
# ARTICLES LOADING (needed for analytics scoping and articles table)
# =============================================================================

tracking = get_tracking_service()
if is_brand_view:
    articles = tracking.list_articles(
        organization_id=org_id,
        brand_id=brand_id,
    )
else:
    articles = tracking.list_articles(
        organization_id=org_id,
        project_id=selected_project_id,
    )

brand_article_ids = [a["id"] for a in articles]


# Load discovered article IDs for site-wide analytics scope
@st.cache_data(ttl=300)
def _load_discovered_articles(_brand_id):
    """Load discovered (GSC auto-created) articles for site-wide view."""
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    result = (
        supabase.table("seo_articles")
        .select("id, keyword, published_url")
        .eq("brand_id", _brand_id)
        .eq("status", "discovered")
        .execute()
    )
    return result.data or []


discovered_articles = _load_discovered_articles(brand_id)
discovered_article_ids = [a["id"] for a in discovered_articles]
all_article_ids = brand_article_ids + discovered_article_ids


# =============================================================================
# EXTERNAL ANALYTICS
# =============================================================================

st.divider()
st.subheader("Analytics")


def _load_connected_integrations():
    """Load connected integration platforms for this brand."""
    try:
        from viraltracker.core.database import get_supabase_client
        supabase = get_supabase_client()
        query = (
            supabase.table("brand_integrations")
            .select("platform, config")
            .eq("brand_id", brand_id)
        )
        if org_id != "all":
            query = query.eq("organization_id", org_id)
        integrations = query.execute().data or []
        return {i["platform"]: i for i in integrations}
    except Exception:
        return {}


@st.cache_data(ttl=300)
def _load_gsc_analytics(article_ids_tuple, date_from_str, date_to_str):
    """Load GSC analytics data scoped to brand articles."""
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    article_ids = list(article_ids_tuple)
    if not article_ids:
        return []
    query = (
        supabase.table("seo_article_analytics")
        .select("article_id, date, impressions, clicks, ctr, average_position")
        .eq("source", "gsc")
        .gte("date", date_from_str)
        .lte("date", date_to_str)
        .in_("article_id", article_ids)
        .order("date")
        .limit(5000)
    )
    return query.execute().data or []


@st.cache_data(ttl=300)
def _load_source_totals(article_ids_tuple, source):
    """Load simple totals for a source (GA4 or Shopify), scoped to brand articles."""
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    article_ids = list(article_ids_tuple)
    if not article_ids:
        return []
    query = (
        supabase.table("seo_article_analytics")
        .select("sessions, pageviews, conversions, revenue")
        .eq("source", source)
        .in_("article_id", article_ids)
        .limit(5000)
    )
    return query.execute().data or []


connected_integrations = _load_connected_integrations()

# --- GSC Performance Report ---
if "gsc" in connected_integrations:
    st.markdown("**Search Performance (Google Search Console)**")

    # Scope toggle + controls row
    scope_col, ctrl1, ctrl2 = st.columns([0.8, 1, 1])
    with scope_col:
        gsc_scope = st.radio(
            "Scope",
            ["Site-wide", "Tracked articles"],
            index=0,
            key="seo_dash_gsc_scope",
            horizontal=True,
        )
    with ctrl1:
        time_range = st.selectbox(
            "Time range",
            ["Last 7 days", "Last 28 days", "Last 3 months", "Last 6 months", "Custom"],
            index=1,
            key="seo_dash_time_range",
        )
    with ctrl2:
        if gsc_scope == "Tracked articles":
            article_label_map = {a["id"]: a.get("keyword") or a.get("title") or "Untitled" for a in articles}
            selected_article_ids = st.multiselect(
                "Filter articles",
                options=list(article_label_map.keys()),
                format_func=lambda x: article_label_map[x],
                key="seo_dash_article_filter",
            )
        else:
            selected_article_ids = []
            st.caption("Showing all pages from GSC")

    today = datetime.date.today()
    if time_range == "Last 7 days":
        date_from = today - datetime.timedelta(days=7)
        date_to = today
    elif time_range == "Last 28 days":
        date_from = today - datetime.timedelta(days=28)
        date_to = today
    elif time_range == "Last 3 months":
        date_from = today - datetime.timedelta(days=90)
        date_to = today
    elif time_range == "Last 6 months":
        date_from = today - datetime.timedelta(days=180)
        date_to = today
    else:
        custom_cols = st.columns(2)
        with custom_cols[0]:
            date_from = st.date_input(
                "From", value=today - datetime.timedelta(days=28), key="seo_dash_date_from"
            )
        with custom_cols[1]:
            date_to = st.date_input("To", value=today, key="seo_dash_date_to")

    # Determine which article IDs to query based on scope
    if gsc_scope == "Site-wide":
        query_article_ids = all_article_ids
    elif selected_article_ids:
        query_article_ids = selected_article_ids
    else:
        query_article_ids = brand_article_ids

    with st.spinner("Loading search performance data..."):
        gsc_rows = _load_gsc_analytics(
            tuple(query_article_ids),
            date_from.isoformat(),
            date_to.isoformat(),
        )

    if gsc_rows:
        df = pd.DataFrame(gsc_rows)
        df["date"] = pd.to_datetime(df["date"])
        df["impressions"] = df["impressions"].fillna(0).astype(int)
        df["clicks"] = df["clicks"].fillna(0).astype(int)
        df["ctr"] = df["ctr"].fillna(0.0).astype(float)
        df["average_position"] = df["average_position"].fillna(0.0).astype(float)
        df["_weighted_pos"] = df["average_position"] * df["impressions"]

        # KPI cards
        total_impressions = int(df["impressions"].sum())
        total_clicks = int(df["clicks"].sum())
        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0.0
        weighted_pos_sum = float(df["_weighted_pos"].sum())
        avg_position = (weighted_pos_sum / total_impressions) if total_impressions else 0.0

        with st.container(border=True):
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Total Impressions", f"{total_impressions:,}")
            with k2:
                st.metric("Total Clicks", f"{total_clicks:,}")
            with k3:
                st.metric("Avg CTR", f"{avg_ctr:.1f}%")
            with k4:
                st.metric("Avg Position", f"{avg_position:.1f}")

        # Metric toggles
        tog_cols = st.columns(4)
        with tog_cols[0]:
            show_impressions = st.checkbox("Impressions", value=True, key="seo_dash_show_imp")
        with tog_cols[1]:
            show_clicks = st.checkbox("Clicks", value=True, key="seo_dash_show_clicks")
        with tog_cols[2]:
            show_ctr = st.checkbox("CTR", value=False, key="seo_dash_show_ctr")
        with tog_cols[3]:
            show_position = st.checkbox("Position", value=False, key="seo_dash_show_pos")

        # Daily aggregation
        daily = df.groupby("date").agg(
            impressions=("impressions", "sum"),
            clicks=("clicks", "sum"),
            weighted_pos_sum=("_weighted_pos", "sum"),
        ).reset_index()
        daily["ctr"] = daily.apply(
            lambda r: (r["clicks"] / r["impressions"] * 100) if r["impressions"] else 0.0, axis=1
        )
        daily["avg_position"] = daily.apply(
            lambda r: (r["weighted_pos_sum"] / r["impressions"]) if r["impressions"] else None, axis=1
        )

        # Fill date gaps
        full_range = pd.date_range(date_from, date_to, freq="D")
        daily = daily.set_index("date").reindex(full_range).reset_index()
        daily.rename(columns={"index": "date"}, inplace=True)
        daily["impressions"] = daily["impressions"].fillna(0).astype(int)
        daily["clicks"] = daily["clicks"].fillna(0).astype(int)
        daily["ctr"] = daily["ctr"].fillna(0.0)
        # avg_position stays NaN for gap days — chart shows gaps

        # Build time series chart
        any_toggled = show_impressions or show_clicks or show_ctr or show_position
        if any_toggled:
            base = alt.Chart(daily).encode(
                x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d")),
            )
            layers = []
            if show_impressions:
                layers.append(
                    base.mark_line(color="#8430CE", strokeWidth=2).encode(
                        y=alt.Y("impressions:Q", title="Impressions"),
                        tooltip=[
                            alt.Tooltip("date:T", format="%b %d, %Y"),
                            alt.Tooltip("impressions:Q", format=",", title="Impressions"),
                        ],
                    )
                )
            if show_clicks:
                layers.append(
                    base.mark_line(color="#4285F4", strokeWidth=2).encode(
                        y=alt.Y("clicks:Q", title="Clicks"),
                        tooltip=[
                            alt.Tooltip("date:T", format="%b %d, %Y"),
                            alt.Tooltip("clicks:Q", format=",", title="Clicks"),
                        ],
                    )
                )
            if show_ctr:
                layers.append(
                    base.mark_line(color="#0D652D", strokeWidth=2).encode(
                        y=alt.Y("ctr:Q", title="CTR (%)"),
                        tooltip=[
                            alt.Tooltip("date:T", format="%b %d, %Y"),
                            alt.Tooltip("ctr:Q", format=".1f", title="CTR (%)"),
                        ],
                    )
                )
            if show_position:
                layers.append(
                    base.mark_line(color="#E37400", strokeWidth=2).encode(
                        y=alt.Y(
                            "avg_position:Q",
                            title="Avg Position",
                            scale=alt.Scale(reverse=True),
                        ),
                        tooltip=[
                            alt.Tooltip("date:T", format="%b %d, %Y"),
                            alt.Tooltip("avg_position:Q", format=".1f", title="Position"),
                        ],
                    )
                )

            chart = alt.layer(*layers).resolve_scale(y="independent").properties(height=350)
            st.altair_chart(chart, use_container_width=True)

        # Per-article breakdown table
        article_stats = df.groupby("article_id").agg(
            impressions=("impressions", "sum"),
            clicks=("clicks", "sum"),
            weighted_pos_sum=("_weighted_pos", "sum"),
        ).reset_index()
        article_stats["ctr"] = article_stats.apply(
            lambda r: (r["clicks"] / r["impressions"] * 100) if r["impressions"] else 0.0, axis=1
        )
        article_stats["avg_position"] = article_stats.apply(
            lambda r: (r["weighted_pos_sum"] / r["impressions"]) if r["impressions"] else 0.0, axis=1
        )

        # Sparkline data: daily impressions per article
        sparklines = {}
        for aid, group in df.groupby("article_id"):
            daily_imp = group.groupby("date")["impressions"].sum()
            daily_imp = daily_imp.reindex(full_range, fill_value=0)
            sparklines[aid] = daily_imp.tolist()

        article_name_map = {
            a["id"]: a.get("keyword") or a.get("title") or "Untitled" for a in articles
        }
        # Add discovered articles to name map (use published_url path as label)
        if gsc_scope == "Site-wide":
            from urllib.parse import urlparse
            for a in discovered_articles:
                url = a.get("published_url", "")
                label = urlparse(url).path if url else a.get("keyword", "Unknown")
                article_name_map[a["id"]] = label
        article_stats["Article"] = article_stats["article_id"].map(article_name_map)
        article_stats["Trend"] = article_stats["article_id"].map(sparklines)
        article_stats = article_stats.sort_values("impressions", ascending=False)

        display_df = article_stats[
            ["Article", "Trend", "impressions", "clicks", "ctr", "avg_position"]
        ].copy()
        display_df.columns = ["Article", "Trend", "Impressions", "Clicks", "CTR", "Avg Position"]

        use_expander = len(display_df) > 10
        container = (
            st.expander("Per-Article Breakdown", expanded=True) if use_expander else st.container()
        )
        with container:
            st.dataframe(
                display_df,
                column_config={
                    "Article": st.column_config.TextColumn("Article"),
                    "Trend": st.column_config.LineChartColumn("Trend", width="small"),
                    "Impressions": st.column_config.NumberColumn("Impressions", format="%d"),
                    "Clicks": st.column_config.NumberColumn("Clicks", format="%d"),
                    "CTR": st.column_config.NumberColumn("CTR", format="%.1f%%"),
                    "Avg Position": st.column_config.NumberColumn("Avg Position", format="%.1f"),
                },
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("GSC connected. No data yet — click Sync Now or wait for daily sync.")
else:
    # Check if we're in the property selection step (post-OAuth, pre-save)
    _pending_tokens = st.session_state.get("_gsc_pending_tokens")
    _pending_sites = st.session_state.get("_gsc_pending_sites", [])
    _pending_state = st.session_state.get("_gsc_pending_state", {})

    if _pending_tokens and _pending_sites:
        with st.container(border=True):
            st.markdown("**Select your Search Console property**")
            site_options = {s["siteUrl"]: s["siteUrl"] for s in _pending_sites}
            selected_site = st.selectbox(
                "Property",
                options=list(site_options.keys()),
                format_func=lambda x: site_options[x],
                key="seo_dash_gsc_site_picker",
            )
            if st.button("Save & Connect", key="seo_dash_gsc_save", type="primary"):
                try:
                    from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
                    gsc = GSCService()
                    _cb_org_id = _pending_state.get("org_id", "all")
                    _cb_brand_id = _pending_state.get("brand_id", brand_id)
                    if _cb_org_id == "all":
                        _cb_org_id = _resolve_org_id_for_brand(_cb_brand_id, _cb_org_id)
                    gsc.save_integration(
                        brand_id=_cb_brand_id,
                        organization_id=_cb_org_id,
                        site_url=selected_site,
                        tokens=_pending_tokens,
                    )
                    # Clear pending state
                    del st.session_state["_gsc_pending_tokens"]
                    del st.session_state["_gsc_pending_sites"]
                    del st.session_state["_gsc_pending_state"]
                    st.success("GSC connected!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")
            if st.button("Cancel", key="seo_dash_gsc_cancel"):
                del st.session_state["_gsc_pending_tokens"]
                del st.session_state["_gsc_pending_sites"]
                del st.session_state["_gsc_pending_state"]
                st.rerun()
    elif _pending_tokens:
        # OAuth succeeded but no sites found
        with st.container(border=True):
            st.warning("No Search Console properties found for this Google account. "
                       "Add a property at [Google Search Console](https://search.google.com/search-console) first.")
            if st.button("Dismiss", key="seo_dash_gsc_dismiss"):
                del st.session_state["_gsc_pending_tokens"]
                st.session_state.pop("_gsc_pending_sites", None)
                st.session_state.pop("_gsc_pending_state", None)
                st.rerun()
    else:
        with st.container(border=True):
            st.markdown("**Connect Google Search Console** to see real ranking and click data.")
            if st.button("Connect GSC", key="seo_dash_gsc_connect"):
                try:
                    import secrets
                    from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
                    gsc = GSCService()
                    nonce = secrets.token_urlsafe(16)
                    state = gsc.encode_oauth_state(brand_id, org_id, nonce)
                    redirect_uri = _get_oauth_redirect_uri()
                    auth_url = gsc.get_authorization_url(redirect_uri, state)
                    st.markdown(f"[Authorize with Google]({auth_url})")
                except Exception as e:
                    st.error(f"Failed: {e}")

# GA4 section — simple totals, scoped by brand articles
if "ga4" in connected_integrations:
    ga4_rows = _load_source_totals(tuple(brand_article_ids), "ga4")
    if ga4_rows:
        st.markdown("**Traffic (Google Analytics 4)**")
        ga4_sessions = sum(r.get("sessions", 0) for r in ga4_rows)
        ga4_pageviews = sum(r.get("pageviews", 0) for r in ga4_rows)
        t1, t2 = st.columns(2)
        with t1:
            st.metric("Sessions", f"{ga4_sessions:,}")
        with t2:
            st.metric("Pageviews", f"{ga4_pageviews:,}")
    else:
        st.info("GA4 connected. No data yet — click Sync Now or wait for daily sync.")

# Shopify conversions section — simple totals, scoped by brand articles
if "shopify" in connected_integrations:
    shopify_rows = _load_source_totals(tuple(brand_article_ids), "shopify")
    if shopify_rows:
        st.markdown("**Conversions (Shopify)**")
        shop_conversions = sum(r.get("conversions", 0) for r in shopify_rows)
        shop_revenue = sum(float(r.get("revenue", 0)) for r in shopify_rows)
        s1, s2 = st.columns(2)
        with s1:
            st.metric("Conversions", shop_conversions)
        with s2:
            st.metric("Revenue", f"${shop_revenue:,.2f}")
    else:
        st.info("Shopify connected. No data yet — click Sync Now or wait for daily sync.")

# Analytics settings expander
if connected_integrations:
    with st.expander("Analytics Settings"):
        for platform, integration in connected_integrations.items():
            st.markdown(f"**{platform.upper()}**: Connected")

        if st.button("Sync Now", key="seo_dash_sync_now"):
            with st.spinner("Syncing analytics..."):
                results = {}
                # Use real UUID org_id for DB writes
                sync_org_id = _real_org_id
                # GSC
                if "gsc" in connected_integrations:
                    try:
                        from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
                        results["gsc"] = GSCService().sync_to_db(brand_id, sync_org_id)
                    except Exception as e:
                        results["gsc"] = {"error": str(e)}

                # GA4
                if "ga4" in connected_integrations:
                    try:
                        from viraltracker.services.seo_pipeline.services.ga4_service import GA4Service
                        results["ga4"] = GA4Service().sync_to_db(brand_id, sync_org_id)
                    except Exception as e:
                        results["ga4"] = {"error": str(e)}

                # Shopify
                if "shopify" in connected_integrations:
                    try:
                        from viraltracker.services.seo_pipeline.services.shopify_analytics_service import ShopifyAnalyticsService
                        results["shopify"] = ShopifyAnalyticsService().sync_to_db(brand_id, sync_org_id)
                    except Exception as e:
                        results["shopify"] = {"error": str(e)}

                # Clear cached data so site-wide toggle picks up new discovered articles
                _load_discovered_articles.clear()
                _load_gsc_analytics.clear()

                for source, result in results.items():
                    if "error" in result:
                        st.error(f"{source.upper()}: {result['error']}")
                    elif source == "gsc" and "api_rows" in result:
                        # Show detailed GSC sync stats
                        matched = result.get("analytics_matched", 0)
                        total = result.get("analytics_total", 0)
                        unmatched = total - matched
                        st.success(
                            f"GSC: {result['api_rows']:,} API rows, "
                            f"{result.get('api_impressions', 0):,} impressions, "
                            f"{result.get('unique_urls', 0)} pages found"
                        )
                        st.info(
                            f"Matched {matched}/{total} page-dates "
                            f"({result.get('discovered_created', 0)} new pages discovered). "
                            f"Stored {result.get('analytics_rows', 0)} analytics + "
                            f"{result.get('ranking_rows', 0)} ranking rows."
                        )
                        if unmatched > 0:
                            st.warning(f"{unmatched} page-date entries could not be matched to articles.")
                    else:
                        st.success(f"{source.upper()}: synced {result.get('analytics_rows', 0)} rows")


# =============================================================================
# ARTICLES TABLE
# =============================================================================

st.divider()
st.subheader("Articles")

if articles:
    table_data = []
    for a in articles:
        table_data.append({
            "Keyword": a.get("keyword", "—"),
            "Status": a.get("status", "—"),
            "Phase": (a.get("phase") or "—").upper(),
            "CMS ID": (a.get("cms_article_id") or "—")[:12],
            "Published URL": a.get("published_url") or "—",
        })
    st.dataframe(table_data, use_container_width=True)
else:
    st.info("No articles yet.")

# Import from Shopify
if "shopify" in connected_integrations:
    with st.expander("Import Existing Articles from Shopify"):
        st.markdown(
            "Pull in blog articles that already exist in Shopify so "
            "analytics data can be matched to them."
        )
        if projects:
            _import_project_opts = {p["id"]: p["name"] for p in projects}
            _import_project = st.selectbox(
                "Import into project",
                options=list(_import_project_opts.keys()),
                format_func=lambda x: _import_project_opts[x],
                key="seo_dash_import_project",
            )
        else:
            st.caption("No projects yet — one will be created automatically.")
            _import_project = None
        _import_domain = st.text_input(
            "Public domain (for URL matching)",
            value="yaketypack.com",
            help="Your public domain, NOT the .myshopify.com domain",
            key="seo_dash_import_domain",
        )
        if st.button("Import Articles", key="seo_dash_import_btn"):
            with st.spinner("Importing articles from Shopify..."):
                try:
                    # Auto-create project if none exists
                    target_project_id = _import_project
                    if not target_project_id:
                        from viraltracker.core.database import get_supabase_client
                        _sb = get_supabase_client()
                        new_project = _sb.table("seo_projects").insert({
                            "brand_id": brand_id,
                            "organization_id": _real_org_id,
                            "name": "Imported Articles",
                            "status": "active",
                        }).execute()
                        target_project_id = new_project.data[0]["id"]

                    from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                    cms = CMSPublisherService()
                    result = cms.import_from_shopify(
                        brand_id=brand_id,
                        organization_id=_real_org_id,
                        project_id=target_project_id,
                        public_domain=_import_domain,
                    )
                    st.success(
                        f"Imported {result['imported']} articles "
                        f"(skipped {result['skipped']} existing, "
                        f"{result['total']} total in Shopify)"
                    )
                    if result["imported"] > 0:
                        st.rerun()
                except Exception as e:
                    st.error(f"Import failed: {e}")


# =============================================================================
# TOPIC CLUSTERS SUMMARY
# =============================================================================

st.divider()
st.subheader("Topic Clusters")

try:
    from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
    _cluster_svc = ClusterManagementService()
    if is_brand_view:
        # Aggregate clusters across all projects for this brand
        _clusters = []
        for _p in projects:
            _clusters.extend(_cluster_svc.list_clusters(_p["id"]))
    else:
        _clusters = _cluster_svc.list_clusters(selected_project_id)

    if _clusters:
        _cluster_cols = st.columns(min(len(_clusters), 3))
        for _i, _c in enumerate(_clusters[:6]):
            with _cluster_cols[_i % len(_cluster_cols)]:
                _stats = _c.get("spoke_stats", {})
                _total = _stats.get("total", 0)
                _pub = _stats.get("published", 0)
                with st.container(border=True):
                    st.markdown(f"**{_c['name']}**  `{_c.get('status', 'draft')}`")
                    if _total > 0:
                        st.progress(_pub / _total, text=f"{_pub}/{_total} published")
                    else:
                        st.caption("No spokes")
        if len(_clusters) > 6:
            st.caption(f"... and {len(_clusters) - 6} more clusters")
    else:
        st.info("No topic clusters yet. Create them in the SEO Clusters page.")
except Exception as _e:
    logger.warning(f"Failed to load cluster summary: {_e}")


# =============================================================================
# LINK MANAGEMENT
# =============================================================================

st.divider()
st.subheader("Internal Link Tools")

if is_brand_view:
    st.info("Select a specific project to use link tools.")
else:
    link_tabs = st.tabs(["Suggest Links", "Auto-Link", "Add Related"])

    # Tab 1: Suggest Links
    with link_tabs[0]:
        if not articles:
            st.info("Add articles first to use link suggestions.")
        else:
            article_opts = {a["id"]: a.get("keyword", "Untitled") for a in articles}
            suggest_article = st.selectbox(
                "Article",
                options=list(article_opts.keys()),
                format_func=lambda x: article_opts[x],
                key="seo_dash_suggest_article",
            )
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                min_sim = st.slider("Min Similarity", 0.1, 0.8, 0.2, 0.05, key="seo_dash_min_sim")
            with col_s2:
                max_sugg = st.number_input("Max Suggestions", 1, 20, 5, key="seo_dash_max_sugg")

            if st.button("Get Suggestions", key="seo_dash_suggest_btn"):
                interlinking = get_interlinking_service()
                with st.spinner("Finding related articles..."):
                    try:
                        result = interlinking.suggest_links(
                            suggest_article, min_sim, max_sugg
                        )
                        if result["suggestions"]:
                            for s in result["suggestions"]:
                                priority_icon = "🔥" if s["priority"] == "high" else "💡"
                                st.markdown(
                                    f"{priority_icon} **{s['target_keyword']}** "
                                    f"(similarity: {s['similarity']:.0%}, "
                                    f"placement: {s['placement']})"
                                )
                                if s["anchor_texts"]:
                                    st.caption(f"Anchor: \"{s['anchor_texts'][0]}\"")
                        else:
                            st.info("No related articles found above the similarity threshold.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Tab 2: Auto-Link
    with link_tabs[1]:
        if not articles:
            st.info("Add articles first to use auto-linking.")
        else:
            al_article_opts = {a["id"]: a.get("keyword", "Untitled") for a in articles}
            autolink_article = st.selectbox(
                "Article to auto-link",
                options=list(al_article_opts.keys()),
                format_func=lambda x: al_article_opts[x],
                key="seo_dash_autolink_article",
            )

            if st.button("Run Auto-Link", key="seo_dash_autolink_btn"):
                interlinking = get_interlinking_service()
                with st.spinner("Finding linkable text..."):
                    try:
                        result = interlinking.auto_link_article(autolink_article)
                        if result.get("message"):
                            st.warning(result["message"])
                        elif result["links_added"] > 0:
                            st.success(f"Added {result['links_added']} link(s)")
                            for linked in result.get("linked_articles", []):
                                st.markdown(f"  -> {linked['keyword']} ({linked['links_added']} links)")
                        else:
                            st.info("No linkable text found.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Tab 3: Add Related
    with link_tabs[2]:
        if not articles:
            st.info("Add articles first to use bidirectional linking.")
        else:
            br_article_opts = {a["id"]: a.get("keyword", "Untitled") for a in articles}
            bidir_source = st.selectbox(
                "Source Article",
                options=list(br_article_opts.keys()),
                format_func=lambda x: br_article_opts[x],
                key="seo_dash_bidir_source",
            )
            bidir_targets = st.multiselect(
                "Related Articles",
                options=[aid for aid in br_article_opts if aid != bidir_source],
                format_func=lambda x: br_article_opts[x],
                key="seo_dash_bidir_targets",
            )

            if st.button("Add Related Section", key="seo_dash_bidir_btn"):
                if not bidir_targets:
                    st.warning("Select at least one related article.")
                else:
                    interlinking = get_interlinking_service()
                    with st.spinner("Adding Related Articles section..."):
                        try:
                            result = interlinking.add_related_section(
                                bidir_source, bidir_targets
                            )
                            if result.get("message"):
                                st.warning(result["message"])
                            else:
                                st.success(
                                    f"Added {result['articles_linked']} related article(s) "
                                    f"({result['placement']})"
                                )
                        except Exception as e:
                            st.error(f"Error: {e}")
