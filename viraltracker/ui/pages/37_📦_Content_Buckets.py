"""
Content Buckets — Organize bulk uploads (images + videos) into content buckets.

Upload images and videos, Gemini analyzes each one (transcript, text overlays,
visual elements), and outputs a filename → bucket mapping for efficient
organization with the right ad copy.

Five tabs:
1. Manage Buckets — CRUD for content bucket definitions
2. Categorize Content — Upload or import from Drive, auto-categorize
3. Results — View past categorization sessions
4. Uploaded — Reference of all files marked as uploaded
"""

import io
import logging
import mimetypes
import os
import streamlit as st
import json
import zipfile
from uuid import uuid4

# Page config (must be first Streamlit call)
st.set_page_config(page_title="Content Buckets", page_icon="📦", layout="wide")

# Auth
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("video_buckets", "Content Buckets")

logger = logging.getLogger(__name__)

# Accepted file types (GIF excluded — Gemini 2.0+ doesn't support it)
IMAGE_TYPES = ["jpg", "jpeg", "png", "webp", "heic", "heif"]
VIDEO_TYPES = ["mp4", "mov", "avi", "webm", "mpeg"]
ALL_FILE_TYPES = IMAGE_TYPES + VIDEO_TYPES

# MIME types for Drive file listing
DRIVE_MIME_TYPES = [
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/webm", "video/mpeg",
]


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


def _get_drive_service():
    from viraltracker.services.google_drive_service import GoogleDriveService
    return GoogleDriveService()


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


def _infer_mime_type(filename: str) -> str:
    """Infer MIME type from filename extension."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    # Fallback for common extensions not in mimetypes DB
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    fallbacks = {
        "mp4": "video/mp4", "mov": "video/quicktime",
        "avi": "video/x-msvideo", "webm": "video/webm",
        "mpeg": "video/mpeg", "heic": "image/heic", "heif": "image/heif",
    }
    return fallbacks.get(ext, "application/octet-stream")


def _resolve_org_id_for_brand(brand_id: str, org_id: str) -> str:
    """Resolve actual UUID org_id from brand when superuser has org_id='all'."""
    if org_id != "all":
        return org_id
    from viraltracker.core.database import get_supabase_client
    row = get_supabase_client().table("brands").select("organization_id").eq("id", brand_id).execute()
    if row.data:
        return row.data[0]["organization_id"]
    return org_id


def _format_file_size(size_bytes) -> str:
    """Format bytes as human-readable size."""
    if not size_bytes:
        return "—"
    size = int(size_bytes)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# ============================================
# OAUTH CALLBACK HANDLING
# ============================================

def _get_oauth_redirect_uri() -> str:
    base = os.environ.get("APP_BASE_URL", "http://localhost:8501")
    return f"{base.rstrip('/')}/Content_Buckets"


if "code" in st.query_params and "state" in st.query_params:
    try:
        from viraltracker.services.google_drive_service import GoogleDriveService
        from viraltracker.services.google_oauth_utils import decode_oauth_state

        state_data = decode_oauth_state(st.query_params["state"])
        redirect_uri = _get_oauth_redirect_uri()

        drive_svc = GoogleDriveService()
        tokens = drive_svc.exchange_code_for_tokens(
            st.query_params["code"], redirect_uri
        )

        cb_org_id = state_data["org_id"]
        if cb_org_id == "all":
            cb_org_id = _resolve_org_id_for_brand(state_data["brand_id"], cb_org_id)

        drive_svc.save_integration(
            brand_id=state_data["brand_id"],
            organization_id=cb_org_id,
            tokens=tokens,
        )

        st.query_params.clear()
        st.rerun()
    except Exception as e:
        logger.error(f"Drive OAuth callback failed: {e}")
        st.error(f"Drive OAuth callback failed: {e}")
        st.query_params.clear()


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
            best_for = st.text_area("Best For", placeholder="What types of content belong here?", height=68)
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
# TAB 2: CATEGORIZE CONTENT
# ============================================

def render_categorize_content(product_id: str, org_id: str, brand_id: str):
    """Render content upload, Drive import, and categorization interface."""
    service = get_service()
    buckets = service.get_buckets(product_id, org_id)

    if not buckets:
        st.warning("You need to create at least one content bucket before categorizing. Go to the **Manage Buckets** tab first.")
        return

    def _retry_files(filenames: list):
        """Retry failed files: delete old error records, reprocess, merge results."""
        file_map = st.session_state.vb_file_map
        files = [file_map[fn] for fn in filenames if fn in file_map]
        if not files:
            st.error("File data no longer available. Please re-upload the files.")
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
            brand_id=brand_id,
        )

        # Merge: replace old entries with new results
        old = st.session_state.vb_results or []
        retried_names = {r["filename"] for r in new_results}
        merged = [r for r in old if r["filename"] not in retried_names] + new_results
        st.session_state.vb_results = merged
        st.rerun()

    # ── Local Upload Section ────────────────────────────────────────
    st.subheader("Upload & Categorize")
    st.caption(f"{len(buckets)} buckets available. Files will be analyzed by Gemini and matched to the best bucket.")

    uploaded_files = st.file_uploader(
        "Upload files",
        accept_multiple_files=True,
        type=ALL_FILE_TYPES,
        help="Upload 1-30 files (images + videos). Images: ~3s each, Videos: ~12s each.",
    )

    if uploaded_files and len(uploaded_files) <= 30:
        # Count images vs videos for time estimate
        image_count = sum(1 for f in uploaded_files if f.name.rsplit(".", 1)[-1].lower() in set(IMAGE_TYPES))
        video_count = len(uploaded_files) - image_count
        est_seconds = image_count * 4 + video_count * 14
        est_str = f"~{est_seconds // 60} min {est_seconds % 60}s" if est_seconds >= 60 else f"~{est_seconds}s"
        parts = []
        if image_count:
            parts.append(f"{image_count} image{'s' if image_count != 1 else ''}")
        if video_count:
            parts.append(f"{video_count} video{'s' if video_count != 1 else ''}")
        st.info(f"**{' + '.join(parts)}** ready. Estimated time: {est_str}.")

        if st.button("Analyze & Categorize", type="primary", disabled=st.session_state.vb_processing):
            _run_batch(uploaded_files, buckets, product_id, org_id, service, source="upload", brand_id=brand_id)

    elif uploaded_files and len(uploaded_files) > 30:
        st.error(f"Maximum 30 files per batch ({len(uploaded_files)} selected). Please reduce your selection.")
    elif not uploaded_files:
        st.info("Upload files above to begin categorization.")

    # ── Drive Import Section ────────────────────────────────────────
    st.divider()
    st.subheader("Or Import from Google Drive")

    drive_svc = _get_drive_service()
    resolved_org = _resolve_org_id_for_brand(brand_id, org_id)

    if not drive_svc.is_connected(brand_id, resolved_org):
        _render_drive_connect_button(brand_id, org_id)
    else:
        _render_drive_import(brand_id, resolved_org, product_id, org_id, buckets, service)

    # ── Results display (always visible when results exist) ─────────
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
            with st.spinner(f"Retrying {len(error_filenames)} file(s)..."):
                _retry_files(error_filenames)

    # Results table with per-row retry buttons
    hdr_cols = st.columns([3, 2, 1.5, 0.5, 1, 1, 1])
    hdr_cols[0].markdown("**Filename**")
    hdr_cols[1].markdown("**Bucket**")
    hdr_cols[2].markdown("**Product**")
    hdr_cols[3].markdown("**Lang**")
    hdr_cols[4].markdown("**Confidence**")
    hdr_cols[5].markdown("**Status**")
    hdr_cols[6].markdown("**Action**")

    for i, r in enumerate(results):
        row_cols = st.columns([3, 2, 1.5, 0.5, 1, 1, 1])
        row_cols[0].text(r["filename"])
        row_cols[1].text(r.get("bucket_name", "—"))
        row_cols[2].text(r.get("detected_product_name") or "—")
        lang = r.get("detected_language", "en")
        row_cols[3].text({"en": "EN", "es": "ES"}.get(lang, lang.upper() if lang else "—"))
        conf = r.get("confidence_score")
        row_cols[4].text(f"{conf:.0%}" if conf else "—")
        status = r.get("status", "unknown")
        row_cols[5].text(status)

        if status == "error":
            if row_cols[6].button("Retry", key=f"retry_{i}_{r['filename']}"):
                with st.spinner(f"Retrying {r['filename']}..."):
                    _retry_files([r["filename"]])

    # ── Download per Product x Language x Bucket (ZIP) ───────────
    file_map = st.session_state.vb_file_map
    categorized_results = [r for r in results if r.get("status") == "categorized" and r.get("bucket_name")]
    if categorized_results and file_map:
        st.divider()
        st.subheader("Download by Bucket")

        # Group by Product x Language x Bucket
        groups: dict[str, list] = {}
        for r in categorized_results:
            product_name = r.get("detected_product_name") or "Unknown"
            lang = r.get("detected_language", "en")
            lang_label = {"en": "English", "es": "Spanish"}.get(lang, lang.upper() if lang else "Unknown")
            bname = r["bucket_name"]
            group_key = f"{product_name} / {lang_label} / {bname}"
            groups.setdefault(group_key, []).append(r["filename"])

        dl_cols = st.columns(min(len(groups), 3))
        for idx, (group_key, filenames) in enumerate(sorted(groups.items())):
            available = [fn for fn in filenames if fn in file_map]
            if not available:
                continue
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn in available:
                    zf.writestr(fn, file_map[fn]["bytes"])
            zip_buffer.seek(0)

            # Build a safe filename from the group key
            safe_name = group_key.replace(" / ", "_").replace(" ", "_").replace(",", "")
            col = dl_cols[idx % len(dl_cols)]
            col.download_button(
                f"{group_key} ({len(available)})",
                data=zip_buffer.getvalue(),
                file_name=f"{safe_name}.zip",
                mime="application/zip",
                key=f"dl_bucket_{idx}",
            )


def _run_batch(uploaded_files, buckets, product_id, org_id, service, source="upload", brand_id=None):
    """Run the analyze + categorize batch for uploaded files."""
    session_id = str(uuid4())
    st.session_state.vb_session_id = session_id
    st.session_state.vb_processing = True

    progress_bar = st.progress(0)
    status_placeholder = st.empty()

    # Prepare file data and save to session state for retry
    files = []
    file_map = {}
    for f in uploaded_files:
        file_bytes = f.getvalue() if hasattr(f, "getvalue") else f["bytes"]
        file_name = f.name if hasattr(f, "name") else f["name"]
        file_type = (f.type if hasattr(f, "type") and f.type else None) or _infer_mime_type(file_name)
        file_data = {
            "bytes": file_bytes,
            "name": file_name,
            "type": file_type,
        }
        files.append(file_data)
        file_map[file_name] = file_data
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
            source=source,
            brand_id=brand_id,
        )

        st.session_state.vb_results = results
        st.session_state.vb_processing = False
        progress_bar.progress(1.0)
        status_placeholder.success(f"Done! {len(results)} file(s) processed.")
        st.rerun()

    except Exception as e:
        st.error(f"Batch processing error: {e}")
        st.session_state.vb_processing = False


# ============================================
# DRIVE IMPORT HELPERS
# ============================================

def _render_drive_connect_button(brand_id: str, org_id: str, key_suffix: str = "import"):
    """Show the Connect Google Drive button with OAuth flow."""
    from viraltracker.services.google_drive_service import GoogleDriveService
    from viraltracker.services.google_oauth_utils import encode_oauth_state

    if st.button("Connect Google Drive", key=f"cb_drive_connect_{key_suffix}"):
        nonce = str(uuid4())[:8]
        state = encode_oauth_state(brand_id, org_id, nonce)
        redirect_uri = _get_oauth_redirect_uri()
        auth_url = GoogleDriveService.get_authorization_url(redirect_uri, state)
        st.markdown(f"[Authorize Google Drive]({auth_url})")


def _render_drive_import(brand_id, resolved_org, product_id, org_id, buckets, service):
    """Render the Drive folder picker and file list for import."""
    from viraltracker.ui.drive_picker import render_drive_folder_picker
    from viraltracker.services.google_drive_service import GoogleDriveService

    # Disconnect button
    if st.button("Disconnect Drive", key="cb_drive_disconnect", type="secondary"):
        drive_svc = _get_drive_service()
        drive_svc.disconnect(brand_id, resolved_org)
        st.rerun()

    # Folder picker
    selected = render_drive_folder_picker(
        brand_id, resolved_org,
        prefix="cb_import",
        allow_create=False,
        label="Select folder to import from",
    )

    if not selected:
        return

    folder_id = selected["id"]

    # Get token and list files
    try:
        drive_svc = _get_drive_service()
        token, _ = drive_svc._get_credentials(brand_id, resolved_org)
        drive_files = GoogleDriveService.list_files(
            token, folder_id, mime_types=DRIVE_MIME_TYPES
        )
    except Exception as e:
        st.error(f"Failed to list Drive files: {e}")
        return

    if not drive_files:
        st.info("No image or video files found in this folder.")
        return

    st.markdown(f"**{len(drive_files)} files** in `{selected['name']}`")

    # File list with checkboxes
    select_col1, select_col2 = st.columns(2)
    select_all = select_col1.button("Select All", key="cb_import_select_all")
    select_none = select_col2.button("Select None", key="cb_import_select_none")

    selected_file_ids = []
    for idx, df in enumerate(drive_files):
        is_image = df.get("mimeType", "").startswith("image/")
        type_badge = "IMG" if is_image else "VID"
        size_str = _format_file_size(df.get("size"))

        # Default to selected if Select All was clicked
        default = True if select_all else (False if select_none else True)
        checked = st.checkbox(
            f"`{type_badge}` {df['name']} ({size_str})",
            value=default,
            key=f"cb_import_file_{idx}",
        )
        if checked:
            selected_file_ids.append(df["id"])

    if not selected_file_ids:
        return

    st.info(f"**{len(selected_file_ids)} file(s)** selected for import.")

    if st.button("Import & Categorize", type="primary", key="cb_import_go",
                  disabled=st.session_state.vb_processing):
        st.session_state.vb_processing = True
        session_id = str(uuid4())
        st.session_state.vb_session_id = session_id

        progress_bar = st.progress(0)
        status = st.empty()

        # Download files from Drive
        downloaded_files = []
        file_map = {}
        download_total = len(selected_file_ids)

        for dl_idx, file_id in enumerate(selected_file_ids):
            # Find file metadata from our list
            file_meta = next((f for f in drive_files if f["id"] == file_id), None)
            file_name = file_meta["name"] if file_meta else file_id

            status.markdown(f"**[{dl_idx + 1}/{download_total}]** Downloading `{file_name}`...")
            progress_bar.progress((dl_idx + 0.5) / download_total)

            try:
                file_bytes, metadata = GoogleDriveService.download_file(token, file_id)
                mime_type = metadata.get("mimeType", _infer_mime_type(file_name))
                file_data = {
                    "bytes": file_bytes,
                    "name": metadata.get("name", file_name),
                    "type": mime_type,
                }
                downloaded_files.append(file_data)
                file_map[file_data["name"]] = file_data
            except Exception as e:
                logger.warning(f"Drive download failed for {file_name}: {e}")
                st.warning(f"Failed to download `{file_name}`: {e}")

        if not downloaded_files:
            st.error("No files were successfully downloaded.")
            st.session_state.vb_processing = False
            return

        st.session_state.vb_file_map = file_map

        # Run analysis batch
        def progress_callback(index, total_count, filename, status_msg):
            pct = (index + 1) / total_count
            progress_bar.progress(pct)
            status.markdown(f"**[{index + 1}/{total_count}]** `{filename}` — {status_msg}")

        try:
            results = service.analyze_and_categorize_batch(
                files=downloaded_files,
                buckets=buckets,
                product_id=product_id,
                org_id=org_id,
                session_id=session_id,
                progress_callback=progress_callback,
                source="google_drive",
                brand_id=brand_id,
            )

            st.session_state.vb_results = results
            st.session_state.vb_processing = False
            progress_bar.progress(1.0)
            status.success(f"Done! {len(results)} file(s) imported and processed.")
            st.rerun()

        except Exception as e:
            st.error(f"Batch processing error: {e}")
            st.session_state.vb_processing = False


# ============================================
# TAB 3: RESULTS
# ============================================

def render_results(product_id: str, org_id: str, brand_id: str):
    """Render past categorization sessions."""
    service = get_service()
    sessions = service.get_recent_sessions(product_id, org_id, limit=10)

    if not sessions:
        st.info("No categorization sessions yet. Go to **Categorize Content** to get started.")
        return

    st.subheader("Past Sessions")

    # Session selector
    session_options = {
        s["session_id"]: f"{s['created_at'][:16]} ({s['file_count']} files)"
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

    # Filters
    filter_cols = st.columns(3)

    # Media type filter
    media_types_in_session = set(r.get("media_type", "video") for r in results)
    if len(media_types_in_session) > 1:
        with filter_cols[0]:
            filter_choice = st.radio(
                "Filter by type",
                ["All", "Images", "Videos"],
                horizontal=True,
                key=f"media_filter_{selected_session[:8]}",
            )
            if filter_choice == "Images":
                results = [r for r in results if r.get("media_type") == "image"]
            elif filter_choice == "Videos":
                results = [r for r in results if r.get("media_type") == "video"]

    # Language filter
    languages_in_session = set(r.get("detected_language", "en") for r in results)
    if len(languages_in_session) > 1:
        with filter_cols[1]:
            lang_filter = st.radio(
                "Filter by language",
                ["All", "English", "Spanish"],
                horizontal=True,
                key=f"lang_filter_{selected_session[:8]}",
            )
            if lang_filter == "English":
                results = [r for r in results if r.get("detected_language", "en") == "en"]
            elif lang_filter == "Spanish":
                results = [r for r in results if r.get("detected_language") == "es"]

    # Product filter
    products_in_session = sorted(set(
        r.get("detected_product_name") or "Unknown"
        for r in results if r.get("status") == "categorized"
    ))
    if len(products_in_session) > 1:
        with filter_cols[2]:
            product_filter = st.selectbox(
                "Filter by product",
                ["All"] + products_in_session,
                key=f"product_filter_{selected_session[:8]}",
            )
            if product_filter != "All":
                results = [r for r in results if (r.get("detected_product_name") or "Unknown") == product_filter]

    # Summary stats
    categorized = sum(1 for r in results if r.get("status") == "categorized")
    errors = sum(1 for r in results if r.get("status") == "error")
    bucket_names = set(r.get("bucket_name") for r in results if r.get("bucket_name") and r.get("bucket_name") != "Uncategorized")

    cols = st.columns(4)
    cols[0].metric("Total Files", len(results))
    cols[1].metric("Categorized", categorized)
    cols[2].metric("Buckets Used", len(bucket_names))
    cols[3].metric("Errors", errors)

    # Retry errored files
    error_results = [r for r in results if r.get("status") == "error"]
    if error_results:
        error_names = [r["filename"] for r in error_results]
        st.warning(f"**{len(error_results)} file(s) failed:** {', '.join(error_names)}")
        st.markdown("Re-upload the failed files below to retry.")

        retry_files = st.file_uploader(
            "Upload failed files to retry",
            accept_multiple_files=True,
            type=ALL_FILE_TYPES,
            key=f"retry_upload_{selected_session[:8]}",
        )

        if retry_files:
            matched = [f for f in retry_files if f.name in error_names]
            unmatched = [f.name for f in retry_files if f.name not in error_names]

            if unmatched:
                st.info(f"Skipping files that didn't error: {', '.join(unmatched)}")

            if matched and st.button(f"Retry {len(matched)} File(s)", type="primary"):
                buckets = service.get_buckets(product_id, org_id)
                files = [{"bytes": f.getvalue(), "name": f.name, "type": f.type or _infer_mime_type(f.name)} for f in matched]

                for f in matched:
                    service.delete_categorization(selected_session, f.name)

                with st.spinner(f"Retrying {len(matched)} file(s)..."):
                    service.analyze_and_categorize_batch(
                        files=files,
                        buckets=buckets,
                        product_id=product_id,
                        org_id=org_id,
                        session_id=selected_session,
                        brand_id=brand_id,
                    )
                st.rerun()

    # Results table
    import pandas as pd
    df = pd.DataFrame([
        {
            "Filename": r["filename"],
            "Type": r.get("media_type", "video").capitalize(),
            "Bucket": r.get("bucket_name") or "—",
            "Product": r.get("detected_product_name") or "—",
            "Language": {"en": "EN", "es": "ES"}.get(r.get("detected_language", "en"), r.get("detected_language", "—").upper() if r.get("detected_language") else "—"),
            "Confidence": round(r.get("confidence_score") or 0, 2),
            "Reasoning": r.get("reasoning") or "—",
            "Status": r.get("status", "unknown"),
            "Uploaded": "Yes" if r.get("is_uploaded") else "No",
        }
        for r in results
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # CSV download
    csv = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=f"content_buckets_{selected_session[:8]}.csv",
        mime="text/csv",
    )

    # ── Drive Export ───────────────────────────────────────────────
    _render_drive_export(brand_id, org_id, selected_session, results)

    # ── Mark as Uploaded controls ──────────────────────────────────
    categorized_results = [r for r in results if r.get("status") == "categorized"]
    if categorized_results:
        st.divider()
        st.subheader("Mark as Uploaded")

        not_uploaded = [r for r in categorized_results if not r.get("is_uploaded")]
        if not_uploaded:
            if st.button(
                f"Mark All as Uploaded ({len(not_uploaded)} files)",
                type="primary",
                key=f"mark_all_{selected_session[:8]}",
            ):
                ids = [r["id"] for r in not_uploaded]
                service.mark_as_uploaded(ids)
                st.success(f"Marked {len(ids)} file(s) as uploaded.")
                st.rerun()

        for i, r in enumerate(categorized_results):
            row_cols = st.columns([4, 2, 1])
            is_up = r.get("is_uploaded", False)
            row_cols[0].text(r["filename"])
            row_cols[1].text(r.get("bucket_name", "—"))
            if is_up:
                if row_cols[2].button("Unmark", key=f"unmark_{selected_session[:8]}_{i}"):
                    service.mark_as_uploaded([r["id"]], uploaded=False)
                    st.rerun()
            else:
                if row_cols[2].button("Mark Uploaded", key=f"mark_{selected_session[:8]}_{i}"):
                    service.mark_as_uploaded([r["id"]])
                    st.rerun()

    # Per-file details
    st.subheader("File Details")
    for r in results:
        media_type = r.get("media_type", "video")
        with st.expander(f"`{r['filename']}` → {r.get('bucket_name', '—')}"):
            # Product and language
            det_product = r.get("detected_product_name")
            det_lang = r.get("detected_language", "en")
            lang_display = {"en": "English", "es": "Spanish"}.get(det_lang, det_lang.upper() if det_lang else "Unknown")
            if det_product:
                st.markdown(f"**Product:** {det_product}")
            st.markdown(f"**Language:** {lang_display}")
            if r.get("summary"):
                st.markdown(f"**Summary:** {r['summary']}")
            if r.get("reasoning"):
                st.markdown(f"**Reasoning:** {r['reasoning']}")
            if r.get("confidence_score") is not None:
                st.markdown(f"**Confidence:** {r['confidence_score']:.0%}")
            # Show transcript only for videos
            if media_type == "video" and r.get("transcript"):
                st.text_area("Transcript", value=r["transcript"], height=120,
                             disabled=True, key=f"transcript_{r['id']}")
            # Show image-specific fields
            if media_type == "image":
                analysis = r.get("analysis_data")
                if isinstance(analysis, str):
                    try:
                        analysis = json.loads(analysis)
                    except (json.JSONDecodeError, TypeError):
                        analysis = None
                if analysis and isinstance(analysis, dict):
                    if analysis.get("visual_elements"):
                        st.markdown(f"**Visual Elements:** {', '.join(analysis['visual_elements'])}")
                    if analysis.get("dominant_colors"):
                        st.markdown(f"**Dominant Colors:** {', '.join(analysis['dominant_colors'])}")
                # Show thumbnail if file bytes available in session
                file_map = st.session_state.vb_file_map
                if r["filename"] in file_map:
                    st.image(file_map[r["filename"]]["bytes"], width=300)
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


def _render_drive_export(brand_id: str, org_id: str, session_id: str, results):
    """Render Drive export controls for a session's results."""
    from viraltracker.services.google_drive_service import GoogleDriveService

    file_map = st.session_state.vb_file_map
    categorized_with_bytes = [
        r for r in results
        if r.get("status") == "categorized" and r["filename"] in file_map
    ]

    if not categorized_with_bytes:
        return

    st.divider()
    st.subheader("Export to Google Drive")

    drive_svc = _get_drive_service()
    resolved_org = _resolve_org_id_for_brand(brand_id, org_id)

    if not drive_svc.is_connected(brand_id, resolved_org):
        _render_drive_connect_button(brand_id, org_id, key_suffix="export")
        return

    from viraltracker.ui.drive_picker import render_drive_folder_picker

    selected = render_drive_folder_picker(
        brand_id, resolved_org,
        prefix="cb_export",
        allow_create=True,
        label="Target folder",
    )

    if not selected:
        return

    if st.button(
        f"Upload {len(categorized_with_bytes)} files to Drive",
        type="primary",
        key="cb_export_go",
    ):
        try:
            token, _ = drive_svc._get_credentials(brand_id, resolved_org)
        except Exception as e:
            st.error(f"Drive auth error: {e}")
            return

        progress_bar = st.progress(0)
        status = st.empty()
        total = len(categorized_with_bytes)
        uploaded_count = 0
        failed_count = 0

        # Group by Product > Language > Bucket for nested subfolder creation
        by_product_lang_bucket: dict[tuple, list] = {}
        for r in categorized_with_bytes:
            product_name = r.get("detected_product_name") or "Unknown Product"
            lang = r.get("detected_language", "en")
            lang_label = {"en": "English", "es": "Spanish"}.get(lang, lang.upper() if lang else "Unknown")
            bname = r.get("bucket_name", "Uncategorized")
            key = (product_name, lang_label, bname)
            by_product_lang_bucket.setdefault(key, []).append(r)

        skipped_count = 0
        # Cache created folder IDs to avoid redundant API calls
        folder_cache: dict[str, str] = {}

        for (product_name, lang_label, bucket_name), group_results in by_product_lang_bucket.items():
            try:
                # Product folder
                product_cache_key = product_name
                if product_cache_key not in folder_cache:
                    folder_cache[product_cache_key] = GoogleDriveService.get_or_create_folder(
                        token, product_name, selected["id"]
                    )
                product_folder_id = folder_cache[product_cache_key]

                # Language folder
                lang_cache_key = f"{product_name}/{lang_label}"
                if lang_cache_key not in folder_cache:
                    folder_cache[lang_cache_key] = GoogleDriveService.get_or_create_folder(
                        token, lang_label, product_folder_id
                    )
                lang_folder_id = folder_cache[lang_cache_key]

                # Bucket folder
                bucket_cache_key = f"{product_name}/{lang_label}/{bucket_name}"
                if bucket_cache_key not in folder_cache:
                    folder_cache[bucket_cache_key] = GoogleDriveService.get_or_create_folder(
                        token, bucket_name, lang_folder_id
                    )
                subfolder_id = folder_cache[bucket_cache_key]
            except Exception as e:
                st.warning(f"Failed to create folder '{product_name}/{lang_label}/{bucket_name}': {e}")
                failed_count += len(group_results)
                continue

            # List existing files in subfolder to avoid duplicates
            try:
                existing = GoogleDriveService.list_files(token, subfolder_id)
                existing_names = {f["name"] for f in existing}
            except Exception:
                existing_names = set()

            for r in group_results:
                filename = r["filename"]

                if filename in existing_names:
                    skipped_count += 1
                    progress_bar.progress((uploaded_count + failed_count + skipped_count) / total)
                    continue

                status.markdown(f"Uploading `{filename}` to `{product_name}/{lang_label}/{bucket_name}/`...")

                try:
                    fb = file_map[filename]["bytes"]
                    mime = file_map[filename].get("type", _infer_mime_type(filename))
                    GoogleDriveService.upload_file_bytes(
                        token, fb, filename, mime, subfolder_id
                    )
                    uploaded_count += 1
                except Exception as e:
                    logger.warning(f"Drive upload failed for {filename}: {e}")
                    failed_count += 1

                progress_bar.progress((uploaded_count + failed_count + skipped_count) / total)

        progress_bar.progress(1.0)
        folder_link = f"https://drive.google.com/drive/folders/{selected['id']}"
        skip_msg = f" ({skipped_count} already in folder, skipped)" if skipped_count else ""
        if failed_count:
            status.warning(f"Uploaded {uploaded_count} files, {failed_count} failed.{skip_msg}")
        else:
            status.success(
                f"Uploaded {uploaded_count} files!{skip_msg} "
                f"[Open folder in Google Drive]({folder_link})"
            )


# ============================================
# TAB 4: UPLOADED
# ============================================

def render_uploaded(product_id: str, org_id: str):
    """Render a reference list of all files marked as uploaded, grouped by Product x Language x Bucket."""
    service = get_service()
    uploaded = service.get_uploaded_files(product_id, org_id)

    if not uploaded:
        st.info("No files have been marked as uploaded yet. Use the **Results** tab to mark files after uploading them to your ad platform.")
        return

    # Group by Product x Language x Bucket
    groups: dict[str, list] = {}
    for r in uploaded:
        product_name = r.get("detected_product_name") or "Unknown"
        lang = r.get("detected_language", "en")
        lang_label = {"en": "English", "es": "Spanish"}.get(lang, lang.upper() if lang else "Unknown")
        bname = r.get("bucket_name") or "Uncategorized"
        group_key = f"{product_name} / {lang_label} / {bname}"
        groups.setdefault(group_key, []).append(r)

    st.subheader(f"Uploaded Files ({len(uploaded)} total)")

    for group_key in sorted(groups.keys()):
        files = groups[group_key]
        with st.expander(f"**{group_key}** ({len(files)} files)", expanded=True):
            for i, r in enumerate(files):
                row_cols = st.columns([4, 2, 1])
                row_cols[0].text(r["filename"])
                conf = r.get("confidence_score")
                row_cols[1].text(f"{conf:.0%}" if conf else "—")
                if row_cols[2].button("Unmark", key=f"uploaded_unmark_{r['id']}_{i}"):
                    service.mark_as_uploaded([r["id"]], uploaded=False)
                    st.rerun()


# ============================================
# MAIN PAGE
# ============================================

st.title("📦 Content Buckets")

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
tab1, tab2, tab3, tab4 = st.tabs(["Manage Buckets", "Categorize Content", "Results", "Uploaded"])

with tab1:
    render_manage_buckets(product_id, org_id)

with tab2:
    render_categorize_content(product_id, org_id, brand_id)

with tab3:
    render_results(product_id, org_id, brand_id)

with tab4:
    render_uploaded(product_id, org_id)
