# Fix 12+13: Ad Export — CHECKPOINT

**Date**: 2026-03-09
**Branch**: `feat/ad-creator-v2-phase0`
**Commit**: `a7a34de`
**Status**: Implementation complete, ready for manual QA

---

## What Was Built

### New Files (5)
| File | Purpose |
|------|---------|
| `viraltracker/services/google_oauth_utils.py` | Shared OAuth: `encode_oauth_state()`, `decode_oauth_state()`, `refresh_google_token()` |
| `viraltracker/services/google_drive_service.py` | Drive service: OAuth, folder CRUD, multipart file upload, `upload_export_list()` |
| `viraltracker/ui/export_utils.py` | `get_export_list()`, `get_export_count()`, `create_zip_from_export_list()`, filename helpers |
| `viraltracker/ui/pages/22b_📦_Ad_Export.py` | Export page: list table, ZIP download, Drive OAuth + folder browser + upload |
| `tests/test_google_drive_service.py` | 19 tests — OAuth, token refresh, folders, upload, multi-tenant, shared utils |

### Modified Files (6)
| File | Change |
|------|--------|
| `gsc_service.py` | Imports from `google_oauth_utils`; `_get_credentials` delegates to `refresh_google_token` |
| `feature_service.py` | Added `AD_EXPORT = "ad_export"` |
| `nav.py` | Added superuser flag + page entry after Ad History |
| `69_Admin.py` | Added to Ads opt-in list |
| `22_Ad_History.py` | Session init, sidebar count, per-run "Add All to Export", per-ad "Export" button |
| `21b_Ad_Creator_V2.py` | Session init, per-ad "Export" in card, bulk "Export All" per template group |

### Design Decisions
- Export list: `st.session_state.export_ads` (plain dicts, no TypedDict)
- Drive platform: `google_drive` in `brand_integrations`
- Drive scope: `drive.file` (non-sensitive, app-managed folders only)
- OAuth: shared utils extracted from GSC, backward compatible
- ZIP: adapted from Ad History's `create_zip_for_run()` (copies, not extracted)
- No DB migration needed

---

## QA Done
- All 11 files compile (`py_compile`)
- 19/19 tests pass
- GSC backward compat verified (`encode_oauth_state`/`decode_oauth_state` roundtrip)
- Code review: fixed column order, ZIP flag staleness, UUID stringification, import placement

## Prerequisites Before Testing
1. Enable Google Drive API in Google Cloud Console (same project as GSC)
2. Add `https://www.googleapis.com/auth/drive.file` scope to OAuth consent screen
3. Add redirect URI: `{APP_BASE_URL}/Ad_Export` to OAuth credentials
4. Enable `ad_export` feature for your org in Admin > Features
