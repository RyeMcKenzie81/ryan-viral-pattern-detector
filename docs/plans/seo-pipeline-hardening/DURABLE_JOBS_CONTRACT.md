# Durable SEO Jobs — Execution Contract (R1 deliverable)

**Status:** Design contract, NOT built. Written 2026-06-09 alongside the dead-graph
deletion (hardening plan §11 R1), so the API-foundation-phase build starts from a
spec instead of from scratch. Locked decisions: plan §11 (R1) + §4.

**What this replaces:** the in-process daemon-thread execution inside
`SEOWorkflowService` (`threading.Thread` + `asyncio.run` + `Semaphore(3)`). The
imperative phase logic is KEPT; only the execution host moves to the scheduler
worker. The pydantic-graph orchestrator was deleted (zero callers) — this contract
is the durable-execution design that replaces what the graph would have provided.

**Why a contract now:** Codex outside-voice (eng review round 2): "'move execution
later' punts the hardest design work — document phase names, checkpoint payload
shape, idempotency keys, retry semantics, cancellation, approval state BEFORE
deleting the graph."

---

## 1. Execution model

```
UI / API / MCP                     scheduler worker (pool)
     |                                   |
start_run(config) ──► seo_workflow_jobs row (status=pending)
     |                                   |  claim_next_job (atomic, advisory-locked)
get_status(job_id) ◄── progress JSONB    |  execute from last completed phase
     |                                   |  persist checkpoint after EVERY phase
approve(job_id, checkpoint) ──► status pending(+approval cleared)
cancel(job_id)     ──► status cancelled  |  worker observes between phases
```

- The "start" call ONLY writes the job row. No thread spawn. A stateless caller
  (Streamlit, REST, MCP tool) can start / poll / approve / cancel across restarts.
- The worker executes via the existing claim path (`claim_next_job` RPC + run rows
  in `scheduled_job_runs`) — the same machinery proven by `seo_publish` (2,700+
  runs) — either by registering `seo_one_off` / `seo_cluster_batch` as job types,
  or by teaching the claim query to also read `seo_workflow_jobs`. Prefer the
  former: one queue, one claim path, one recovery owner.

## 2. Phase names (checkpoint boundaries)

Resume points match LLM-cost boundaries — never re-run a completed expensive phase:

| # | Phase | Expensive? | Idempotency anchor |
|---|-------|-----------|---------------------|
| 1 | `validate` | no | pure read |
| 2 | `keyword` | no | keyword row reused on resume (dedup by project+keyword) |
| 3 | `create_article` | no | `existing_article_id` short-circuits (regen wipe lives here) |
| 4 | `competitor` | scrape | persisted to `config`/article row before phase completes |
| 5 | `phase_a` (outline) | LLM | `phase_a_output` saved (raise-on-save, B1) |
| 6 | `phase_b` (write) | LLM | `phase_b_output` saved |
| 7 | `phase_c` (optimize) | LLM | `phase_c_output` + `content_html` saved |
| 8 | `images` | LLM/Gemini | `image_metadata` + `image_status` saved |
| 9 | `checklist_schema` | cheap LLM | `schema_markup` saved |
| 10 | `finalize` | no | status → `qa_passed` (eval/publish take over from here) |

`PAUSE_POINTS` (`phase_a`, `phase_b`, `pre_publish_checklist`) stay valid: they are
checkpoints whose post-state is `paused` + `awaiting_approval`.

## 3. Checkpoint payload (persisted in `seo_workflow_jobs.progress` JSONB)

```json
{
  "current_step": "phase_b",
  "completed_steps": ["validate", "keyword", "create_article", "competitor", "phase_a"],
  "article_id": "uuid",
  "keyword_id": "uuid",
  "awaiting_approval": null,
  "attempt_of_step": 1,
  "last_checkpoint_at": "iso"
}
```

Rules:
- Write the checkpoint AFTER the phase's outputs are durably saved (the phase's
  DB write is the source of truth; the checkpoint is the index into it).
- Resume = skip every step in `completed_steps`; re-enter `current_step` from its
  idempotency anchor. Phase outputs already saved make re-entry a no-op read.
- The existing reaper/heal machinery covers the host: a crashed run is reset by
  `recover_stuck_runs_v2`; an orphaned recurring row by
  `heal_orphaned_recurring_jobs`; resume happens on the next claim.

## 4. Idempotency keys

- Job dedup: existing partial unique index on `seo_workflow_jobs`
  (`idx_seo_workflow_jobs_dedup_keyword`) — same keyword can't double-run.
- Phase re-entry: each phase checks its own output column first
  (`phase_a_output IS NOT NULL` ⇒ skip). Wipes are explicit (regenerate) and
  happen inside the running job, never at enqueue time.
- Side-effectful integrations: images upsert by `(article_id, slot)`; publish is
  guarded by `cms_article_id` (update-not-create when present); interlink writes
  are idempotent per D5.2.

## 5. Retry / failure semantics

- Per-phase failure marks the run failed; `_reschedule_after_failure` applies
  backoff (5/10/20m, cap 60m, max_retries). Resume re-enters the FAILED phase
  only — completed phases never re-run.
- Poison-pill guard: `attempt_of_step` >= 3 ⇒ job `failed`, surfaced in
  Exceptions UI with the existing fix buttons (regenerate / re-optimize / etc.).
- LLM-output-empty raises (B1 raise-on-save already shipped) so a bad phase can
  never checkpoint as complete.

## 6. Cancellation & approval

- `cancel(job_id)`: status → `cancelled`; the worker checks between phases (same
  contract as today's `_is_cancelled`) — no mid-LLM-call abort guarantee.
- `approve(job_id, checkpoint, payload)`: validates `awaiting_approval ==
  checkpoint`, merges payload (e.g. outline edits) into config, clears the flag,
  sets status `pending` so any worker can claim the resume. Approval is data,
  not a callback — survives restarts, works over MCP.

## 7. Concurrency

- The in-process `Semaphore(3)` is replaced by claim-time caps (the worker pool
  already enforces global / per-job-type / per-brand / brand+type caps in
  `claim_next_job`): set `seo_one_off` per-brand cap = 3.
- Lease/heartbeat: run rows already carry `started_at` + per-job-type runtime
  limits (`job_runtime_limits`) consumed by `recover_stuck_runs_v2` — that IS the
  lease. No second mechanism.
- KNOWN CONSTRAINT (verified live 2026-06-09): async handlers doing sync
  Supabase/LLM work serialize the worker event loop — pool slots do not give true
  concurrency for sync work. The SEO job handlers must run their phase bodies via
  `asyncio.to_thread` (or the dispatcher gains a thread-per-job mode) BEFORE
  per-brand cap 3 means anything. This is the §4 concurrency work item.

## 8. MCP surface (later phase, shape only)

`seo.start_run(config) -> job_id` · `seo.get_status(job_id)` ·
`seo.approve(job_id, checkpoint, payload)` · `seo.cancel(job_id)` ·
`seo.list_runs(brand_id, status)` — thin wrappers over the same five operations
the UI uses. No new execution semantics.

## 9. Migration path (when built)

1. Register worker handlers `seo_one_off` / `seo_cluster_batch` that call the
   EXISTING `SEOWorkflowService._execute_*` bodies refactored to (a) take a
   resume point, (b) checkpoint after each phase, (c) run under
   `asyncio.to_thread`.
2. Feature-flag the host per brand (`brand_content_policies.worker_execution`):
   start calls write scheduled_jobs rows instead of spawning threads.
3. Burn-in on one brand → flip default → delete the thread-spawn path.
