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
import time
from datetime import datetime, timedelta

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

# ----- Recently kicked-off regeneration confirmations -----
# When Regenerate-from-scratch is clicked, we stash a banner here so the user
# has persistent confirmation even after the eval row is superseded and the
# success toast fades.
_recent_regens = st.session_state.get("exceptions_recent_regens", [])
# Drop confirmations older than 10 minutes so the list stays useful.
_recent_regens = [r for r in _recent_regens if (time.time() - r.get("ts", 0)) < 600]
st.session_state["exceptions_recent_regens"] = _recent_regens

if _recent_regens:
    for r in reversed(_recent_regens):
        ago_s = int(time.time() - r["ts"])
        ago = f"{ago_s}s ago" if ago_s < 60 else f"{ago_s // 60}m ago"
        st.success(
            f"🔁 Regeneration started for **{r['keyword']}** ({ago}). "
            f"Job `{r['job_id'][:8]}` is running in the background — see the "
            "**Background jobs** panel below for live status."
        )

# ----- In-flight background jobs (Quick Write + Regenerate from scratch) -----
# Querying directly instead of adding a service method — it's a single read
# and only this page needs it today.
_db = get_db()
_active_query = (
    _db.table("seo_workflow_jobs")
    .select("id, job_type, status, config, progress, created_at, updated_at, error")
    .in_("status", ["pending", "running", "paused"])
    .order("created_at", desc=True)
    .limit(20)
)
if brand_id and brand_id != "all":
    _active_query = _active_query.eq("brand_id", brand_id)
if organization_id and organization_id != "all":
    _active_query = _active_query.eq("organization_id", organization_id)
active_jobs = _active_query.execute().data or []

# Also surface jobs that finished or failed in the last 2 minutes so the user
# sees the transition from "running" to "done" without having to refresh on
# exact timing. Anything older than that is on the SEO Workflow page already.
_recent_query = (
    _db.table("seo_workflow_jobs")
    .select("id, job_type, status, config, progress, created_at, updated_at, error")
    .in_("status", ["completed", "failed", "cancelled"])
    .order("updated_at", desc=True)
    .limit(10)
)
if brand_id and brand_id != "all":
    _recent_query = _recent_query.eq("brand_id", brand_id)
if organization_id and organization_id != "all":
    _recent_query = _recent_query.eq("organization_id", organization_id)
_recently_finished_raw = _recent_query.execute().data or []
_now = datetime.now().astimezone()
recently_finished = []
for j in _recently_finished_raw:
    upd = j.get("updated_at") or ""
    try:
        dt = datetime.fromisoformat(upd.replace("Z", "+00:00"))
        if (_now - dt).total_seconds() < 120:
            recently_finished.append(j)
    except (ValueError, TypeError):
        continue

if active_jobs or recently_finished:
    with st.container(border=True):
        st.markdown("**Background jobs**")
        st.caption(
            "Regeneration and Quick Write jobs run in the background. This panel "
            "shows what's in flight so you can confirm your click did something. "
            "Auto-refreshes every 10 seconds while jobs are active."
        )

        for j in active_jobs:
            cfg = j.get("config", {}) or {}
            prog = j.get("progress", {}) or {}
            keyword = cfg.get("keyword", "?")
            is_regen = bool(cfg.get("existing_article_id"))
            label = "🔁 Regenerating" if is_regen else "✍️ Writing"
            step = prog.get("current_step_label") or prog.get("current_step") or "starting"
            pct = prog.get("percent", 0) or 0
            started = j.get("created_at", "")
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                started_ago_s = int((_now - dt).total_seconds())
                started_label = (
                    f"{started_ago_s}s ago" if started_ago_s < 60
                    else f"{started_ago_s // 60}m {started_ago_s % 60}s ago"
                )
            except (ValueError, TypeError):
                started_label = "just now"
            st.markdown(
                f"- {label} `{keyword}` — **{step}** ({pct}%)  ·  "
                f"started {started_label}  ·  job `{j['id'][:8]}`"
            )

        for j in recently_finished:
            cfg = j.get("config", {}) or {}
            keyword = cfg.get("keyword", "?")
            is_regen = bool(cfg.get("existing_article_id"))
            kind = "Regeneration" if is_regen else "Quick Write"
            status = j.get("status", "?")
            icon = {"completed": "✅", "failed": "❌", "cancelled": "⏹️"}.get(status, "•")
            err = j.get("error") or ""
            err_suffix = f" — {err[:120]}" if status == "failed" and err else ""
            st.markdown(
                f"- {icon} {kind} `{keyword}` — **{status}**{err_suffix}  ·  job `{j['id'][:8]}`"
            )

        # Manual refresh — explicit and never blocks the rest of the page.
        if st.button("🔄 Refresh", key="exc_jobs_refresh"):
            st.rerun()

        # Non-blocking auto-refresh while jobs are active. Uses
        # st.fragment(run_every=...) so the server thread is never blocked and
        # the rest of the page (tabs, expanders) renders immediately.
        if active_jobs:
            @st.fragment(run_every=timedelta(seconds=10))
            def _poll_active_jobs():
                ts_key = "_exc_jobs_last_poll"
                now = time.time()
                last = st.session_state.get(ts_key, 0)
                # Skip the initial render — only the timer-fired reruns
                # should kick a full app rerun.
                if last > 0 and (now - last) >= 8:
                    st.session_state[ts_key] = now
                    st.rerun(scope="app")
                st.session_state[ts_key] = now

            _poll_active_jobs()

total = eval_count + publish_count

if total == 0:
    if active_jobs:
        st.info(
            "No current exceptions — background jobs above are still running. "
            "If any of them produce a new failure, it will appear here once they finish."
        )
    else:
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
                article_word_count = article_info.get("word_count") or 0
                eval_brand_id = eval_result.get("brand_id") or brand_id
                eval_org_id = eval_result.get("organization_id") or organization_id

                # If the article body is effectively empty, the surgical fixes
                # below won't help — they all operate on the existing content.
                # Surface "Regenerate from scratch" at the top with a warning.
                is_empty_article = article_word_count < 50
                if is_empty_article:
                    st.warning(
                        f"This article has only {article_word_count} word(s). The surgical "
                        "fixes below operate on existing content and won't help here. "
                        "Use **Regenerate from scratch** to re-run the full pipeline."
                    )
                    if st.button(
                        "🔁 Regenerate from scratch (rewrite everything)",
                        key=f"exc_fix_regen_top_{eval_result['id']}",
                        type="primary",
                        use_container_width=True,
                        help="Re-runs Phase A → B → C → images against this article's keyword. Takes several minutes; runs in the background.",
                    ):
                        try:
                            job_id = get_workflow_service().regenerate_article(
                                article_id=article_id,
                                brand_id=eval_brand_id,
                                organization_id=eval_org_id,
                            )
                            _reset_for_re_evaluation(eval_result["id"], article_id)
                            _recent = st.session_state.get("exceptions_recent_regens", [])
                            _recent.append({
                                "ts": time.time(),
                                "job_id": job_id,
                                "keyword": article_keyword or "article",
                                "article_id": article_id,
                            })
                            st.session_state["exceptions_recent_regens"] = _recent
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"Could not start regeneration: {str(e)[:300]}")

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

                # Last-resort "rewrite everything" — always available, but only
                # rendered down here when the article actually has content
                # (otherwise the prominent top-of-panel version above is shown).
                if not is_empty_article:
                    st.caption(
                        "If none of the surgical fixes match the failure (article is structurally "
                        "wrong, off-topic, or you just want a fresh take), regenerate from scratch:"
                    )
                    if st.button(
                        "🔁 Regenerate from scratch (rewrite everything)",
                        key=f"exc_fix_regen_bottom_{eval_result['id']}",
                        use_container_width=True,
                        help="Re-runs Phase A → B → C → images against this article's keyword. Takes several minutes; runs in the background.",
                    ):
                        try:
                            job_id = get_workflow_service().regenerate_article(
                                article_id=article_id,
                                brand_id=eval_brand_id,
                                organization_id=eval_org_id,
                            )
                            _reset_for_re_evaluation(eval_result["id"], article_id)
                            _recent = st.session_state.get("exceptions_recent_regens", [])
                            _recent.append({
                                "ts": time.time(),
                                "job_id": job_id,
                                "keyword": article_keyword or "article",
                                "article_id": article_id,
                            })
                            st.session_state["exceptions_recent_regens"] = _recent
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"Could not start regeneration: {str(e)[:300]}")

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
