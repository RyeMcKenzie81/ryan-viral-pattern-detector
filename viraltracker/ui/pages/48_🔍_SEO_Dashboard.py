"""
SEO Dashboard Page - Overview, KPIs, articles table, and link management.

Provides UI for:
- Project-level KPIs (article counts, keyword counts, link stats)
- Articles table with status and actions
- Internal link management (suggest, auto-link, bidirectional)
- Ranking history display
"""

import logging

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="SEO Dashboard", page_icon="🔍", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


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


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("🔍 SEO Dashboard")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_dashboard_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()

# Project selector
project_service = get_project_service()
projects = project_service.list_projects(org_id, brand_id=brand_id)

if not projects:
    st.info("No SEO projects found. Create one in the Keyword Research page.")
    st.stop()

project_options = {p["id"]: p["name"] for p in projects}
selected_project_id = st.selectbox(
    "SEO Project",
    options=list(project_options.keys()),
    format_func=lambda x: project_options[x],
    key="seo_dash_project_selector",
)


# =============================================================================
# KPIs
# =============================================================================

analytics = get_analytics_service()
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
# ARTICLES TABLE
# =============================================================================

st.divider()
st.subheader("Articles")

tracking = get_tracking_service()
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
    st.info("No articles in this project yet.")


# =============================================================================
# TOPIC CLUSTERS SUMMARY
# =============================================================================

st.divider()
st.subheader("Topic Clusters")

try:
    from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
    _cluster_svc = ClusterManagementService()
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
