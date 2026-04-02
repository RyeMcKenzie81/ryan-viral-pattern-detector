"""
Pipeline Status Page — visual overview of the SEO content autopilot pipeline.

Shows articles flowing through stages:
  discovered → draft → draft_complete → qa_passed → eval_passed → publish_queued → publishing → published

Includes:
- Stage counts with visual pipeline
- Article table per stage with drill-down
- Publish queue status
- Recent eval results
"""

import logging
from datetime import datetime, timezone

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Pipeline Status", page_icon="📊", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def get_db():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_tracking_service():
    from viraltracker.services.seo_pipeline.services.article_tracking_service import ArticleTrackingService
    return ArticleTrackingService()


# Pipeline stages in order
PIPELINE_STAGES = [
    ("discovered", "Discovered"),
    ("draft", "Draft"),
    ("outline_complete", "Outlined"),
    ("draft_complete", "Written"),
    ("optimized", "Optimized"),
    ("qa_pending", "QA Pending"),
    ("qa_passed", "QA Passed"),
    ("qa_failed", "QA Failed"),
    ("eval_passed", "Eval Passed"),
    ("eval_failed", "Eval Failed"),
    ("publish_queued", "Queued"),
    ("publishing", "Publishing"),
    ("published", "Published"),
    ("archived", "Archived"),
]

# Color coding for stages
STAGE_COLORS = {
    "discovered": "#6c757d",
    "draft": "#17a2b8",
    "outline_complete": "#17a2b8",
    "draft_complete": "#17a2b8",
    "optimized": "#17a2b8",
    "qa_pending": "#ffc107",
    "qa_passed": "#28a745",
    "qa_failed": "#dc3545",
    "eval_passed": "#28a745",
    "eval_failed": "#dc3545",
    "publish_queued": "#fd7e14",
    "publishing": "#fd7e14",
    "published": "#28a745",
    "archived": "#6c757d",
}


# =============================================================================
# DATA LOADING
# =============================================================================

def load_status_counts(brand_id: str) -> dict:
    """Load article counts grouped by status for a brand."""
    db = get_db()
    resp = db.table("seo_articles").select("status").eq("brand_id", brand_id).execute()
    counts = {}
    for row in resp.data:
        status = row.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def load_articles_by_status(brand_id: str, status: str) -> list:
    """Load articles with a specific status."""
    db = get_db()
    resp = (
        db.table("seo_articles")
        .select("id, keyword, title, seo_title, status, phase, word_count, content_markdown, updated_at, cms_article_id, published_url")
        .eq("brand_id", brand_id)
        .eq("status", status)
        .order("updated_at", desc=True)
        .execute()
    )
    return resp.data or []


def load_publish_queue(brand_id: str) -> list:
    """Load publish queue entries for a brand."""
    db = get_db()
    resp = (
        db.table("seo_publish_queue")
        .select("id, article_id, status, publish_at, published_at, error_message, retry_count")
        .eq("brand_id", brand_id)
        .order("publish_at", desc=False)
        .execute()
    )
    return resp.data or []


def load_recent_evals(brand_id: str, limit: int = 20) -> list:
    """Load recent content evaluation results."""
    db = get_db()
    resp = (
        db.table("seo_content_eval_results")
        .select("id, article_id, verdict, total_checks, passed_checks, failed_checks, warning_count, evaluated_at")
        .eq("brand_id", brand_id)
        .order("evaluated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def load_article_titles(brand_id: str) -> dict:
    """Load keyword/title lookup for article IDs."""
    db = get_db()
    resp = (
        db.table("seo_articles")
        .select("id, keyword, title, seo_title")
        .eq("brand_id", brand_id)
        .execute()
    )
    lookup = {}
    for row in resp.data or []:
        name = row.get("seo_title") or row.get("title") or row.get("keyword") or row["id"][:8]
        lookup[row["id"]] = name
    return lookup


# =============================================================================
# UI RENDERING
# =============================================================================

def render_pipeline_overview(counts: dict):
    """Render the pipeline stage counts as a visual overview."""
    st.subheader("Pipeline Overview")

    # Split into active pipeline stages and terminal/error states
    active_stages = [
        ("discovered", "Discovered", "Keywords found via GSC or research. Not yet written."),
        ("draft", "Draft", "Article writing in progress (outline, free-write, or optimization phase)."),
        ("draft_complete", "Written", "Article fully written and ready for QA validation."),
        ("qa_passed", "QA Passed", "Passed automated QA checks. Waiting for content evaluation."),
        ("eval_passed", "Eval Passed", "Passed content eval (auto-fix + quality checks). Ready to queue for publishing."),
        ("publish_queued", "Queued", "In the publish queue with a scheduled time slot."),
        ("published", "Published", "Live on Shopify."),
    ]
    error_stages = [
        ("qa_failed", "QA Failed"),
        ("eval_failed", "Eval Failed"),
    ]

    # Main pipeline flow
    cols = st.columns(len(active_stages))
    for i, (status, label, tooltip) in enumerate(active_stages):
        count = counts.get(status, 0)
        with cols[i]:
            color = STAGE_COLORS.get(status, "#6c757d")
            st.markdown(
                f"<div title='{tooltip}' style='text-align:center; padding:12px; border-radius:8px; "
                f"cursor:help; border: 2px solid {color}; background: {color}15;'>"
                f"<div style='font-size:24px; font-weight:bold; color:{color};'>{count}</div>"
                f"<div style='font-size:12px; color:#666;'>{label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Error/blocked states
    if any(counts.get(s, 0) > 0 for s, _ in error_stages):
        st.markdown("---")
        err_cols = st.columns(len(error_stages))
        for i, (status, label) in enumerate(error_stages):
            count = counts.get(status, 0)
            if count > 0:
                with err_cols[i]:
                    st.metric(label, count, delta=f"-{count}", delta_color="inverse")

    # Show other statuses not in the main flow
    other_counts = {
        k: v for k, v in counts.items()
        if k not in {s for s, *_ in active_stages} and k not in dict(error_stages) and v > 0
    }
    if other_counts:
        with st.expander("Other statuses"):
            for status, count in sorted(other_counts.items()):
                st.write(f"**{status}**: {count}")

    total = sum(counts.values())
    st.caption(f"Total articles: {total}")


def render_stage_detail(brand_id: str, counts: dict):
    """Render article details for a selected stage."""
    st.subheader("Articles by Stage")

    # Build options with counts
    options = [(s, f"{label} ({counts.get(s, 0)})") for s, label in PIPELINE_STAGES if counts.get(s, 0) > 0]
    if not options:
        st.info("No articles found for this brand.")
        return

    status_keys = [o[0] for o in options]
    status_labels = [o[1] for o in options]

    # Default to qa_passed if available, otherwise first option
    default_idx = 0
    if "qa_passed" in status_keys:
        default_idx = status_keys.index("qa_passed")

    selected_label = st.selectbox("Stage", status_labels, index=default_idx, key="pipeline_stage_select")
    selected_status = status_keys[status_labels.index(selected_label)]

    articles = load_articles_by_status(brand_id, selected_status)
    if not articles:
        st.info(f"No articles in {selected_status} stage.")
        return

    table_data = []
    for a in articles:
        name = a.get("seo_title") or a.get("title") or a.get("keyword") or "—"
        if len(name) > 60:
            name = name[:57] + "..."
        updated = a.get("updated_at", "")
        if updated:
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                updated = dt.strftime("%b %d, %H:%M")
            except (ValueError, TypeError):
                pass
        words = a.get("word_count")
        if not words and a.get("content_markdown"):
            words = len(a["content_markdown"].split())
        row = {
            "Article": name,
            "Keyword": a.get("keyword", "—"),
            "Words": words or "—",
            "Updated": updated,
        }
        if selected_status == "published":
            url = a.get("published_url", "")
            row["URL"] = url if url else "—"
        table_data.append(row)

    st.dataframe(table_data, use_container_width=True, hide_index=True)


def render_publish_queue(brand_id: str, article_lookup: dict):
    """Render the publish queue status."""
    st.subheader("Publish Queue")

    queue = load_publish_queue(brand_id)
    if not queue:
        st.info("Publish queue is empty.")
        return

    # Summary metrics
    status_counts = {}
    for entry in queue:
        s = entry.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    cols = st.columns(4)
    for i, (status, label) in enumerate([("queued", "Queued"), ("publishing", "In Progress"), ("published", "Published"), ("failed", "Failed")]):
        with cols[i]:
            st.metric(label, status_counts.get(status, 0))

    # Queue table
    table_data = []
    for entry in queue:
        article_id = entry.get("article_id", "")
        article_name = article_lookup.get(article_id, article_id[:8] if article_id else "—")
        if len(article_name) > 50:
            article_name = article_name[:47] + "..."

        publish_at = entry.get("publish_at", "")
        if publish_at:
            try:
                dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
                publish_at = dt.strftime("%b %d, %H:%M")
            except (ValueError, TypeError):
                pass

        row = {
            "Article": article_name,
            "Status": entry.get("status", "—"),
            "Scheduled": publish_at,
            "Retries": entry.get("retry_count", 0),
        }
        if entry.get("error_message"):
            row["Error"] = entry["error_message"][:80]
        else:
            row["Error"] = "—"
        table_data.append(row)

    st.dataframe(table_data, use_container_width=True, hide_index=True)


def render_recent_evals(brand_id: str, article_lookup: dict):
    """Render recent content evaluation results."""
    st.subheader("Recent Evaluations")

    evals = load_recent_evals(brand_id)
    if not evals:
        st.info("No evaluation results yet.")
        return

    table_data = []
    for ev in evals:
        article_id = ev.get("article_id", "")
        article_name = article_lookup.get(article_id, article_id[:8] if article_id else "—")
        if len(article_name) > 50:
            article_name = article_name[:47] + "..."

        verdict = ev.get("verdict", "—")
        evaluated_at = ev.get("evaluated_at", "")
        if evaluated_at:
            try:
                dt = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
                evaluated_at = dt.strftime("%b %d, %H:%M")
            except (ValueError, TypeError):
                pass

        table_data.append({
            "Article": article_name,
            "Verdict": verdict.upper() if verdict else "—",
            "Passed": ev.get("passed_checks", 0),
            "Failed": ev.get("failed_checks", 0),
            "Warnings": ev.get("warning_count", 0),
            "Evaluated": evaluated_at,
        })

    st.dataframe(table_data, use_container_width=True, hide_index=True)


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("📊 Pipeline Status")
st.caption("SEO content autopilot pipeline overview")

from viraltracker.ui.utils import render_brand_selector

brand_id = render_brand_selector(key="pipeline_status_brand_selector")
if not brand_id:
    st.stop()

# Load data
counts = load_status_counts(brand_id)
article_lookup = load_article_titles(brand_id)

if not counts:
    st.info("No articles found for this brand. Start by running the SEO Workflow to discover and write articles.")
    st.stop()

# Render sections
render_pipeline_overview(counts)

st.divider()

tab1, tab2, tab3 = st.tabs(["Articles by Stage", "Publish Queue", "Recent Evaluations"])

with tab1:
    render_stage_detail(brand_id, counts)

with tab2:
    render_publish_queue(brand_id, article_lookup)

with tab3:
    render_recent_evals(brand_id, article_lookup)
