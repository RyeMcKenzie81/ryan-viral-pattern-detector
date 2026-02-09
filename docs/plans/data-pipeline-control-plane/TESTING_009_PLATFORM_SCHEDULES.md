# Testing Plan: Platform Schedules (Checkpoint 009)

**Date:** 2026-02-07
**Status:** Pending QA
**Estimated time:** 15-20 minutes

---

## Prerequisites

- [ ] App running locally
- [ ] Migration `2026-02-07_platform_template_jobs.sql` has been run
- [ ] Worker is running (or can be started for end-to-end test)
- [ ] Supabase dashboard open for DB verification

---

## 1. Sub-Tab Structure

Navigate to **Pipeline Manager** → **Schedules** tab.

- [ ] Two sub-tabs visible: "🏢 Brand Schedules" and "🌐 Platform Schedules"
- [ ] Brand Schedules loads the brand selector as before
- [ ] Platform Schedules has no brand selector, shows "These jobs run across all brands..." caption

## 2. Brand Schedules — Correct Job Types

Select a brand in Brand Schedules.

- [ ] Shows: Meta Sync, Ad Classification, Asset Download, Scorecard, Congruence Reanalysis
- [ ] Does **NOT** show Template Scrape or Template Approval
- [ ] Existing schedules for these types still display correctly (status, cadence, params)

## 3. Platform Schedules — Template Approval

Open the Template Approval expander.

- [ ] Status shows correctly (Active / Paused / Not configured)
- [ ] If a previous run exists, last run info shows (status emoji + time ago)
- [ ] Select a cadence (e.g., "Daily") and click "Save Schedule"
- [ ] Verify in DB: `SELECT * FROM scheduled_jobs WHERE job_type = 'template_approval' AND schedule_type = 'recurring'` — `brand_id` is NULL
- [ ] Toggle enabled/disabled works
- [ ] "Run Now" creates a one-time job
- [ ] Verify in DB: new row with `brand_id = NULL`, `schedule_type = 'one_time'`, `status = 'active'`

## 4. Platform Schedules — Template Scrape (Editable Params)

Open the Template Scrape expander.

- [ ] Has editable **Search URL** text input field
- [ ] Has editable **Max Ads** number input (1-500 range)
- [ ] Enter a search URL and save schedule
- [ ] Verify in DB: `parameters` JSONB contains `{"search_url": "...", "max_ads": ...}`
- [ ] Close and reopen the expander — saved values are pre-filled
- [ ] "Run Now" with a search URL creates a runnable one-time job

## 5. Active Jobs Tab

Navigate to **Active Jobs** tab.

- [ ] Platform jobs (brand_id NULL) show **"Platform"** in the brand column, not "Unknown"
- [ ] Brand-scoped jobs still show the correct brand name
- [ ] Each job row shows **"Created: [date]"** under the Next Run info
- [ ] Jobs with previous runs show **"Last: [status emoji] [date]"** in the Runs column
- [ ] Pause/Resume buttons work on platform jobs

## 6. Run History Tab

Navigate to **Run History** tab.

- [ ] Runs from platform jobs appear in the list
- [ ] Filtering by "All" brand still includes platform job runs
- [ ] Filtering by specific brand does NOT show platform job runs (correct — they have no brand)

## 7. Health Overview Tab

Navigate to **Health Overview** tab.

- [ ] Run Now buttons show 3 options: Meta Sync, Ad Classification, Asset Download
- [ ] Template Scrape button is **gone** from Health Overview

## 8. Migration Verification

In Supabase SQL editor:

```sql
-- All template jobs should have NULL brand_id
SELECT id, job_type, brand_id, status, schedule_type
FROM scheduled_jobs
WHERE job_type IN ('template_scrape', 'template_approval');
```

- [ ] All rows have `brand_id IS NULL`

## 9. End-to-End: Run a Platform Job

*Requires worker to be running.*

- [ ] Go to Platform Schedules → Template Approval → click "Run Now"
- [ ] Switch to Active Jobs tab — see the one-time job appear with "Platform" label
- [ ] Wait for worker to pick it up (~60s poll interval)
- [ ] Switch to Run History — see the run with status (completed/failed)
- [ ] If failed, check error message — should NOT be a brand_id/freshness error
- [ ] Job auto-archives after completion (status → 'archived', disappears from Active Jobs)

---

## Known Limitations

- Template scrape "Run Now" from Platform Schedules requires `search_url` in parameters — job will fail without it
- Freshness tracking is skipped for platform template_scrape jobs (by design — `dataset_status.brand_id` is NOT NULL)
- The Ad Scheduler page (`24_📅_Ad_Scheduler.py`) still has its own template_scrape/template_approval forms — these create brand-scoped jobs. Consider consolidating in a future pass.

---

## Pass Criteria

All checkboxes above are checked. No errors related to `brand_id`, freshness tracking, or "Unknown" brand labels.
