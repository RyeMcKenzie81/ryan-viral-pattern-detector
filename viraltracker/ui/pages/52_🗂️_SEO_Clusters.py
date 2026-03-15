"""
SEO Clusters Page - Topic cluster management, keyword pool, and performance.

Provides UI for:
- Cluster overview (list) and detail view (view-switch)
- Keyword pool with assignment, auto-assign, and pre-write check
- Performance tracking with ranking trends
"""

import logging

import streamlit as st

from viraltracker.ui.auth import require_auth
from viraltracker.services.seo_pipeline.models import (
    ClusterStatus,
    ClusterIntent,
    SpokeRole,
    SpokeStatus,
)

st.set_page_config(page_title="SEO Clusters", page_icon="🗂️", layout="wide")
require_auth()

logger = logging.getLogger(__name__)

# Enum-derived constants for UI dropdowns
CLUSTER_STATUSES = [e.value for e in ClusterStatus]
CLUSTER_INTENTS = [e.value for e in ClusterIntent]


# =============================================================================
# HELPERS
# =============================================================================

def get_project_service():
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
    return SEOProjectService()


def get_cluster_service():
    from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
    return ClusterManagementService()


def get_analytics_service():
    from viraltracker.services.seo_pipeline.services.seo_analytics_service import SEOAnalyticsService
    return SEOAnalyticsService()


def get_interlinking_service():
    from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
    return InterlinkingService()


STATUS_COLORS = {
    ClusterStatus.DRAFT.value: "gray",
    ClusterStatus.ACTIVE.value: "blue",
    ClusterStatus.PUBLISHING.value: "orange",
    ClusterStatus.COMPLETE.value: "green",
    ClusterStatus.ARCHIVED.value: "red",
}

SPOKE_STATUS_ICONS = {
    SpokeStatus.PLANNED.value: "⬜",
    SpokeStatus.WRITING.value: "🟡",
    SpokeStatus.PUBLISHED.value: "🟢",
    SpokeStatus.SKIPPED.value: "⚫",
}


# =============================================================================
# SESSION STATE
# =============================================================================

def init_session_state():
    defaults = {
        "seo_view": "overview",
        "seo_selected_cluster_id": None,
        "seo_filter_status": "all",
        "seo_sort_by": "name",
        "seo_creating": False,
        "seo_confirm_delete": None,
        "seo_kw_filter": "unassigned",
        "seo_kw_intent": "all",
        "seo_kw_search": "",
        "seo_auto_assign_results": None,
        "seo_perf_days": 30,
        "seo_perf_cluster": "all",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


# =============================================================================
# CLUSTER OVERVIEW
# =============================================================================

def render_cluster_overview(project_id):
    """Render cluster list with cards and metrics."""
    svc = get_cluster_service()
    clusters = svc.list_clusters(project_id)

    # Metrics row
    total_clusters = len(clusters)
    total_spokes = sum(c.get("spoke_stats", {}).get("total", 0) for c in clusters)
    total_published = sum(c.get("spoke_stats", {}).get("published", 0) for c in clusters)
    pub_pct = round(total_published / total_spokes * 100) if total_spokes > 0 else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Clusters", total_clusters)
    m2.metric("Total Spokes", total_spokes)
    m3.metric("Published", f"{total_published}/{total_spokes} ({pub_pct}%)")

    # Filter / sort / create row
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    with fc1:
        filter_status = st.selectbox(
            "Status", ["all"] + CLUSTER_STATUSES,
            key="seo_filter_status",
        )
    with fc2:
        sort_by = st.selectbox("Sort by", ["name", "created_at"], key="seo_sort_by")
    with fc3:
        st.write("")  # spacer
        if st.button("+ New Cluster", key="seo_new_cluster_btn"):
            st.session_state.seo_creating = True

    # Create cluster dialog
    if st.session_state.seo_creating:
        _render_create_cluster_form(project_id)

    # Empty state
    if not clusters:
        st.info("No clusters yet. Create your first topic cluster.")
        return

    # Filter
    filtered = clusters
    if filter_status != "all":
        filtered = [c for c in filtered if c.get("status") == filter_status]

    # Sort
    if sort_by == "name":
        filtered.sort(key=lambda c: c.get("name", "").lower())
    else:
        filtered.sort(key=lambda c: c.get("created_at", ""), reverse=True)

    # Render cluster cards
    for cluster in filtered:
        _render_cluster_card(cluster)


def _render_create_cluster_form(project_id):
    """Render the new cluster creation form."""
    with st.container(border=True):
        st.subheader("Create New Cluster")
        name = st.text_input("Cluster Name", key="seo_new_cluster_name")
        c1, c2 = st.columns(2)
        with c1:
            pillar_kw = st.text_input("Pillar Keyword", key="seo_new_cluster_pillar")
        with c2:
            intent = st.selectbox(
                "Intent",
                CLUSTER_INTENTS,
                key="seo_new_cluster_intent",
            )
        description = st.text_area("Description (optional)", key="seo_new_cluster_desc")
        target = st.number_input("Target Spoke Count", 0, 100, 0, key="seo_new_cluster_target")

        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("Create", key="seo_create_cluster_confirm"):
                if not name:
                    st.error("Name is required.")
                else:
                    try:
                        svc = get_cluster_service()
                        svc.create_cluster(
                            project_id, name,
                            pillar_keyword=pillar_kw or None,
                            intent=intent,
                            description=description or None,
                            target_spoke_count=target,
                        )
                        st.session_state.seo_creating = False
                        st.success(f"Created cluster: {name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        with bc2:
            if st.button("Cancel", key="seo_create_cluster_cancel"):
                st.session_state.seo_creating = False
                st.rerun()


def _render_cluster_card(cluster):
    """Render a single cluster card."""
    stats = cluster.get("spoke_stats", {})
    total = stats.get("total", 0)
    published = stats.get("published", 0)
    status = cluster.get("status", ClusterStatus.DRAFT.value)
    intent = cluster.get("intent", ClusterIntent.INFORMATIONAL.value)

    with st.container(border=True):
        hc1, hc2 = st.columns([4, 1])
        with hc1:
            st.markdown(f"**{cluster['name']}**  `{intent}`  `{status}`")
            pillar = cluster.get("pillar_keyword")
            if pillar:
                st.caption(f"Pillar: {pillar}")

            # Progress bar
            if total > 0:
                progress = published / total
                st.progress(progress, text=f"{published}/{total} spokes published")
            else:
                st.caption("No spokes assigned")

        with hc2:
            if st.button("Open →", key=f"seo_open_{cluster['id']}"):
                st.session_state.seo_view = "detail"
                st.session_state.seo_selected_cluster_id = cluster["id"]
                st.rerun()


# =============================================================================
# CLUSTER DETAIL
# =============================================================================

def render_cluster_detail(project_id):
    """Render the detail view for a single cluster."""
    cluster_id = st.session_state.seo_selected_cluster_id
    svc = get_cluster_service()

    # Back button
    if st.button("← Back to Overview", key="seo_back_to_overview"):
        st.session_state.seo_view = "overview"
        st.session_state.seo_selected_cluster_id = None
        st.rerun()

    cluster = svc.get_cluster(cluster_id)
    if not cluster:
        st.error("Cluster not found.")
        return

    # Header
    status = cluster.get("status", ClusterStatus.DRAFT.value)
    intent = cluster.get("intent", ClusterIntent.INFORMATIONAL.value)
    st.markdown(f"# {cluster['name']}  `{intent}`  `{status}`")

    pillar = cluster.get("pillar_keyword")
    if pillar:
        pillar_status = cluster.get("pillar_status", SpokeStatus.PLANNED.value)
        st.markdown(f"Pillar: **{pillar}**  Status: `{pillar_status}`")

    # Health metrics
    health = svc.get_cluster_health(cluster_id)
    hc1, hc2, hc3, hc4 = st.columns(4)
    hc1.metric("Completion", f"{health['completion_pct']}%")
    hc2.metric("Published", health["published"])
    hc3.metric("Writing", health["writing"])
    hc4.metric("Planned", health["planned"])

    if health["completion_pct"] > 0:
        st.progress(health["completion_pct"] / 100)

    # Edit / Delete actions
    ec1, ec2 = st.columns([1, 1])
    with ec1:
        with st.popover("Edit Cluster"):
            new_status = st.selectbox(
                "Status", CLUSTER_STATUSES,
                index=CLUSTER_STATUSES.index(status),
                key="seo_edit_status",
            )
            new_intent = st.selectbox(
                "Intent", CLUSTER_INTENTS,
                index=CLUSTER_INTENTS.index(intent),
                key="seo_edit_intent",
            )
            new_desc = st.text_area("Description", value=cluster.get("description") or "", key="seo_edit_desc")
            if st.button("Save", key="seo_save_cluster_edit"):
                updates = {}
                if new_status != status:
                    updates["status"] = new_status
                if new_intent != intent:
                    updates["intent"] = new_intent
                if new_desc != (cluster.get("description") or ""):
                    updates["description"] = new_desc
                if updates:
                    svc.update_cluster(cluster_id, **updates)
                    st.success("Updated.")
                    st.rerun()

    with ec2:
        if st.session_state.seo_confirm_delete == cluster_id:
            st.warning(f"This will remove {health['total_spokes']} spoke(s). Are you sure?")
            dc1, dc2 = st.columns(2)
            with dc1:
                if st.button("Confirm Delete", key="seo_confirm_delete_btn", type="primary"):
                    svc.delete_cluster(cluster_id)
                    st.session_state.seo_view = "overview"
                    st.session_state.seo_selected_cluster_id = None
                    st.session_state.seo_confirm_delete = None
                    st.rerun()
            with dc2:
                if st.button("Cancel", key="seo_cancel_delete_btn"):
                    st.session_state.seo_confirm_delete = None
                    st.rerun()
        else:
            if st.button("Delete Cluster", key="seo_delete_cluster_btn"):
                st.session_state.seo_confirm_delete = cluster_id

    st.divider()

    # --- Section 1: Next Article Suggestions ---
    st.subheader("Next Article to Write")
    suggestions = svc.suggest_next_article(project_id, cluster_id=cluster_id)
    if suggestions:
        for i, s in enumerate(suggestions):
            with st.container(border=True):
                sc1, sc2 = st.columns([3, 1])
                with sc1:
                    st.markdown(f"**{s['keyword']}**")
                    st.caption(
                        f"Score: {s['score']:.0f} | KD: {s['kd']:.0f} | "
                        f"Vol: {s['volume']:,}/mo | Priority: {s['priority']}"
                    )
                    for reason in s.get("reasons", []):
                        st.caption(f"  {reason}")
                with sc2:
                    pass  # Could add "Start Writing" button linked to Article Writer
    else:
        st.info("No planned spokes to suggest. All articles may already be in progress or published.")

    st.divider()

    # --- Section 2: Spoke Articles Table ---
    st.subheader("Spoke Articles")
    spokes = cluster.get("spokes", [])
    if spokes:
        # Status grid
        status_line = " ".join(SPOKE_STATUS_ICONS.get(s.get("status", SpokeStatus.PLANNED.value), "⬜") for s in spokes)
        st.caption(f"Status: {status_line}  (⬜planned 🟡writing 🟢published ⚫skipped)")

        table_data = []
        for spoke in spokes:
            kw_data = spoke.get("seo_keywords") or {}
            table_data.append({
                "Status": SPOKE_STATUS_ICONS.get(spoke.get("status", SpokeStatus.PLANNED.value), "⬜"),
                "Role": spoke.get("role", SpokeRole.SPOKE.value),
                "Keyword": kw_data.get("keyword", "—"),
                "Priority": spoke.get("priority", 2),
                "KD": kw_data.get("keyword_difficulty") or "—",
                "Volume": kw_data.get("search_volume") or "—",
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)
    else:
        st.info("No spokes assigned. Add keywords from the Keyword Pool tab.")

    # --- Section 3: Link Health (collapsed) ---
    with st.expander("Link Health"):
        _render_link_health(cluster_id)

    # --- Section 4: Gap Analysis (collapsed) ---
    with st.expander("Gap Analysis"):
        if st.button("Analyze Gaps", key="seo_analyze_gaps_btn"):
            with st.spinner("Analyzing..."):
                try:
                    gaps = svc.analyze_gaps(cluster_id)
                    if gaps:
                        for gap in gaps:
                            gc1, gc2 = st.columns([3, 1])
                            with gc1:
                                st.text(
                                    f"{gap['suggested_keyword']}  "
                                    f"(vol: {gap.get('search_volume') or '?'}, "
                                    f"KD: {gap.get('keyword_difficulty') or '?'})"
                                )
                                st.caption(gap.get("reason", ""))
                    else:
                        st.info("No gap keywords found.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Section 5: Import Articles (collapsed) ---
    with st.expander("Import Existing Articles"):
        st.caption("Paste article data (one per line): keyword | title | url")
        import_text = st.text_area("Articles", key="seo_import_text", height=150)
        if st.button("Import", key="seo_import_btn"):
            if import_text.strip():
                article_data = []
                for line in import_text.strip().split("\n"):
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        article_data.append({
                            "keyword": parts[0],
                            "title": parts[1],
                            "url": parts[2],
                            "brand_id": brand_id,
                            "organization_id": org_id,
                        })
                if article_data:
                    try:
                        results = svc.import_existing_articles(cluster_id, article_data)
                        st.success(f"Imported {len(results)} article(s)")
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("No valid lines found. Format: keyword | title | url")

    # --- Section 6: Publication Schedule (collapsed) ---
    with st.expander("Publication Schedule"):
        sc1, sc2 = st.columns(2)
        with sc1:
            rate = st.number_input("Spokes per week", 1, 7, 3, key="seo_schedule_rate")
        with sc2:
            start = st.date_input("Start date", key="seo_schedule_start")
        if st.button("Generate Schedule", key="seo_gen_schedule_btn"):
            schedule = svc.generate_publication_schedule(
                cluster_id, spokes_per_week=rate, start_date=start.isoformat(),
            )
            if schedule:
                st.dataframe(
                    [{"Week": s["week_number"], "Date": s["target_date"],
                      "Keyword": s["keyword"], "Role": s["role"]}
                     for s in schedule],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No planned spokes to schedule.")


def _render_link_health(cluster_id):
    """Render link health audit for a cluster."""
    svc = get_cluster_service()
    audit = svc.get_interlinking_audit(cluster_id)

    if audit.get("message"):
        st.info(audit["message"])
        return

    st.metric("Link Coverage", f"{audit['coverage_pct']}%")
    st.caption(f"{audit['total_linked']}/{audit['total_possible']} possible links exist")

    missing = audit.get("missing_links", [])
    if missing:
        st.markdown("**Missing links (similarity >= 0.2):**")
        for link in missing[:10]:
            st.caption(
                f"{link['source_keyword']} → {link['target_keyword']}  "
                f"(similarity: {link['similarity']:.0%})"
            )

    st.caption(
        "Adds contextual links between all published articles in this cluster, "
        "prioritizes pillar-to-spoke connections, and rebuilds Related Articles sections."
    )
    push_cms = st.checkbox(
        "Push to CMS",
        value=False,
        key="seo_cluster_interlink_push",
        help="Update live Shopify articles with the new links. Only affects published articles.",
    )
    if st.button("Interlink Cluster", key="seo_cluster_interlink_btn", type="primary"):
        interlinking = get_interlinking_service()
        with st.spinner("Interlinking cluster (pillar-first, related sections)..."):
            try:
                result = interlinking.interlink_cluster(
                    cluster_id,
                    push_to_cms=push_cms,
                    brand_id=brand_id,
                    organization_id=org_id,
                )
                st.success(
                    f"Processed {result['articles_processed']} articles: "
                    f"{result['links_added']} links, "
                    f"{result['related_sections_added']} related sections"
                )
                if result.get("errors"):
                    for err in result["errors"]:
                        st.warning(f"Error on {err.get('article_id', '?')}: {err.get('error', '')}")
            except Exception as e:
                st.error(f"Cluster interlinking failed: {str(e)[:200]}")


# =============================================================================
# KEYWORD POOL TAB
# =============================================================================

def render_keyword_pool(project_id):
    """Render keyword pool with filtering, assignment, auto-assign, and pre-write check."""
    svc = get_cluster_service()

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        kw_filter = st.selectbox(
            "Show", ["unassigned", "all", "assigned"],
            key="seo_kw_filter",
        )
    with fc2:
        kw_intent = st.selectbox(
            "Intent", ["all"] + CLUSTER_INTENTS,
            key="seo_kw_intent",
        )
    with fc3:
        kw_search = st.text_input("Search", key="seo_kw_search")

    # Fetch keywords via service
    keywords = svc.get_keywords_for_pool(
        project_id,
        filter_type=kw_filter,
        intent=kw_intent,
        search_text=kw_search,
    )

    if not keywords:
        if kw_filter == "unassigned":
            st.info("No unassigned keywords. Run keyword discovery first.")
        else:
            st.info("No keywords match the current filters.")
        return

    # Display as selectable table
    st.caption(f"{len(keywords)} keywords")

    # Cluster assignment bar
    clusters = svc.list_clusters(project_id)
    if clusters:
        ac1, ac2, ac3 = st.columns([3, 2, 1])
        with ac1:
            cluster_opts = {c["id"]: c["name"] for c in clusters}
            assign_cluster = st.selectbox(
                "Assign to cluster",
                options=list(cluster_opts.keys()),
                format_func=lambda x: cluster_opts[x],
                key="seo_kw_assign_cluster",
            )
        with ac2:
            selected_kw_ids = st.multiselect(
                "Select keywords",
                options=[k["id"] for k in keywords],
                format_func=lambda x: next(
                    (k["keyword"] for k in keywords if k["id"] == x), x
                ),
                key="seo_kw_selected",
            )
        with ac3:
            st.write("")
            if st.button("Assign", key="seo_kw_assign_btn"):
                if selected_kw_ids and assign_cluster:
                    with st.spinner("Assigning..."):
                        results = svc.bulk_assign_keywords(assign_cluster, selected_kw_ids)
                        st.success(f"Assigned {len(results)} keyword(s)")
                        st.rerun()
                else:
                    st.warning("Select keywords and a cluster.")

    # Keywords table
    table_data = []
    for k in keywords:
        table_data.append({
            "Keyword": k.get("keyword", ""),
            "Volume": k.get("search_volume") or "—",
            "KD": k.get("keyword_difficulty") or "—",
            "Intent": k.get("search_intent") or "—",
            "Cluster": k.get("cluster_id") or "—",
            "Status": k.get("status", "discovered"),
        })
    st.dataframe(table_data, use_container_width=True, hide_index=True)

    # --- Auto-Assign expander ---
    with st.expander("Auto-Assign Keywords"):
        st.caption("Automatically assign unassigned keywords to clusters based on word overlap scoring.")
        if st.button("Run Auto-Assign (Preview)", key="seo_auto_assign_btn"):
            with st.spinner("Analyzing keyword-cluster matches..."):
                results = svc.auto_assign_keywords(project_id, dry_run=True)
                st.session_state.seo_auto_assign_results = results

        if st.session_state.seo_auto_assign_results:
            results = st.session_state.seo_auto_assign_results
            if not results:
                st.info("No keywords could be matched to clusters.")
            else:
                high = [r for r in results if r["confidence"] == "HIGH"]
                medium = [r for r in results if r["confidence"] == "MEDIUM"]
                low = [r for r in results if r["confidence"] == "LOW"]

                if high:
                    st.markdown(f"**HIGH confidence ({len(high)})** — will auto-assign")
                    for r in high:
                        st.caption(f"  {r['keyword']} → {r['cluster_name']} (score: {r['score']})")

                if medium:
                    st.markdown(f"**MEDIUM confidence ({len(medium)})** — review recommended")
                    for r in medium:
                        alts = ", ".join(a["cluster_name"] for a in r.get("alternatives", []))
                        st.caption(
                            f"  {r['keyword']} → {r['cluster_name']} (score: {r['score']})"
                            + (f"  Alternatives: {alts}" if alts else "")
                        )

                if low:
                    st.markdown(f"**LOW confidence ({len(low)})** — skipped")

                if high:
                    if st.button("Confirm Assignments", key="seo_confirm_auto_assign"):
                        with st.spinner("Assigning..."):
                            svc.auto_assign_keywords(project_id, dry_run=False)
                            st.session_state.seo_auto_assign_results = None
                            st.success(f"Assigned {len(high)} keyword(s)")
                            st.rerun()

    # --- Pre-Write Check expander ---
    with st.expander("Pre-Write Check"):
        st.caption("Check for content overlap before writing a new article.")
        check_kw = st.text_input("Keyword to check", key="seo_prewrite_keyword")
        if st.button("Check", key="seo_prewrite_btn"):
            if check_kw:
                result = svc.pre_write_check(check_kw, project_id)
                risk = result["risk_level"]
                if risk == "HIGH":
                    st.error(f"Risk: {risk}")
                elif risk == "MEDIUM":
                    st.warning(f"Risk: {risk}")
                else:
                    st.success(f"Risk: {risk}")

                st.markdown(result["recommendation"])

                if result["overlapping_articles"]:
                    st.markdown("**High overlap articles:**")
                    for a in result["overlapping_articles"]:
                        st.caption(f"  {a['keyword']} ({a['overlap_pct']}% overlap) — {a['status']}")

                if result["link_candidates"]:
                    st.markdown("**Link candidates:**")
                    for a in result["link_candidates"]:
                        st.caption(f"  {a['keyword']} ({a['overlap_pct']}% overlap)")


# =============================================================================
# PERFORMANCE TAB
# =============================================================================

def render_performance(project_id):
    """Render ranking trends and cluster performance summary."""
    svc = get_cluster_service()

    # Time range filter
    pc1, pc2 = st.columns(2)
    with pc1:
        days = st.selectbox("Time range", [7, 30, 90], index=1, key="seo_perf_days",
                            format_func=lambda x: f"{x} days")
    with pc2:
        clusters = svc.list_clusters(project_id)
        cluster_opts = {"all": "All Clusters"}
        for c in clusters:
            cluster_opts[c["id"]] = c["name"]
        perf_cluster = st.selectbox(
            "Cluster", list(cluster_opts.keys()),
            format_func=lambda x: cluster_opts[x],
            key="seo_perf_cluster",
        )

    # Get ranking data
    analytics = get_analytics_service()
    try:
        rankings = analytics.get_ranking_history(project_id, days=days)
    except Exception:
        rankings = []

    if rankings:
        try:
            import pandas as pd
            import plotly.express as px

            df = pd.DataFrame(rankings)
            if "keyword" in df.columns and "position" in df.columns and "checked_at" in df.columns:
                fig = px.line(
                    df, x="checked_at", y="position", color="keyword",
                    title="Ranking Trends",
                )
                fig.update_yaxes(autorange="reversed", title="Position")
                fig.update_xaxes(title="Date")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Ranking data format not recognized.")
        except ImportError:
            st.warning("Install plotly for ranking charts: pip install plotly")
    else:
        st.info("No ranking data yet. Rankings are tracked after articles are published.")

    # Cluster performance summary table
    if clusters:
        st.subheader("Cluster Performance")
        perf_data = []
        for c in clusters:
            if perf_cluster != "all" and c["id"] != perf_cluster:
                continue
            stats = c.get("spoke_stats", {})
            perf_data.append({
                "Cluster": c["name"],
                "Articles": stats.get("total", 0),
                "Published": stats.get("published", 0),
                "Writing": stats.get("writing", 0),
                "Planned": stats.get("planned", 0),
            })
        if perf_data:
            st.dataframe(perf_data, use_container_width=True, hide_index=True)


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("🗂️ SEO Clusters")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_clusters_brand_selector")
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
    key="seo_clusters_project_selector",
)

# Tabs
tab_clusters, tab_pool, tab_perf = st.tabs(["Clusters", "Keyword Pool", "Performance"])

with tab_clusters:
    if st.session_state.seo_view == "detail" and st.session_state.seo_selected_cluster_id:
        render_cluster_detail(selected_project_id)
    else:
        render_cluster_overview(selected_project_id)

with tab_pool:
    render_keyword_pool(selected_project_id)

with tab_perf:
    render_performance(selected_project_id)
