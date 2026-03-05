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

import json
import logging

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

        # Resolve actual org_id from brand when superuser has org_id="all"
        org_id = state_data["org_id"]
        if org_id == "all":
            from viraltracker.core.database import get_supabase_client
            _sb = get_supabase_client()
            brand_row = _sb.table("brands").select("organization_id").eq("id", state_data["brand_id"]).execute()
            if brand_row.data:
                org_id = brand_row.data[0]["organization_id"]
            else:
                raise ValueError(f"Brand {state_data['brand_id']} not found")

        gsc.save_integration(
            brand_id=state_data["brand_id"],
            organization_id=org_id,
            site_url=state_data.get("site_url", ""),
            tokens=tokens,
        )
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
# EXTERNAL ANALYTICS
# =============================================================================

st.divider()
st.subheader("Analytics")


def _load_analytics_data():
    """Load external analytics data if any integrations exist."""
    try:
        from viraltracker.core.database import get_supabase_client
        supabase = get_supabase_client()

        # Check which integrations exist
        integrations_query = (
            supabase.table("brand_integrations")
            .select("platform, config")
            .eq("brand_id", brand_id)
        )
        if org_id != "all":
            integrations_query = integrations_query.eq("organization_id", org_id)
        integrations = integrations_query.execute().data or []

        connected = {i["platform"]: i for i in integrations}

        # Load analytics data if any exists
        analytics_data = []
        if connected:
            query = (
                supabase.table("seo_article_analytics")
                .select("*")
                .order("date", desc=True)
                .limit(200)
            )
            if org_id != "all":
                query = query.eq("organization_id", org_id)
            analytics_data = query.execute().data or []

        return connected, analytics_data
    except Exception as e:
        logger.warning(f"Failed to load analytics data: {e}")
        return {}, []


connected_integrations, analytics_rows = _load_analytics_data()

# GSC section
if "gsc" in connected_integrations:
    gsc_data = [r for r in analytics_rows if r.get("source") == "gsc"]
    if gsc_data:
        st.markdown("**Search Performance (Google Search Console)**")
        gsc_totals = {"impressions": 0, "clicks": 0}
        for row in gsc_data:
            gsc_totals["impressions"] += row.get("impressions", 0)
            gsc_totals["clicks"] += row.get("clicks", 0)
        avg_ctr = (gsc_totals["clicks"] / gsc_totals["impressions"] * 100) if gsc_totals["impressions"] else 0

        g1, g2, g3 = st.columns(3)
        with g1:
            st.metric("Impressions", f"{gsc_totals['impressions']:,}")
        with g2:
            st.metric("Clicks", f"{gsc_totals['clicks']:,}")
        with g3:
            st.metric("Avg CTR", f"{avg_ctr:.1f}%")
    else:
        st.info("GSC connected. No data yet — click Sync Now or wait for daily sync.")
else:
    with st.container(border=True):
        st.markdown("**Connect Google Search Console** to see real ranking and click data.")
        with st.expander("Connect GSC"):
            st.markdown(
                "Enter your Search Console site URL below. "
                "You'll be redirected to Google to authorize access."
            )
            gsc_site_url = st.text_input("Site URL", placeholder="https://example.com", key="seo_dash_gsc_site")
            if st.button("Connect GSC", key="seo_dash_gsc_connect"):
                if gsc_site_url:
                    try:
                        import secrets
                        from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
                        gsc = GSCService()
                        nonce = secrets.token_urlsafe(16)
                        state = gsc.encode_oauth_state(brand_id, org_id, nonce, site_url=gsc_site_url)
                        redirect_uri = _get_oauth_redirect_uri()
                        auth_url = gsc.get_authorization_url(redirect_uri, state)
                        st.markdown(f"[Authorize with Google]({auth_url})")
                    except Exception as e:
                        st.error(f"Failed: {e}")
                else:
                    st.warning("Enter your site URL first.")

# GA4 section
if "ga4" in connected_integrations:
    ga4_data = [r for r in analytics_rows if r.get("source") == "ga4"]
    if ga4_data:
        st.markdown("**Traffic (Google Analytics 4)**")
        ga4_totals = {"sessions": 0, "pageviews": 0}
        for row in ga4_data:
            ga4_totals["sessions"] += row.get("sessions", 0)
            ga4_totals["pageviews"] += row.get("pageviews", 0)

        t1, t2 = st.columns(2)
        with t1:
            st.metric("Sessions", f"{ga4_totals['sessions']:,}")
        with t2:
            st.metric("Pageviews", f"{ga4_totals['pageviews']:,}")
    else:
        st.info("GA4 connected. No data yet — click Sync Now or wait for daily sync.")

# Shopify conversions section
if "shopify" in connected_integrations:
    shopify_data = [r for r in analytics_rows if r.get("source") == "shopify"]
    if shopify_data:
        st.markdown("**Conversions (Shopify)**")
        shop_totals = {"conversions": 0, "revenue": 0.0}
        for row in shopify_data:
            shop_totals["conversions"] += row.get("conversions", 0)
            shop_totals["revenue"] += float(row.get("revenue", 0))

        s1, s2 = st.columns(2)
        with s1:
            st.metric("Conversions", shop_totals["conversions"])
        with s2:
            st.metric("Revenue", f"${shop_totals['revenue']:,.2f}")

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

                for source, result in results.items():
                    if "error" in result:
                        st.error(f"{source.upper()}: {result['error']}")
                    else:
                        st.success(f"{source.upper()}: synced {result.get('analytics_rows', 0)} rows")


# =============================================================================
# ARTICLES TABLE
# =============================================================================

st.divider()
st.subheader("Articles")

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
