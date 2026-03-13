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

                    # Image Management & Publish Tabs
                    img_tab, pub_tab = st.tabs(["Images", "Publish"])

                    with img_tab:
                        if article_id:
                            # Load image data (cached per article to avoid re-fetching on every rerun)
                            cache_key = f"seo_wf_image_data_{article_id}"
                            if cache_key not in st.session_state:
                                st.session_state[cache_key] = workflow_svc.get_article_images(article_id)
                            img_data = st.session_state[cache_key]
                            images = img_data.get("image_metadata") or []

                            if not images:
                                st.info("No images found for this article.")
                            else:
                                st.caption(f"{len(images)} image(s)")

                                for i, img in enumerate(images):
                                    with st.container(border=True):
                                        img_left, img_right = st.columns([2, 1])

                                        with img_left:
                                            cdn_url = img.get("cdn_url")
                                            if cdn_url and img.get("status") == "success":
                                                # Cache-bust URL after regeneration
                                                bust = st.session_state.get(f"seo_img_bust_{article_id}_{i}", "")
                                                display_url = f"{cdn_url}?t={bust}" if bust else cdn_url
                                                st.image(display_url, use_container_width=True)
                                            else:
                                                err = img.get("error", "Generation failed")
                                                st.warning(f"Image unavailable: {err}")

                                        with img_right:
                                            img_type = img.get("type", "inline")
                                            badge = "Hero" if img_type == "hero" else f"Inline #{i}"
                                            st.markdown(f"**{badge}**")

                                            original_desc = img.get("description", "")
                                            prompt_val = st.text_area(
                                                "Prompt",
                                                value=original_desc,
                                                height=100,
                                                key=f"seo_img_{i}_prompt",
                                                label_visibility="collapsed",
                                            )

                                            btn_col1, btn_col2 = st.columns(2)
                                            with btn_col1:
                                                if st.button("Regenerate", key=f"seo_img_{i}_regen", use_container_width=True):
                                                    # Use whatever is in the text_area (may be edited)
                                                    regen_prompt = prompt_val.strip()
                                                    custom = regen_prompt if regen_prompt != original_desc else None
                                                    try:
                                                        with st.spinner(f"Regenerating {badge.lower()}..."):
                                                            workflow_svc.regenerate_single_image(
                                                                article_id=article_id,
                                                                image_index=i,
                                                                brand_id=brand_id,
                                                                organization_id=org_id,
                                                                custom_prompt=custom,
                                                            )
                                                        # Bust cache and refresh
                                                        st.session_state[f"seo_img_bust_{article_id}_{i}"] = str(int(time.time()))
                                                        if cache_key in st.session_state:
                                                            del st.session_state[cache_key]
                                                        st.rerun()
                                                    except Exception as e:
                                                        _err = str(e)
                                                        if len(_err) > 200:
                                                            _err = _err[:200] + "..."
                                                        st.error(f"Failed: {_err}")

                                            with btn_col2:
                                                st.caption(f"Edit prompt above, then click Regenerate")

                            # Retry All Images button
                            st.divider()
                            if st.button("Retry All Images", key="seo_wf_retry_images"):
                                try:
                                    with st.spinner("Generating all images... this may take 1-2 minutes per image."):
                                        img_result = workflow_svc.regenerate_images(
                                            article_id=article_id,
                                            brand_id=brand_id,
                                            organization_id=org_id,
                                        )
                                    stats = img_result.get("stats", {})
                                    success_count = stats.get("success", 0)
                                    failed_count = stats.get("failed", 0)
                                    msg = f"Done! {success_count} image(s) generated."
                                    if failed_count:
                                        msg += f" {failed_count} failed."
                                    if img_result.get("hero_image_url"):
                                        msg += " Hero image set."
                                    st.success(msg)
                                    # Clear cached image data
                                    if cache_key in st.session_state:
                                        del st.session_state[cache_key]
                                    st.rerun()
                                except Exception as e:
                                    err_str = str(e)
                                    if len(err_str) > 300 or "<html" in err_str.lower():
                                        import re as _re
                                        code_match = _re.search(r"'code':\s*(\d+)", err_str)
                                        msg_match = _re.search(r"'message':\s*'([^']+)'", err_str)
                                        code = code_match.group(1) if code_match else ""
                                        msg = msg_match.group(1) if msg_match else "Server error"
                                        err_str = f"{msg} (code {code}). Try again in a minute." if code else f"{msg}. Try again in a minute."
                                    st.error(f"Image generation failed: {err_str}")
                        else:
                            st.info("No article ID available.")

                    with pub_tab:
                        if article_id and st.button("Re-publish to Shopify", key="seo_wf_republish", type="primary"):
                            try:
                                with st.spinner("Updating Shopify draft..."):
                                    from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                                    pub_svc = CMSPublisherService()
                                    pub_result = pub_svc.publish_article(
                                        article_id=article_id,
                                        brand_id=brand_id,
                                        organization_id=org_id,
                                        draft=True,
                                    )
                                admin_url = pub_result.get("admin_url", "")
                                if admin_url:
                                    st.success(f"Updated! [View in Shopify]({admin_url})")
                                else:
                                    st.success("Article updated in Shopify.")
                            except Exception as e:
                                st.error(f"Publish failed: {str(e)[:200]}")
                        elif not article_id:
                            st.info("No article ID available.")

                    # Bottom action row
                    st.divider()
                    if st.button("Start another", key="seo_wf_restart"):
                        # Clear image cache for this article
                        if article_id:
                            _img_cache_key = f"seo_wf_image_data_{article_id}"
                            if _img_cache_key in st.session_state:
                                del st.session_state[_img_cache_key]
                        del st.session_state["seo_wf_active_job"]
                        st.rerun()

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

    sub_smart, sub_manual = st.tabs(["Smart Research", "Manual Research"])

    # ------------------------------------------------------------------
    # SMART RESEARCH SUB-TAB
    # ------------------------------------------------------------------
    with sub_smart:
        def _get_seed_generator():
            from viraltracker.services.seo_pipeline.services.brand_seed_generator_service import (
                BrandSeedGeneratorService,
            )
            return BrandSeedGeneratorService()

        # State 1: Discover Topics
        if st.button("Discover Topics from Brand Data", type="primary", key="seo_wf_discover_btn"):
            with st.spinner("Analyzing brand data and discovering topics (10-15s)..."):
                svc = _get_seed_generator()
                result = svc.discover_topics(brand_id=brand_id, organization_id=org_id)
                # Cache context for reuse in seed generation
                st.session_state["seo_wf_brand_context"] = svc.last_brand_context
                st.session_state["seo_wf_smart_topics"] = result
                # Clear downstream state
                st.session_state.pop("seo_wf_smart_seeds", None)
                st.session_state.pop("seo_wf_custom_topics", None)
            st.rerun()

        # State 2: Topic Review
        topic_result = st.session_state.get("seo_wf_smart_topics")
        if topic_result:
            if topic_result.warnings:
                for w in topic_result.warnings:
                    st.warning(w)

            if topic_result.topics:
                st.subheader("Discovered Topics")
                if topic_result.brand_context_summary:
                    st.caption(topic_result.brand_context_summary)

                # Checkboxes for each topic
                selected_topics = []
                for i, t in enumerate(topic_result.topics):
                    gap_badge = " `GAP`" if t.gap else ""
                    sources_str = ", ".join(t.sources[:3]) if t.sources else ""
                    label = f"**{t.topic}**{gap_badge} — {t.rationale}"
                    if sources_str:
                        label += f" _{sources_str}_"
                    checked = st.checkbox(
                        label,
                        value=True,
                        key=f"seo_wf_topic_chk_{i}",
                    )
                    if checked:
                        selected_topics.append(t.topic)

                # Custom topic input
                custom_topics = st.session_state.get("seo_wf_custom_topics", [])
                for ci, ct in enumerate(custom_topics):
                    if st.checkbox(f"**{ct}** _(custom)_", value=True, key=f"seo_wf_custom_chk_{ci}"):
                        selected_topics.append(ct)

                col_add, col_clear = st.columns([3, 1])
                with col_add:
                    new_topic = st.text_input(
                        "Add a custom topic",
                        key="seo_wf_add_topic_input",
                        placeholder="e.g. gut health for athletes",
                    )
                    if st.button("Add Topic", key="seo_wf_add_topic_btn") and new_topic.strip():
                        existing = st.session_state.get("seo_wf_custom_topics", [])
                        existing.append(new_topic.strip())
                        st.session_state["seo_wf_custom_topics"] = existing
                        st.rerun()
                with col_clear:
                    if st.button("Clear Topics", key="seo_wf_clear_topics"):
                        st.session_state.pop("seo_wf_smart_topics", None)
                        st.session_state.pop("seo_wf_smart_seeds", None)
                        st.session_state.pop("seo_wf_custom_topics", None)
                        st.rerun()

                # Generate Seeds button
                if selected_topics:
                    if st.button(
                        f"Generate Seeds for {len(selected_topics)} Topic(s)",
                        type="primary",
                        key="seo_wf_gen_seeds_btn",
                    ):
                        brand_ctx = st.session_state.get("seo_wf_brand_context")
                        if not brand_ctx:
                            svc = _get_seed_generator()
                            brand_ctx = svc._gather_brand_context(brand_id)
                            st.session_state["seo_wf_brand_context"] = brand_ctx

                        with st.spinner("Generating long-tail seed phrases (10-15s)..."):
                            svc = _get_seed_generator()
                            seed_result = svc.generate_seeds_for_topics(
                                topics=selected_topics,
                                brand_context=brand_ctx,
                                organization_id=org_id,
                            )
                            st.session_state["seo_wf_smart_seeds"] = seed_result
                        st.rerun()
                else:
                    st.info("Select at least one topic to generate seeds.")
            elif not topic_result.warnings:
                st.info("No topics discovered. Try adding more brand data.")

        # State 3: Seed Review
        seed_result = st.session_state.get("seo_wf_smart_seeds")
        if seed_result:
            if seed_result.warnings:
                for w in seed_result.warnings:
                    st.warning(w)

            if seed_result.seeds_by_topic:
                st.subheader("Generated Seeds")
                st.caption(f"{seed_result.total_seeds} seeds across {len(seed_result.seeds_by_topic)} topics")

                checked_seeds = []
                for topic, seeds in seed_result.seeds_by_topic.items():
                    if not seeds:
                        continue
                    st.markdown(f"**{topic}** ({len(seeds)} seeds)")
                    for si, seed in enumerate(seeds):
                        intent_icon = {"commercial": "💰", "comparison": "⚖️"}.get(
                            seed.intent, "ℹ️"
                        )
                        label = f"{intent_icon} {seed.keyword}"
                        if seed.rationale:
                            label += f" — _{seed.rationale}_"
                        if st.checkbox(
                            label, value=True,
                            key=f"seo_wf_seed_chk_{topic}_{si}",
                        ):
                            checked_seeds.append(seed.keyword)

                if checked_seeds:
                    # Research sources + mode (shared with manual)
                    from viraltracker.services.seo_pipeline.services.cluster_research_registry import ClusterResearchRegistry
                    registry = ClusterResearchRegistry()
                    available_sources = registry.get_sources()
                    source_names = [s["name"] for s in available_sources]

                    smart_sources = st.multiselect(
                        "Research sources",
                        options=source_names,
                        default=source_names,
                        format_func=lambda x: next(
                            (s["description"] for s in available_sources if s["name"] == x), x
                        ),
                        key="seo_wf_smart_sources",
                    )
                    smart_mode = st.radio(
                        "Research mode",
                        ["Quick (algorithmic)", "Deep (AI-powered)"],
                        index=1,
                        horizontal=True,
                        key="seo_wf_smart_research_mode",
                    )

                    if st.button(
                        f"Run Cluster Research ({len(checked_seeds)} seeds)",
                        type="primary",
                        key="seo_wf_smart_run_btn",
                    ):
                        mode = "quick" if "Quick" in smart_mode else "deep"
                        with st.spinner("Researching clusters..."):
                            import asyncio
                            from concurrent.futures import ThreadPoolExecutor

                            def _run_smart_research():
                                loop = asyncio.new_event_loop()
                                try:
                                    return loop.run_until_complete(
                                        workflow_svc.start_cluster_research(
                                            brand_id=brand_id,
                                            organization_id=org_id,
                                            seed_keywords=checked_seeds,
                                            sources=smart_sources,
                                            research_mode=mode,
                                        )
                                    )
                                finally:
                                    loop.close()

                            try:
                                with ThreadPoolExecutor(max_workers=1) as pool:
                                    report = pool.submit(_run_smart_research).result(timeout=120)
                                st.session_state["seo_wf_cluster_report"] = report
                            except Exception as e:
                                st.error(f"Research failed: {e}")
                else:
                    st.info("Select at least one seed to run research.")

    # ------------------------------------------------------------------
    # MANUAL RESEARCH SUB-TAB
    # ------------------------------------------------------------------
    with sub_manual:
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
                from concurrent.futures import ThreadPoolExecutor

                def _run_research():
                    loop = asyncio.new_event_loop()
                    try:
                        return loop.run_until_complete(
                            workflow_svc.start_cluster_research(
                                brand_id=brand_id,
                                organization_id=org_id,
                                seed_keywords=seeds,
                                sources=selected_sources,
                                research_mode=mode,
                            )
                        )
                    finally:
                        loop.close()

                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        report = pool.submit(_run_research).result(timeout=120)
                    st.session_state["seo_wf_cluster_report"] = report
                except Exception as e:
                    st.error(f"Research failed: {e}")

    # ---- Batch Progress Panel (check for active batch job) ----
    batch_job_id = st.session_state.get("seo_wf_batch_job")
    if batch_job_id:
        st.divider()
        batch_job = workflow_svc.get_job_status(batch_job_id)
        if batch_job:
            b_status = batch_job.get("status", "unknown")
            b_progress = batch_job.get("progress", {})
            b_config = batch_job.get("config", {})
            b_pct = b_progress.get("percent", 0)
            b_label = b_progress.get("current_step_label", "")
            per_article = b_progress.get("per_article_results", [])

            with st.container(border=True):
                st.markdown(f"**Batch: {b_config.get('pillar_keyword', '')}**")
                total_articles = b_progress.get("total_articles", 0)
                completed_so_far = sum(1 for r in per_article if r.get("status") == "completed")
                st.progress(b_pct / 100, text=f"{b_label} ({completed_so_far}/{total_articles} articles)")

                # Per-article status
                if per_article:
                    for ar in per_article:
                        icon = "+" if ar.get("status") == "completed" else "!"
                        role_badge = "Pillar" if ar.get("role") == "pillar" else "Spoke"
                        url = ar.get("published_url", "")
                        link = f" — [View]({url})" if url else ""
                        st.markdown(f"  [{icon}] **{role_badge}**: {ar.get('keyword', '')}{link}")

                if b_status == "running":
                    col_bc, _ = st.columns([1, 3])
                    with col_bc:
                        if st.button("Cancel Batch", key="seo_wf_batch_cancel"):
                            workflow_svc.cancel_job(batch_job_id)
                            st.info("Cancelling...")
                            st.rerun()
                    time.sleep(5)
                    st.rerun()

                elif b_status == "completed":
                    b_result = batch_job.get("result", {})
                    completed_count = b_result.get("completed", 0)
                    failed_count = b_result.get("failed", 0)
                    st.success(f"Batch complete! {completed_count} articles generated, {failed_count} failed.")

                    # Per-article results with image management
                    final_articles = b_result.get("per_article_results", per_article)
                    for ar_idx, ar in enumerate(final_articles):
                        if ar.get("status") != "completed" or not ar.get("article_id"):
                            continue
                        ar_id = ar["article_id"]
                        ar_kw = ar.get("keyword", "")
                        ar_role = "Pillar" if ar.get("role") == "pillar" else "Spoke"
                        ar_url = ar.get("published_url", "")

                        with st.expander(f"{ar_role}: {ar_kw}", expanded=ar_idx == 0):
                            if ar_url:
                                st.markdown(f"[View Shopify Draft]({ar_url})")

                            # Image management (same pattern as Quick Write)
                            b_img_tab, b_pub_tab = st.tabs(["Images", "Publish"])

                            with b_img_tab:
                                b_cache_key = f"seo_wf_image_data_{ar_id}"
                                if b_cache_key not in st.session_state:
                                    st.session_state[b_cache_key] = workflow_svc.get_article_images(ar_id)
                                b_img_data = st.session_state[b_cache_key]
                                b_images = b_img_data.get("image_metadata") or []

                                if not b_images:
                                    st.info("No images found.")
                                else:
                                    st.caption(f"{len(b_images)} image(s)")
                                    for bi, bimg in enumerate(b_images):
                                        with st.container(border=True):
                                            bi_left, bi_right = st.columns([2, 1])
                                            with bi_left:
                                                cdn = bimg.get("cdn_url")
                                                if cdn and bimg.get("status") == "success":
                                                    bust = st.session_state.get(f"seo_img_bust_{ar_id}_{bi}", "")
                                                    d_url = f"{cdn}?t={bust}" if bust else cdn
                                                    st.image(d_url, use_container_width=True)
                                                else:
                                                    st.warning(f"Image unavailable: {bimg.get('error', 'Failed')}")
                                            with bi_right:
                                                badge = "Hero" if bimg.get("type") == "hero" else f"Inline #{bi}"
                                                st.markdown(f"**{badge}**")
                                                orig_desc = bimg.get("description", "")
                                                p_val = st.text_area(
                                                    "Prompt", value=orig_desc, height=80,
                                                    key=f"seo_batch_{ar_idx}_{bi}_prompt",
                                                    label_visibility="collapsed",
                                                )
                                                if st.button("Regenerate", key=f"seo_batch_{ar_idx}_{bi}_regen", use_container_width=True):
                                                    custom = p_val.strip() if p_val.strip() != orig_desc else None
                                                    try:
                                                        with st.spinner(f"Regenerating {badge.lower()}..."):
                                                            workflow_svc.regenerate_single_image(
                                                                article_id=ar_id, image_index=bi,
                                                                brand_id=brand_id, organization_id=org_id,
                                                                custom_prompt=custom,
                                                            )
                                                        st.session_state[f"seo_img_bust_{ar_id}_{bi}"] = str(int(time.time()))
                                                        if b_cache_key in st.session_state:
                                                            del st.session_state[b_cache_key]
                                                        st.rerun()
                                                    except Exception as e:
                                                        st.error(f"Failed: {str(e)[:200]}")

                            with b_pub_tab:
                                if st.button("Re-publish to Shopify", key=f"seo_batch_{ar_idx}_republish", type="primary"):
                                    try:
                                        with st.spinner("Updating Shopify draft..."):
                                            from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                                            pub_svc = CMSPublisherService()
                                            pub_result = pub_svc.publish_article(
                                                article_id=ar_id, brand_id=brand_id,
                                                organization_id=org_id, draft=True,
                                            )
                                        admin_url = pub_result.get("admin_url", "")
                                        if admin_url:
                                            st.success(f"Updated! [View in Shopify]({admin_url})")
                                        else:
                                            st.success("Article updated in Shopify.")
                                    except Exception as e:
                                        st.error(f"Publish failed: {str(e)[:200]}")

                    st.divider()
                    if st.button("Clear batch", key="seo_wf_batch_clear"):
                        # Clear image caches for all batch articles
                        for ar in final_articles:
                            _aid = ar.get("article_id")
                            if _aid:
                                _ck = f"seo_wf_image_data_{_aid}"
                                if _ck in st.session_state:
                                    del st.session_state[_ck]
                        del st.session_state["seo_wf_batch_job"]
                        st.rerun()

                elif b_status == "failed":
                    st.error(f"Batch failed: {batch_job.get('error', 'Unknown error')}")
                    if per_article:
                        st.markdown("**Completed before failure:**")
                        for ar in per_article:
                            if ar.get("status") == "completed":
                                st.markdown(f"  [+] {ar.get('keyword', '')} — [View]({ar.get('published_url', '')})")
                    if st.button("Dismiss", key="seo_wf_batch_dismiss"):
                        del st.session_state["seo_wf_batch_job"]
                        st.rerun()

                elif b_status == "cancelled":
                    st.info("Batch cancelled.")
                    if st.button("Dismiss", key="seo_wf_batch_dismiss_cancel"):
                        del st.session_state["seo_wf_batch_job"]
                        st.rerun()

    # ---- Research Report ----
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
                    pillar_kw = cluster.get("pillar_keyword", "Unknown")
                    st.markdown(f"### {pillar_kw}")
                    st.markdown(f"**Score:** {score:.1f} | **Summary:** {cluster.get('topic_summary', '')}")

                    if cluster.get("reasoning"):
                        st.caption(cluster["reasoning"])

                    spokes = cluster.get("spokes", [])
                    if spokes:
                        st.markdown(f"**Spokes ({len(spokes)}):**")
                        for spoke in spokes:
                            angle = spoke.get("angle", "")
                            diff = spoke.get("estimated_difficulty", "")
                            st.markdown(f"- {spoke.get('keyword', '')} {f'— {angle}' if angle else ''} {f'({diff})' if diff else ''}")

                    # Generate button
                    total_articles = 1 + len(spokes)
                    if st.button(
                        f"Generate Cluster ({total_articles} articles)",
                        key=f"seo_wf_gen_cluster_{i}",
                        type="primary",
                        disabled=batch_job_id is not None,
                    ):
                        try:
                            cluster_id = workflow_svc.save_cluster_from_research(
                                cluster_data=cluster,
                                brand_id=brand_id,
                                organization_id=org_id,
                            )
                            job_id = workflow_svc.start_cluster_batch(
                                cluster_id=cluster_id,
                                brand_id=brand_id,
                                organization_id=org_id,
                            )
                            st.session_state["seo_wf_batch_job"] = job_id
                            st.success("Batch started! Monitoring progress...")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"Failed to start batch: {str(e)[:300]}")

            st.info(
                "For best indexing results, publish 1-2 articles per day "
                "rather than all at once."
            )

    # ---- Recent Batch Jobs ----
    st.divider()
    st.subheader("Recent Batches")
    recent_batches = [
        j for j in workflow_svc.get_recent_jobs(brand_id, limit=10)
        if j.get("job_type") == "cluster_batch"
    ]
    if recent_batches:
        for bj in recent_batches:
            _bjid = bj.get("id")
            bc = bj.get("config", {})
            bj_status = bj.get("status", "?")
            bj_created = bj.get("created_at", "")[:16]
            bj_result = bj.get("result", {})
            bj_completed = bj_result.get("completed", 0)
            bj_total = bj_result.get("total", 0)

            icon = {"completed": "+", "failed": "!", "cancelled": "x", "running": "~"}.get(bj_status, "?")

            bc1, bc2 = st.columns([4, 1])
            with bc1:
                st.markdown(
                    f"[{icon}] **{bc.get('pillar_keyword', '?')}** — "
                    f"{bj_status} ({bj_completed}/{bj_total} articles) — {bj_created}"
                )
            with bc2:
                if bj_status in ("completed", "failed") and st.button("Load", key=f"seo_wf_load_batch_{_bjid}"):
                    st.session_state["seo_wf_batch_job"] = _bjid
                    st.rerun()
    else:
        st.caption("No recent batch jobs for this brand.")
