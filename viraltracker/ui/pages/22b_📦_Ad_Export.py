"""
Ad Export — bulk download (ZIP) or push to Google Drive.

Users collect ads from Ad History and Ad Creator V2,
then export them here as a ZIP or upload to Drive.
"""

import os
import streamlit as st
import logging

# Page config
st.set_page_config(page_title="Ad Export", page_icon="📦", layout="wide")

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("ad_export", "Ad Export")

logger = logging.getLogger(__name__)

# Initialize export list
if "export_ads" not in st.session_state:
    st.session_state.export_ads = []


# =============================================================================
# OAUTH CALLBACK HANDLING (must be before UI renders)
# =============================================================================

def _get_oauth_redirect_uri() -> str:
    base = os.environ.get("APP_BASE_URL", "http://localhost:8501")
    return f"{base.rstrip('/')}/Ad_Export"


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

        # Save integration
        drive_svc.save_integration(
            brand_id=state_data["brand_id"],
            organization_id=state_data["org_id"],
            tokens=tokens,
        )

        st.session_state["_drive_connected"] = True
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        logger.error(f"Drive OAuth callback failed: {e}")
        st.error(f"Drive OAuth callback failed: {e}")
        st.query_params.clear()


# =============================================================================
# HELPERS
# =============================================================================

def _get_drive_service():
    from viraltracker.services.google_drive_service import GoogleDriveService
    return GoogleDriveService()


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("Ad Export")

from viraltracker.ui.export_utils import get_export_list, get_export_count, create_zip_from_export_list

export_list = get_export_list()
count = len(export_list)

# Header row
hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.markdown(f"**{count} ad{'s' if count != 1 else ''}** in export list")
with hcol2:
    if count > 0:
        if st.button("Clear All", key="export_clear_all", type="secondary"):
            st.session_state.export_ads = []
            st.session_state.export_zip_ready = False
            st.rerun()

if count == 0:
    st.info("No ads in export list. Add ads from Ad History or Ad Creator V2.")
    st.stop()

# =============================================================================
# EXPORT LIST TABLE
# =============================================================================

st.subheader("Export List")

# Table header
tcol1, tcol2, tcol3, tcol4, tcol5 = st.columns([3, 1, 1, 1, 1])
with tcol1:
    st.caption("**Filename**")
with tcol2:
    st.caption("**Format**")
with tcol3:
    st.caption("**Ext**")
with tcol4:
    st.caption("**Brand**")
with tcol5:
    st.caption("**Action**")

# Table rows
from viraltracker.ui.export_utils import generate_structured_filename

items_to_remove = []
for idx, item in enumerate(export_list):
    rcol1, rcol2, rcol3, rcol4, rcol5 = st.columns([3, 1, 1, 1, 1])
    with rcol1:
        filename = generate_structured_filename(
            brand_code=item.get("brand_code", "XX"),
            product_code=item.get("product_code", "XX"),
            run_id=item.get("run_id", "000000"),
            ad_id=item.get("ad_id", "000000"),
            format_code=item.get("format_code", "SQ"),
            ext=item.get("ext", "png"),
        )
        st.text(filename)
    with rcol2:
        st.text(item.get("format_code", "SQ"))
    with rcol3:
        st.text(item.get("ext", "png"))
    with rcol4:
        st.text(item.get("brand_code", "XX"))
    with rcol5:
        if st.button("Remove", key=f"export_remove_{idx}"):
            items_to_remove.append(idx)

# Process removals
if items_to_remove:
    for idx in sorted(items_to_remove, reverse=True):
        st.session_state.export_ads.pop(idx)
    st.session_state.export_zip_ready = False
    st.rerun()


# =============================================================================
# ZIP DOWNLOAD
# =============================================================================

st.divider()
st.subheader("Download as ZIP")

zcol1, zcol2 = st.columns([2, 1])
with zcol1:
    zip_name = st.text_input(
        "ZIP filename",
        value="ad_export",
        key="export_zip_name",
        label_visibility="collapsed",
        placeholder="ZIP filename (without .zip)",
    )

# Use a session state flag to trigger ZIP creation
if "export_zip_ready" not in st.session_state:
    st.session_state.export_zip_ready = False

with zcol2:
    if st.button("Prepare ZIP", key="export_prepare_zip", use_container_width=True):
        st.session_state.export_zip_ready = True
        st.rerun()

if st.session_state.export_zip_ready:
    with st.spinner("Creating ZIP..."):
        zip_bytes = create_zip_from_export_list(export_list, zip_name)

    safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in zip_name)
    st.download_button(
        label="Download ZIP",
        data=zip_bytes,
        file_name=f"{safe_name}.zip",
        mime="application/zip",
        key="export_download_zip",
        use_container_width=True,
    )


# =============================================================================
# GOOGLE DRIVE UPLOAD
# =============================================================================

st.divider()
st.subheader("Upload to Google Drive")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="export_drive_brand_selector")
if not brand_id:
    st.info("Select a brand to connect Google Drive.")
    st.stop()

org_id = get_current_organization_id() or ""

drive_svc = _get_drive_service()
connected = drive_svc.is_connected(brand_id, org_id)

# Connect / Disconnect
if connected:
    st.success("Google Drive connected")
    if st.button("Disconnect Google Drive", key="export_drive_disconnect"):
        drive_svc.disconnect(brand_id, org_id)
        st.rerun()
else:
    st.warning("Google Drive not connected for this brand.")
    if st.button("Connect Google Drive", key="export_drive_connect"):
        import uuid
        from viraltracker.services.google_oauth_utils import encode_oauth_state

        nonce = str(uuid.uuid4())
        state = encode_oauth_state(brand_id, org_id, nonce)
        redirect_uri = _get_oauth_redirect_uri()
        auth_url = drive_svc.get_authorization_url(redirect_uri, state)
        st.markdown(f"[Authorize Google Drive]({auth_url})")
    st.stop()

# Folder browser
try:
    access_token, _ = drive_svc._get_credentials(brand_id, org_id)
except Exception as e:
    st.error(f"Drive credentials error: {e}")
    st.stop()

folders = drive_svc.list_folders(access_token)

fcol1, fcol2 = st.columns([2, 1])
with fcol1:
    folder_options = {f["id"]: f["name"] for f in folders}

    if folder_options:
        selected_folder_id = st.selectbox(
            "Target folder",
            options=list(folder_options.keys()),
            format_func=lambda x: folder_options[x],
            key="export_drive_folder",
        )
    else:
        st.info("No folders found. Create one below.")
        selected_folder_id = None

with fcol2:
    new_folder_name = st.text_input(
        "Create subfolder",
        key="export_drive_new_folder",
        placeholder="New folder name...",
        label_visibility="collapsed",
    )
    if new_folder_name and st.button("Create Folder", key="export_drive_create_folder"):
        try:
            parent = selected_folder_id if selected_folder_id else None
            new_folder = drive_svc.create_folder(access_token, new_folder_name, parent)
            st.success(f"Created folder: {new_folder_name}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to create folder: {e}")

# Upload button
if selected_folder_id:
    if st.button(
        f"Upload {count} ad{'s' if count != 1 else ''} to Google Drive",
        key="export_drive_upload",
        type="primary",
        use_container_width=True,
    ):
        progress_bar = st.progress(0, text="Uploading...")

        def update_progress(current, total):
            progress_bar.progress(current / total, text=f"Uploading {current}/{total}...")

        try:
            result = drive_svc.upload_export_list(
                brand_id=brand_id,
                organization_id=org_id,
                items=export_list,
                folder_id=selected_folder_id,
                progress_callback=update_progress,
            )
            progress_bar.empty()
            st.success(
                f"Uploaded {result['uploaded']}/{result['total']} files"
                + (f" ({result['failed']} failed)" if result['failed'] else "")
            )

            if result.get("links"):
                with st.expander("Uploaded files"):
                    for link in result["links"]:
                        if link.get("link"):
                            st.markdown(f"- [{link['filename']}]({link['link']})")
                        else:
                            st.text(f"- {link['filename']}")
        except Exception as e:
            progress_bar.empty()
            st.error(f"Upload failed: {e}")
