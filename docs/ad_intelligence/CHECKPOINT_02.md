# Ad Intelligence Agent - Checkpoint 02

**Date:** 2026-02-02
**Branch:** `feat/veo-avatar-tool`
**Status:** Two bugs fixed, ready for re-test. Scheduler resilience fix in progress.

## Bugs Fixed Since Checkpoint 01

### 1. "0 Active Ads" Bug — FIXED ✅
**Root cause:** `get_active_ad_ids` uses a 7-day window (`active_window_days=7`) by default. Wonder Paws had no data in the last 7 days (last sync was Jan 27 before the scheduler crashed). The Ad Performance page showed 156 ads because it uses a 30-day window.

**Fix:** `full_analysis()` in `ad_intelligence_service.py` now falls back to the full `days_back` window (default 30) if the narrow 7-day window returns no ads. Also added debug logging for row counts in `helpers.py`.

**Files changed:**
- `viraltracker/services/ad_intelligence/ad_intelligence_service.py` — Added fallback logic at line 174
- `viraltracker/services/ad_intelligence/helpers.py` — Added query/row-count logging

### 2. Classifier Rate Limiting — FIXED ✅
**Root cause:** `_classify_with_gemini()` created a new `GeminiService()` per call, bypassing the configured rate limiter and usage tracking from AgentDependencies.

**Fix:** Shared `GeminiService` instance (with rate limiting + usage tracking) is now passed from `AgentDependencies` → `AdIntelligenceService` → `ClassifierService`.

**Files changed:**
- `viraltracker/services/ad_intelligence/classifier_service.py` — Accept `gemini_service` in `__init__`, use it in `_classify_with_gemini()`
- `viraltracker/services/ad_intelligence/ad_intelligence_service.py` — Accept and pass through `gemini_service`
- `viraltracker/agent/dependencies.py` — Pass `gemini` to `AdIntelligenceService(supabase, gemini_service=gemini)`

**Commit:** `846a313` — pushed to `feat/veo-avatar-tool`

## Scheduler Bug Found (IN PROGRESS)

### 3. Scheduler Stops Recurring Jobs on Failure
**Root cause:** When any scheduled job fails, the exception handler marks the job_run as failed but **never recalculates `next_run_at`** on the parent `scheduled_jobs` record. Since the handler clears `next_run_at` to NULL at the start (to prevent duplicate execution), the job is permanently stuck.

**Affected:** All 5 job types (ad_creation, meta_sync, scorecard, template_scrape, template_approval).

**Impact:** Wonder Paws' daily meta_sync crashed on Jan 27 with a `RunResult` import error and never ran again. This is why there was no fresh data for the ad intelligence analysis.

**Fix in progress:** Added `_reschedule_after_failure()` helper in `scheduler_worker.py`. Need to call it from all 5 exception handlers.

**File:** `viraltracker/worker/scheduler_worker.py`
- Helper added at line ~1549
- Exception handlers to update: lines ~859 (ad_creation), ~1061 (meta_sync), ~1276 (scorecard), ~1534 (template_scrape), ~1722 (template_approval)

### 4. RunResult Import Error (Jan 27 scheduler crash)
**Error:** `cannot import name 'RunResult' from 'pydantic_ai.result'`
**Context:** Scheduler worker Docker container (Python 3.11) has a pydantic-ai version where `RunResult` was renamed to `AgentRunResult`. The Streamlit app doesn't hit this because it runs in a different environment.
**Status:** Root cause is pydantic-ai version mismatch in the deployed scheduler container. The `RunResult` reference was previously fixed in `services/agent_tracking.py` but the scheduler container may have stale deps.

## What's Next
1. **Finish scheduler fix** — Call `_reschedule_after_failure()` from all 5 exception handlers
2. **Restart Streamlit app** and re-test "Analyze the Wonder Paws ad account"
3. **Continue testing plan** (steps 2-10 in `TESTING_PLAN.md`)
4. **Fix scheduler container** — Rebuild with correct pydantic-ai version
5. **Write unit tests** for golden test cases (1-16)
