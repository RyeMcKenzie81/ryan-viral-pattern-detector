"""
Exceptions Dashboard — shows SEO content that needs human attention.

Three exception types:
1. Failed evaluations (image/content QA failures)
2. Failed publishes (Shopify API errors)
3. Failed interlinks (pattern matching or CMS update errors)

Each exception has actions: Override, Retry, Skip, etc.
"""

import json
import logging
import streamlit as st
from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Exceptions", page_icon="⚠️", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def get_eval_service():
    from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
    return ContentEvalService()


def get_queue_service():
    from viraltracker.services.seo_pipeline.services.publish_queue_service import PublishQueueService
    return PublishQueueService()


def get_workflow_service():
    from viraltracker.services.seo_pipeline.services.seo_workflow_service import SEOWorkflowService
    return SEOWorkflowService()


def get_db():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def _parse_json_field(value):
    """Parse a JSONB field that might be a string or already a dict."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value or {}


def _suggest_fixes_for_eval(ev: dict) -> dict:
    """Inspect a failed eval's JSONB and flag which fix actions are likely to help.

    Returns a dict of booleans the UI uses to add a 💡 hint next to the most
    relevant button. All buttons remain clickable regardless — the user can
    pick anything; the hint is just a nudge.
    """
    qa = _parse_json_field(ev.get("qa_result"))
    cl = _parse_json_field(ev.get("checklist_result"))
    img = _parse_json_field(ev.get("image_eval_result"))

    failure_names: list[str] = []
    for src in (qa, cl):
        for f in (src.get("failures") or []):
            failure_names.append((f.get("name") or "").lower())

    has_image_failures = any(
        any(not r.get("passed") for r in (e.get("rules") or []))
        for e in (img.get("evaluations") or [])
    )
    has_meta = any(("meta" in n) or ("description" in n) for n in failure_names)
    has_first_para = any(("first_paragraph" in n) or ("first paragraph" in n) for n in failure_names)
    has_other_content = any(
        n
        and "meta" not in n
        and "description" not in n
        and "first_paragraph" not in n
        and "first paragraph" not in n
        for n in failure_names
    )

    return {
        "image": has_image_failures,
        "meta_description": has_meta,
        "first_paragraph": has_first_para,
        "content": has_other_content,
    }


def _reset_for_re_evaluation(eval_id: str, article_id: str) -> None:
    """Mark the current eval as superseded and reset article status so the
    scheduler worker picks it up on its next pass (~60s) and re-evaluates.

    Same shape as the existing Re-evaluate button so behaviour is consistent
    across all the fix actions.
    """
    db = get_db()
    db.table("seo_content_eval_results").update(
        {"superseded_by": eval_id}
    ).eq("id", eval_id).execute()
    db.table("seo_articles").update(
        {"status": "qa_passed"}
    ).eq("id", article_id).execute()


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("⚠️ Exceptions Dashboard")
st.caption("Content that needs your attention. Only failed items appear here.")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="exceptions_brand")
if not brand_id:
    st.stop()

from viraltracker.ui.utils import get_current_organization_id
organization_id = get_current_organization_id()

# Load counts for tabs
eval_service = get_eval_service()
queue_service = get_queue_service()

filter_kwargs = {}
if brand_id and brand_id != "all":
    filter_kwargs["brand_id"] = brand_id
if organization_id and organization_id != "all":
    filter_kwargs["organization_id"] = organization_id

failed_evals = eval_service.get_failed_evals(**filter_kwargs)
failed_publishes = queue_service.get_failed_publishes(**filter_kwargs)

eval_count = len(failed_evals)
publish_count = len(failed_publishes)
total = eval_count + publish_count

if total == 0:
    st.success("No exceptions! All content is passing evaluation and publishing successfully.")
    st.stop()

# Summary metrics
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Failed Evaluations", eval_count)
with col2:
    st.metric("Failed Publishes", publish_count)
with col3:
    st.metric("Total Exceptions", total)

st.divider()

# =============================================================================
# FAILED EVALUATIONS TAB
# =============================================================================

tab1, tab2 = st.tabs([
    f"Failed Evaluations ({eval_count})",
    f"Failed Publishes ({publish_count})",
])

with tab1:
    # Deep-link support: when another page (e.g. Pipeline Status > Recent
    # Evaluations) sends a user here via "Open in Exceptions →", it sets
    # `exceptions_focus_article_id` in session state. Auto-expand the matching
    # row and clear the key so subsequent reruns don't keep forcing it open.
    focus_article_id = st.session_state.pop("exceptions_focus_article_id", None)

    if not failed_evals:
        st.info("No failed evaluations.")
    else:
        for i, eval_result in enumerate(failed_evals):
            article_info = eval_result.get("seo_articles") or {}
            keyword = article_info.get("keyword", "Unknown")
            title = article_info.get("title", "")

            is_focused = bool(
                focus_article_id and eval_result.get("article_id") == focus_article_id
            )
            # If a specific article is focused, only it expands; otherwise fall
            # back to the prior behaviour of expanding the first row.
            should_expand = is_focused if focus_article_id else (i == 0)

            with st.expander(
                f"{'🔴' if eval_result.get('failed_checks', 0) > 0 else '🟡'} "
                f"{keyword} — {eval_result.get('failed_checks', 0)} errors, "
                f"{eval_result.get('warning_count', 0)} warnings",
                expanded=should_expand,
            ):
                st.caption(f"Evaluated: {eval_result.get('evaluated_at', 'Unknown')}")

                # QA Results
                qa_result = _parse_json_field(eval_result.get("qa_result"))
                if qa_result:
                    qa_failures = qa_result.get("failures", [])
                    qa_warnings = qa_result.get("warnings", [])
                    if qa_failures or qa_warnings:
                        st.markdown("**QA Check Results:**")
                        for f in qa_failures:
                            st.error(f"❌ {f.get('name', 'unknown')}: {f.get('message', '')}")
                        for w in qa_warnings:
                            st.warning(f"⚠️ {w.get('name', 'unknown')}: {w.get('message', '')}")

                # Checklist Results
                checklist_result = _parse_json_field(eval_result.get("checklist_result"))
                if checklist_result:
                    cl_failures = checklist_result.get("failures", [])
                    cl_warnings = checklist_result.get("warnings", [])
                    if cl_failures or cl_warnings:
                        st.markdown("**Pre-Publish Checklist:**")
                        for f in cl_failures:
                            st.error(f"❌ {f.get('name', 'unknown')}: {f.get('message', '')}")
                        for w in cl_warnings:
                            st.warning(f"⚠️ {w.get('name', 'unknown')}: {w.get('message', '')}")

                # Image Eval Results
                image_result = _parse_json_field(eval_result.get("image_eval_result"))
                if image_result and image_result.get("evaluations"):
                    st.markdown("**Image Evaluation:**")
                    for img_eval in image_result["evaluations"]:
                        img_status = "✅" if img_eval.get("passed") else ("❓" if img_eval.get("uncertain") else "❌")
                        st.markdown(f"{img_status} **{img_eval.get('image_type', 'image').title()}**")

                        if img_eval.get("image_url"):
                            try:
                                st.image(img_eval["image_url"], width=300)
                            except Exception:
                                st.caption(f"Image: {img_eval['image_url']}")

                        for rule in img_eval.get("rules", []):
                            if not rule.get("passed"):
                                confidence = rule.get("confidence", 0)
                                st.markdown(
                                    f"  - [{rule.get('severity', 'error').upper()}] "
                                    f"{rule.get('rule', '')} "
                                    f"(confidence: {confidence:.0%}): "
                                    f"_{rule.get('explanation', '')}_"
                                )

                # ----- Fix the article: actually rebuild what's broken -----
                # These buttons call the existing SEOWorkflowService re-run
                # methods (`regenerate_images`, `rerun_phase_c`,
                # `fix_meta_description`, `fix_first_paragraph`) and then reset
                # the article so the scheduler worker re-evaluates it on its
                # next pass.
                st.markdown("---")
                st.markdown("**Fix the article**")
                st.caption(
                    "Pick the action that matches the failure. Each one regenerates the "
                    "broken piece and then queues the article for re-evaluation. 💡 marks "
                    "the action most likely to address the failures shown above."
                )

                suggestions = _suggest_fixes_for_eval(eval_result)
                article_id = eval_result["article_id"]
                article_keyword = article_info.get("keyword", "") or ""
                eval_brand_id = eval_result.get("brand_id") or brand_id
                eval_org_id = eval_result.get("organization_id") or organization_id

                fix_col1, fix_col2 = st.columns(2)
                with fix_col1:
                    img_label = "🎨 Regenerate Images" + (" 💡" if suggestions["image"] else "")
                    if st.button(
                        img_label,
                        key=f"exc_fix_images_{eval_result['id']}",
                        help="Re-run image generation. Use this when image evaluation failed (wrong subject, off-brand, low quality).",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner("Regenerating images..."):
                                get_workflow_service().regenerate_images(
                                    article_id=article_id,
                                    brand_id=eval_brand_id,
                                    organization_id=eval_org_id,
                                )
                            _reset_for_re_evaluation(eval_result["id"], article_id)
                            st.success("Images regenerated. Article queued for re-evaluation.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Image regeneration failed: {str(e)[:300]}")

                    phasec_label = "✍️ Re-optimize Content" + (" 💡" if suggestions["content"] else "")
                    if st.button(
                        phasec_label,
                        key=f"exc_fix_phasec_{eval_result['id']}",
                        help="Re-run the optimize phase (Phase C). Use this when content quality, brand voice, structure, or general QA checks failed.",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner("Re-running optimize phase..."):
                                get_workflow_service().rerun_phase_c(
                                    article_id=article_id,
                                    brand_id=eval_brand_id,
                                    organization_id=eval_org_id,
                                    republish=False,
                                )
                            _reset_for_re_evaluation(eval_result["id"], article_id)
                            st.success("Content re-optimized. Article queued for re-evaluation.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Re-optimize failed: {str(e)[:300]}")

                with fix_col2:
                    meta_label = "🏷️ Fix Meta Description" + (" 💡" if suggestions["meta_description"] else "")
                    if st.button(
                        meta_label,
                        key=f"exc_fix_meta_{eval_result['id']}",
                        help="Generate a new meta description that fits 150–160 chars and includes the target keyword.",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner("Fixing meta description..."):
                                fix_result = get_workflow_service().fix_meta_description(
                                    article_id=article_id,
                                    keyword=article_keyword,
                                )
                            if fix_result.get("error"):
                                st.error(f"Could not fix meta description: {fix_result['error']}")
                            else:
                                _reset_for_re_evaluation(eval_result["id"], article_id)
                                st.success(
                                    f"Meta description rewritten ({fix_result.get('length', '?')} chars). "
                                    "Article queued for re-evaluation."
                                )
                                st.rerun()
                        except Exception as e:
                            st.error(f"Meta description fix failed: {str(e)[:300]}")

                    fp_label = "📝 Fix First Paragraph" + (" 💡" if suggestions["first_paragraph"] else "")
                    if st.button(
                        fp_label,
                        key=f"exc_fix_fp_{eval_result['id']}",
                        help="Rewrite the opening paragraph so the target keyword appears naturally.",
                        use_container_width=True,
                    ):
                        try:
                            with st.spinner("Fixing first paragraph..."):
                                fix_result = get_workflow_service().fix_first_paragraph(
                                    article_id=article_id,
                                    keyword=article_keyword,
                                )
                            if fix_result.get("error"):
                                st.error(f"Could not fix first paragraph: {fix_result['error']}")
                            else:
                                _reset_for_re_evaluation(eval_result["id"], article_id)
                                st.success("First paragraph rewritten. Article queued for re-evaluation.")
                                st.rerun()
                        except Exception as e:
                            st.error(f"First paragraph fix failed: {str(e)[:300]}")

                # ----- Decide what to do (existing flow) -----
                st.markdown("---")
                st.markdown("**Decide what to do**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    override_reason = st.text_input(
                        "Override reason",
                        placeholder="e.g., Image is acceptable for this brand",
                        key=f"exc_override_reason_{eval_result['id']}",
                    )
                    if st.button(
                        "Override & Publish",
                        key=f"exc_override_{eval_result['id']}",
                        type="primary",
                    ):
                        if override_reason.strip():
                            eval_service.override_eval(
                                eval_result["id"], override_reason.strip()
                            )
                            st.success("Overridden! Article moved to eval_passed.")
                            st.rerun()
                        else:
                            st.error("Please provide a reason for overriding.")

                with col2:
                    if st.button(
                        "Skip (Keep Failed)",
                        key=f"exc_skip_{eval_result['id']}",
                    ):
                        st.info("Article remains in eval_failed status.")

                with col3:
                    if st.button(
                        "Re-evaluate (no changes)",
                        key=f"exc_reeval_{eval_result['id']}",
                        help="Re-run the eval against the current content without changing anything. Use this if you think the eval was wrong.",
                    ):
                        _reset_for_re_evaluation(eval_result["id"], eval_result["article_id"])
                        st.success("Article queued for re-evaluation.")
                        st.rerun()

with tab2:
    if not failed_publishes:
        st.info("No failed publishes.")
    else:
        for i, entry in enumerate(failed_publishes):
            article_info = entry.get("seo_articles") or {}
            keyword = article_info.get("keyword", "Unknown")

            with st.expander(
                f"🔴 {keyword} — {entry.get('retry_count', 0)} retries",
                expanded=(i == 0),
            ):
                st.caption(f"Last attempt: {entry.get('updated_at', 'Unknown')}")
                st.error(f"Error: {entry.get('error_message', 'Unknown error')}")
                st.text(f"Retries: {entry.get('retry_count', 0)} / {entry.get('max_retries', 3)}")

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button(
                        "Retry Now",
                        key=f"exc_retry_pub_{entry['id']}",
                        type="primary",
                    ):
                        queue_service.retry_publish(entry["id"])
                        st.success("Queued for immediate retry!")
                        st.rerun()

                with col2:
                    if st.button(
                        "Cancel",
                        key=f"exc_cancel_pub_{entry['id']}",
                    ):
                        queue_service.cancel_publish(entry["id"])
                        st.success("Publish cancelled.")
                        st.rerun()

                with col3:
                    scheduled = entry.get("publish_at", "")
                    st.caption(f"Originally scheduled: {scheduled}")
