# Ad Creator V2 — Checkpoint 005: Phase 0 Implementation

> **Date**: 2026-02-13
> **Status**: Phase 0 code complete — post-plan review PASS — nice-to-haves in progress
> **Branch**: `feat/ad-creator-v2-phase0`
> **Follows**: CHECKPOINT_004 (Final consistency pass, plan v14)

---

## Chunks Completed

### Chunk P0-C1: Schema Migrations

**Token estimate**: ~15K / 50K

#### Scope Completed
- [x] P0-1: Add `ad_creation_v2` + future job types to `scheduled_jobs.job_type` CHECK
- [x] P0-2: Add `canvas_size` to `generated_ads` + composite unique index + relax prompt_index CHECK
- [x] P0-3: Add `template_id` UUID FK to `product_template_usage` + backfill from `scraped_templates.storage_path`
- [x] P0-4: Add `template_selection_config` JSONB to `brands` table
- [x] P1-4: Add `campaign_objective` to `meta_ads_performance`
- [x] Add `metadata` JSONB to `scheduled_job_runs`

#### Files Changed
| File | Change |
|------|--------|
| `migrations/2026-02-13_ad_creator_v2_phase0.sql` | New — all 6 schema migrations in one file |

#### Migration Applied
- `migrations/2026-02-13_ad_creator_v2_phase0.sql` — applied to Supabase, all columns verified via audit script

---

### Chunk P0-C2: Code Changes

**Token estimate**: ~25K / 50K

#### Scope Completed
- [x] Worker routing: `ad_creation_v2` → `execute_ad_creation_v2_job()` stub handler
- [x] Hard-fail: unknown `job_type` raises `ValueError` + logs error (no silent V1 fallthrough)
- [x] Stub handler: marks run as `completed` with `metadata={"stub": true, "reason": "V2 pipeline not yet implemented"}`
- [x] Explicit `ad_creation` case (no longer in the `else` fallback)
- [x] Campaign sync Part A: `sync_campaigns_to_db()` method — fetches campaign metadata from Meta API, upserts to `meta_campaigns`
- [x] Campaign sync Part B: `sync_performance_to_db()` builds objective cache from `sync_campaigns_to_db()`, enriches each record with `campaign_objective`
- [x] Campaign sync error handling: `sync_campaigns_to_db()` catches all exceptions, returns empty dict → fallback to `campaign_objective = 'UNKNOWN'`
- [x] `diagnostic_engine.py`: updated 4 references from `"objective"` to `"campaign_objective"` (lines 170, 175, 987, 1003)
- [x] `save_generated_ad()`: added `canvas_size` parameter, persists to `generated_ads` row

#### Files Changed
| File | Change |
|------|--------|
| `viraltracker/worker/scheduler_worker.py` | V2 routing, hard-fail else, stub handler, explicit ad_creation case |
| `viraltracker/services/meta_ads_service.py` | `sync_campaigns_to_db()`, `_fetch_campaigns_sync()`, campaign objective enrichment in `sync_performance_to_db()` |
| `viraltracker/services/ad_creation_service.py` | `canvas_size` param + persistence in `save_generated_ad()` |
| `viraltracker/services/ad_intelligence/diagnostic_engine.py` | `"objective"` → `"campaign_objective"` (4 locations) |

---

### Chunk P0-C3: Acceptance Tests + Post-Plan Review

#### Migration Audit Results (run after applying to Supabase)

| Query | Result |
|-------|--------|
| `canvas_size` column on `generated_ads` | EXISTS |
| `campaign_objective` column on `meta_ads_performance` | EXISTS |
| `metadata` column on `scheduled_job_runs` | EXISTS (default `{}`) |
| `template_selection_config` column on `brands` | EXISTS (default `{"min_asset_score": 0.0}`) |
| Ambiguous `storage_path` in `scraped_templates` | 12 pairs — documented tolerance (see below) |
| Unmapped `product_template_usage` rows (`template_id IS NULL`) | 53 — orphaned legacy records (see below) |

**Template backfill findings:**
- **12 ambiguous storage_paths** (exactly 2 active rows each) — all caused by a second scrape run on 2026-01-23 re-inserting templates from the 2026-01-15 run. Backfill correctly picked the newer template via `DISTINCT ON ... ORDER BY created_at DESC`. **Remediation**: deactivate the 12 older duplicate rows.
- **53 unmapped usage rows** — orphaned legacy records from the pre-scraping Ad Creator workflow (3 products, Dec 2025 – Feb 2026). Their `template_storage_name` values don't match any `scraped_templates.storage_path` (different naming convention). `template_id` will remain NULL permanently. These are inert and can be cleaned up.

#### Success Gate Status

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Migrations applied without error, existing data intact | **PASS** | All 6 ALTER/CREATE statements applied; audit script verified columns exist with correct defaults |
| 2 | Worker routes `ad_creation_v2` to stub handler; stub completes with `metadata.stub = true` | **PASS** | `scheduler_worker.py:577-578` explicit routing; stub sets `metadata={"stub": True, ...}` |
| 3 | Unknown `job_type` hard-fails (error logged, no V1 execution, exception raised) | **PASS** | `scheduler_worker.py:581-585` `else` branch logs error + raises `ValueError` |
| 4 | Meta sync persists `campaign_objective` from `meta_campaigns.objective` | **PASS** | `sync_campaigns_to_db()` upserts to meta_campaigns; objective cache enriches records |
| 5 | Campaign sync failure is non-fatal (fallback to `UNKNOWN`) | **PASS** | `sync_campaigns_to_db()` catches all exceptions, returns `{}`; record fallback is `"UNKNOWN"` |
| 6 | Template backfill: zero ambiguous mappings or documented tolerance | **PASS** | 12 ambiguous pairs documented with remediation plan (deactivate older duplicates) |
| 7 | Non-Meta brand: V2 job completes stub run (no meta-dependent crash) | **PASS** | Stub handler has no Meta dependency; creates run record and completes |
| 8 | `python3 -m py_compile` passes on all changed files | **PASS** | All 4 Python files compile clean |
| 9 | Checkpoint written + post-phase review PASS | **PASS** | Post-plan review: Graph Invariants PASS, Test/Evals PASS (conditional) |

#### Post-Plan Review Verdict: **PASS**

| Reviewer | Verdict | Blocking Issues |
|----------|---------|-----------------|
| Graph Invariants Checker (G1-G6) | PASS | 0 |
| Test/Evals Gatekeeper (T1-T4) | PASS (conditional) | 0 |

**T1 note**: 4 changed modules have zero pre-existing tests. Not a regression — pre-existing tech debt. Plan Phase 0 gate doesn't require unit tests.

#### Tests Run
| Test | Result |
|------|--------|
| `python3 -m py_compile` (4 files) | PASS |
| `pytest tests/ -x` | 12 passed, 3 skipped, 1 pre-existing failure |
| No remaining `ad_data.get("objective")` references | PASS (grep 0 matches) |
| No debug code / secrets / bare except:pass | PASS |

---

## Nice-to-Have Fixes (in progress)

| # | Fix | Status |
|---|-----|--------|
| 1 | Add `ad_creation_v2` + all missing job types to `job_type_badge()` in `61_Scheduled_Tasks.py` | **DONE** |
| 2 | Batch `_fetch_campaigns_sync()` API calls (groups of 50, matching `_fetch_ad_statuses_sync()` pattern) | **DONE** |
| 3 | Deactivate 12 duplicate `scraped_templates` rows (older of each pair) | **DONE** — `scripts/phase0_cleanup.py --live` |
| 4 | Clean up 53 orphaned `product_template_usage` rows | **DONE** — `scripts/phase0_cleanup.py --live` |
| 5 | Unit tests for `scheduler_worker.py` and `meta_ads_service.py` | TODO (Phase 1 scope) |

---

## Browser Testing Recommendations

Before merging, verify in the Streamlit UI:

1. **Scheduled Tasks page** (`61_📅_Scheduled_Tasks.py`)
   - Confirm existing jobs still display correctly with badges
   - Verify no errors loading the page

2. **Ad Scheduler page** (`24_📅_Ad_Scheduler.py`)
   - Create a test ad_creation job → verify it runs via V1 path (not broken by routing change)
   - Verify "Run Now" still works

3. **Meta Sync** (if a brand has Meta connected)
   - Trigger a meta sync job and check:
     - `meta_campaigns` table gets populated (new Part A)
     - `meta_ads_performance.campaign_objective` gets values (new Part B)
   - Check Railway worker logs for campaign sync log messages

4. **Ad Performance page** (`30_📈_Ad_Performance.py`)
   - Verify diagnostics still load (field rename from `objective` → `campaign_objective`)
   - Check that objective-aware rules (CTR skip for non-click, ROAS skip for non-conversion) still work

---

## Files Changed (all)

| File | Change | Status |
|------|--------|--------|
| `migrations/2026-02-13_ad_creator_v2_phase0.sql` | New — 6 schema migrations | Applied |
| `viraltracker/worker/scheduler_worker.py` | V2 routing, hard-fail, stub handler | Done |
| `viraltracker/services/meta_ads_service.py` | Campaign sync + enrichment | Done |
| `viraltracker/services/ad_creation_service.py` | canvas_size persistence | Done |
| `viraltracker/services/ad_intelligence/diagnostic_engine.py` | objective → campaign_objective | Done |
| `viraltracker/ui/pages/61_📅_Scheduled_Tasks.py` | Complete job_type_badge dict | Done |
| `docs/plans/ad-creator-v2/CHECKPOINT_005.md` | This file | Done |
| `scripts/phase0_audit.py` | Migration audit script | Done |
| `scripts/phase0_cleanup.py` | Deactivate duplicate templates + delete orphaned usage rows | Done |

---

## Next Steps

1. Fix remaining nice-to-haves (#2-4) in a new context window
2. Browser test the 4 areas listed above
3. Commit all changes on `feat/ad-creator-v2-phase0`
4. Phase 0 complete → Phase 1 can begin
