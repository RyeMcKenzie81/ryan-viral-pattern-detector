# Dynamic Sidebar Navigation — Checkpoint 1

**Date:** 2026-01-28
**Branch:** `feat/veo-avatar-tool`
**Last commit:** `9a3bb45` — Two-tier feature gating

## What Was Done

### Files Created
- `viraltracker/ui/app.py` — New entry point using `st.navigation()` (replaced original)
- `viraltracker/ui/app_legacy.py` — Backup of original app.py
- `viraltracker/ui/nav.py` — Navigation builder with two-tier feature gating
- `viraltracker/ui/pages/login.py` — Login page for unauthenticated users
- `viraltracker/ui/pages/00_🎯_Agent_Chat.py` — Chat interface extracted from old app.py

### Files Modified
- `requirements.txt` — `streamlit==1.40.0` → `streamlit>=1.43.0`
- `viraltracker/services/feature_service.py` — Added 5 `SECTION_*` keys to `FeatureKey`, updated `enable_all_features()`

### Architecture

**Entry point flow** (`app.py`):
1. Force `DefaultEventLoopPolicy` (uvloop compat for nest_asyncio)
2. Apply `nest_asyncio` once
3. `st.set_page_config()`
4. Init observability (Logfire)
5. Check `is_authenticated()`
6. If auth: render org selector → build navigation pages → `st.navigation(pages)`
7. If not auth: show only Sign In + Public Gallery

**Two-tier gating** (`nav.py`):
- Section keys (`section_brands`, etc.) — **opt-out**: visible by default, disable to hide entire section
- Page keys (`ad_creator`, etc.) — **opt-in**: hidden by default, enable to show
- Rule: `page_visible = section_enabled OR page_key_enabled`
- Features cached 5min via `@st.cache_data(ttl=300)`
- Returns `Dict[str, bool]` (key → enabled) instead of `Set[str]`

### Issues Fixed
- Duplicate `_logout_btn` key — removed `_add_logout_button()` from entry point (pages handle it via `require_auth()`)
- uvloop/nest_asyncio — forced `DefaultEventLoopPolicy` at top of entry point

### Known Issues (TODO)
1. **Admin page broken** — `TypeError: 'NoneType' object is not subscriptable` at `69_Admin.py:92`. Line does `o.get("owner_user_id", "")[:8]` but `o` is None. Likely a data issue exposed by the navigation change (page now runs under `st.navigation()` context).
2. **Debug expander** in sidebar — temporary, remove after validation.
3. **5 separator files** still exist — can be deleted after full validation (not used by `st.navigation()`).
4. **Phase 2 cutover not done** — `app_legacy.py` still exists as backup.

### Feature Keys Reference

| Key | Type | Default | Controls |
|-----|------|---------|----------|
| `section_brands` | section | visible | Brand Manager, Personas, URL Mapping, Client Onboarding |
| `section_competitors` | section | visible | Competitors, Competitive Analysis |
| `section_ads` | section | visible | Ad Gallery, Plan List/Executor, Template Queue/Eval/Recs |
| `section_content` | section | visible | Comic Video, Comic JSON, Editor Handoff, Audio, Knowledge Base |
| `section_system` | section | visible | All System pages |
| `ad_creator` | page | hidden | Ad Creator |
| `ad_library` | page | hidden | Ad History, Ad Performance |
| `ad_scheduler` | page | hidden | Ad Scheduler |
| `ad_planning` | page | hidden | Ad Planning |
| `veo_avatars` | page | hidden | Veo Avatars |
| `competitor_research` | page | hidden | Competitor Research |
| `reddit_research` | page | hidden | Reddit Research |
| `brand_research` | page | hidden | Brand Research |
| `belief_canvas` | page | hidden | Belief Canvas |
| `content_pipeline` | page | hidden | Content Pipeline |
| `research_insights` | page | hidden | Research Insights |

### Always Visible
- Agent Chat (default page)
- Public Gallery (in System section, gated by `section_system`)
- Login page (unauthenticated only)
