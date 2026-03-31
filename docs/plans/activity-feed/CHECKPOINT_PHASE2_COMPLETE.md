# Activity Feed — Phase 2 Complete Checkpoint

**Date:** 2026-03-31
**Branch:** RyeMcKenzie81/office-hours (merged to main)
**Status:** Phase 1 + Phase 2 shipped and live

---

## What Shipped

### Phase 1 — Core Event Bus & Feed Page
- **Migration:** `migrations/2026-03-30_activity_events.sql` — `activity_events` table, `user_feed_state` table, 3 indexes, RLS, idempotent 30-day backfill
- **Event emission:** `_emit_activity_event()` in `scheduler_worker.py` — fire-and-forget, resolves org_id from brand_id, sends Slack on errors
- **Lifecycle hooks:** `create_job_run()` emits `job_started`, `update_job_run()` emits `job_completed`/`job_failed` with duration_ms, `recover_stuck_runs()` emits `job_stuck_recovered`, `_reschedule_after_failure()` emits `job_retrying`
- **Rich events for top 3 job types:** `ads_generated` (ad count), `sync_completed` (sync stats), `templates_scraped` (template count)
- **Activity Feed page:** `00_📊_Activity_Feed.py` — default landing page, attention strip, in-progress jobs, while-you-were-away, filter tabs (All/Failures/Success), pagination
- **Slack webhook:** POST on severity='error', configurable in Platform Settings
- **Nav changes:** Activity Feed as default, Agent Chat moved to Chainlit external link, old Streamlit chat page removed from nav
- **Shared `job_type_badge()`** in `ui/utils.py` — 23 job types
- **Feature key:** `ACTIVITY_FEED` registered in `FeatureService`

### Phase 2 — Health Cards, Acknowledgment, Search, Deep Links
- **Browser tab unread badge:** `(N) Activity Feed` in tab title when unread errors exist
- **Brand health summary cards:** Per-brand cards with success rate (24h), last failure age, active job count, color-coded green/yellow/red
- **Event acknowledgment:** Dismiss button on attention strip errors, `acknowledged_at` column, dismissed events hidden from strip
- **Event search:** Text search over event titles (ILIKE)
- **Improved deep links:** "View" buttons link to result pages (Ad History, Ad Performance, Template Queue, etc.) not just the scheduler

### Bug Fixes
- Duplicate Streamlit widget keys across tabs (key_prefix parameter)
- Agent Chat linked to Chainlit service instead of Streamlit page

### Sidebar Reorganization (PR #28)
- SEO section: all SEO tools grouped together
- Deprecated section: Ad Creator (original) moved to bottom

---

## What's Live Now

| Feature | Status |
|---------|--------|
| Event emission (all 23 job types) | ✅ Live |
| Activity Feed as default page | ✅ Live |
| Attention strip with dismiss | ✅ Live |
| Brand health cards | ✅ Live |
| While-you-were-away | ✅ Live |
| Search | ✅ Live |
| Browser tab badge | ✅ Live |
| Slack webhook on errors | ✅ Live |
| Deep links to results | ✅ Live |
| Rich events (ads, templates, sync) | ✅ Live |

---

## What's Next — Phase 3: Rich Media Cards

**Concept:** Facebook-style image grid cards in the Activity Feed. When ads finish generating, show a hero image + 3-4 thumbnails + "+N" overflow badge.

**Applicable to:**
- `ads_generated` — show generated ad creatives
- `templates_scraped` — show scraped ad creatives
- Asset downloads — show downloaded assets
- SEO images — show generated article images

**Requirements:**
1. Store image URLs in event `details` JSONB during emission
2. Grid renderer in `render_event_card` — 1 hero + 3-4 thumbs + "+N"
3. Investigate where generated ad images are stored (Supabase storage? URLs in DB?)
4. Consider click-to-expand for full gallery view

---

## Key Files

| File | Role |
|------|------|
| `viraltracker/ui/pages/00_📊_Activity_Feed.py` | Main feed page |
| `viraltracker/worker/scheduler_worker.py` | Event emission, lifecycle hooks |
| `viraltracker/ui/utils.py` | Shared `job_type_badge()` |
| `viraltracker/ui/nav.py` | Nav config, default page |
| `viraltracker/ui/app.py` | Sidebar rendering, Chainlit link |
| `viraltracker/services/feature_service.py` | Feature key registration |
| `viraltracker/ui/pages/64_⚙️_Platform_Settings.py` | Slack webhook config |
| `migrations/2026-03-30_activity_events.sql` | Phase 1 migration |
| `migrations/2026-03-31_activity_feed_phase2.sql` | Phase 2 migration |

## Remaining Housekeeping

- **Event retention:** pg_cron not yet enabled on Supabase. SQL documented in TODOS.md.
