# Tech Debt & Future Improvements

This document tracks technical debt and planned future enhancements that aren't urgent but shouldn't be forgotten.

## How This Works

- **Add items** when you identify improvements that can wait but should be done eventually
- **Include context** - why it matters, rough complexity, and any relevant links
- **Remove items** when completed (or move to a "Completed" section if you want history)
- **Review periodically** when starting new work to see if anything should be prioritized

---

## Backlog

### 1. Meta Ads OAuth Per-Brand Authentication

**Priority**: Low (only needed for external client accounts)
**Complexity**: Medium-High
**Added**: 2025-12-20

**Context**: Currently using a single System User token for all ad accounts in the Business Manager. This works fine for internal brands but won't work for external client accounts.

**What's needed**:
1. Database migration - Add token columns to `brand_ad_accounts`:
   ```sql
   ALTER TABLE brand_ad_accounts ADD COLUMN IF NOT EXISTS
       access_token TEXT,
       token_expires_at TIMESTAMPTZ,
       refresh_token TEXT,
       auth_method TEXT DEFAULT 'system_user';
   ```

2. OAuth flow implementation:
   - "Connect Facebook" button in brand settings
   - Redirect to Facebook OAuth dialog
   - Handle callback, store tokens per-brand
   - Token refresh logic (60-day tokens)

3. Service updates:
   - `_get_access_token(brand_id)` - Check DB first, fallback to env var
   - Token expiry checking and refresh

4. UI:
   - Connection status indicator per brand
   - "Reconnect" button when token expires

**Reference**:
- Plan: `~/.claude/plans/rippling-cuddling-summit.md` (Phase 7)
- Checkpoint: `docs/archive/CHECKPOINT_meta_ads_phase6_final.md`

---

### 2. Pattern Discovery - Suggested Actions for Low Confidence

**Priority**: Medium
**Complexity**: Low-Medium
**Added**: 2026-01-06

**Context**: When Pattern Discovery finds clusters with low confidence scores (10-20%), users don't know what action to take. The system should suggest specific data sources to scrape to improve confidence.

**What's needed**:
1. Analyze which source types are missing from the pattern's `source_breakdown`
2. Show contextual suggestions in the Research Insights UI:
   - **Low confidence** → "Add more sources" with specific suggestions (Reddit, competitor ads, more reviews)
   - **Low novelty** → "Similar to existing angle X" with link
   - **High confidence + High novelty** → "🎯 Strong candidate for promotion!"

3. Potentially link to the relevant scraping pages (Competitor Research, URL Mapping, etc.)

**Example UI**:
```
💡 Low confidence (20%) - This pattern needs more evidence. Try:
  • Scrape Reddit discussions about joint supplements
  • Analyze competitor Facebook ads
  • Add more Amazon reviews
```

---

### 3. Ad Scheduler - Scraped Template Support

**Priority**: Medium
**Complexity**: Medium
**Added**: 2026-01-19

**Context**: The Template Recommendation system only integrates with Ad Creator because the Ad Scheduler uses uploaded templates from `reference-ads` bucket, not the scraped template library. Users can't leverage recommendations in scheduled runs.

**What's needed**:
1. Add "Scraped Template Library" as a template source option in Ad Scheduler
2. Port the template selection UI from Ad Creator (filters, grid, checkboxes)
3. Add recommendation filter (All / Recommended / Unused Recommended)
4. Update job execution to download from `scraped-templates` bucket

**Related files**:
- `viraltracker/ui/pages/24_📅_Ad_Scheduler.py`
- `viraltracker/services/template_recommendation_service.py`

---

### 4. Template Recommendations - Performance-Based Methodology

**Priority**: Low (needs performance data first)
**Complexity**: Medium
**Added**: 2026-01-19

**Context**: The `RecommendationMethodology.PERFORMANCE` enum exists but raises "not yet available" error. Once we have ad performance data (CTR, conversions, ROAS) linked to templates, we can recommend templates based on historical performance.

**What's needed**:
1. Track which template was used for each ad run (already done via `source_template_id`)
2. Link ad performance metrics (from Meta Ads) back to templates
3. Calculate template performance scores per product/niche
4. Implement `_score_templates_performance()` method in recommendation service

**Prerequisite**: Meta Ads performance data syncing must be working

---

### 5. Template Recommendations - Batch AI Analysis

**Priority**: Low
**Complexity**: Low
**Added**: 2026-01-19

**Context**: Currently the AI Match methodology analyzes templates sequentially (one Gemini call per template). For 100 templates, this can take several minutes.

**What's needed**:
1. Use `asyncio.gather()` to analyze multiple templates in parallel
2. Respect Gemini rate limits (add semaphore for concurrency control)
3. Show real-time progress as templates are scored

**File**: `viraltracker/services/template_recommendation_service.py` - `_score_templates_ai()` method

---

### 6. Template Recommendations - Auto-Generation on Template Approval

**Priority**: Low
**Complexity**: Low-Medium
**Added**: 2026-01-19

**Context**: Users must manually go to the Recommendations page to generate suggestions. Could automatically generate recommendations when new templates are approved in Template Queue.

**What's needed**:
1. Hook into `template_queue_service.finalize_approval()`
2. For each product with recommendations enabled, score the new template
3. If score > threshold, auto-add to recommendations
4. Notify user of new recommendations (optional)

**Consideration**: May want a per-product setting to opt-in to auto-recommendations

---

### 7. Phase 8: Row-Level Security (RLS) Policies

**Priority**: Low (security hardening, not blocking any features)
**Complexity**: High
**Added**: 2026-01-28

**Context**: Multi-tenant auth Phases 1-7 are complete. All data isolation is enforced at the Python/service layer. Phase 8 adds database-level RLS as defense-in-depth — Postgres policies that prevent cross-tenant data access even if application code has a bug.

**What's needed**:
1. Enable RLS on `brands`, `organizations`, `user_organizations` tables
2. Create `auth.user_organization_ids()` helper function
3. Create SELECT/INSERT/UPDATE/DELETE policies per table
4. Switch UI pages from `get_supabase_client()` (service key, bypasses RLS) to `get_anon_client()` (respects RLS)
5. Pass user access tokens to Supabase client per request
6. Extensive testing with multiple users/orgs + rollback plan

**When to prioritize**: Before onboarding external/untrusted tenants. Not needed while platform is internal-only.

**Reference**: `docs/plans/multi-tenant-auth/PLAN.md` (Phase 8 section)

---

---

### 9. Centralized Notification System

**Priority**: Medium
**Complexity**: Medium
**Added**: 2026-02-03

**Context**: Background operations (asset downloads, sync jobs, scheduled tasks) complete silently or show a toast that disappears on page refresh. Users have no way to see the history of what happened, forcing them to check Logfire manually.

**What's needed**:
1. Database table for notifications:
   ```sql
   CREATE TABLE notifications (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       organization_id UUID REFERENCES organizations(id),
       user_id UUID REFERENCES auth.users(id),  -- NULL = org-wide
       type TEXT NOT NULL,  -- 'success', 'error', 'warning', 'info'
       category TEXT,  -- 'asset_download', 'sync', 'scheduler', etc.
       title TEXT NOT NULL,
       message TEXT,
       metadata JSONB,  -- Additional context (counts, IDs, etc.)
       read_at TIMESTAMPTZ,
       created_at TIMESTAMPTZ DEFAULT now()
   );
   ```

2. NotificationService:
   - `create_notification(org_id, type, title, message, category, metadata)`
   - `get_unread_count(org_id, user_id)`
   - `get_notifications(org_id, user_id, limit, include_read)`
   - `mark_read(notification_id)` / `mark_all_read()`

3. UI Component:
   - Bell icon in sidebar/header with unread count badge
   - Dropdown/panel showing recent notifications
   - "View all" link to full notification history page
   - Click notification to see details + navigate to relevant page

4. Integration points:
   - Asset download completion → notification with counts
   - Sync job completion → notification with summary
   - Scheduler job results → notification with success/failure
   - Error conditions → notification with error details

**Benefit**: Users can see what happened without checking logs, and have a history of all background operations.

---

### 10. Deep Video Analysis - Agent Tool Visibility & Reporting

**Priority**: Medium
**Complexity**: Medium
**Added**: 2026-02-04
**Partially completed**: 2026-02-05 (UI integration done, agent tools & reporting remain)

**Context**: The Deep Video Analysis feature now has UI visibility on the Ad Performance page (expandable per-ad sections showing classification, congruence components, hooks, transcript, storyboard, claims). Remaining work:

**What's needed**:

1. **Agent tool updates**:
   - Update `/congruence_check` to show per-dimension results when `congruence_components` exist
   - Or create new `/deep_congruence` tool for detailed analysis
   - Add hook analysis tool (`/hook_analysis` or `/top_hooks`)

2. **Reporting**:
   - Congruence summary across brand (how many aligned vs weak vs missing)
   - Hook performance dashboard (which hooks convert best)
   - Standalone "Hook Analysis" page

**Reference**:
- Plan: `~/.claude/plans/squishy-tinkering-snowflake.md`
- Checkpoints: `docs/plans/deep-video-analysis/CHECKPOINT_*.md`

---

### 11. Improve Data Pipeline Infrastructure

**Priority**: Medium
**Complexity**: Medium-High
**Added**: 2026-02-04

**Context**: The current data pipeline (Meta Ads sync, asset downloads, classification jobs) works but could be more robust, observable, and maintainable. As we scale to more brands and ads, the infrastructure needs improvement.

**What's needed**:
1. **Pipeline orchestration**: Consider using a proper workflow engine (Temporal, Prefect, or Airflow) instead of cron-based scheduler_worker
2. **Better retry logic**: Exponential backoff, dead letter queues for failed jobs
3. **Observability**: Pipeline-specific dashboards, SLOs, alerting on failures
4. **Incremental processing**: Track high-water marks to avoid reprocessing
5. **Data validation**: Schema validation between pipeline stages
6. **Parallelization**: Process multiple brands/ads concurrently where possible

**Current pain points**:
- Scheduler worker polls every 60s, no event-driven triggers
- Failures require manual intervention
- Hard to see pipeline health at a glance
- Asset downloads and classifications are sequential

---

## Completed

### ~~8~~. Fix CPC Baseline Per-Row Inflation

**Completed**: 2026-02-05
**Branch**: `feat/veo-avatar-tool`

Refactored `_compute_cohort_baseline()` in `baseline_service.py` to aggregate raw counts per-ad before computing derived ratio metrics (CPC, CPM, CTR, cost-per-purchase, cost-per-ATC). Previously used per-row daily values which inflated baselines on low-volume days (e.g., 1 click + $80 spend = $80 CPC). Now computes `total_spend / total_clicks` per ad, matching the diagnostic engine's correct approach.

---

### ~~10 (partial)~~. Deep Video Analysis - UI Integration

**Completed**: 2026-02-05
**Branch**: `feat/veo-avatar-tool`

Added expandable "Deep Analysis" sections to Ad Performance page for Top and Bottom performers. Shows classification data (awareness level, format, congruence score), per-dimension congruence components, hook analysis (spoken/overlay/visual), benefits, angles, claims, full transcript, and storyboard. Uses batch-fetch (2 queries for all ads) to avoid N+1.

---

### ~~12~~. Decouple Asset Downloads as Standalone Job

**Completed**: 2026-02-05
**Branch**: `feat/veo-avatar-tool`

Added `asset_download` as a standalone scheduled job type. Created `execute_asset_download_job()` in scheduler_worker, `_render_asset_download_form()` in Ad Scheduler UI, and DB migration for CHECK constraint. Also fixed the `max_downloads` kwarg bug in meta_sync Step 4 (item 13).

---

### ~~13~~. Fix meta_sync Asset Download Bug

**Completed**: 2026-02-05 (fixed as part of item 12)

Changed `max_downloads=20` to `max_videos`/`max_images` with configurable job params.

---

### ~~12 (original)~~. Decouple Ad Classification from Chat Analysis

**Completed**: 2026-02-05
**Branch**: `feat/veo-avatar-tool`

Background `ad_classification` job type pre-computes classifications via scheduler. Existing dedup logic (`_find_existing_classification` by `input_hash` + `prompt_version`) means `full_analysis()` automatically reuses fresh cached results. Chat analysis goes from 25+ min to seconds.

**What was built**:
- `execute_ad_classification_job()` in scheduler_worker — standalone job handler
- `_run_classification_for_brand()` — shared helper (used by standalone job + auto_classify chain)
- `auto_classify` option in `meta_sync` job — non-fatal chaining after sync
- `BatchClassificationResult` model — accurate new/cached/skipped/error breakdown
- "Run Now" buttons for all scheduler job types (classification, template scrape, ad creation)
- Ad Scheduler UI form for `ad_classification` with brand selector, max_new/max_video/days_back
- Source granularity: `gemini_light_stored` vs `gemini_light_thumbnail` (tracks image provenance)
- Skip pattern for image ads without available media (`skipped_missing_image`)
- Removed copy-only fallback and garbage-dict error fallback

