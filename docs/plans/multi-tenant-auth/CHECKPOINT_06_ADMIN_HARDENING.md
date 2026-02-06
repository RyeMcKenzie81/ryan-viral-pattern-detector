# Checkpoint 06: Admin Page Hardening — Stale State, User Management

**Date:** 2026-01-28
**Branch:** `feat/veo-avatar-tool`
**Commits:** `a708d2e`, `fe13987`, `1b2b405`, `4e89bec`

## Context

After Phase 7 delivered the Admin page, manual testing revealed three categories of issues:
1. **Stale widget state** — Streamlit reuses cached `session_state` values when widget keys don't change, causing incorrect values when switching orgs or members
2. **Missing user info** — Email addresses weren't shown in the members table
3. **Dangerous actions without confirmation** — Accidentally assigning the "owner" role couldn't be easily undone

## What Was Done

### Bug Fix: Usage Limits Tab — Stale Values on Org Switch

**Root cause:** Widget keys like `admin_limit_val_{lt}` didn't include the selected org. Streamlit cached the first org's values and ignored the `value=` parameter when switching to a different org.

**Fix:** Appended `_{tab_org}` to all 5 widget key patterns:
- `admin_limit_val_{lt}_{tab_org}` — number_input
- `admin_limit_thresh_{lt}_{tab_org}` — slider
- `admin_limit_enabled_{lt}_{tab_org}` — checkbox
- `admin_limit_save_{lt}_{tab_org}` — save button
- `admin_limit_del_{lt}_{tab_org}` — remove button

### Bug Fix: Features & Limits Tabs — Stale State on Org Re-visit

**Root cause:** Even with `_{tab_org}` in keys, Streamlit session state persists widget values across reruns within a session. Revisiting a previously-viewed org (or even visiting a new one in some cases) could show stale cached values instead of fresh DB data.

**Fix:** Added explicit session state flushing at the top of both tabs. When the selected org changes, all relevant widget keys are deleted from `st.session_state` before checkboxes/inputs render, forcing Streamlit to use the `value=` parameter from the DB:

```python
# Features tab
_prev_key = "_admin_features_prev_org"
if st.session_state.get(_prev_key) != tab_org:
    for k in [k for k in st.session_state
              if k.startswith(("admin_section_", "admin_page_"))]:
        del st.session_state[k]
    st.session_state[_prev_key] = tab_org

# Usage Limits tab (same pattern with "admin_limit_" prefix)
```

### Bug Fix: Manage Member — Stale Role/Name on Member Switch

**Root cause:** Widget keys for the role selectbox (`admin_role_change`), display name input, and action buttons were static — they didn't change when selecting a different member. This caused the previous member's role to appear in the dropdown for the newly selected member.

**Fix:** All "Manage Member" widget keys now include both `_{tab_org}` and `_{sel_uid}` (selected member's user ID):
- `admin_member_select_{tab_org}`
- `admin_edit_display_name_{tab_org}_{sel_uid}`
- `admin_save_display_name_{tab_org}_{sel_uid}`
- `admin_role_change_{tab_org}_{sel_uid}`
- `admin_confirm_owner_{tab_org}_{sel_uid}`
- `admin_update_role_{tab_org}_{sel_uid}`
- `admin_remove_member_{tab_org}_{sel_uid}`

### Feature: Email Addresses in Users Tab

**Problem:** `user_profiles` has no email column — email lives in Supabase `auth.users`.

**Fix:** `get_org_members()` now fetches emails via the Supabase admin API (`client.auth.admin.get_user_by_id(uid)`) for each member. Email is included in the returned dicts and displayed in the members table.

Errors fetching individual emails are caught and logged as warnings (graceful degradation).

### Feature: Edit Display Name

**Added:**
- `OrganizationService.update_display_name(user_id, display_name)` — upserts into `user_profiles`
- UI: text_input + "Save Name" button in the "Manage Member" section, between the member selector and role/remove controls

### Feature: Owner Role Confirmation

**Problem:** Accidentally selecting "owner" in the role dropdown and clicking "Update Role" was too easy and hard to reverse (non-superusers can't demote owners).

**Fix:** When "owner" is selected as the new role, the UI:
1. Shows a warning explaining that owners have full control and can't be demoted by non-superusers
2. Requires the user to type **CONFIRM** in a text input
3. Blocks the role change if CONFIRM isn't typed exactly

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/ui/pages/69_🔧_Admin.py` | +`_{tab_org}` to Usage Limits keys; session state flushing for Features & Limits; +`_{sel_uid}` to Manage Member keys; +Email column; +Edit Display Name UI; +Owner confirmation |
| `viraltracker/services/organization_service.py` | +email fetching via admin API in `get_org_members()`; +`update_display_name()` method |

## Streamlit Stale State Pattern (Lesson Learned)

This is a recurring issue worth documenting. Streamlit's `st.session_state` caches widget values by key. The `value=` parameter is only used when the key is NEW. Once a key exists in session state, the cached value takes precedence.

**Two-part defense:**
1. **Unique keys** — Include all relevant context in widget keys (`_{org_id}`, `_{user_id}`, etc.)
2. **Explicit flushing** — When context changes (org switch, member switch), delete stale keys from `st.session_state` before widgets render

Both parts are needed. Unique keys alone aren't sufficient because session state persists across reruns.

## Verification

- [x] All modified files pass `python3 -m py_compile`
- [x] Usage Limits: switching orgs shows correct DB values
- [x] Features: switching orgs shows correct DB values
- [x] Manage Member: switching members shows correct role/name
- [x] Email addresses display in members table
- [x] Display name edit saves and persists
- [x] Owner role change requires typed CONFIRM

## Multi-Tenant Auth Progress

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | User Registration/Login | ✅ Complete |
| 2 | Organization Auto-Creation | ✅ Complete |
| 3 | Organization Schema | ✅ Complete |
| 4 | Usage Tracking | ✅ Complete |
| 5 | Workspace Selector | ✅ Complete |
| 6 | Feature Access Control | ✅ Complete |
| 7 | Usage Limits & Admin | ✅ Complete |
| 7+ | **Admin Hardening** | **✅ Complete** |
| 8 | RLS Policies | Planned (Optional) |
