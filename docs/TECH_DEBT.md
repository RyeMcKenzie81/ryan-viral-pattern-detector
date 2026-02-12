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
**Complexity**: Medium (schema ready, need OAuth UI flow)
**Added**: 2025-12-20
**Updated**: 2026-02-10

**Context**: Currently using a single System User token for all ad accounts in the Business Manager. This works fine for internal brands but won't work for external client accounts.

**Status**: OAuth-ready schema columns now exist on `brand_ad_accounts` (`auth_method`, `access_token`, `token_expires_at`, `refresh_token`) via migration `2026-02-10_brand_ad_accounts_oauth.sql`. Manual ad account ID entry + validation (format, existence, access checks) works in onboarding. Validated accounts are auto-linked on import.

**Remaining work**:
1. OAuth flow implementation:
   - "Connect Facebook" button in brand settings
   - Redirect to Facebook OAuth dialog
   - Handle callback, store tokens per-brand
   - Token refresh logic (60-day tokens)

2. Service updates:
   - `_get_access_token(brand_id)` - Check DB first, fallback to env var
   - Token expiry checking and refresh

3. UI:
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

### 11. Audit `model_dump()` Calls for JSON Serialization Safety

**Priority**: Medium
**Complexity**: Low
**Added**: 2026-02-06

**Context**: A production bug in `regenerate_ad()` was caused by `product.model_dump()` preserving UUID objects that leaked into a Supabase JSONB column insert, raising `TypeError: Object of type UUID is not JSON serializable`. The fix was `model_dump(mode='json')` which serializes UUIDs to strings, datetimes to ISO strings, etc.

There are 70+ `model_dump()` calls across the codebase. Any that feed into JSONB columns, JSON serialization, or API responses should use `mode='json'`.

**What's needed**:
1. Audit all `model_dump()` calls — identify which ones flow into:
   - Supabase JSONB column inserts
   - `json.dumps()` / JSON serialization contexts
   - API response payloads
2. Change those to `model_dump(mode='json')`
3. Leave internal Python-to-Python calls as-is (they benefit from preserving native types)

**Known risky call**:
- `viraltracker/pipelines/ad_creation/nodes/fetch_context.py:55` — `product.model_dump()` in the ad creation pipeline (same pattern as the bug that was fixed)

**Reference**: `docs/archive/CHECKPOINT_2026-02-06_regenerate-ad-uuid-fix.md`

---

### 13. Improve Data Pipeline Infrastructure

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

### 14. Consolidate Template Job Scheduling Between Ad Scheduler and Pipeline Manager

**Priority**: Low
**Complexity**: Low-Medium
**Added**: 2026-02-07

**Context**: The Ad Scheduler page (`24_📅_Ad_Scheduler.py`) still has its own `template_scrape` and `template_approval` scheduling forms that create brand-scoped jobs. With the Platform Schedules sub-tab in Pipeline Manager (Checkpoint 009), these jobs are now intended to be platform-level (`brand_id=NULL`). Having two places to schedule the same job types creates confusion.

**What's needed**:
1. Remove or redirect `template_scrape` / `template_approval` forms from Ad Scheduler
2. Add a link or note pointing users to Pipeline Manager → Platform Schedules
3. Audit any other pages that create template jobs to ensure they use `brand_id=None`

**Reference**:
- Checkpoint: `docs/plans/data-pipeline-control-plane/CHECKPOINT_009.md`
- Testing plan: `docs/plans/data-pipeline-control-plane/TESTING_009_PLATFORM_SCHEDULES.md`

---

### 16. Landing Page Analyzer — Unit Tests

**Priority**: Low
**Complexity**: Medium
**Added**: 2026-02-09

**Context**: The Landing Page Analyzer (Phase 1) passed graph invariants review but has no unit tests. Key functions to test: `_parse_llm_json()`, `run_full_analysis()` partial failure handling, `_finalize_analysis()` denormalization, org_id filtering in `list_analyses()`. Also the Pydantic models in `models.py` are reference-only — could be wired up for LLM output validation when prompts stabilize.

**Files**: `viraltracker/services/landing_page_analysis/analysis_service.py`, `models.py`

---

### 17. Landing Page Analyzer — Blueprint Enhancements

**Priority**: Low
**Complexity**: Low-Medium
**Added**: 2026-02-09

**Context**: Phase 2 (Reconstruction Blueprint) is functional but has deferred enhancements:
- **Formatted doc export (docx):** Currently only JSON and Markdown exports. Could add docx/PDF for handing to copywriters.
- **Blueprint comparison view:** Side-by-side comparison of two brands from the same analysis.
- **Screenshot storage in Supabase storage:** Currently screenshots are passed as base64 directly to Gemini. Could store in Supabase storage for reference.
- **Re-run failed blueprints:** Button to retry a failed blueprint without re-selecting all options.
- **Unit tests for BrandProfileService:** Gap detection logic, offer variant fallback chain, graceful degradation when tables are missing.

**Files**: `viraltracker/services/landing_page_analysis/blueprint_service.py`, `brand_profile_service.py`

---

### 15. Platform Schedules — Pending QA

**Priority**: High
**Complexity**: N/A (testing only)
**Added**: 2026-02-07

**Context**: Platform Schedules sub-tab has been implemented and passed automated post-plan review, but needs manual QA before considering complete.

**Testing plan**: `docs/plans/data-pipeline-control-plane/TESTING_009_PLATFORM_SCHEDULES.md`

**Remove this item** after QA is complete.

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

---

### ~~14~~. Fix Ad Regeneration UUID Serialization Error

**Completed**: 2026-02-06
**Branch**: `main`
**Commits**: `a9cc789`, `d3eb5d8`

`regenerate_ad()` failed with `TypeError: Object of type UUID is not JSON serializable` when inserting prompt spec into Supabase JSONB column. Root cause: `product.model_dump()` preserves UUID objects. Fixed with `model_dump(mode='json')`. Also fixed error message visibility in Ad History — `st.rerun()` was hiding errors by reloading the page immediately after `st.error()`.

**Files**: `ad_creation_service.py` (line 1928), `22_📊_Ad_History.py` (rerun handler)
**Checkpoint**: `docs/archive/CHECKPOINT_2026-02-06_regenerate-ad-uuid-fix.md`

### 18. Brand Voice/Tone — Per-Offer-Variant and Per-Persona Overrides

**Priority**: Medium
**Complexity**: Medium
**Added**: 2026-02-10

**Context**: Brand voice/tone is currently stored at the brand level (`brands.brand_voice_tone`). This works when a brand has a single consistent voice, but breaks down when different landing pages need different tones — e.g., an empathetic/urgent tone for worried pet parents vs. an authoritative/scientific tone for health-conscious buyers. The tone often depends on the offer variant (different product angles) or the target persona (different audience segments).

**What's needed**:

1. **Database migrations** — Add voice/tone override columns:
   ```sql
   ALTER TABLE product_offer_variants
       ADD COLUMN IF NOT EXISTS voice_tone_override TEXT;
   COMMENT ON COLUMN product_offer_variants.voice_tone_override
       IS 'Optional voice/tone override for this offer variant. Takes precedence over brand-level voice_tone during blueprint generation.';

   ALTER TABLE personas_4d
       ADD COLUMN IF NOT EXISTS voice_tone_override TEXT;
   COMMENT ON COLUMN personas_4d.voice_tone_override
       IS 'Optional voice/tone override for this persona. Takes precedence over offer-variant and brand-level voice_tone.';
   ```

2. **Blueprint service** — Update `ReconstructionBlueprintService` to resolve voice/tone with a precedence chain:
   - Persona `voice_tone_override` (highest priority — if a persona is selected)
   - Offer variant `voice_tone_override` (if set)
   - Brand `brand_voice_tone` (fallback default)
   - This means a brand can set a general tone, an offer variant can override it for specific product angles, and a persona can further specialize it for the target audience.

3. **Content Gap Filler** — Update `GAP_FIELD_REGISTRY` to add:
   - `offer_variant.voice_tone` (`product_offer_variants.voice_tone_override`, `confirm_overwrite`)
   - `persona.voice_tone` (`personas_4d.voice_tone_override`, `confirm_overwrite`)
   - Keep existing `brand.voice_tone` as the brand-wide default
   - AI suggestions should consider the offer variant's product angle and persona's psychographic profile when synthesizing tone

4. **Brand Manager UI** — Add voice/tone fields to:
   - Offer variant editor section (with hint: "Leave blank to use brand default")
   - Persona detail view (with hint: "Leave blank to use offer variant or brand default")

5. **Gap fixer UX** — When the gap fixer detects `brand.voice_tone` is missing, show the resolution chain:
   - "This will set the brand-wide default tone. You can override per offer variant or persona later."
   - When saving to offer variant or persona level, show which level is being set

**Precedence chain summary**:
```
Persona voice_tone_override  →  Offer Variant voice_tone_override  →  Brand brand_voice_tone
(most specific)                                                        (most general)
```

**Files**: `blueprint_service.py`, `brand_profile_service.py`, `content_gap_filler_service.py`, Brand Manager UI, Persona UI

---

### Content Gap Filler — Integrate with Brand Ingestion Tools

**Priority**: Medium (partially done)
**Complexity**: Medium
**Added**: 2026-02-10
**Updated**: 2026-02-10

**Context**: The Content Gap Filler now uses heading-based markdown chunking (`chunk_markdown.py`) instead of hard truncation. Full LP content is always stored; only relevant chunks go to the LLM.

**Completed**:
- `chunk_markdown()` with heading split + size/keyword fallback strategies
- `pick_chunks_for_fields()` with keyword scoring and budget caps
- Removed all `[:3000]`, `[:6000]`, `[:12000]` truncations from extraction pipeline
- Content hash dedup for brand_landing_pages (avoids re-storing identical scrapes)
- `extract_from_raw_content()` + `extract_from_amazon_analysis()` for onboarding auto-fill
- Auto-fill from LP and Reviews in Client Onboarding (06_Client_Onboarding.py)
- 29 unit tests for chunking module

**Remaining work**:
1. Proactively run `check_available_sources()` during onboarding and surface which fields are already fillable
2. Deterministic evidence snippets using `extract_deterministic_snippet()` — wire into suggestion display
3. Integrate chunking into Brand Manager product setup (not just onboarding)

**Files**: `chunk_markdown.py`, `content_gap_filler_service.py`, `06_Client_Onboarding.py`

---

### 19. Replace `asyncio.get_event_loop()` in UI Pages

**Priority**: Low (only fails when Streamlit thread has no event loop)
**Complexity**: Trivial (find-and-replace)
**Added**: 2026-02-10

**Context**: Several UI pages use `asyncio.get_event_loop().run_until_complete()` to call async service methods. This fails in Streamlit's `ScriptRunner.scriptThread` which has no event loop, causing `"There is no current event loop"` errors. Already fixed in `06_Client_Onboarding.py` by switching to `asyncio.run()`.

**Remaining instances**:
- `viraltracker/ui/pages/21_🎨_Ad_Creator.py:2451` — `editable_ads = asyncio.get_event_loop().run_until_complete(...)`
- `viraltracker/ui/pages/21_🎨_Ad_Creator.py:2531` — `result = asyncio.get_event_loop().run_until_complete(...)`
- `viraltracker/ui/pages/47_🎬_Veo_Avatars.py:107` — `return asyncio.get_event_loop().run_until_complete(coro)`

**Fix**: Replace `asyncio.get_event_loop().run_until_complete(coro)` with `asyncio.run(coro)` in each instance.

**Files**: `21_Ad_Creator.py`, `47_Veo_Avatars.py`

---

### 21. Remove SQLite References from Archived Docs

**Priority**: Low
**Complexity**: Trivial
**Added**: 2026-02-11

**Context**: SQLite references exist only in archived docs (`docs/PYDANTIC_AI_MIGRATION_PLAN.md`, `docs/HANDOFF_TASK_1.11.md`). Zero Python code uses SQLite — the entire stack is Supabase/Postgres. These references are misleading to anyone reading the docs.

**What's needed**: Remove or update SQLite mentions in those two files. No code changes required.

---

### 23. Persona Synthesis — Fallback to `ad_creative_classifications`

**Priority**: Medium
**Complexity**: Low-Medium
**Added**: 2026-02-11

**Context**: Brand Research (`brand_ad_analysis`) is the canonical source for persona synthesis. For brands that have Meta API data but no Brand Research analysis yet, `ad_creative_classifications` can serve as a temporary fallback source. Scope: add fallback-only path in persona synthesis that reads from `ad_creative_classifications` when `brand_ad_analysis` has no rows for the brand. Once Phase 3 of the Meta API parity work is complete (Brand Research can analyze Meta API ads), this fallback becomes unnecessary for new brands.

**Files**: `viraltracker/services/persona_service.py`, `viraltracker/ui/pages/03_👤_Personas.py`

---

### 20. Meta API Ads as First-Class Data Source — Remaining Work

**Priority**: Medium (core implementation done, remaining items are polish/robustness)
**Complexity**: Low-Medium per item
**Added**: 2026-02-11
**Updated**: 2026-02-12

**Status**: Core 4-phase implementation complete (commit `65119c2`). Tool Readiness `any_of_groups`, ad_copy extraction, destination sync wiring, Brand Research parallel Meta methods, URL Mapping Meta integration all shipped. Amazon review re-scrape buttons added to Brand Research, Brand Manager, and Pipeline Manager (commit `5e92787`). All UI model references updated from Opus 4.5 to Opus 4.6.

**Known issue — destination sync bootstrap**: `discover_meta_urls()` depends on `meta_ad_destinations` being populated, which only happens during a meta_sync job (Step 4.5). For brands that haven't had a meta_sync since the deploy, the table is empty and URL discovery returns 0. **Fix**: either trigger a meta_sync job, or add a manual "Fetch Destinations" button to URL Mapping that calls `sync_ad_destinations_to_db()` on demand.

**Testing protocol** (use for QA after any changes to this subsystem):

1. **Meta-only brand** (ad account linked, no Ad Library URL):
   - Tool Readiness: tools show PARTIAL not BLOCKED, "Satisfied by: Meta ad account linked"
   - Trigger meta_sync → verify `ad_copy` populated in `meta_ads_performance`
   - Verify `meta_ad_destinations` populated after meta_sync (Step 4.5)
   - Verify `brand_landing_pages` created during auto-classification (`scrape_missing_lp=True`)
   - Brand Research: ad count shows Meta ads, copy/image/video analysis works
   - URL Mapping: Discover URLs finds URLs from `meta_ad_destinations`, bulk match writes to `meta_ad_product_matches`

2. **Scrape-only brand** (Ad Library URL, no ad account):
   - No regressions across all tools
   - `brand_ad_analysis` rows have `data_source='ad_library'`

3. **Both-sources brand**:
   - Tool Readiness says "Satisfied by: Ad Library URL, Meta ad account linked"
   - Brand Research shows combined ad counts
   - URL Mapping discovers from both sources, matches to both tables
   - No duplicate analysis rows

**Remaining work**:

1. **Destination sync bootstrap UX** — Add "Fetch Destinations" button to URL Mapping page that calls `sync_ad_destinations_to_db()` directly, so users don't have to wait for the scheduler. Low complexity.

2. **`get_matching_stats()` performance** — Currently fetches all `meta_ad_id` rows to COUNT(DISTINCT) in Python. For brands with very large Meta ad volumes, add a DB function or RPC. Low priority.

3. ~~**Copy analysis double-save**~~ — FIXED (commit `5e92787`). Added `skip_save=True` param to `analyze_copy()`, used by `analyze_copy_batch_meta()` so the Meta batch method handles its own save with correct FKs.

4. **Hook Analysis / Congruence Insights Meta path** — These tools read from `ad_creative_classifications` which already handles Meta ads. But their hard requirement `has_ad_data` now uses `any_of_groups`. Verify end-to-end that classifications feed correctly when only Meta data exists.

---

### 24. Persona Synthesis — Custom Data Source Combinations

**Priority**: Medium
**Complexity**: Medium
**Added**: 2026-02-12

**Context**: Persona synthesis currently has three separate paths that each consume a fixed, hard-coded set of data sources:

| Path | Ad Analyses | Amazon Reviews | Landing Page Data | Offer Variant Fields | Product Filter |
|------|-------------|----------------|-------------------|---------------------|----------------|
| Brand Research "From Analyses" | All (brand-wide) | Yes (brand-wide) | **No** | No | **No** (ignores product selector) |
| Brand Research "From Variant" | **No** | Yes (brand-wide) | **No** (URL only) | Yes | N/A |
| Personas Page "Generate" | Partial (`product_images` + `brand_research_synthesis`) | **No** | **No** | Yes (if selected) | Yes |

**Problems identified**:
1. **No path consumes landing page data** — `brand_landing_pages` has rich structured data (`persona_signals`, `copy_patterns`, `belief_first_analysis`, `objection_handling`, `benefits`, `testimonials`) but none of the three persona synthesis paths use it. Ironically, competitor persona synthesis DOES use `competitor_landing_pages`.
2. **"From Analyses" ignores the product selector** — passes only `brand_id` to the service, so synthesis always uses all 300+ analyses regardless of which product is selected in the UI.
3. **No way to mix data sources** — Users can't say "use ad analyses + landing page insights + Amazon reviews for this specific product." Each path is all-or-nothing with its fixed combination.
4. **Amazon reviews inconsistently included** — Paths 1 and 2 use them, Path 3 does not.

**What's needed**:
1. **Unified persona synthesis UI** with checkboxes for data sources:
   - Ad copy analyses (with option to filter by product)
   - Amazon review analyses
   - Landing page scraped content + belief-first analysis
   - Offer variant fields (if variant selected)
   - `ad_creative_classifications` (fallback for brands without Brand Research)
2. **Product-scoped filtering** — when a product is selected, filter ad analyses and landing page data to that product
3. **Landing page integration** — aggregate `persona_signals`, `copy_patterns`, and `belief_first_analysis` from `brand_landing_pages` into the synthesis prompt alongside existing ad analysis and Amazon review data
4. **Single service method** that accepts a configuration of which sources to include, replacing the three separate paths

**Related files**:
- `viraltracker/services/brand_research_service.py` — `synthesize_to_personas()` (line 2547), `synthesize_from_offer_variant()` (line 3042), `_integrate_amazon_review_data()` (line 2822)
- `viraltracker/services/persona_service.py` — `generate_persona_from_product()` (line 749)
- `viraltracker/ui/pages/05_🔬_Brand_Research.py` — `render_synthesis_section()` (line 1686)
- `viraltracker/ui/pages/03_👤_Personas.py` — persona generation form (line 838+)

---

### 25. Promote Landing Pages to Offer Variants from Brand Research / URL Mapping

**Priority**: Medium-High
**Complexity**: Medium
**Added**: 2026-02-12

**Context**: There is no UI flow to create an offer variant from a landing page. Offer variant creation happens exclusively on the Brand Manager page (page 02), either manually or via the "Discover Variants" tab (which only works with scraped Ad Library ads). For Meta-only brands, the Discover Variants tab shows "This brand has Meta API ads but no Ad Library scrapes" with no action.

Meanwhile, Brand Research's landing page section has rich scraped + analyzed data (`raw_markdown`, `benefits`, `persona_signals`, `objection_handling`, `belief_first_analysis`, etc.) and URL Mapping has product-URL associations — but neither page can turn a landing page into an offer variant.

**What's needed**:
1. **Brand Research — "Create Offer Variant" button** per landing page in the "View Scraped Landing Pages" section:
   - Pre-populate variant fields from `brand_landing_pages` data (benefits, pain_points from `persona_signals`, objections, etc.)
   - If belief-first analysis exists, extract mechanism (UMP/UMS), desires, sample hooks
   - Allow user to review/edit before saving
   - Call `ProductOfferVariantService.create_offer_variant()` (proper service-layer method)
   - Auto-assign to selected product (or prompt for product selection)

2. **URL Mapping — "Create Offer Variant" action** in the URL review queue:
   - When a URL is matched to a product, offer an action to also create an offer variant
   - If the URL exists in `brand_landing_pages` with scraped content, pre-populate from that data
   - If not yet scraped, offer to scrape-then-create

3. **Brand Manager Discover Variants — Meta-only path**:
   - When brand has Meta ads but no Ad Library scrapes, group `meta_ad_destinations` by URL
   - Use `meta_ads_performance.ad_copy` for messaging synthesis (instead of requiring scraped ad body text)
   - Falls back to the same `synthesize_messaging()` flow but with Meta ad copy as input

**Related files**:
- `viraltracker/ui/pages/05_🔬_Brand_Research.py` — `render_landing_page_section()` (line 1051)
- `viraltracker/ui/pages/04_🔗_URL_Mapping.py` — URL review queue section
- `viraltracker/ui/pages/02_🏢_Brand_Manager.py` — `render_offer_variant_discovery()` (line 753)
- `viraltracker/services/product_offer_variant_service.py` — `create_offer_variant()`, `analyze_landing_page()`

