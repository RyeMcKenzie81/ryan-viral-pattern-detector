"""
Reusable Google Drive folder picker for Streamlit.

Provides browse (My Drive / Shared with Me), search, and paste-URL
modes for selecting a Drive folder. Handles credential refresh
internally so tokens don't expire during long browse sessions.
"""

import time
import logging
from typing import Optional

import streamlit as st

logger = logging.getLogger(__name__)

# Display pagination — folders shown per page
_FOLDERS_PER_PAGE = 20
# Cache TTL in seconds
_CACHE_TTL = 300


def _ss(prefix: str, key: str):
    """Session state key helper."""
    return f"{prefix}_{key}"


def _init_state(prefix: str):
    """Initialize all session state keys for this picker instance."""
    defaults = {
        "selected_folder": None,       # {"id": ..., "name": ..., "can_write": bool}
        "mode": "browse",              # "browse" | "search" | "paste"
        "browse_source": "my_drive",   # "my_drive" | "shared_with_me"
        "current_folder_id": None,     # None = root
        "breadcrumbs": [],             # [(id, name), ...]
        "breadcrumbs_shared": [],      # separate for Shared with Me tab
        "folder_cache": {},            # {folder_id: {"children": [...], "fetched_at": float}}
        "recents": [],                 # last 5 selected folders
        "display_page": 0,            # pagination offset
        "picker_open": True,           # whether picker is expanded
        "search_query": "",            # last search query
        "search_results": None,        # cached search results
        "creating_folder": False,      # toggle for new folder input
    }
    for k, v in defaults.items():
        sk = _ss(prefix, k)
        if sk not in st.session_state:
            st.session_state[sk] = v


def _get_token(brand_id: str, organization_id: str) -> Optional[str]:
    """Refresh and return a valid access token."""
    try:
        from viraltracker.services.google_drive_service import GoogleDriveService
        svc = GoogleDriveService()
        token, _ = svc._get_credentials(brand_id, organization_id)
        return token
    except Exception as e:
        logger.error(f"Drive credential refresh failed: {e}")
        return None


def _get_cached_folders(prefix: str, cache_key: str, fetch_fn):
    """Return cached folder list or fetch and cache."""
    cache = st.session_state[_ss(prefix, "folder_cache")]
    entry = cache.get(cache_key)
    if entry and (time.time() - entry["fetched_at"]) < _CACHE_TTL:
        return entry["children"]

    children = fetch_fn()
    cache[cache_key] = {"children": children, "fetched_at": time.time()}
    return children


def _invalidate_cache(prefix: str, cache_key: str):
    """Remove a specific cache entry (e.g., after creating a folder)."""
    cache = st.session_state[_ss(prefix, "folder_cache")]
    cache.pop(cache_key, None)


def _select_folder(prefix: str, folder_id: str, folder_name: str, can_write: bool = True):
    """Set the selected folder and update recents."""
    selection = {"id": folder_id, "name": folder_name, "can_write": can_write}
    st.session_state[_ss(prefix, "selected_folder")] = selection
    st.session_state[_ss(prefix, "picker_open")] = False

    # Update recents (deduplicate, keep last 5)
    recents = st.session_state[_ss(prefix, "recents")]
    recents = [r for r in recents if r["id"] != folder_id]
    recents.insert(0, selection)
    st.session_state[_ss(prefix, "recents")] = recents[:5]


def _get_breadcrumbs(prefix: str) -> list:
    """Get breadcrumbs for the current browse source."""
    source = st.session_state[_ss(prefix, "browse_source")]
    if source == "shared_with_me":
        return st.session_state[_ss(prefix, "breadcrumbs_shared")]
    return st.session_state[_ss(prefix, "breadcrumbs")]


def _set_breadcrumbs(prefix: str, value: list):
    """Set breadcrumbs for the current browse source."""
    source = st.session_state[_ss(prefix, "browse_source")]
    if source == "shared_with_me":
        st.session_state[_ss(prefix, "breadcrumbs_shared")] = value
    else:
        st.session_state[_ss(prefix, "breadcrumbs")] = value


def render_drive_folder_picker(
    brand_id: str,
    organization_id: str,
    prefix: str = "drive",
    allow_create: bool = True,
    show_recents: bool = True,
    label: str = "Target folder",
) -> Optional[dict]:
    """
    Reusable Google Drive folder picker.

    Args:
        brand_id: Brand ID for credential lookup
        organization_id: Organization ID (multi-tenant)
        prefix: Session state key namespace
        allow_create: Show "New Folder" button
        show_recents: Show recent folders section
        label: Section label

    Returns:
        {"id": ..., "name": ..., "can_write": bool} or None
    """
    from viraltracker.services.google_drive_service import GoogleDriveService

    _init_state(prefix)
    selected = st.session_state[_ss(prefix, "selected_folder")]

    # ----- Selected folder display -----
    if selected:
        sel_col1, sel_col2 = st.columns([4, 1])
        with sel_col1:
            write_icon = "" if selected.get("can_write") else " (read-only)"
            st.success(f"**{label}:** {selected['name']}{write_icon}")
        with sel_col2:
            if st.button("Change", key=f"{prefix}_change_folder"):
                st.session_state[_ss(prefix, "picker_open")] = True
                st.rerun()

        if not st.session_state[_ss(prefix, "picker_open")]:
            return selected

    # ----- Recent folders -----
    recents = st.session_state[_ss(prefix, "recents")]
    if show_recents and recents:
        st.caption("**Recent folders**")
        rcols = st.columns(min(len(recents), 5))
        for i, recent in enumerate(recents):
            with rcols[i]:
                if st.button(
                    f"📁 {recent['name']}",
                    key=f"{prefix}_recent_{recent['id']}",
                    use_container_width=True,
                ):
                    _select_folder(prefix, recent["id"], recent["name"], recent.get("can_write", True))
                    st.rerun()

    # ----- Mode selector (radio, not tabs — survives reruns) -----
    mode = st.radio(
        "Find folder",
        ["Browse", "Search", "Paste URL"],
        horizontal=True,
        key=f"{prefix}_mode_radio",
        label_visibility="collapsed",
    )
    # Sync to session state
    mode_map = {"Browse": "browse", "Search": "search", "Paste URL": "paste"}
    st.session_state[_ss(prefix, "mode")] = mode_map.get(mode, "browse")
    current_mode = st.session_state[_ss(prefix, "mode")]

    # Get a fresh token for API calls
    access_token = _get_token(brand_id, organization_id)
    if not access_token:
        st.error("Could not get Drive credentials. Try disconnecting and reconnecting.")
        return selected

    # =====================================================================
    # BROWSE MODE
    # =====================================================================
    if current_mode == "browse":
        _render_browse(prefix, access_token, allow_create)

    # =====================================================================
    # SEARCH MODE
    # =====================================================================
    elif current_mode == "search":
        _render_search(prefix, access_token)

    # =====================================================================
    # PASTE URL MODE
    # =====================================================================
    elif current_mode == "paste":
        _render_paste_url(prefix, access_token)

    return st.session_state[_ss(prefix, "selected_folder")]


def _render_browse(prefix: str, access_token: str, allow_create: bool):
    """Render the hierarchical folder browser."""
    from viraltracker.services.google_drive_service import GoogleDriveService

    # Source selector (My Drive vs Shared with Me)
    source = st.radio(
        "Source",
        ["My Drive", "Shared with Me"],
        horizontal=True,
        key=f"{prefix}_source_radio",
        label_visibility="collapsed",
    )
    source_key = "shared_with_me" if source == "Shared with Me" else "my_drive"

    # Reset navigation when switching sources
    if source_key != st.session_state[_ss(prefix, "browse_source")]:
        st.session_state[_ss(prefix, "browse_source")] = source_key
        st.session_state[_ss(prefix, "current_folder_id")] = None
        st.session_state[_ss(prefix, "display_page")] = 0

    current_folder_id = st.session_state[_ss(prefix, "current_folder_id")]
    breadcrumbs = _get_breadcrumbs(prefix)

    # ----- Breadcrumbs -----
    if breadcrumbs:
        crumb_parts = []
        root_label = "Shared with Me" if source_key == "shared_with_me" else "My Drive"
        crumb_parts.append(root_label)
        for _, name in breadcrumbs:
            crumb_parts.append(name)
        st.caption(" > ".join(crumb_parts))

        # Navigation buttons row
        nav_cols = st.columns([1, 1, 6])
        with nav_cols[0]:
            if st.button("↑ Up", key=f"{prefix}_up"):
                if len(breadcrumbs) > 1:
                    breadcrumbs.pop()
                    st.session_state[_ss(prefix, "current_folder_id")] = breadcrumbs[-1][0]
                else:
                    breadcrumbs.clear()
                    st.session_state[_ss(prefix, "current_folder_id")] = None
                _set_breadcrumbs(prefix, breadcrumbs)
                st.session_state[_ss(prefix, "display_page")] = 0
                st.rerun()
        with nav_cols[1]:
            if st.button("⌂ Root", key=f"{prefix}_root"):
                _set_breadcrumbs(prefix, [])
                st.session_state[_ss(prefix, "current_folder_id")] = None
                st.session_state[_ss(prefix, "display_page")] = 0
                st.rerun()

    # ----- Fetch folder listing -----
    is_shared = source_key == "shared_with_me"
    cache_key = f"{'shared' if is_shared else 'my'}_{current_folder_id or 'root'}"

    def fetch():
        if is_shared and not current_folder_id:
            return GoogleDriveService.list_folders(access_token, shared_with_me=True)
        return GoogleDriveService.list_folders(access_token, parent_id=current_folder_id)

    with st.spinner("Loading folders..."):
        folders = _get_cached_folders(prefix, cache_key, fetch)

    # ----- "Select this folder" button -----
    if current_folder_id:
        current_name = breadcrumbs[-1][1] if breadcrumbs else "Current folder"
        can_write = True  # With full drive scope, assume writable

        if st.button(
            f"✅ Select: {current_name}",
            key=f"{prefix}_select_current",
            type="primary",
            use_container_width=True,
        ):
            _select_folder(prefix, current_folder_id, current_name, can_write)
            st.rerun()

    # ----- Folder list with display pagination -----
    if not folders:
        st.info("This folder is empty. You can still select it or create a subfolder.")
    else:
        total = len(folders)
        page = st.session_state[_ss(prefix, "display_page")]
        start = page * _FOLDERS_PER_PAGE
        end = min(start + _FOLDERS_PER_PAGE, total)
        page_folders = folders[start:end]

        for f in page_folders:
            f_id = f["id"]
            f_name = f["name"]
            can_add = f.get("capabilities", {}).get("canAddChildren", True)

            col1, col2, col3 = st.columns([5, 1, 1])
            with col1:
                st.text(f"📁 {f_name}")
            with col2:
                if st.button("Select", key=f"{prefix}_sel_{f_id}"):
                    _select_folder(prefix, f_id, f_name, can_add)
                    st.rerun()
            with col3:
                if st.button("Open ▶", key=f"{prefix}_open_{f_id}"):
                    breadcrumbs = _get_breadcrumbs(prefix)
                    breadcrumbs.append((f_id, f_name))
                    _set_breadcrumbs(prefix, breadcrumbs)
                    st.session_state[_ss(prefix, "current_folder_id")] = f_id
                    st.session_state[_ss(prefix, "display_page")] = 0
                    st.rerun()

        # Pagination controls
        if total > _FOLDERS_PER_PAGE:
            total_pages = (total + _FOLDERS_PER_PAGE - 1) // _FOLDERS_PER_PAGE
            pcol1, pcol2, pcol3 = st.columns([2, 3, 2])
            with pcol1:
                if page > 0:
                    if st.button("← Previous", key=f"{prefix}_prev"):
                        st.session_state[_ss(prefix, "display_page")] = page - 1
                        st.rerun()
            with pcol2:
                jump_page = st.number_input(
                    "Page",
                    min_value=1,
                    max_value=total_pages,
                    value=page + 1,
                    step=1,
                    key=f"{prefix}_page_jump",
                    label_visibility="collapsed",
                )
                if jump_page != page + 1:
                    st.session_state[_ss(prefix, "display_page")] = jump_page - 1
                    st.rerun()
            with pcol3:
                if end < total:
                    if st.button("Next →", key=f"{prefix}_next"):
                        st.session_state[_ss(prefix, "display_page")] = page + 1
                        st.rerun()
            st.caption(f"Page {page + 1} of {total_pages} ({total} folders)")

    # ----- New Folder -----
    if allow_create:
        creating = st.session_state[_ss(prefix, "creating_folder")]
        if creating:
            fc1, fc2, fc3 = st.columns([4, 1, 1])
            with fc1:
                new_name = st.text_input(
                    "Folder name",
                    key=f"{prefix}_new_folder_name",
                    placeholder="New folder name...",
                    label_visibility="collapsed",
                )
            with fc2:
                if new_name and st.button("Create", key=f"{prefix}_create_confirm"):
                    try:
                        parent = current_folder_id if current_folder_id else None
                        GoogleDriveService.create_folder(access_token, new_name, parent)
                        _invalidate_cache(prefix, cache_key)
                        st.session_state[_ss(prefix, "creating_folder")] = False
                        st.success(f"Created: {new_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            with fc3:
                if st.button("Cancel", key=f"{prefix}_create_cancel"):
                    st.session_state[_ss(prefix, "creating_folder")] = False
                    st.rerun()
        else:
            if st.button("+ New Folder", key=f"{prefix}_new_folder_btn"):
                st.session_state[_ss(prefix, "creating_folder")] = True
                st.rerun()


def _render_search(prefix: str, access_token: str):
    """Render the search interface."""
    from viraltracker.services.google_drive_service import GoogleDriveService

    sc1, sc2 = st.columns([4, 1])
    with sc1:
        query = st.text_input(
            "Search folders",
            key=f"{prefix}_search_input",
            placeholder="Search by folder name...",
            label_visibility="collapsed",
        )
    with sc2:
        do_search = st.button("Search", key=f"{prefix}_search_btn", use_container_width=True)

    if do_search and query:
        with st.spinner("Searching..."):
            results = GoogleDriveService.search_folders(access_token, query)
        st.session_state[_ss(prefix, "search_results")] = results
        st.session_state[_ss(prefix, "search_query")] = query

    results = st.session_state[_ss(prefix, "search_results")]

    if results is None:
        st.caption("Enter a folder name and click Search.")
    elif not results:
        st.info(f"No folders matching '{st.session_state[_ss(prefix, 'search_query')]}'.")
    else:
        st.caption(f"{len(results)} result{'s' if len(results) != 1 else ''}")
        for f in results:
            f_id = f["id"]
            f_name = f["name"]
            parent = f.get("parent_name", "")
            display = f"📁 {f_name}" + (f"  (in {parent})" if parent else "")

            col1, col2 = st.columns([5, 1])
            with col1:
                st.text(display)
            with col2:
                if st.button("Select", key=f"{prefix}_search_sel_{f_id}"):
                    _select_folder(prefix, f_id, f_name)
                    st.rerun()


def _render_paste_url(prefix: str, access_token: str):
    """Render the paste-URL interface."""
    from viraltracker.services.google_drive_service import GoogleDriveService

    url = st.text_input(
        "Google Drive folder URL",
        key=f"{prefix}_paste_url_input",
        placeholder="https://drive.google.com/drive/folders/...",
        label_visibility="collapsed",
    )

    if url:
        # Quick client-side validation
        if "drive.google.com" not in url:
            st.error("Not a Google Drive URL. Expected: drive.google.com/drive/folders/...")
            return

        with st.spinner("Resolving folder..."):
            result = GoogleDriveService.resolve_folder_url(access_token, url)

        if not result:
            st.error("Folder not found or you don't have access. Check the URL and sharing settings.")
        else:
            write_label = "" if result["can_write"] else " (read-only)"
            st.success(f"Found: **{result['name']}**{write_label}")
            if st.button(
                f"Select: {result['name']}",
                key=f"{prefix}_paste_select",
                type="primary",
                use_container_width=True,
            ):
                _select_folder(prefix, result["id"], result["name"], result["can_write"])
                st.rerun()
