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
def _load_gsc_analytics(article_ids_tuple, date_from_str, date_to_str, search_type="all"):
    """Load GSC analytics data scoped to brand articles, optionally filtered by search type."""
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    article_ids = list(article_ids_tuple)
    if not article_ids:
        return []
    query = (
        supabase.table("seo_article_analytics")
        .select("article_id, date, impressions, clicks, ctr, average_position, search_type")
        .eq("source", "gsc")
        .gte("date", date_from_str)
        .lte("date", date_to_str)
        .in_("article_id", article_ids)
        .order("date")
        .limit(5000)
    )
    if search_type != "all":
        query = query.eq("search_type", search_type)
    return query.execute().data or []


@st.cache_data(ttl=300)
def _load_ga4_analytics(article_ids_tuple, date_from_str, date_to_str):
    """Load GA4 analytics data with date range, scoped to articles."""
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    article_ids = list(article_ids_tuple)
    if not article_ids:
        return []
    query = (
        supabase.table("seo_article_analytics")
        .select("article_id, date, sessions, pageviews, avg_time_on_page, bounce_rate")
        .eq("source", "ga4")
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

# Default date range (used by GSC and GA4 sections)
today = datetime.date.today()
date_from = today - datetime.timedelta(days=28)
date_to = today

# --- GSC Performance Report ---
if "gsc" in connected_integrations:
    st.markdown("**Search Performance (Google Search Console)**")

    # Scope toggle + controls row
    scope_col, type_col, ctrl1, ctrl2 = st.columns([0.8, 0.6, 1, 1])
    with scope_col:
        gsc_scope = st.radio(
            "Scope",
            ["Site-wide", "Tracked articles"],
            index=0,
            key="seo_dash_gsc_scope",
            horizontal=True,
        )
    with type_col:
        gsc_search_type = st.selectbox(
            "Search type",
            ["web", "image", "all"],
            index=0,
            format_func=lambda x: {"web": "Web", "image": "Image", "all": "All types"}[x],
            key="seo_dash_search_type",
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
            search_type=gsc_search_type,
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

# GA4 section — traffic data with time series
if "ga4" in connected_integrations:
    ga4_article_ids = all_article_ids  # Include discovered pages
    ga4_rows = _load_ga4_analytics(tuple(ga4_article_ids), date_from.isoformat(), date_to.isoformat())
    if ga4_rows:
        st.markdown("**Traffic (Google Analytics 4)**")
        ga4_df = pd.DataFrame(ga4_rows)
        ga4_df["date"] = pd.to_datetime(ga4_df["date"])
        ga4_df["sessions"] = ga4_df["sessions"].fillna(0).astype(int)
        ga4_df["pageviews"] = ga4_df["pageviews"].fillna(0).astype(int)

        total_sessions = int(ga4_df["sessions"].sum())
        total_pageviews = int(ga4_df["pageviews"].sum())
        avg_bounce = ga4_df["bounce_rate"].mean() if "bounce_rate" in ga4_df.columns else 0.0
        avg_time = ga4_df["avg_time_on_page"].mean() if "avg_time_on_page" in ga4_df.columns else 0.0

        with st.container(border=True):
            g1, g2, g3, g4 = st.columns(4)
            with g1:
                st.metric("Sessions", f"{total_sessions:,}")
            with g2:
                st.metric("Pageviews", f"{total_pageviews:,}")
            with g3:
                st.metric("Avg Bounce Rate", f"{avg_bounce:.1f}%")
            with g4:
                st.metric("Avg Time on Page", f"{avg_time:.0f}s")

        # Daily time series
        ga4_daily = ga4_df.groupby("date").agg(
            sessions=("sessions", "sum"),
            pageviews=("pageviews", "sum"),
        ).reset_index()

        ga4_full_range = pd.date_range(date_from, date_to, freq="D")
        ga4_daily = ga4_daily.set_index("date").reindex(ga4_full_range).reset_index()
        ga4_daily.rename(columns={"index": "date"}, inplace=True)
        ga4_daily["sessions"] = ga4_daily["sessions"].fillna(0).astype(int)
        ga4_daily["pageviews"] = ga4_daily["pageviews"].fillna(0).astype(int)

        ga4_base = alt.Chart(ga4_daily).encode(
            x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d")),
        )
        ga4_layers = [
            ga4_base.mark_line(color="#4285F4", strokeWidth=2).encode(
                y=alt.Y("sessions:Q", title="Sessions"),
                tooltip=[
                    alt.Tooltip("date:T", format="%b %d, %Y"),
                    alt.Tooltip("sessions:Q", format=",", title="Sessions"),
                ],
            ),
            ga4_base.mark_line(color="#34A853", strokeWidth=2).encode(
                y=alt.Y("pageviews:Q", title="Pageviews"),
                tooltip=[
                    alt.Tooltip("date:T", format="%b %d, %Y"),
                    alt.Tooltip("pageviews:Q", format=",", title="Pageviews"),
                ],
            ),
        ]
        ga4_chart = alt.layer(*ga4_layers).resolve_scale(y="independent").properties(height=250)
        st.altair_chart(ga4_chart, use_container_width=True)
    else:
        st.info("GA4 connected. No data yet — click Sync Now or wait for daily sync.")
else:
    with st.container(border=True):
        st.markdown("**Connect Google Analytics 4** to see traffic and engagement data.")
        st.caption(
            "GA4 uses a service account. "
            "[Create one](https://console.cloud.google.com/iam-admin/serviceaccounts) "
            "with Analytics Viewer access, then add the SA email as a viewer on your GA4 property."
        )
        with st.expander("Setup GA4 Connection"):
            ga4_property_id = st.text_input(
                "GA4 Property ID",
                placeholder="e.g. 123456789",
                help="Found in GA4 Admin > Property Settings > Property ID",
                key="seo_dash_ga4_property_id",
            )
            ga4_sa_json = st.text_area(
                "Service Account JSON",
                placeholder='Paste the full JSON key file contents here...',
                height=150,
                key="seo_dash_ga4_sa_json",
            )
            if st.button("Save GA4 Connection", key="seo_dash_ga4_save", type="primary"):
                if not ga4_property_id or not ga4_sa_json:
                    st.warning("Both Property ID and Service Account JSON are required.")
                elif not ga4_property_id.strip().isdigit():
                    st.error("Property ID must be numeric (e.g. 123456789). Find it in GA4 Admin > Property Settings.")
                else:
                    try:
                        import json as _json
                        sa_creds = _json.loads(ga4_sa_json)
                        from viraltracker.core.database import get_supabase_client
                        _sb = get_supabase_client()
                        _sb.table("brand_integrations").upsert(
                            {
                                "brand_id": brand_id,
                                "organization_id": _real_org_id,
                                "platform": "ga4",
                                "config": {
                                    "property_id": ga4_property_id.strip(),
                                    "sa_credentials": sa_creds,
                                },
                            },
                            on_conflict="brand_id,platform",
                        ).execute()
                        st.success(
                            f"GA4 connected! SA email: `{sa_creds.get('client_email', 'unknown')}` — "
                            f"make sure this email has Viewer access on your GA4 property."
                        )
                        st.rerun()
                    except _json.JSONDecodeError:
                        st.error("Invalid JSON. Paste the full service account key file contents.")
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

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
            config = integration.get("config", {})
            detail = ""
            if platform == "gsc":
                detail = f" — {config.get('site_url', '')}"
            elif platform == "ga4":
                detail = f" — Property: {config.get('property_id', '?')}"
            elif platform == "shopify":
                detail = ""
            st.markdown(f"**{platform.upper()}**: Connected{detail}")

        # Edit / Disconnect integrations
        _disconnect_platform = st.selectbox(
            "Manage integration",
            options=[""] + list(connected_integrations.keys()),
            format_func=lambda x: "Select to edit..." if x == "" else f"{x.upper()}",
            key="seo_dash_manage_integration",
        )
        if _disconnect_platform:
            _manage_cols = st.columns(2)
            with _manage_cols[0]:
                if _disconnect_platform == "ga4":
                    _current_config = connected_integrations["ga4"].get("config", {})
                    _new_property_id = st.text_input(
                        "GA4 Property ID",
                        value=_current_config.get("property_id", ""),
                        key="seo_dash_ga4_edit_prop",
                    )
                    if st.button("Update Property ID", key="seo_dash_ga4_update"):
                        if not _new_property_id.strip().isdigit():
                            st.error("Property ID must be numeric (e.g. 123456789)")
                        else:
                            try:
                                from viraltracker.core.database import get_supabase_client
                                _sb = get_supabase_client()
                                _current_config["property_id"] = _new_property_id.strip()
                                _sb.table("brand_integrations").update(
                                    {"config": _current_config}
                                ).eq("brand_id", brand_id).eq("platform", "ga4").execute()
                                st.success("GA4 Property ID updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
            with _manage_cols[1]:
                if st.button(
                    f"Disconnect {_disconnect_platform.upper()}",
                    key="seo_dash_disconnect_btn",
                    type="secondary",
                ):
                    try:
                        from viraltracker.core.database import get_supabase_client
                        _sb = get_supabase_client()
                        _sb.table("brand_integrations").delete().eq(
                            "brand_id", brand_id
                        ).eq("platform", _disconnect_platform).execute()
                        st.success(f"{_disconnect_platform.upper()} disconnected.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

        st.divider()

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
                _load_ga4_analytics.clear()

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
# CONTENT GUIDE
# =============================================================================

with st.expander("Content Guide"):
    from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
    _brand_cfg_svc = SEOBrandConfigService()
    _brand_cfg = _brand_cfg_svc.get_config(brand_id)

    _cfg_style = st.text_area(
        "Content Style Guide",
        value=_brand_cfg.get("content_style_guide", ""),
        height=200,
        placeholder="Write voice/tone instructions with GOOD/BAD examples...",
        key="seo_dash_cfg_style",
    )
    _cfg_product_rules = st.text_area(
        "Product Mention Rules",
        value=_brand_cfg.get("product_mention_rules", ""),
        height=100,
        placeholder="Max mentions, GOOD/BAD examples...",
        key="seo_dash_cfg_product_rules",
    )
    _cfg_image_style = st.text_input(
        "Image Style",
        value=_brand_cfg.get("image_style", ""),
        placeholder="e.g. Shot on iPhone, natural lighting...",
        key="seo_dash_cfg_image_style",
    )
    _cfg_max_mentions = st.number_input(
        "Max Product Mentions",
        value=_brand_cfg.get("max_product_mentions", 2),
        min_value=0, max_value=20,
        key="seo_dash_cfg_max_mentions",
    )

    # Tags editor
    st.markdown("**Available Tags**")
    _cfg_tags = _brand_cfg.get("available_tags") or []
    _tag_container = st.container()
    with _tag_container:
        for ti, tag in enumerate(_cfg_tags):
            tc1, tc2, tc3 = st.columns([1, 2, 2])
            with tc1:
                st.text_input("Name", value=tag.get("name", ""), key=f"seo_dash_tag_name_{ti}", disabled=True)
            with tc2:
                st.text_input("Slug", value=tag.get("slug", ""), key=f"seo_dash_tag_slug_{ti}", disabled=True)
            with tc3:
                st.text_input("Rule", value=tag.get("selection_rule", ""), key=f"seo_dash_tag_rule_{ti}", disabled=True)

    # Author selector — use SEOProjectService instead of raw DB query
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
    _author_svc = SEOProjectService()
    _authors = _author_svc.list_authors(brand_id, _real_org_id)
    _author_opts = {"": "None"} | {a["id"]: a["name"] for a in _authors}
    _current_author = _brand_cfg.get("default_author_id") or ""
    _cfg_author = st.selectbox(
        "Default Author",
        options=list(_author_opts.keys()),
        index=list(_author_opts.keys()).index(_current_author) if _current_author in _author_opts else 0,
        format_func=lambda x: _author_opts[x],
        key="seo_dash_cfg_author",
    )

    # -----------------------------------------------------------------
    # Manage Authors section
    # -----------------------------------------------------------------
    st.divider()
    st.markdown("**Manage Authors**")

    # Initialize session state
    if "seo_dash_author_adding" not in st.session_state:
        st.session_state.seo_dash_author_adding = False
    if "seo_dash_author_editing" not in st.session_state:
        st.session_state.seo_dash_author_editing = None
    if "seo_dash_author_confirm_delete" not in st.session_state:
        st.session_state.seo_dash_author_confirm_delete = None

    _is_adding = st.session_state.seo_dash_author_adding
    _is_editing = st.session_state.seo_dash_author_editing

    # Add Author button
    if not _is_adding:
        if st.button(
            "+ Add Author",
            key="seo_dash_author_add_btn",
            disabled=bool(_is_editing),
        ):
            st.session_state.seo_dash_author_adding = True
            st.rerun()
    else:
        # Inline add form
        with st.form("seo_dash_author_add_form"):
            st.markdown("**New Author**")
            _add_name = st.text_input("Name *", key="seo_dash_author_add_name")
            _add_title = st.text_input("Job Title", key="seo_dash_author_add_title")
            _add_bio = st.text_area("Bio", height=80, key="seo_dash_author_add_bio")
            _add_img = st.text_input("Image URL", key="seo_dash_author_add_img")
            _add_url = st.text_input("Author URL", key="seo_dash_author_add_url")
            _add_col1, _add_col2 = st.columns(2)
            with _add_col1:
                _add_submit = st.form_submit_button("Save", type="primary")
            with _add_col2:
                _add_cancel = st.form_submit_button("Cancel")

            if _add_cancel:
                st.session_state.seo_dash_author_adding = False
                st.rerun()
            if _add_submit:
                if not _add_name or not _add_name.strip():
                    st.error("Author name is required.")
                else:
                    try:
                        _author_svc.create_author(
                            brand_id=brand_id,
                            organization_id=_real_org_id,
                            name=_add_name.strip(),
                            job_title=_add_title.strip() or None,
                            bio=_add_bio.strip() or None,
                            image_url=_add_img.strip() or None,
                            author_url=_add_url.strip() or None,
                        )
                        st.session_state.seo_dash_author_adding = False
                        st.rerun()
                    except Exception as e:
                        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                            st.error("An author with this name already exists.")
                        else:
                            st.error(f"Failed to create author: {e}")

    # Author cards
    for _auth in _authors:
        _aid = _auth["id"]
        _a_name = _auth.get("name", "Unknown")
        _a_title = _auth.get("job_title", "")
        _a_default = _auth.get("is_default", False)
        _confirming_delete = st.session_state.seo_dash_author_confirm_delete == _aid
        _editing_this = _is_editing == _aid

        with st.container(border=True):
            # Header row: name + title + default badge
            _label_parts = [f"**{_a_name}**"]
            if _a_title:
                _label_parts.append(f" · {_a_title}")
            if _a_default:
                _label_parts.append(" · :star: default")
            st.markdown("".join(_label_parts))

            if _editing_this:
                # Inline edit form
                with st.form(f"seo_dash_author_edit_form_{_aid}"):
                    _edit_name = st.text_input(
                        "Name *", value=_a_name,
                        key=f"seo_dash_author_edit_name_{_aid}",
                    )
                    _edit_title = st.text_input(
                        "Job Title", value=_a_title or "",
                        key=f"seo_dash_author_edit_title_{_aid}",
                    )
                    _edit_bio = st.text_area(
                        "Bio", value=_auth.get("bio") or "", height=80,
                        key=f"seo_dash_author_edit_bio_{_aid}",
                    )
                    _edit_img = st.text_input(
                        "Image URL", value=_auth.get("image_url") or "",
                        key=f"seo_dash_author_edit_img_{_aid}",
                    )
                    _edit_url = st.text_input(
                        "Author URL", value=_auth.get("author_url") or "",
                        key=f"seo_dash_author_edit_url_{_aid}",
                    )
                    _ec1, _ec2 = st.columns(2)
                    with _ec1:
                        _edit_submit = st.form_submit_button("Save", type="primary")
                    with _ec2:
                        _edit_cancel = st.form_submit_button("Cancel")

                    if _edit_cancel:
                        st.session_state.seo_dash_author_editing = None
                        st.rerun()
                    if _edit_submit:
                        if not _edit_name or not _edit_name.strip():
                            st.error("Author name is required.")
                        else:
                            try:
                                _author_svc.update_author(
                                    author_id=_aid,
                                    organization_id=_real_org_id,
                                    name=_edit_name.strip(),
                                    job_title=_edit_title.strip() or None,
                                    bio=_edit_bio.strip() or None,
                                    image_url=_edit_img.strip() or None,
                                    author_url=_edit_url.strip() or None,
                                )
                                st.session_state.seo_dash_author_editing = None
                                st.rerun()
                            except Exception as e:
                                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                                    st.error("An author with this name already exists.")
                                else:
                                    st.error(f"Failed to update author: {e}")

            elif _confirming_delete:
                # Delete confirmation
                if _a_default:
                    st.warning(
                        "This author is the default. "
                        "Deleting will clear the default author setting."
                    )
                st.warning(f"Are you sure you want to delete **{_a_name}**?")
                _dc1, _dc2 = st.columns(2)
                with _dc1:
                    if st.button("Yes, delete", key=f"seo_dash_author_confirm_yes_{_aid}", type="primary"):
                        try:
                            _author_svc.delete_author(_aid, brand_id, _real_org_id)
                            st.session_state.seo_dash_author_confirm_delete = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete author: {e}")
                with _dc2:
                    if st.button("No, cancel", key=f"seo_dash_author_confirm_no_{_aid}"):
                        st.session_state.seo_dash_author_confirm_delete = None
                        st.rerun()

            else:
                # Action buttons row
                _btn1, _btn2, _btn3 = st.columns([1, 1, 4])
                with _btn1:
                    if st.button(
                        "Edit", key=f"seo_dash_author_edit_btn_{_aid}",
                        disabled=bool(_is_adding or _is_editing),
                    ):
                        st.session_state.seo_dash_author_editing = _aid
                        st.rerun()
                with _btn2:
                    if st.button(
                        "Delete", key=f"seo_dash_author_del_btn_{_aid}",
                        disabled=bool(_is_adding or _is_editing),
                    ):
                        st.session_state.seo_dash_author_confirm_delete = _aid
                        st.rerun()

    if st.button("Save Content Guide", key="seo_dash_cfg_save", type="primary"):
        try:
            _brand_cfg_svc.upsert_config(
                brand_id=brand_id,
                organization_id=_real_org_id,
                content_style_guide=_cfg_style,
                product_mention_rules=_cfg_product_rules,
                image_style=_cfg_image_style,
                max_product_mentions=int(_cfg_max_mentions),
                default_author_id=_cfg_author or None,
            )
            st.success("Content Guide saved!")
        except Exception as e:
            st.error(f"Failed to save: {e}")


# =============================================================================
# ARTICLES TABLE
# =============================================================================

st.divider()
st.subheader("Articles")

if articles:
    table_data = []
    _CMS_STATUS_MAP = {
        "published": "Live",
        "publishing": "Draft",
    }
    for a in articles:
        status = a.get("status", "")
        cms_status = _CMS_STATUS_MAP.get(status, "—") if a.get("cms_article_id") else "—"
        table_data.append({
            "Keyword": a.get("keyword", "—"),
            "Status": a.get("status", "—"),
            "Shopify": cms_status,
            "Phase": (a.get("phase") or "—").upper(),
            "CMS ID": (a.get("cms_article_id") or "—")[:12],
            "Published URL": a.get("published_url") or "—",
        })
    st.dataframe(table_data, use_container_width=True)
else:
    st.info("No articles yet.")

# "Write about this" for discovered pages
if discovered_articles:
    with st.expander("Discovered Pages (GSC)"):
        st.caption("Pages found in Google Search Console that aren't tracked articles.")
        for da in discovered_articles[:20]:
            da_kw = da.get("keyword", "unknown")
            da_url = da.get("published_url", "")
            dc1, dc2 = st.columns([3, 1])
            with dc1:
                st.markdown(f"**{da_kw}** — {da_url}")
            with dc2:
                if st.button("Write about this", key=f"seo_dash_write_{da['id'][:8]}"):
                    st.session_state["seo_prefill_keyword"] = da_kw
                    st.switch_page("pages/53_🚀_SEO_Workflow.py")

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
