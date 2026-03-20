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

tab_qw, tab_cluster, tab_explorer = st.tabs(["Quick Write", "Cluster Builder", "Keyword Explorer"])


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
        if st.session_state.pop("seo_wf_scroll_top", False):
            import streamlit.components.v1 as components
            components.html("<script>window.parent.document.querySelector('section.main').scrollTo(0, 0);</script>", height=0)
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
                        # Show article title and ID
                        _title_row = workflow_svc.supabase.table("seo_articles").select(
                            "seo_title, title, keyword"
                        ).eq("id", article_id).limit(1).execute()
                        _article_title = ""
                        if _title_row.data:
                            _t = _title_row.data[0]
                            _article_title = _t.get("seo_title") or _t.get("title") or _t.get("keyword") or ""
                        if _article_title:
                            st.markdown(f"**{_article_title}**")
                        st.caption(f"Article ID: {article_id}")

                    checklist = result.get("checklist", {})
                    if checklist:
                        with st.expander("Pre-publish checklist"):
                            all_checks = checklist.get("checks", [])
                            passed_count = sum(1 for c in all_checks if c.get("passed"))
                            total_count = len(all_checks)
                            st.markdown(f"**Passed {passed_count}/{total_count} checks**")
                            for check in all_checks:
                                passed = check.get("passed", False)
                                name = check.get("name", "")
                                msg = check.get("message", "")
                                sub_checks = check.get("sub_checks")

                                if name == "content_qa" and sub_checks:
                                    # Expand content_qa into individual sub-checks
                                    qa_pass = sum(1 for s in sub_checks if s.get("passed"))
                                    qa_total = len(sub_checks)
                                    st.markdown(f"&ensp;**content_qa** ({qa_pass}/{qa_total})")
                                    for sc in sub_checks:
                                        sc_passed = sc.get("passed", False)
                                        sc_name = sc.get("name", "")
                                        sc_icon = "PASS" if sc_passed else "WARN" if sc.get("severity") == "warning" else "FAIL"
                                        sc_msg = sc.get("message", "")
                                        sc_label = f"{sc_name} — {sc_msg}" if sc_msg else sc_name

                                        # Check if this failed check has a targeted fix tool
                                        _fixable = False
                                        if not sc_passed:
                                            if sc_name == "meta_description":
                                                _fixable = True
                                            elif sc_name == "keyword_placement":
                                                _missing = (sc.get("details") or {}).get("missing", [])
                                                _fixable = "first_paragraph" in _missing

                                        if _fixable:
                                            _check_col, _fix_col = st.columns([5, 1])
                                        else:
                                            _check_col = st.container()
                                            _fix_col = None

                                        with _check_col:
                                            if sc_passed:
                                                st.markdown(f"&ensp;&ensp;&ensp;:green[{sc_icon}] {sc_label}")
                                            elif sc.get("severity") == "warning":
                                                st.markdown(f"&ensp;&ensp;&ensp;:orange[{sc_icon}] {sc_label}")
                                            else:
                                                st.markdown(f"&ensp;&ensp;&ensp;:red[{sc_icon}] {sc_label}")

                                        if _fix_col:
                                            with _fix_col:
                                                if sc_name == "meta_description":
                                                    if st.button("Fix", key="fix_meta_desc", help="AI-generate a new meta description (150-160 chars with keyword)"):
                                                        with st.spinner("Generating..."):
                                                            _fix_result = workflow_svc.fix_meta_description(article_id)
                                                        if _fix_result.get("fixed"):
                                                            st.success(f"New meta: {_fix_result['length']} chars. Re-run checklist to verify.")
                                                        else:
                                                            st.warning(_fix_result.get("error", "Fix failed"))
                                                elif sc_name == "keyword_placement":
                                                    if st.button("Fix", key="fix_first_para", help="AI-rewrite opening paragraph to include keyword"):
                                                        with st.spinner("Rewriting..."):
                                                            _fix_result = workflow_svc.fix_first_paragraph(article_id)
                                                        if _fix_result.get("fixed"):
                                                            st.success("First paragraph updated. Re-run checklist to verify.")
                                                        else:
                                                            st.warning(_fix_result.get("error", "Fix failed"))
                                else:
                                    icon = "PASS" if passed else "FAIL"
                                    label = f"**{name}** — {msg}" if msg else f"**{name}**"
                                    if passed:
                                        st.markdown(f"&ensp;:green[{icon}] {label}")
                                    else:
                                        st.markdown(f"&ensp;:red[{icon}] {label}")

                    # Article Maintenance — outside expander so always visible
                    if article_id:
                        with st.container(border=True):
                            st.caption("Article Maintenance")
                            repair_col1, repair_col2, repair_col3, repair_col4 = st.columns(4)
                            with repair_col1:
                                if st.button("Repair Metadata", key="seo_wf_repair_meta", help="Re-extract SEO title, meta description, and tags from the article content without regenerating it."):
                                    with st.spinner("Re-parsing metadata from content..."):
                                        repair_result = workflow_svc.repair_article_metadata(article_id)
                                    fixed = repair_result.get("fixed", [])
                                    if fixed:
                                        st.success(f"Fixed: {', '.join(fixed)}. Click Re-run Checklist to verify.")
                                    elif repair_result.get("already_populated"):
                                        st.info(f"Metadata already populated: {', '.join(repair_result['already_populated'])}. Click Re-run Checklist to refresh.")
                                    else:
                                        st.warning("No metadata could be extracted. Try Re-run Phase C.")
                            with repair_col2:
                                _republish = st.checkbox(
                                    "Re-publish after",
                                    value=bool(result.get("cms_article_id")),
                                    key="seo_wf_rerun_republish",
                                    help="Push updated content to Shopify after re-generation.",
                                )
                                if st.button("Re-run Phase C", key="seo_wf_rerun_phase_c", help="Regenerate the article with Claude (SEO optimization pass). Use when content quality is poor or you want a fresh rewrite."):
                                    with st.spinner("Re-running Phase C (30-60s)..."):
                                        try:
                                            pc_result = workflow_svc.rerun_phase_c(
                                                article_id=article_id,
                                                brand_id=brand_id,
                                                organization_id=org_id,
                                                republish=_republish,
                                            )
                                            parsed_fields = pc_result.get("parsed_fields", [])
                                            msg = f"Phase C complete. Parsed: {', '.join(parsed_fields) or 'none'}"
                                            if _republish:
                                                msg += " Re-published to Shopify."
                                            st.success(msg)
                                        except Exception as e:
                                            st.error(f"Phase C failed: {str(e)[:200]}")
                            with repair_col3:
                                if st.button("Re-run Checklist", key="seo_wf_rerun_checklist", help="Re-validate the article against the pre-publish checklist (word count, readability, keyword usage, etc)."):
                                    with st.spinner("Running checklist..."):
                                        from viraltracker.services.seo_pipeline.services.pre_publish_checklist_service import PrePublishChecklistService
                                        from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
                                        _cl_svc = PrePublishChecklistService()
                                        _bc_svc = SEOBrandConfigService()
                                        _bc = _bc_svc.get_config(brand_id) or {}
                                        new_checklist = _cl_svc.run_checklist(article_id, _bc)
                                        _job_result = job.get("result", {})
                                        _job_result["checklist"] = new_checklist
                                        workflow_svc.supabase.table("seo_workflow_jobs").update(
                                            {"result": _job_result}
                                        ).eq("id", active_job_id).execute()
                                        st.rerun()
                            with repair_col4:
                                if st.button("Re-run Links", key="seo_wf_rerun_links", help="Refresh internal link suggestions, inject contextual links, and rebuild the Related Articles section."):
                                    with st.spinner("Re-running interlinking..."):
                                        try:
                                            link_result = workflow_svc.rerun_interlinking(
                                                article_id=article_id,
                                                brand_id=brand_id,
                                                organization_id=org_id,
                                            )
                                            parts = []
                                            if link_result.get("suggestion_count"):
                                                parts.append(f"{link_result['suggestion_count']} suggestions")
                                            if link_result.get("links_added"):
                                                parts.append(f"{link_result['links_added']} auto-links")
                                            if link_result.get("related_articles_linked"):
                                                parts.append(f"{link_result['related_articles_linked']} related")
                                            st.success(f"Interlinking complete: {', '.join(parts) or 'no changes'}")
                                        except Exception as e:
                                            st.error(f"Interlinking failed: {str(e)[:200]}")

                    # Article status row (image status + published status + admin link)
                    _art_status_row = None
                    if article_id:
                        _art_status_row = (
                            workflow_svc.supabase.table("seo_articles")
                            .select("image_status, image_metadata, status, cms_article_id, published_url")
                            .eq("id", article_id)
                            .limit(1)
                            .execute()
                        )
                    _art_data = _art_status_row.data[0] if _art_status_row and _art_status_row.data else {}
                    _img_status = _art_data.get("image_status") or "none"
                    _img_count = len([m for m in (_art_data.get("image_metadata") or []) if m.get("status") == "success"])

                    # Image status indicator
                    _img_labels = {
                        "pending": ":orange[Queued]",
                        "processing": ":blue[Generating...]",
                        "complete": f":green[Ready ({_img_count} images)]",
                        "failed": ":red[Failed]",
                    }
                    _img_label = _img_labels.get(_img_status, ":gray[Not started]")
                    st.markdown(f"**Images:** {_img_label}")

                    if _img_status in ("pending", "processing"):
                        st.info("Images generating in background...")
                    elif _img_status == "failed":
                        _warn_col, _retry_col = st.columns([3, 1])
                        with _warn_col:
                            st.warning("Image generation failed.")
                        with _retry_col:
                            if st.button("Retry Images", key="seo_wf_retry_deferred_images"):
                                try:
                                    workflow_svc.retry_deferred_images(
                                        article_id=article_id,
                                        brand_id=brand_id,
                                        organization_id=org_id,
                                    )
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Retry failed: {str(e)[:200]}")

                    # Published status badge + Shopify admin link
                    _cms_id = _art_data.get("cms_article_id")
                    _art_status = _art_data.get("status", "")
                    if _cms_id:
                        if _art_status == "published":
                            _pub_badge = ":green[Live]"
                        else:
                            _pub_badge = ":orange[Draft]"
                        _admin_url = result.get("admin_url", "")
                        _pub_line = f"**Shopify:** {_pub_badge}"
                        if _admin_url:
                            _pub_line += f" · [Admin]({_admin_url})"
                        st.markdown(_pub_line)

                    # Image Management & Publish Tabs
                    img_tab, pub_tab = st.tabs(["Images", "Publish"])

                    with img_tab:
                        if article_id:
                            # Load image data (cached per article to avoid re-fetching on every rerun)
                            cache_key = f"seo_wf_image_data_{article_id}"
                            if _img_status in ("pending", "processing"):
                                # Clear cache so fresh data loads on next poll
                                if cache_key in st.session_state:
                                    del st.session_state[cache_key]
                            if cache_key not in st.session_state:
                                st.session_state[cache_key] = workflow_svc.get_article_images(article_id)
                            img_data = st.session_state[cache_key]
                            images = img_data.get("image_metadata") or []

                            if not images:
                                if _img_status in ("pending", "processing"):
                                    st.info("Images are generating in the background. They will appear here when complete.")
                                else:
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
                                                key=f"seo_img_{article_id}_{i}_prompt",
                                                label_visibility="collapsed",
                                            )

                                            btn_col1, btn_col2 = st.columns(2)
                                            with btn_col1:
                                                if st.button("Regenerate", key=f"seo_img_{article_id}_{i}_regen", use_container_width=True):
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
                            if _img_status in ("pending", "processing"):
                                st.button("Retry All Images", key="seo_wf_retry_images", disabled=True)
                                st.caption("Images are generating in the background...")
                            elif st.button("Retry All Images", key="seo_wf_retry_images"):
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
                        if article_id:
                            if _img_status and _img_status != "complete":
                                st.warning("Images are not ready yet. Publishing now will create the article without generated images.")
                            _pub_mode = st.radio(
                                "Publish mode",
                                ["Draft", "Live"],
                                key="seo_wf_pub_mode",
                                horizontal=True,
                                help="Draft pushes content without changing visibility. Live makes the article publicly visible on Shopify.",
                            )
                            _is_live = _pub_mode == "Live"
                            if _is_live:
                                st.warning("This will make the article publicly visible on your Shopify store.")
                            else:
                                st.caption("Push the latest article content, images, and metadata to Shopify without changing visibility.")
                            if st.button(
                                "Publish Live" if _is_live else "Re-publish to Shopify",
                                key="seo_wf_republish",
                                type="primary",
                            ):
                                try:
                                    with st.spinner("Publishing to Shopify..."):
                                        from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                                        pub_svc = CMSPublisherService()
                                        pub_result = pub_svc.publish_article(
                                            article_id=article_id,
                                            brand_id=brand_id,
                                            organization_id=org_id,
                                            draft=not _is_live,
                                        )
                                    admin_url = pub_result.get("admin_url", "")
                                    if admin_url:
                                        st.success(f"{'Published live' if _is_live else 'Updated'}! [View in Shopify]({admin_url})")
                                    else:
                                        st.success("Published live!" if _is_live else "Article updated in Shopify.")
                                except Exception as e:
                                    st.error(f"Publish failed: {str(e)[:200]}")
                        else:
                            st.info("No article ID available.")

                    # Auto-poll while images generating
                    if _img_status in ("pending", "processing"):
                        time.sleep(10)
                        st.rerun()

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

    # Sync article statuses from Shopify (once per page load per brand)
    _sync_key = f"seo_wf_status_synced_{brand_id}"
    if _sync_key not in st.session_state:
        try:
            from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
            _cms_svc = CMSPublisherService()
            _sync_result = _cms_svc.sync_article_statuses(brand_id, org_id)
            if _sync_result.get("synced", 0) > 0:
                logger.info(f"Synced {_sync_result['synced']} article statuses from Shopify")
        except Exception as e:
            logger.warning(f"Shopify status sync failed (non-fatal): {e}")
        st.session_state[_sync_key] = True

    recent = workflow_svc.get_recent_jobs(brand_id, limit=20)
    if recent:
        # Batch-fetch Shopify status for completed jobs
        _article_ids = [
            (j.get("result") or {}).get("article_id")
            for j in recent if (j.get("result") or {}).get("article_id")
        ]
        _shopify_map = {}
        if _article_ids:
            try:
                from viraltracker.core.database import get_supabase_client
                _sb = get_supabase_client()
                _rows = _sb.table("seo_articles").select(
                    "id, status, cms_article_id"
                ).in_("id", _article_ids).execute()
                _CMS_LABELS = {"published": "Live", "publishing": "Draft"}
                for r in (_rows.data or []):
                    if r.get("cms_article_id"):
                        _shopify_map[r["id"]] = _CMS_LABELS.get(r.get("status", ""), "")
            except Exception:
                pass

        for job in recent:
            _jid = job.get("id")
            config = job.get("config", {})
            kw = config.get("keyword", "unknown")
            j_status = job.get("status", "?")
            created = job.get("created_at", "")[:16]
            result = job.get("result", {})
            url = result.get("published_url", "")
            article_id = result.get("article_id", "")

            status_icon = {"completed": "+", "failed": "!", "cancelled": "x", "running": "~", "paused": "||"}.get(j_status, "?")
            shopify_label = _shopify_map.get(article_id, "")
            shopify_tag = f" · **{shopify_label}**" if shopify_label else ""

            # Show article role (pillar/spoke) for cluster jobs
            role = config.get("article_role", "")
            job_type = job.get("job_type", "")
            role_tag = ""
            if role == "pillar":
                role_tag = " · :blue[Pillar]"
            elif role == "spoke":
                role_tag = " · Spoke"
            elif job_type == "batch":
                role_tag = " · :violet[Cluster]"

            with st.container(border=True):
                rc1, rc2, rc3 = st.columns([4, 1, 1])
                with rc1:
                    st.markdown(f"[{status_icon}] **{kw}** — {j_status}{shopify_tag}{role_tag} — {created}")
                with rc2:
                    if url:
                        st.link_button("View", url, use_container_width=True)
                    else:
                        st.write("")
                with rc3:
                    if j_status == "completed":
                        if st.button("Load", key=f"seo_wf_load_{_jid}", use_container_width=True):
                            st.session_state["seo_wf_active_job"] = _jid
                            st.session_state["seo_wf_scroll_top"] = True
                            st.rerun()
                    elif j_status == "failed":
                        if st.button("Retry", key=f"seo_wf_retry_{_jid}", use_container_width=True):
                            from viraltracker.services.seo_pipeline.services.seo_workflow_service import SEOWorkflowService
                            _retry_svc = SEOWorkflowService()
                            _retry_svc.retry_job(_jid)
                            st.session_state["seo_wf_active_job"] = _jid
                            st.session_state["seo_wf_scroll_top"] = True
                            st.rerun()
                    else:
                        st.write("")
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

                # Initialize seed checkboxes to True on first render
                for topic, seeds in seed_result.seeds_by_topic.items():
                    for si in range(len(seeds)):
                        chk_key = f"seo_wf_seed_chk_{topic}_{si}"
                        if chk_key not in st.session_state:
                            st.session_state[chk_key] = True

                # Sync group toggles → individual checkboxes
                for topic, seeds in seed_result.seeds_by_topic.items():
                    toggle_key = f"seo_wf_topic_toggle_{topic}"
                    if toggle_key in st.session_state:
                        group_val = st.session_state[toggle_key]
                        for si in range(len(seeds)):
                            st.session_state[f"seo_wf_seed_chk_{topic}_{si}"] = group_val

                checked_seeds = []
                for topic, seeds in seed_result.seeds_by_topic.items():
                    if not seeds:
                        continue
                    topic_col, toggle_col = st.columns([4, 1])
                    with topic_col:
                        st.markdown(f"**{topic}** ({len(seeds)} seeds)")
                    with toggle_col:
                        st.checkbox(
                            "All",
                            key=f"seo_wf_topic_toggle_{topic}",
                            label_visibility="collapsed",
                        )
                    for si, seed in enumerate(seeds):
                        intent_icon = {"commercial": "💰", "comparison": "⚖️"}.get(
                            seed.intent, "ℹ️"
                        )
                        label = f"{intent_icon} {seed.keyword}"
                        if seed.rationale:
                            label += f" — _{seed.rationale}_"
                        if st.checkbox(
                            label,
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
                    force_refresh = st.checkbox(
                        "Force refresh keyword data (bypass 7-day cache)",
                        value=False,
                        key="seo_wf_force_refresh",
                    )

                    MAX_SEEDS_FOR_RESEARCH = 20
                    capped = len(checked_seeds) > MAX_SEEDS_FOR_RESEARCH
                    seeds_to_run = checked_seeds[:MAX_SEEDS_FOR_RESEARCH]
                    btn_label = f"Run Cluster Research ({len(seeds_to_run)} of {len(checked_seeds)} seeds)" if capped else f"Run Cluster Research ({len(checked_seeds)} seeds)"

                    if capped:
                        st.caption(f"Capped at {MAX_SEEDS_FOR_RESEARCH} seeds to keep research time reasonable. Uncheck lower-priority seeds to control which are used.")

                    if st.button(
                        btn_label,
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
                                            seed_keywords=seeds_to_run,
                                            sources=smart_sources,
                                            research_mode=mode,
                                            force_refresh=force_refresh,
                                        )
                                    )
                                finally:
                                    loop.close()

                            try:
                                with ThreadPoolExecutor(max_workers=1) as pool:
                                    report = pool.submit(_run_smart_research).result(timeout=600)
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
                                force_refresh=False,
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
                    _batch_img_statuses = []  # Collect statuses to avoid re-querying for auto-poll
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

                            # Image status badge
                            _b_img_st_row = (
                                workflow_svc.supabase.table("seo_articles")
                                .select("image_status")
                                .eq("id", ar_id)
                                .limit(1)
                                .execute()
                            )
                            _b_img_st = (_b_img_st_row.data[0].get("image_status", "none") if _b_img_st_row.data else "none")
                            _batch_img_statuses.append(_b_img_st)

                            if _b_img_st in ("pending", "processing"):
                                st.info("Images generating in background...")
                            elif _b_img_st == "failed":
                                _bw_col, _br_col = st.columns([3, 1])
                                with _bw_col:
                                    st.warning("Image generation failed.")
                                with _br_col:
                                    if st.button("Retry Images", key=f"seo_batch_{ar_idx}_retry_deferred"):
                                        try:
                                            workflow_svc.retry_deferred_images(
                                                article_id=ar_id,
                                                brand_id=brand_id,
                                                organization_id=org_id,
                                            )
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Retry failed: {str(e)[:200]}")
                            elif _b_img_st == "complete":
                                st.caption("Images: complete")

                            # Image management (same pattern as Quick Write)
                            b_img_tab, b_pub_tab = st.tabs(["Images", "Publish"])

                            with b_img_tab:
                                b_cache_key = f"seo_wf_image_data_{ar_id}"
                                if _b_img_st in ("pending", "processing"):
                                    if b_cache_key in st.session_state:
                                        del st.session_state[b_cache_key]
                                if b_cache_key not in st.session_state:
                                    st.session_state[b_cache_key] = workflow_svc.get_article_images(ar_id)
                                b_img_data = st.session_state[b_cache_key]
                                b_images = b_img_data.get("image_metadata") or []

                                if not b_images:
                                    if _b_img_st in ("pending", "processing"):
                                        st.info("Images are generating in the background.")
                                    else:
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

                    # Auto-poll while any batch article images are still generating
                    if any(s in ("pending", "processing") for s in _batch_img_statuses):
                        time.sleep(10)
                        st.rerun()

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

                    # Cluster-level aggregate metrics
                    total_vol = cluster.get("total_volume")
                    avg_kd = cluster.get("avg_difficulty")
                    est_traffic = cluster.get("estimated_traffic")
                    if total_vol is not None or avg_kd is not None:
                        metrics_parts = []
                        if total_vol is not None:
                            metrics_parts.append(f"Total Volume: {total_vol:,}/mo")
                        if avg_kd is not None:
                            kd_color = "green" if avg_kd < 30 else ("orange" if avg_kd < 60 else "red")
                            metrics_parts.append(f"Avg KD: :{kd_color}[{avg_kd:.0f}]")
                        if est_traffic is not None and est_traffic > 0:
                            metrics_parts.append(f"Est. Traffic: {est_traffic:,}/mo")
                        spokes_for_count = cluster.get("spokes", [])
                        metrics_parts.append(f"Spokes: {len(spokes_for_count)}")
                        st.markdown(f"📊 {' | '.join(metrics_parts)}")

                    # Opportunity badge
                    if total_vol is not None and avg_kd is not None:
                        if total_vol >= 1000 and avg_kd < 30:
                            st.markdown("🟢 **High Opportunity** — high volume, low difficulty")
                        elif avg_kd >= 60:
                            st.markdown("🔴 **Competitive** — high difficulty")
                        else:
                            st.markdown("🟡 **Medium Opportunity**")

                    if cluster.get("reasoning"):
                        st.caption(cluster["reasoning"])

                    spokes = cluster.get("spokes", [])
                    if spokes:
                        st.markdown(f"**Spokes ({len(spokes)}):**")

                        # Compact bullet view (always shown)
                        for spoke in spokes:
                            kw = spoke.get("keyword", "")
                            angle = spoke.get("angle", "")
                            vol = spoke.get("search_volume")
                            kd = spoke.get("keyword_difficulty")

                            # Build inline metrics
                            parts = []
                            if vol is not None:
                                try:
                                    parts.append(f"vol: {int(vol):,}")
                                except (ValueError, TypeError):
                                    parts.append(f"vol: {vol}")
                            if kd is not None:
                                kd_val = int(kd) if isinstance(kd, (int, float)) else kd
                                parts.append(f"KD: {kd_val}")
                            metrics_str = f" ({', '.join(parts)})" if parts else ""
                            st.markdown(f"- {kw}{f' — {angle}' if angle else ''}{metrics_str}")

                        # Expandable data table (if any spokes have metrics)
                        has_metrics = any(s.get("search_volume") is not None or s.get("keyword_difficulty") is not None for s in spokes)
                        if has_metrics:
                            with st.expander("📊 View detailed keyword data"):
                                import pandas as pd
                                table_data = []
                                for spoke in spokes:
                                    row = {
                                        "Keyword": spoke.get("keyword", ""),
                                        "Volume": spoke.get("search_volume"),
                                        "KD": spoke.get("keyword_difficulty"),
                                        "CPC ($)": round(spoke["cpc"], 2) if spoke.get("cpc") is not None else None,
                                        "Competition": round(float(spoke["competition"]), 2) if spoke.get("competition") is not None and str(spoke["competition"]).replace('.','',1).isdigit() else spoke.get("competition"),
                                        "Est. Traffic": spoke.get("estimated_traffic"),
                                        "Intent": spoke.get("search_intent", ""),
                                        "Angle": spoke.get("angle", ""),
                                    }
                                    table_data.append(row)
                                df = pd.DataFrame(table_data)

                                # Style: color-code KD column
                                def color_kd(val):
                                    if val is None or pd.isna(val):
                                        return ""
                                    val = float(val)
                                    if val < 30:
                                        return "background-color: #d4edda"  # green
                                    elif val < 60:
                                        return "background-color: #fff3cd"  # yellow
                                    return "background-color: #f8d7da"  # red

                                styled = df.style.map(color_kd, subset=["KD"])
                                st.dataframe(styled, use_container_width=True, hide_index=True)

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

            with st.container(border=True):
                bc1, bc2 = st.columns([4, 1])
                with bc1:
                    st.markdown(
                        f"[{icon}] **{bc.get('pillar_keyword', '?')}** — "
                        f"{bj_status} ({bj_completed}/{bj_total} articles) — {bj_created}"
                    )
                with bc2:
                    if bj_status in ("completed", "failed"):
                        if st.button("Load", key=f"seo_wf_load_batch_{_bjid}", use_container_width=True):
                            st.session_state["seo_wf_batch_job"] = _bjid
                            st.session_state["seo_wf_scroll_top"] = True
                            st.rerun()
                    else:
                        st.write("")
    else:
        st.caption("No recent batch jobs for this brand.")


# =============================================================================
# TAB 3: KEYWORD EXPLORER
# =============================================================================

with tab_explorer:
    st.markdown("Explore keyword opportunities with real search data from DataForSEO.")

    # Input
    explorer_seeds = st.text_area(
        "Seed keywords (one per line, max 10)",
        height=100,
        key="seo_wf_explorer_seeds",
        placeholder="e.g.\nbest games for kids\ngaming headset for children",
    )

    col_explore, col_opts = st.columns([2, 1])
    with col_opts:
        explorer_limit = st.slider(
            "Results per seed",
            min_value=50,
            max_value=500,
            value=200,
            step=50,
            key="seo_wf_explorer_limit",
        )
        explorer_force = st.checkbox(
            "Force refresh (bypass cache)",
            value=False,
            key="seo_wf_explorer_force",
        )

    with col_explore:
        explore_btn = st.button(
            "🔍 Explore Keywords",
            type="primary",
            key="seo_wf_explore_btn",
        )

    if explore_btn and explorer_seeds.strip():
        seeds = [s.strip() for s in explorer_seeds.strip().split("\n") if s.strip()][:10]

        with st.spinner(f"Exploring {len(seeds)} seed keywords..."):
            try:
                from viraltracker.services.seo_pipeline.services.dataforseo_service import DataForSEOService
                dataforseo = DataForSEOService()

                all_suggestions = []
                for seed in seeds:
                    suggestions = dataforseo.get_keyword_suggestions(
                        seed_keyword=seed,
                        limit=explorer_limit,
                    )
                    for s in suggestions:
                        s["source_seed"] = seed
                    all_suggestions.extend(suggestions)

                # Deduplicate by keyword
                seen = set()
                unique = []
                for s in all_suggestions:
                    kw = s.get("keyword", "").lower()
                    if kw not in seen:
                        seen.add(kw)
                        unique.append(s)

                st.session_state["seo_wf_explorer_results"] = unique
            except Exception as e:
                st.error(f"Exploration failed: {e}")

    # Display results
    results = st.session_state.get("seo_wf_explorer_results")
    if results:
        import pandas as pd

        # Summary stats
        volumes = [r.get("search_volume") or 0 for r in results]
        kds = [r.get("keyword_difficulty") or 0 for r in results if r.get("keyword_difficulty") is not None]

        stat_cols = st.columns(4)
        with stat_cols[0]:
            st.metric("Keywords Found", f"{len(results):,}")
        with stat_cols[1]:
            st.metric("Avg Volume", f"{int(sum(volumes)/len(volumes)):,}" if volumes else "—")
        with stat_cols[2]:
            easy = len([k for k in kds if k < 30])
            st.metric("Easy KD (<30)", f"{easy} ({int(easy/len(kds)*100) if kds else 0}%)")
        with stat_cols[3]:
            total_vol = sum(volumes)
            st.metric("Total Volume", f"{total_vol:,}")

        # Filters
        with st.expander("🔧 Filters", expanded=False):
            filter_cols = st.columns(3)
            with filter_cols[0]:
                vol_range = st.slider(
                    "Volume range",
                    min_value=0,
                    max_value=max(max(volumes), 1000),
                    value=(0, max(max(volumes), 1000)),
                    key="seo_wf_explorer_vol_range",
                )
            with filter_cols[1]:
                kd_range = st.slider(
                    "KD range",
                    min_value=0,
                    max_value=100,
                    value=(0, 100),
                    key="seo_wf_explorer_kd_range",
                )
            with filter_cols[2]:
                intent_filter = st.multiselect(
                    "Intent",
                    options=["informational", "commercial", "transactional", "navigational"],
                    default=[],
                    key="seo_wf_explorer_intent",
                )

            filter_cols2 = st.columns(2)
            with filter_cols2[0]:
                cpcs = [r.get("cpc") or 0.0 for r in results]
                max_cpc = max(max(cpcs), 1.0) if cpcs else 1.0
                cpc_range = st.slider(
                    "CPC range ($)",
                    min_value=0.0,
                    max_value=float(max_cpc),
                    value=(0.0, float(max_cpc)),
                    step=0.1,
                    key="seo_wf_explorer_cpc_range",
                )
            with filter_cols2[1]:
                min_word_count = st.number_input(
                    "Min word count",
                    min_value=0,
                    max_value=10,
                    value=0,
                    step=1,
                    key="seo_wf_explorer_min_words",
                    help="Filter to keywords with at least this many words (0 = no filter)",
                )

        # Filter results
        filtered = results
        filtered = [r for r in filtered if (r.get("search_volume") or 0) >= vol_range[0] and (r.get("search_volume") or 0) <= vol_range[1]]
        filtered = [r for r in filtered if (r.get("keyword_difficulty") or 0) >= kd_range[0] and (r.get("keyword_difficulty") or 0) <= kd_range[1]]
        if intent_filter:
            filtered = [r for r in filtered if r.get("search_intent", "").lower() in [i.lower() for i in intent_filter]]
        filtered = [r for r in filtered if (r.get("cpc") or 0.0) >= cpc_range[0] and (r.get("cpc") or 0.0) <= cpc_range[1]]
        if min_word_count > 0:
            filtered = [r for r in filtered if len((r.get("keyword") or "").split()) >= min_word_count]

        st.caption(f"Showing {len(filtered)} of {len(results)} keywords")

        # Build dataframe
        table_data = []
        for r in filtered:
            table_data.append({
                "Keyword": r.get("keyword", ""),
                "Volume": r.get("search_volume"),
                "KD": r.get("keyword_difficulty"),
                "CPC ($)": round(r["cpc"], 2) if r.get("cpc") is not None else None,
                "Competition": round(float(r["competition"]), 2) if r.get("competition") is not None and str(r["competition"]).replace('.','',1).isdigit() else r.get("competition"),
                "Intent": r.get("search_intent", ""),
                "Source Seed": r.get("source_seed", ""),
            })

        df = pd.DataFrame(table_data)

        if not df.empty:
            # Color-code KD
            def color_kd_explorer(val):
                if val is None or pd.isna(val):
                    return ""
                val = float(val)
                if val < 30:
                    return "background-color: #d4edda"
                elif val < 60:
                    return "background-color: #fff3cd"
                return "background-color: #f8d7da"

            styled = df.style.map(color_kd_explorer, subset=["KD"])
            st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

            # Actions
            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button("📋 Add to Cluster Research Seeds", key="seo_wf_explorer_to_cluster"):
                    # Push top keywords into cluster builder session state
                    top_kws = [r["Keyword"] for r in table_data[:20] if r.get("Volume")]
                    existing = st.session_state.get("seo_wf_explorer_selected_seeds", [])
                    st.session_state["seo_wf_explorer_selected_seeds"] = list(set(existing + top_kws))
                    st.success(f"Added {len(top_kws)} keywords to cluster research seeds")

            with action_cols[1]:
                if st.button("💾 Save to Project", key="seo_wf_explorer_save"):
                    try:
                        from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
                        project_svc = SEOProjectService()
                        # Get project for brand
                        projects = project_svc.list_projects(
                            organization_id=org_id,
                            brand_id=brand_id,
                        )
                        if projects:
                            project_id = projects[0]["id"]
                            saved = 0
                            failed = 0
                            for r in table_data[:100]:
                                try:
                                    project_svc.supabase.table("seo_keywords").upsert({
                                        "project_id": project_id,
                                        "keyword": r["Keyword"],
                                        "search_volume": r.get("Volume"),
                                        "keyword_difficulty": r.get("KD"),
                                        "search_intent": r.get("Intent"),
                                    }, on_conflict="project_id,keyword").execute()
                                    saved += 1
                                except Exception:
                                    failed += 1
                            if failed:
                                st.warning(f"Saved {saved} keywords ({failed} failed)")
                            else:
                                st.success(f"Saved {saved} keywords to project")
                        else:
                            st.warning("No SEO project found for this brand. Create one first.")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
        else:
            st.info("No keywords match the current filters.")
