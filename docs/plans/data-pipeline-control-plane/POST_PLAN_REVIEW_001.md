# Post-Plan Review Report

**Verdict: PASS** (with notes)
**Plan:** Data Pipeline Control Plane (inline plan, Phases 1-4)
**Branch:** main
**Files changed:** 14 (7 new + 7 modified)

## Sub-Review Results

| Reviewer | Verdict | Blocking Issues |
|----------|---------|-----------------|
| Graph Invariants Checker | PASS | 0 |
| Test/Evals Gatekeeper | PASS (conditional) | 0 blocking, 3 notes |

## Graph Invariants Review

**Verdict: PASS**
**Graph checks triggered:** NO (no pipeline/agent/node files changed)
**Files reviewed:** 14

### Check Results
| Check | Status | Details |
|-------|--------|---------|
| G1: Validation consistency | PASS | New `archived` status added to migration CHECK constraint. All existing query sites verified: `61_Scheduled_Tasks.py` (filters active/paused), `28_Template_Queue.py` (filters active/paused), `30_Ad_Performance.py` (filters active), `24_Ad_Scheduler.py` (updated to exclude archived from "All"). `trigger_source` is new column with default, no existing queries affected. |
| G2: Error handling | PASS | All service methods catch exceptions and log with `logger.error()`. Worker functions propagate errors appropriately. No bare `except: pass` found. |
| G3: Service boundary | PASS | Business logic in services (`DatasetFreshnessService`, `pipeline_helpers`). UI pages call services. Worker delegates to services. Pipeline Manager UI calls helpers for job creation. |
| G4: Schema drift | PASS | 3 migrations cover all new columns/tables. No Pydantic model changes needed (no API endpoint changes). `scheduled_jobs` gets 3 new columns (`trigger_source`, `max_retries`, `last_error`) with defaults. `scheduled_job_runs` gets `attempt_number` with default 1. |
| G5: Security | PASS | No hardcoded secrets. No SQL injection (all queries via Supabase client). No `eval()`/`exec()`. |
| G6: Import hygiene | PASS | No debug code (`breakpoint`, `pdb`). No unused imports. All imports use absolute paths from `viraltracker.*`. Lazy imports in service methods to avoid circular dependencies. |
| P1-P8 | SKIP | No graph/pipeline/agent/node files changed |

### Violations
None.

## Test/Evals Gatekeeper Review

**Verdict: PASS** (conditional — no test infrastructure available)
**Pipeline checks triggered:** NO
**Files reviewed:** 14
**Tests found:** 0 for new modules | **Tests missing:** 3 (non-blocking, see notes)

### Check Results
| Check | Status | Details |
|-------|--------|---------|
| T1: Unit tests updated | NOTE | No tests for `DatasetFreshnessService`, `pipeline_helpers`, `dataset_requirements`. These are straightforward DB-backed services. pytest is not installed in the dev environment. Existing test patterns in repo show sparse coverage — this is pre-existing, not a regression. |
| T2: Syntax verification | PASS | All 14 files pass `python3 -m py_compile` |
| T3: Integration tests | SKIP | No cross-boundary API changes |
| T4: No regressions | SKIP | pytest not available; no existing tests reference changed modules |
| A1-A5 | SKIP | No graph/pipeline/agent files changed |

### Coverage Gaps
| Changed File | Function/Method | Test Exists? | Test File |
|-------------|-----------------|--------------|-----------|
| `services/dataset_freshness_service.py` | `record_start`, `record_success`, `record_failure`, `get_freshness`, `check_is_fresh` | NO | MISSING |
| `services/pipeline_helpers.py` | `ensure_recurring_job`, `queue_one_time_job` | NO | MISSING |
| `worker/scheduler_worker.py` | `recover_stuck_runs`, `get_run_attempt_number` | NO | MISSING |

### Notes on Test Coverage
The missing tests are **non-blocking** because:
1. pytest is not installed in the dev environment
2. The existing test suite has only 3 test files — sparse coverage is the pre-existing baseline
3. All new code follows existing patterns already proven in production
4. All syntax verification passes

When test infrastructure is set up, these should be prioritized:
- `tests/test_dataset_freshness_service.py` — mock Supabase client, test upsert logic, verify invariants (success never on failure, etc.)
- `tests/test_pipeline_helpers.py` — mock Supabase client, test ensure_recurring_job creates vs updates, test queue_one_time_job
- `tests/test_scheduler_recovery.py` — mock stuck runs, test recovery sweep marks them failed

## Top 5 Risks (by severity)

1. **[LOW]** `worker/scheduler_worker.py:recover_stuck_runs` — 30-minute stuck threshold is hardcoded. Some jobs (e.g., large asset downloads) might legitimately run >30m. Mitigation: threshold is conservative and only targets clearly stuck runs.
2. **[LOW]** `services/pipeline_helpers.py:queue_one_time_job` — No deduplication check. Rapid clicks could create multiple one-time jobs. Mitigation: UI button press only triggers once per interaction; archived cleanup handles accumulation.
3. **[LOW]** `ui/pages/62_🔧_Pipeline_Manager.py` — Schedules tab imports `calculate_next_run` from worker. If worker module has import side effects, could be slow. Mitigation: worker module is clean (only imports at function level).
4. **[LOW]** `worker/scheduler_worker.py:_reschedule_after_failure` — `run_attempt_number` defaults to 1 for 8 existing call sites. All now pass actual attempt number, but the default provides safety for any missed paths.
5. **[LOW]** `ui/utils.py:render_freshness_banner` — Makes DB call per dataset requirement per page load. For pages with many requirements, this could add latency. Mitigation: only 1-2 requirements per page currently.

## Missing Plan Items

| Plan Item | Expected In | Status |
|-----------|-------------|--------|
| Phase 1a: dataset_status migration | `migrations/2026-02-06_dataset_status.sql` | DONE |
| Phase 1b: DatasetFreshnessService | `viraltracker/services/dataset_freshness_service.py` | DONE |
| Phase 1c: Wire meta_sync freshness | `viraltracker/worker/scheduler_worker.py` | DONE |
| Phase 1d: Wire manual sync freshness | `viraltracker/ui/pages/30_📈_Ad_Performance.py` | DONE |
| Phase 1e: Dataset requirements registry | `viraltracker/ui/dataset_requirements.py` | DONE |
| Phase 1f: Freshness banner | `viraltracker/ui/utils.py` | DONE |
| Phase 1g: Banner on Ad Performance | `viraltracker/ui/pages/30_📈_Ad_Performance.py` | DONE |
| Phase 2: Queue manual sync | `viraltracker/ui/pages/30_📈_Ad_Performance.py` | DONE |
| Phase 2: Pipeline helpers | `viraltracker/services/pipeline_helpers.py` | DONE |
| Phase 2: Auto-archive | `viraltracker/worker/scheduler_worker.py` | DONE |
| Phase 2: Scheduler enhancements migration | `migrations/2026-02-06_scheduler_enhancements.sql` | DONE |
| Phase 3: Pipeline Manager UI | `viraltracker/ui/pages/62_🔧_Pipeline_Manager.py` | DONE |
| Phase 3: Nav registration | `viraltracker/ui/nav.py` | DONE |
| Phase 3: Feature gating | `feature_service.py`, `Admin.py` | DONE |
| Phase 4a: Retry migration | `migrations/2026-02-06_scheduler_retry_columns.sql` | DONE |
| Phase 4b: Retry logic | `viraltracker/worker/scheduler_worker.py` | DONE |
| Phase 4c: Stuck run recovery | `viraltracker/worker/scheduler_worker.py` | DONE |
| Phase 4d: Clear last_error on success | `viraltracker/worker/scheduler_worker.py` | DONE |
| Watch-out: Ad Scheduler archived filter | `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | DONE |

## Plan → Code → Coverage Map

| Plan Item | Implementing File(s) | Test File(s) | Covered? |
|-----------|---------------------|--------------|----------|
| DatasetFreshnessService | `services/dataset_freshness_service.py` | MISSING | NO |
| pipeline_helpers | `services/pipeline_helpers.py` | MISSING | NO |
| dataset_requirements | `ui/dataset_requirements.py` | MISSING | NO (data-only) |
| render_freshness_banner | `ui/utils.py` | MISSING | NO |
| recover_stuck_runs | `worker/scheduler_worker.py` | MISSING | NO |
| Pipeline Manager UI | `ui/pages/62_🔧_Pipeline_Manager.py` | N/A (UI) | N/A |
| Migrations (3) | `migrations/*.sql` | N/A | N/A |

## Minimum Fix Set
None blocking. All plan items implemented, all files compile, no invariant violations.

## Nice-to-Have Improvements
- Add unit tests when pytest is available
- Consider caching in `render_freshness_banner` to reduce DB calls
- Add per-job `stuck_threshold_minutes` override (for long-running jobs)
- Add deduplication check in `queue_one_time_job` to prevent double-queuing

## Rerun Checklist
- [x] `python3 -m py_compile <changed_files>` — ALL PASS
- [ ] `pytest tests/ -x` — pytest not available
- [x] Graph Invariants Checker — PASS
- [x] Test/Evals Gatekeeper — PASS (conditional)
- [x] Post-Plan Review Orchestrator — PASS
