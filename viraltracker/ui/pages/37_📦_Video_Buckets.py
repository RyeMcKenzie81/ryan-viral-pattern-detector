"""
Video Buckets — Organize bulk video uploads into content buckets.

Upload 10-20 videos, Gemini analyzes each one (transcript, text overlays,
storyboard), and outputs a filename → bucket mapping for efficient
organization with the right ad copy.

Three tabs:
1. Manage Buckets — CRUD for content bucket definitions
2. Categorize Videos — Upload and auto-categorize videos
3. Results — View past categorization sessions
"""

import streamlit as st
import json
from uuid import uuid4

# Page config (must be first Streamlit call)
st.set_page_config(page_title="Video Buckets", page_icon="📦", layout="wide")

# Auth
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("video_buckets", "Video Buckets")


# ============================================
# SESSION STATE
# ============================================

if "vb_session_id" not in st.session_state:
    st.session_state.vb_session_id = None
if "vb_results" not in st.session_state:
    st.session_state.vb_results = None
if "vb_processing" not in st.session_state:
    st.session_state.vb_processing = False
if "vb_file_map" not in st.session_state:
    st.session_state.vb_file_map = {}


# ============================================
# SERVICES
# ============================================

@st.cache_resource
def get_service():
    from viraltracker.services.content_bucket_service import ContentBucketService
    return ContentBucketService()


# ============================================
# HELPERS
# ============================================

def parse_textarea_lines(text: str) -> list:
    """Parse a textarea into a list of non-empty lines."""
    return [line.strip() for line in text.strip().split("\n") if line.strip()]


def format_list_for_display(items) -> str:
    """Format a JSON list or list for display."""
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (json.JSONDecodeError, TypeError):
            return items
    if isinstance(items, list):
        return "\n".join(f"- {item}" for item in items) if items else "—"
    return str(items) if items else "—"


# ============================================
# TAB 1: MANAGE BUCKETS
# ============================================

def render_manage_buckets(product_id: str, org_id: str):
    """Render bucket CRUD interface."""
    service = get_service()
    buckets = service.get_buckets(product_id, org_id)

    st.subheader(f"Content Buckets ({len(buckets)})")

    # Add new bucket form
    with st.expander("Add New Bucket", expanded=not buckets):
        with st.form("add_bucket_form"):
            name = st.text_input("Bucket Name *", placeholder="e.g., Digestion & Gut Health")
            best_for = st.text_area("Best For", placeholder="What types of videos belong here?", height=68)
            angle = st.text_input("Angle", placeholder="e.g., Fear-based, educational")
            avatar = st.text_input("Avatar", placeholder="e.g., Health-conscious woman, 35-55")

            col1, col2, col3 = st.columns(3)
            with col1:
                pain_points_text = st.text_area(
                    "Pain Points (one per line)", height=100,
                    placeholder="Bloating after meals\nLow energy\nBrain fog"
                )
            with col2:
                solution_text = st.text_area(
                    "Solution Mechanism (one per line)", height=100,
                    placeholder="Probiotic strains\nGut-brain connection"
                )
            with col3:
                hooks_text = st.text_area(
                    "Key Copy Hooks (one per line)", height=100,
                    placeholder="Your gut is your second brain\nStop ignoring these signs"
                )

            submitted = st.form_submit_button("Create Bucket", type="primary")
            if submitted:
                if not name:
                    st.error("Bucket name is required.")
                else:
                    try:
                        service.create_bucket(
                            org_id=org_id,
                            product_id=product_id,
                            name=name,
                            best_for=best_for or None,
                            angle=angle or None,
                            avatar=avatar or None,
                            pain_points=parse_textarea_lines(pain_points_text),
                            solution_mechanism=parse_textarea_lines(solution_text),
                            key_copy_hooks=parse_textarea_lines(hooks_text),
                        )
                        st.success(f"Created bucket: {name}")
                        st.rerun()
                    except Exception as e:
                        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                            st.error(f"A bucket named '{name}' already exists for this product.")
                        else:
                            st.error(f"Error creating bucket: {e}")

    # List existing buckets
    if not buckets:
        st.info("No buckets yet. Create your first bucket above.")
        return

    for bucket in buckets:
        pain_pts = bucket.get("pain_points", [])
        if isinstance(pain_pts, str):
            pain_pts = json.loads(pain_pts)
        sol_mech = bucket.get("solution_mechanism", [])
        if isinstance(sol_mech, str):
            sol_mech = json.loads(sol_mech)
        hooks = bucket.get("key_copy_hooks", [])
        if isinstance(hooks, str):
            hooks = json.loads(hooks)

        with st.expander(f"**{bucket['name']}**"):
            col1, col2 = st.columns([3, 1])
            with col1:
                if bucket.get("best_for"):
                    st.markdown(f"**Best For:** {bucket['best_for']}")
                if bucket.get("angle"):
                    st.markdown(f"**Angle:** {bucket['angle']}")
                if bucket.get("avatar"):
                    st.markdown(f"**Avatar:** {bucket['avatar']}")

                if pain_pts:
                    st.markdown("**Pain Points:**")
                    st.markdown(format_list_for_display(pain_pts))
                if sol_mech:
                    st.markdown("**Solution Mechanism:**")
                    st.markdown(format_list_for_display(sol_mech))
                if hooks:
                    st.markdown("**Key Copy Hooks:**")
                    st.markdown(format_list_for_display(hooks))

            with col2:
                if st.button("Delete", key=f"del_{bucket['id']}", type="secondary"):
                    service.delete_bucket(bucket["id"])
                    st.success(f"Deleted: {bucket['name']}")
                    st.rerun()


# ============================================
# TAB 2: CATEGORIZE VIDEOS
# ============================================

def render_categorize_videos(product_id: str, org_id: str):
    """Render video upload and categorization interface."""
    service = get_service()
    buckets = service.get_buckets(product_id, org_id)

    if not buckets:
        st.warning("You need to create at least one content bucket before categorizing videos. Go to the **Manage Buckets** tab first.")
        return

    def _retry_videos(filenames: list):
        """Retry failed videos: delete old error records, reprocess, merge results."""
        file_map = st.session_state.vb_file_map
        files = [file_map[fn] for fn in filenames if fn in file_map]
        if not files:
            st.error("File data no longer available. Please re-upload the videos.")
            return
        session_id = st.session_state.vb_session_id

        # Delete old error records
        for fn in filenames:
            service.delete_categorization(session_id, fn)

        # Reprocess
        new_results = service.analyze_and_categorize_batch(
            files=files,
            buckets=buckets,
            product_id=product_id,
            org_id=org_id,
            session_id=session_id,
        )

        # Merge: replace old entries with new results
        old = st.session_state.vb_results or []
        retried_names = {r["filename"] for r in new_results}
        merged = [r for r in old if r["filename"] not in retried_names] + new_results
        st.session_state.vb_results = merged
        st.rerun()

    st.subheader("Upload & Categorize Videos")
    st.caption(f"{len(buckets)} buckets available. Videos will be analyzed by Gemini and matched to the best bucket.")

    uploaded_files = st.file_uploader(
        "Upload videos",
        accept_multiple_files=True,
        type=["mp4", "mov", "avi", "webm"],
        help="Upload 1-20 videos at a time. Each will be analyzed individually.",
    )

    if uploaded_files and len(uploaded_files) <= 20:
        # Estimate time
        est_minutes = (len(uploaded_files) * 12 + 30) // 60  # ~12s per video + buffer
        st.info(f"**{len(uploaded_files)} video(s)** ready. Estimated time: ~{est_minutes} minute(s).")

        if st.button("Analyze & Categorize", type="primary", disabled=st.session_state.vb_processing):
            session_id = str(uuid4())
            st.session_state.vb_session_id = session_id
            st.session_state.vb_processing = True

            progress_bar = st.progress(0)
            status_placeholder = st.empty()

            # Prepare file data and save to session state for retry
            files = []
            file_map = {}
            for f in uploaded_files:
                file_data = {
                    "bytes": f.getvalue(),
                    "name": f.name,
                    "type": f.type or "video/mp4",
                }
                files.append(file_data)
                file_map[f.name] = file_data
            st.session_state.vb_file_map = file_map

            def progress_callback(index, total_count, filename, status_msg):
                pct = (index + 1) / total_count
                progress_bar.progress(pct)
                status_placeholder.markdown(f"**[{index + 1}/{total_count}]** `{filename}` — {status_msg}")

            try:
                results = service.analyze_and_categorize_batch(
                    files=files,
                    buckets=buckets,
                    product_id=product_id,
                    org_id=org_id,
                    session_id=session_id,
                    progress_callback=progress_callback,
                )

                st.session_state.vb_results = results
                st.session_state.vb_processing = False
                progress_bar.progress(1.0)
                status_placeholder.success(f"Done! {len(results)} video(s) processed.")
                st.rerun()

            except Exception as e:
                st.error(f"Batch processing error: {e}")
                st.session_state.vb_processing = False

    elif uploaded_files and len(uploaded_files) > 20:
        st.error("Maximum 20 videos per batch. Please reduce your selection.")
    elif not uploaded_files:
        st.info("Upload videos above to begin categorization.")

    # ── Results display (always visible when results exist) ───────
    results = st.session_state.vb_results
    if not results or not st.session_state.vb_session_id:
        return

    st.divider()

    # Summary metrics
    categorized = sum(1 for r in results if r.get("status") == "categorized")
    error_count = sum(1 for r in results if r.get("status") == "error")

    cols = st.columns(3)
    cols[0].metric("Categorized", categorized)
    cols[1].metric("Errors", error_count)
    cols[2].metric("Session", st.session_state.vb_session_id[:8])

    # Retry All Errors button
    error_filenames = [r["filename"] for r in results if r.get("status") == "error"]
    if error_filenames:
        if st.button(f"Retry All Errors ({len(error_filenames)})", type="primary"):
            with st.spinner(f"Retrying {len(error_filenames)} video(s)..."):
                _retry_videos(error_filenames)

    # Results table with per-row retry buttons
    # Header
    hdr_cols = st.columns([3, 2, 1, 1, 1])
    hdr_cols[0].markdown("**Filename**")
    hdr_cols[1].markdown("**Bucket**")
    hdr_cols[2].markdown("**Confidence**")
    hdr_cols[3].markdown("**Status**")
    hdr_cols[4].markdown("**Action**")

    for i, r in enumerate(results):
        row_cols = st.columns([3, 2, 1, 1, 1])
        row_cols[0].text(r["filename"])
        row_cols[1].text(r.get("bucket_name", "—"))
        conf = r.get("confidence_score")
        row_cols[2].text(f"{conf:.0%}" if conf else "—")
        status = r.get("status", "unknown")
        row_cols[3].text(status)

        if status == "error":
            if row_cols[4].button("Retry", key=f"retry_{i}_{r['filename']}"):
                with st.spinner(f"Retrying {r['filename']}..."):
                    _retry_videos([r["filename"]])


# ============================================
# TAB 3: RESULTS
# ============================================

def render_results(product_id: str, org_id: str):
    """Render past categorization sessions."""
    service = get_service()
    sessions = service.get_recent_sessions(product_id, org_id, limit=10)

    if not sessions:
        st.info("No categorization sessions yet. Go to **Categorize Videos** to get started.")
        return

    st.subheader("Past Sessions")

    # Session selector
    session_options = {
        s["session_id"]: f"{s['created_at'][:16]} ({s['video_count']} videos)"
        for s in sessions
    }

    selected_session = st.selectbox(
        "Select session",
        options=list(session_options.keys()),
        format_func=lambda x: session_options[x],
    )

    if not selected_session:
        return

    results = service.get_session_results(selected_session)

    if not results:
        st.warning("No results found for this session.")
        return

    # Summary stats
    categorized = sum(1 for r in results if r.get("status") == "categorized")
    analyzed = sum(1 for r in results if r.get("status") == "analyzed")
    errors = sum(1 for r in results if r.get("status") == "error")
    bucket_names = set(r.get("bucket_name") for r in results if r.get("bucket_name") and r.get("bucket_name") != "Uncategorized")

    cols = st.columns(4)
    cols[0].metric("Total Videos", len(results))
    cols[1].metric("Categorized", categorized)
    cols[2].metric("Buckets Used", len(bucket_names))
    cols[3].metric("Errors", errors)

    # Results table
    import pandas as pd
    df = pd.DataFrame([
        {
            "Filename": r["filename"],
            "Bucket": r.get("bucket_name") or "—",
            "Confidence": round(r.get("confidence_score") or 0, 2),
            "Reasoning": r.get("reasoning") or "—",
            "Status": r.get("status", "unknown"),
        }
        for r in results
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # CSV download
    csv = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=f"video_buckets_{selected_session[:8]}.csv",
        mime="text/csv",
    )

    # Per-video details
    st.subheader("Video Details")
    for r in results:
        with st.expander(f"`{r['filename']}` → {r.get('bucket_name', '—')}"):
            if r.get("video_summary"):
                st.markdown(f"**Summary:** {r['video_summary']}")
            if r.get("reasoning"):
                st.markdown(f"**Reasoning:** {r['reasoning']}")
            if r.get("confidence_score") is not None:
                st.markdown(f"**Confidence:** {r['confidence_score']:.0%}")
            if r.get("transcript"):
                st.text_area("Transcript", value=r["transcript"], height=120,
                             disabled=True, key=f"transcript_{r['id']}")
            if r.get("analysis_data"):
                analysis = r["analysis_data"]
                if isinstance(analysis, str):
                    try:
                        analysis = json.loads(analysis)
                    except (json.JSONDecodeError, TypeError):
                        analysis = None
                if analysis and isinstance(analysis, dict):
                    with st.expander("Full Analysis JSON"):
                        st.json(analysis)
            if r.get("error_message"):
                st.error(f"Error: {r['error_message']}")


# ============================================
# MAIN PAGE
# ============================================

st.title("📦 Video Buckets")

# Brand + product selector
from viraltracker.ui.utils import (
    render_brand_selector,
    get_products_for_brand,
    get_current_organization_id,
)

brand_id, product_id = render_brand_selector(
    key="vb_brand_selector",
    include_product=True,
    product_key="vb_product_selector",
    product_label="Select Product",
)

if not brand_id:
    st.stop()

if not product_id:
    products = get_products_for_brand(brand_id)
    if products:
        product_id = st.selectbox(
            "Select Product",
            options=[p["id"] for p in products],
            format_func=lambda x: next((p["name"] for p in products if p["id"] == x), x),
            key="vb_product_fallback",
        )
    if not product_id:
        st.warning("Please select a product to continue.")
        st.stop()

org_id = get_current_organization_id()
if not org_id:
    st.error("Organization not found. Please log in again.")
    st.stop()

# Tabs
tab1, tab2, tab3 = st.tabs(["Manage Buckets", "Categorize Videos", "Results"])

with tab1:
    render_manage_buckets(product_id, org_id)

with tab2:
    render_categorize_videos(product_id, org_id)

with tab3:
    render_results(product_id, org_id)
