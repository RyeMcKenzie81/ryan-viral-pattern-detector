# Checkpoint: Workspace Selector — Persistence + Duplicate Fix

**Date:** 2026-01-30
**Branch:** `feat/veo-avatar-tool`
**Commit:** `b92affc`
**Status:** COMPLETE

## Summary

Fixed two bugs in the workspace (organization) selector:

1. **Workspace resets on page refresh** — org_id was stored only in `st.session_state`, which clears on refresh. Now persisted to a browser cookie.
2. **Changing workspace doesn't update sidebar pages** — caused by (a) navigation building before the selector ran, and (b) 10 pages + `render_brand_selector()` rendering duplicate org selectors that overwrote the value back.

---

## What Changed

### Before

- `render_organization_selector(key=...)` was called in **11 places**: once in `app.py` and once in each of 10 pages
- Each call created a **separate sidebar selectbox** with a different widget key
- Streamlit widgets with existing state ignore the `index` parameter, so page selectors retained the old value and overwrote `current_organization_id` back
- `render_brand_selector()` internally called `render_organization_selector()`, adding yet another duplicate
- `build_navigation_pages()` in `app.py` ran before the org selector, reading stale `current_organization_id`
- On page refresh, `_auto_init_organization()` defaulted to the user's first org (no persistence)

### After

- `render_organization_selector()` called **once** in `app.py` — no `key` parameter, uses hardcoded `"_workspace_selectbox"` key
- All 10 pages replaced with `get_current_organization_id()` (reads session state, no widget)
- `render_brand_selector()` uses `get_current_organization_id()` instead of rendering a selector
- `on_change` callback fires **before** the page reruns, so `build_navigation_pages()` reads the new org_id
- The callback also clears `selected_brand_id` / `selected_product_id` (belong to old workspace) and invalidates `_get_org_features_cached`
- `_auto_init_organization()` checks a browser cookie (`viraltracker_workspace`, 30-day TTL) before falling back to the first org
- Cookie is saved on every workspace change via the `on_change` callback

---

## Files Modified (12)

| File | Change |
|------|--------|
| `viraltracker/ui/utils.py` | Added cookie helpers, updated `_auto_init_organization()`, rewrote `render_organization_selector()` with `on_change`, fixed `render_brand_selector()` |
| `viraltracker/ui/app.py` | Removed `key=` argument from `render_organization_selector()` |
| `viraltracker/ui/pages/21_Ad_Creator.py` | Replaced org selector with `get_current_organization_id()` |
| `viraltracker/ui/pages/22_Ad_History.py` | Same |
| `viraltracker/ui/pages/23_Ad_Gallery.py` | Same |
| `viraltracker/ui/pages/24_Ad_Scheduler.py` | Same |
| `viraltracker/ui/pages/26_Plan_List.py` | Same |
| `viraltracker/ui/pages/15_Reddit_Research.py` | Same |
| `viraltracker/ui/pages/43_Comic_JSON_Generator.py` | Same |
| `viraltracker/ui/pages/46_Knowledge_Base.py` | Same |
| `viraltracker/ui/pages/68_Usage_Dashboard.py` | Same |
| `viraltracker/ui/pages/69_Admin.py` | Same |

---

## Key Design Decisions

1. **Cookie over URL param**: Used browser cookie (same library as auth) rather than URL query params. Simpler, no URL pollution, and the auth cookie already proves this pattern works across refreshes.

2. **`on_change` callback**: Streamlit fires `on_change` before the script reruns. This means `build_navigation_pages()` in `app.py` reads the *new* org_id, not the stale one.

3. **Hardcoded widget key**: `"_workspace_selectbox"` — only one selectbox should ever exist. This prevents multiple widgets from fighting over the value.

4. **Cookie validation**: `_auto_init_organization()` validates the cookie value against the user's actual org memberships. Stale/invalid cookies are ignored. `"all"` is only accepted for superusers.

---

## Edge Cases Handled

| Scenario | Behavior |
|----------|----------|
| Cookie has stale org_id (user removed from org) | Ignored, falls through to first org |
| Cookie has `"all"` but user is no longer superuser | Ignored, falls through to first org |
| Cookie JS not loaded on first render | Falls through to default; cookie restores on next interaction |
| User switches workspace | Brand/product selections cleared, feature cache invalidated |

---

## Verification

- All 12 files pass `python3 -m py_compile`
- `grep` confirms `render_organization_selector` only referenced in `utils.py` (definition) and `app.py` (single caller)
- Documentation updated in `docs/MULTI_TENANT_AUTH.md`
