"""
SEO Workflow Page — Quick Write and Cluster Builder.

Quick Write: keyword -> complete Shopify draft (zero-pause or step-through)
Cluster Builder: research topic -> AI clusters -> batch generate articles

Article Writer gives manual control over each phase. Quick Write automates the full process.
"""

import datetime
import logging
import time

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="SEO Workflow", page_icon="🚀", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# SERVICE HELPERS
# =============================================================================

def _get_workflow_service():
    from viraltracker.services.seo_pipeline.services.seo_workflow_service import SEOWorkflowService
    return SEOWorkflowService()


def _get_brand_config_service():
    from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
    return SEOBrandConfigService()


def _get_tracking_service():
    from viraltracker.services.seo_pipeline.services.article_tracking_service import ArticleTrackingService
    return ArticleTrackingService()


# =============================================================================
# AUTH & BRAND SELECTION
# =============================================================================

from viraltracker.ui.utils import render_brand_selector
org_id = st.session_state.get("organization_id", "all")
brand_id = render_brand_selector(key="seo_workflow_brand")
if not brand_id:
    st.stop()

# Cleanup stale jobs on page load
workflow_svc = _get_workflow_service()
workflow_svc.cleanup_stale_jobs()

# Check for active jobs
active_jobs = workflow_svc.get_active_jobs(brand_id)
if active_jobs:
    with st.container(border=True):
        st.markdown(f"**{len(active_jobs)} active job(s)** for this brand")
        for job in active_jobs:
            config = job.get("config", {})
            progress = job.get("progress", {})
            kw = config.get("keyword", "unknown")
            pct = progress.get("percent", 0)
            step_label = progress.get("current_step_label", "")
            st.markdown(f"- **{kw}** — {job['status']} ({pct}%) — {step_label}")

# First-run check: warn if no brand config
brand_config_svc = _get_brand_config_service()
brand_config = brand_config_svc.get_config(brand_id)
if not brand_config.get("content_style_guide"):
    st.warning(
        "No Content Guide configured for this brand. "
        "Set up your style guide, tags, and image style in the SEO Dashboard settings "
        "for best results."
    )

# Check for pre-filled keyword from other pages
prefill_keyword = st.session_state.pop("seo_prefill_keyword", "")

# =============================================================================
# TABS
# =============================================================================

tab_qw, tab_cluster = st.tabs(["Quick Write", "Cluster Builder"])


# =============================================================================
# TAB 1: QUICK WRITE
# =============================================================================

with tab_qw:
    st.caption(
        "Article Writer gives you manual control over each phase. "
        "Quick Write automates the full process."
    )

    with st.form("quick_write_form"):
        keyword = st.text_input(
            "Keyword",
            value=prefill_keyword,
            max_chars=200,
            help="2-200 characters. The article will target this keyword.",
            key="seo_wf_keyword",
        )

        # Author selector
        from viraltracker.core.database import get_supabase_client
        _sb = get_supabase_client()
        authors = (
            _sb.table("seo_authors")
            .select("id, name")
            .eq("brand_id", brand_id)
            .execute()
        ).data or []
        author_options = {a["id"]: a["name"] for a in authors}
        default_author = brand_config.get("default_author_id")

        if author_options:
            author_ids = list(author_options.keys())
            default_idx = author_ids.index(default_author) if default_author in author_ids else 0
            author_id = st.selectbox(
                "Author",
                options=author_ids,
                index=default_idx,
                format_func=lambda x: author_options[x],
                key="seo_wf_author",
            )
        else:
            author_id = None
            st.caption("No authors configured. Add authors in the SEO Dashboard.")

        # Tags
        available_tags = brand_config.get("available_tags") or []
        if available_tags:
            tag_options = ["Auto-select"] + [t["slug"] for t in available_tags]
            tag_format = {"Auto-select": "Auto-select (AI chooses)"}
            tag_format.update({t["slug"]: t.get("name", t["slug"]) for t in available_tags})
            selected_tags = st.multiselect(
                "Tags",
                options=tag_options,
                default=["Auto-select"],
                format_func=lambda x: tag_format.get(x, x),
                key="seo_wf_tags",
            )
            tags = None if "Auto-select" in selected_tags else selected_tags
        else:
            tags = None
            st.caption("No tags configured. Tags will be auto-selected if available.")

        col1, col2 = st.columns(2)
        with col1:
            step_through = st.checkbox(
                "Step-through mode",
                help="Pause at each major step for review",
                key="seo_wf_step_through",
            )
        with col2:
            competitor_urls_text = st.text_area(
                "Competitor URLs (optional)",
                height=80,
                help="One URL per line. Skip to auto-detect competitors.",
                key="seo_wf_competitors",
            )

        submitted = st.form_submit_button("Generate", type="primary")

    if submitted and keyword:
        keyword = keyword.strip()
        if len(keyword) < 2:
            st.error("Keyword must be at least 2 characters.")
        else:
            # Parse competitor URLs
            competitor_urls = None
            if competitor_urls_text.strip():
                competitor_urls = [
                    u.strip() for u in competitor_urls_text.strip().split("\n")
                    if u.strip().startswith("http")
                ]

            # Check for existing article
            tracking = _get_tracking_service()
            existing = tracking.list_articles(
                organization_id=org_id,
                brand_id=brand_id,
                exclude_discovered=True,
            )
            existing_match = [a for a in existing if a.get("keyword", "").lower() == keyword.lower()]
            if existing_match:
                st.warning(
                    f"An article for '{keyword}' already exists "
                    f"(status: {existing_match[0].get('status', 'unknown')}). "
                    "Proceeding will create a new one."
                )

            try:
                job_id = workflow_svc.start_one_off(
                    keyword=keyword,
                    brand_id=brand_id,
                    organization_id=org_id,
                    author_id=author_id,
                    tags=tags,
                    step_through=step_through,
                    competitor_urls=competitor_urls,
                )
                st.session_state["seo_wf_active_job"] = job_id
                st.success(f"Job started! Monitoring progress...")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Failed to start job: {e}")

    # Progress panel for active job
    active_job_id = st.session_state.get("seo_wf_active_job")
    if active_job_id:
        st.divider()
        job = workflow_svc.get_job_status(active_job_id)
        if job:
            status = job.get("status", "unknown")
            progress = job.get("progress", {})
            config = job.get("config", {})
            pct = progress.get("percent", 0)
            step_label = progress.get("current_step_label", "")
            steps_done = progress.get("steps_completed", [])

            with st.container(border=True):
                st.markdown(f"**Job: {config.get('keyword', '')}**")
                st.progress(pct / 100, text=f"{step_label} ({pct}%)")

                if steps_done:
                    with st.expander("Completed steps"):
                        for s in steps_done:
                            st.markdown(f"- {s}")

                if status == "running":
                    # Check for stalled job
                    updated = job.get("updated_at", "")
                    if updated:
                        try:
                            updated_dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                            age = (datetime.datetime.now(datetime.timezone.utc) - updated_dt).total_seconds()
                            if age > 300:
                                st.warning("This job may have stalled. Try refreshing or cancelling.")
                        except Exception:
                            pass

                    col_cancel, _ = st.columns([1, 3])
                    with col_cancel:
                        if st.button("Cancel", key="seo_wf_cancel"):
                            workflow_svc.cancel_job(active_job_id)
                            st.info("Cancelling...")
                            st.rerun()

                    # Auto-refresh
                    time.sleep(5)
                    st.rerun()

                elif status == "paused":
                    paused_data = progress.get("paused_data", {})
                    current_step = progress.get("current_step", "")

                    if paused_data:
                        with st.expander(f"Review: {current_step}", expanded=True):
                            for key, value in paused_data.items():
                                if isinstance(value, dict):
                                    st.json(value)
                                else:
                                    st.text_area(key, value=str(value)[:5000], height=200, disabled=True)

                    p_col1, p_col2 = st.columns(2)
                    with p_col1:
                        if st.button("Approve & Continue", type="primary", key="seo_wf_approve"):
                            workflow_svc.resume_job(active_job_id, action="approve")
                            st.rerun()
                    with p_col2:
                        if st.button("Cancel Job", key="seo_wf_pause_cancel"):
                            workflow_svc.cancel_job(active_job_id)
                            st.rerun()

                elif status == "completed":
                    result = job.get("result", {})
                    st.success("Article generated!")
                    url = result.get("published_url", "")
                    if url:
                        st.markdown(f"[View Shopify Draft]({url})")
                    article_id = result.get("article_id")
                    if article_id:
                        st.caption(f"Article ID: {article_id}")

                    checklist = result.get("checklist", {})
                    if checklist:
                        with st.expander("Pre-publish checklist"):
                            passed = checklist.get("passed", False)
                            st.markdown(f"**Result: {'PASSED' if passed else 'FAILED'}**")
                            for check in checklist.get("checks", []):
                                icon = "+" if check.get("passed") else "-"
                                st.markdown(f"  {icon} {check.get('name', '')} — {check.get('message', 'OK')}")

                    c_col1, c_col2 = st.columns(2)
                    with c_col1:
                        if st.button("Start another", key="seo_wf_restart"):
                            del st.session_state["seo_wf_active_job"]
                            st.rerun()
                    with c_col2:
                        if article_id and st.button("Retry Images", key="seo_wf_retry_images"):
                            try:
                                with st.spinner("Generating images... this may take 1-2 minutes per image."):
                                    img_result = workflow_svc.regenerate_images(
                                        article_id=article_id,
                                        brand_id=brand_id,
                                        organization_id=org_id,
                                    )
                                hero = img_result.get("hero_image_url", "")
                                stats = img_result.get("stats", {})
                                generated = stats.get("generated", 0)
                                st.success(f"Images regenerated! {generated} image(s) created." + (f" Hero: {hero}" if hero else ""))
                            except Exception as e:
                                st.error(f"Image generation failed: {e}")

                elif status == "failed":
                    error = job.get("error", "Unknown error")
                    failed_step = progress.get("failed_at_step", "")
                    st.error(f"Failed at {failed_step}: {error}")

                    r_col1, r_col2 = st.columns(2)
                    with r_col1:
                        if st.button("Retry", key="seo_wf_retry"):
                            workflow_svc.retry_job(active_job_id)
                            st.rerun()
                    with r_col2:
                        if st.button("Dismiss", key="seo_wf_dismiss"):
                            del st.session_state["seo_wf_active_job"]
                            st.rerun()

                elif status == "cancelled":
                    st.info("Job cancelled.")
                    if st.button("Dismiss", key="seo_wf_dismiss_cancel"):
                        del st.session_state["seo_wf_active_job"]
                        st.rerun()

    # Recent jobs
    st.divider()
    st.subheader("Recent Jobs")
    recent = workflow_svc.get_recent_jobs(brand_id, limit=10)
    if recent:
        for job in recent:
            _jid = job.get("id")
            config = job.get("config", {})
            kw = config.get("keyword", "unknown")
            j_status = job.get("status", "?")
            created = job.get("created_at", "")[:16]
            result = job.get("result", {})
            url = result.get("published_url", "")

            status_icon = {"completed": "+", "failed": "!", "cancelled": "x", "running": "~", "paused": "||"}.get(j_status, "?")

            rc1, rc2, rc3 = st.columns([4, 1, 1])
            with rc1:
                st.markdown(f"[{status_icon}] **{kw}** — {j_status} — {created}")
            with rc2:
                if url:
                    st.markdown(f"[View]({url})")
            with rc3:
                if j_status in ("completed", "failed") and st.button("Load", key=f"seo_wf_load_{_jid}"):
                    st.session_state["seo_wf_active_job"] = _jid
                    st.rerun()
    else:
        st.caption("No recent jobs for this brand.")


# =============================================================================
# TAB 2: CLUSTER BUILDER
# =============================================================================

with tab_cluster:
    st.caption(
        "Research a topic, get AI-powered cluster recommendations, "
        "then batch-generate all articles."
    )

    with st.form("cluster_research_form"):
        seeds_text = st.text_area(
            "Seed keywords",
            height=100,
            help="One keyword per line. These are starting points for cluster research.",
            key="seo_wf_seeds",
        )

        # Research sources
        from viraltracker.services.seo_pipeline.services.cluster_research_registry import ClusterResearchRegistry
        registry = ClusterResearchRegistry()
        available_sources = registry.get_sources()
        source_names = [s["name"] for s in available_sources]

        selected_sources = st.multiselect(
            "Research sources",
            options=source_names,
            default=source_names,
            format_func=lambda x: next((s["description"] for s in available_sources if s["name"] == x), x),
            key="seo_wf_sources",
        )

        research_mode = st.radio(
            "Research mode",
            ["Quick (algorithmic)", "Deep (AI-powered)"],
            index=1,
            horizontal=True,
            key="seo_wf_research_mode",
        )

        research_submitted = st.form_submit_button("Research", type="primary")

    if research_submitted and seeds_text.strip():
        seeds = [s.strip() for s in seeds_text.strip().split("\n") if s.strip()]
        mode = "quick" if "Quick" in research_mode else "deep"

        with st.spinner("Researching clusters..."):
            import asyncio
            try:
                report = asyncio.run(
                    workflow_svc.start_cluster_research(
                        brand_id=brand_id,
                        organization_id=org_id,
                        seed_keywords=seeds,
                        sources=selected_sources,
                        research_mode=mode,
                    )
                )
                st.session_state["seo_wf_cluster_report"] = report
            except Exception as e:
                st.error(f"Research failed: {e}")

    # Show research report
    report = st.session_state.get("seo_wf_cluster_report")
    if report:
        st.subheader("Cluster Recommendations")
        st.caption(f"Mode: {report.get('mode', '?')} | Keywords analyzed: {report.get('total_keywords', 0)}")

        clusters = report.get("clusters", [])
        if not clusters:
            st.info("No clusters found. Try different seed keywords.")
        else:
            for i, cluster in enumerate(clusters):
                with st.container(border=True):
                    score = cluster.get("opportunity_score", 0)
                    st.markdown(f"### {cluster.get('pillar_keyword', 'Unknown')}")
                    st.markdown(f"**Score:** {score:.1f} | **Summary:** {cluster.get('topic_summary', '')}")

                    if cluster.get("reasoning"):
                        st.caption(cluster["reasoning"])

                    spokes = cluster.get("spokes", [])
                    if spokes:
                        st.markdown("**Spokes:**")
                        for spoke in spokes:
                            angle = spoke.get("angle", "")
                            diff = spoke.get("estimated_difficulty", "")
                            st.markdown(f"- {spoke.get('keyword', '')} {f'— {angle}' if angle else ''} {f'({diff})' if diff else ''}")

            st.info(
                "For best indexing results, publish 1-2 articles per day "
                "rather than all at once."
            )
