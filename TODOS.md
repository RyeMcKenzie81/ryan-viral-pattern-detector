# TODOS

## Event Retention Automation
**What:** Add automated cleanup of activity_events older than 90 days (pg_cron or scheduler job type).
**Why:** Without automation, the table grows indefinitely. At 500 events/day, ~180K rows/year.
**Pros:** Set-and-forget retention policy.
**Cons:** Requires pg_cron setup on Supabase or a new scheduler job type.
**Context:** Current volume is low enough that this is not urgent. The table has good indexes so query performance won't degrade meaningfully even at 1-2 years of data. But it's good hygiene to cap it.
**Depends on:** Activity Feed Phase 1 (activity_events table must exist).
**Added:** 2026-03-30 from /plan-eng-review of Activity Feed feature.

## Event Acknowledgment / Resolution Tracking (v2)
**What:** Add ability to mark a failed event as "acknowledged" or "resolved" so it stops showing in the attention strip.
**Why:** Without this, the attention strip will show stale failures the user already knows about and has fixed manually. After a few days, the strip fills with old failures and loses signal.
**Pros:** Cleaner attention strip, reduces noise, completes the triage loop (see failure → retry → confirm resolved).
**Cons:** Adds mutable state to events (currently immutable). Needs UI for acknowledge action + a new column or separate table.
**Context:** Both design reviewers (Codex + Claude subagent) flagged the missing resolution path. The user sees a failure, retries it, but the original failure event still shows red. Consider: `acknowledged_at TIMESTAMPTZ` column on activity_events, or a separate `event_acknowledgments` table for clean separation.
**Depends on:** Activity Feed v1 (attention strip must exist first).
**Added:** 2026-03-30 from /plan-design-review of Activity Feed feature.

## Brand Health Summary Cards (v2)
**What:** Add per-brand health cards at the top of the Activity Feed showing success rate (24h), last failure age, and active job count. Color-coded green/yellow/red.
**Why:** Makes the feed feel like an operating console, not a log viewer. At-a-glance brand health without reading the timeline.
**Pros:** Executive summary view. Quickly spot which brand needs attention.
**Cons:** Adds a second query pattern (aggregate query over recent events per brand). Needs refresh logic or caching.
**Context:** Deferred from CEO review expansion #3. The attention strip + while-you-were-away already provide at-a-glance awareness. Health cards are a clean addition once event data is flowing and patterns are understood. Query: aggregate events by brand_id, compute success/failure counts for last 24h.
**Depends on:** Activity Feed Phase 1 (activity_events table must exist with data flowing).
**Added:** 2026-03-30 from /plan-ceo-review of Activity Feed feature.

## Browser Tab Unread Badge (v2)
**What:** Show unread failure count in the browser tab title: "(3) Activity Feed" when error events exist since last_seen_at.
**Why:** If the app is open in a background tab, you still get a visual signal that something needs attention.
**Pros:** Tiny effort (~5 min), nice polish touch.
**Cons:** Streamlit's st.set_page_config must be the first call, so the count query needs to happen before any other rendering.
**Context:** Deferred from CEO review expansion #4. Not day-1 essential but a quick win post-launch. Implementation: query error count since last_seen_at, pass to st.set_page_config(page_title=f"({count}) Activity Feed") if count > 0.
**Depends on:** Activity Feed Phase 1 + user_feed_state table.
**Added:** 2026-03-30 from /plan-ceo-review of Activity Feed feature.

## Event Search (v2)
**What:** Add a search box to the Activity Feed that filters events by title text (ILIKE '%query%').
**Why:** Power user feature for finding specific past events ("what happened with Brand X last Tuesday").
**Pros:** Simple implementation, useful at scale.
**Cons:** ILIKE can be slow without a trigram index at high volumes. Consider adding pg_trgm index if search becomes a frequent pattern.
**Context:** Deferred from CEO review expansion #6. At current volumes (200-500 events/day), scrolling and filtering is sufficient. Search becomes valuable after months of accumulated data. Brand filter + severity tabs already provide strong filtering for day-to-day use.
**Depends on:** Activity Feed Phase 1.
**Added:** 2026-03-30 from /plan-ceo-review of Activity Feed feature.
