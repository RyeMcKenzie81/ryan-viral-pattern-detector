# Drive Folder Picker Redesign — Plan

**Date**: 2026-03-09
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Planning (reviewed by QA x2 + UX agent)

---

## Problem

The current Drive folder picker is a flat selectbox showing every folder the user has access to — unusable at scale. Users need to browse, search, and paste URLs to find folders.

---

## Critical Scope Decision (MUST RESOLVE BEFORE BUILD)

### The `drive.file` vs `drive` scope problem

**Current scopes**: `drive.file` + `drive.readonly`

- `drive.readonly` lets us **see** all folders (browse, search)
- `drive.file` only lets us **write** to folders the app created or the user explicitly opened via Google Picker
- **Result**: Uploading to a folder the user browses to will **403** unless the app created that folder

### Options

| Option | Pros | Cons |
|--------|------|------|
| **(A) Upgrade to `drive` scope** | Full read+write to all folders. True Google Drive experience. | Restricted scope — requires Google OAuth verification (days/weeks). Shows scary consent screen. |
| **(B) Use Google Picker API** | Google-recommended. Grants `drive.file` access to selected items. No verification needed. | Requires JavaScript embed — harder in Streamlit. Different UX (Google's picker modal). |
| **(C) Accept limitation** | No scope changes. Simple. Works today. | Users can only upload to app-created folders. Must create folders through our app, not browse to existing ones. |
| **(D) Hybrid: browse + create** | Use `drive.readonly` to browse for context, but always create a new subfolder (via `drive.file`) inside the browsed location for upload. | Extra folder created every time. May not work if user lacks create permission in browsed folder. |

**Recommendation**: Option (A) for production, Option (C) for immediate MVP. Build the picker UI now with Option (C) behavior, then upgrade scope later. The picker UI is the same regardless — only the write permission changes.

**If Option (C)**: The picker should clearly indicate which folders are "app-managed" (uploadable) vs "browse-only" (read-only). Disable the "Select" button on browse-only folders with a tooltip: "Create a subfolder here to upload."

---

## Architecture

### New file: `viraltracker/ui/drive_picker.py` (reusable component)

```python
def render_drive_folder_picker(
    brand_id: str,
    organization_id: str,
    prefix: str = "drive",          # namespace session state keys
    allow_create: bool = True,
    show_recents: bool = True,
    label: str = "Target folder",
) -> dict | None:
    """
    Reusable Google Drive folder picker widget.

    Returns {"folder_id": "...", "folder_name": "...", "can_write": bool} or None.
    Handles credential refresh internally.
    """
```

**Key design decision**: Accepts `brand_id`/`organization_id` (not `access_token`) so it can refresh credentials internally before each API call. This avoids token expiry during long browse sessions.

### Layout

```
┌──────────────────────────────────────────────┐
│ 📁 Selected: My Drive > Client A > Ads       │
│ [Change]                                      │
├──────────────────────────────────────────────┤
│ Recent: Client A > Ads | Client B > Q1       │  (if show_recents)
├──────────────────────────────────────────────┤
│ [ Browse ]  [ Search ]  [ Paste URL ]        │  (st.radio horizontal, NOT st.tabs)
│ ──────────────────────────────────────────── │
│ (My Drive) / (Shared with Me)                │  (st.radio, only in Browse mode)
│                                               │
│ My Drive > Client A > [↑ Up]                 │  (breadcrumbs, clickable)
│                                               │
│  📁 Campaigns    [Select] [Open ▶]           │
│  📁 Assets       [Select] [Open ▶]           │
│  📁 (empty)                                  │
│                                               │
│  Showing 1-20 of 45  [← Prev] [Next →]      │  (display pagination)
│                                               │
│  [+ New Folder]                              │  (if allow_create + can_write)
│                                               │
│  ✅ Select this folder                        │  (selects current browsed folder)
└──────────────────────────────────────────────┘
```

### Session state keys (all prefixed with `{prefix}_`)

| Key | Type | Purpose |
|-----|------|---------|
| `{prefix}_selected_folder` | `dict \| None` | `{"id": ..., "name": ..., "can_write": bool}` |
| `{prefix}_mode` | `str` | "browse" / "search" / "paste" |
| `{prefix}_browse_source` | `str` | "my_drive" / "shared_with_me" |
| `{prefix}_current_folder_id` | `str \| None` | Folder being browsed (None = root) |
| `{prefix}_breadcrumbs` | `list[tuple]` | `[(id, name), ...]` for navigation |
| `{prefix}_breadcrumbs_shared` | `list[tuple]` | Separate breadcrumbs for Shared with Me tab |
| `{prefix}_folder_cache` | `dict` | `{folder_id: {"children": [...], "fetched_at": float}}` |
| `{prefix}_recents` | `list[dict]` | Last 5 selected folders |
| `{prefix}_display_page` | `int` | Current page of folder listing (0-indexed) |
| `{prefix}_picker_open` | `bool` | Whether picker is expanded (collapses after selection) |

---

## Service Changes: `google_drive_service.py`

### Modified: `list_folders()`

```python
@staticmethod
def list_folders(
    access_token: str,
    parent_id: str = None,
    shared_with_me: bool = False,
    page_size: int = 1000,        # API max — fewer round trips
    max_results: int = 500,       # safety cap
) -> List[Dict]:
```

**Query patterns** (corrected per QA):
- My Drive root: `q="'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"`
- Subfolder: `q="'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"`
- Shared with Me (top-level only): `q="sharedWithMe=true and mimeType='application/vnd.google-apps.folder' and trashed=false"`
- All queries: pagination via `nextPageToken` loop, capped at `max_results`
- Fields: `files(id,name,capabilities/canAddChildren)`

**Backward compat**: When `parent_id=None` and `shared_with_me=False`, adds `'root' in parents` to only return top-level My Drive folders (not all folders flat). This is a behavior change from the old flat list, but the old caller (225_Ad_Export.py) is being migrated to the picker simultaneously.

### New: `search_folders()`

```python
@staticmethod
def search_folders(
    access_token: str,
    query: str,
    page_size: int = 100,
    max_results: int = 100,
) -> List[Dict]:
```

- Query: `q="name contains '{escaped_query}' and mimeType='..folder' and trashed=false"`
- **Must escape single quotes** in query (matching `find_folder()` pattern)
- Fields: `files(id,name,parents)` — fetch parent IDs, batch-resolve names for display
- Returns: `[{"id": ..., "name": ..., "parent_name": ...}]`
- Parent name resolution: collect unique parent IDs from results, batch `files.get` for names (max ~20 calls for 100 results)

### New: `get_folder_info()`

```python
@staticmethod
def get_folder_info(access_token: str, folder_id: str) -> Optional[Dict]:
```

- `files.get` with `fields=id,name,parents,capabilities/canAddChildren`
- `supportsAllDrives=true` (handles shared drive folders)
- Returns None on 404/403 (don't distinguish — matches Google's pattern)

### New: `resolve_folder_url()`

```python
@staticmethod
def resolve_folder_url(access_token: str, url: str) -> Optional[Dict]:
```

- Regex patterns for URL formats:
  - `https://drive.google.com/drive/folders/{id}`
  - `https://drive.google.com/drive/u/0/folders/{id}` (multi-account)
  - `https://drive.google.com/drive/folders/{id}?usp=sharing` (with query params)
  - `https://drive.google.com/open?id={id}` (legacy)
- Extract folder ID, then call `get_folder_info()` to validate + get name
- Returns `{"id": ..., "name": ..., "can_write": bool}` or None

---

## UI Behavior Details

### Browse tab
- Use `st.radio` (horizontal) for My Drive / Shared with Me — NOT `st.tabs` (tabs reset on rerun)
- Each folder row: folder name + [Select] + [Open ▶] buttons
- Display pagination: show 20 folders at a time with Prev/Next
- Breadcrumbs: clickable segments, truncate middle if > 5 levels deep
- "↑ Up" button alongside breadcrumbs
- Empty folder: "This folder is empty. You can still select it or create a subfolder."
- New Folder: inline text input + Create/Cancel, disabled if `canAddChildren` is false

### Search tab
- Text input + "Search" button (no search-on-type — avoids API spam)
- Results show: 📁 folder_name (in parent_name)
- Click result to select it
- "No results" state with suggestion to try Browse

### Paste URL tab
- Text input for URL
- Client-side regex validation before API call
- On valid URL: show folder name for confirmation + Select button
- Error states: invalid format, folder not found/no access

### Recent Folders
- Last 5 selected folders, stored in session state
- Each is a single-click button to re-select
- Updated when user selects a folder via any method

### Selected Folder Display
- Always visible above the picker tabs
- Shows: 📁 folder_name (or breadcrumb path)
- [Change] button to re-open picker
- Green-tinted or bordered for visual confirmation
- Picker collapses after selection (toggle via `{prefix}_picker_open`)

### Caching
- Cache folder listings in `{prefix}_folder_cache`
- Key: `folder_id` (or "root" / "shared_root")
- Value: `{"children": [...], "fetched_at": time.time()}`
- TTL: 5 minutes — invalidate stale entries
- Invalidate specific entry when user creates a folder in that location

### Error Handling
- Empty folder: inline message, keep Select/New Folder active
- No search results: message + link to Browse
- Invalid URL: immediate feedback before API call
- Folder not found: "This folder doesn't exist or you don't have access"
- API error: "Google Drive is temporarily unavailable. [Retry]"
- No write access: disable Select button, show "Read-only — create a subfolder to upload"

---

## Files Changed

| File | Change |
|------|--------|
| `viraltracker/ui/drive_picker.py` | **NEW** — reusable folder picker component |
| `viraltracker/services/google_drive_service.py` | Add pagination to `list_folders()`, new `search_folders()`, `get_folder_info()`, `resolve_folder_url()` |
| `viraltracker/ui/pages/225_Ad_Export.py` | Replace flat selectbox with `render_drive_folder_picker()` |
| `tests/test_google_drive_service.py` | Add tests for new/modified service methods |

---

## Build Order

1. **Service methods** — pagination in `list_folders()`, new `search_folders()`, `get_folder_info()`, `resolve_folder_url()`
2. **Tests** — for all new/modified service methods
3. **`drive_picker.py`** — reusable component with full UI
4. **Update `225_Ad_Export.py`** — integrate picker, remove old selectbox

---

## Test Plan

| Test | Priority |
|------|----------|
| `test_list_folders_pagination` — mock nextPageToken, verify all pages collected | HIGH |
| `test_list_folders_pagination_cap` — verify stops at max_results | HIGH |
| `test_list_folders_root` — verify `'root' in parents` query for My Drive root | HIGH |
| `test_list_folders_shared_with_me` — verify `sharedWithMe=true` query | HIGH |
| `test_search_folders_basic` — verify `name contains` query | HIGH |
| `test_search_folders_escapes_quotes` — input with `'` chars | HIGH |
| `test_get_folder_info_success` — correct fields requested | HIGH |
| `test_get_folder_info_not_found` — 404 returns None | HIGH |
| `test_resolve_folder_url_formats` — all URL variants | HIGH |
| `test_resolve_folder_url_invalid` — bad URL returns None | MEDIUM |
| `test_list_folders_backward_compat` — existing callers still work | HIGH |
| `test_list_folders_api_error_mid_pagination` — fails on page 2 | MEDIUM |

---

## QA Review Summary

### Round 1 Findings (all addressed)
- ✅ Wrong `corpora` semantics → corrected query patterns
- ✅ No pagination → added nextPageToken loop
- ✅ Token expiry → re-fetch credentials per operation
- ✅ Paste URL edge cases → specified URL formats

### Round 2 Findings
- ⚠️ **CRITICAL**: `drive.file` can't write to browsed folders → deferred to scope decision (Option A vs C)
- ✅ `access_token` param → changed to `brand_id`/`org_id`
- ✅ `st.tabs` resets on rerun → switched to `st.radio`
- ✅ Search query injection → escape quotes
- ✅ Breadcrumbs conflict across tabs → separate state per tab
- ✅ Display pagination → 20 folders per page with Prev/Next
- ✅ `pageSize` → 1000 (API max) to reduce round trips
- ✅ Parent name in search → batch resolve unique parent IDs

### UX Review Findings
- ✅ Recent Folders → top 5, session state, 1-click re-select
- ✅ Persistent selected display → above tabs, always visible
- ✅ Two affordances per row → Select + Open buttons
- ✅ Session state caching → 5-min TTL per folder
- ✅ Error messages per failure mode → specified in detail
- ✅ Validate at upload time → deferred to upload flow
- ✅ Reusable component interface → function with prefix + brand_id/org_id
- 📋 DB persistence for recents → deferred to v2
- 📋 Shared Drives tab → deferred to v2
