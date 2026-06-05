# SEO Pipeline Hardening Plan

**Status:** Draft for review — 2026-06-04
**Author:** Ryan + Claude (post-merge hardening review)
**Eng review:** Not yet run. The architectural section (§4) is the part to run `/plan-eng-review` against before building. The "do-now" reliability fixes (§3) are low-risk and ship without review.

---

## 1. Context

After porting the SEO content pipeline and shipping a run of fixes (markdown-in-`<pre>`,
word_count persistence, the P0 re-evaluation bug, three P1s, and image product-scale),
we did a full walkthrough of the pipeline + eval gate looking for reliability,
correctness, and observability gaps. This doc captures that backlog so the context
isn't lost, and frames the one architectural decision worth reviewing before we build:
**how the pipeline executes, and how that maps to a future MCP / remote-agent surface.**

### Verified production flow

```
discover -> create keyword + article
  -> Phase A (outline) -> Phase B (write) -> Phase C (optimize + frontmatter)
  -> images (deferred) -> pre-publish checklist -> schema -> status=qa_passed
       |  [scheduler job: seo_content_eval, recurring]
  auto-fix (Tier1 deterministic + Tier2 AI) -> evaluate_article
       -> QA checks + checklist + image-eval -> verdict -> eval_passed / eval_failed
       |  if policy.publish_enabled -> enqueue to seo_publish_queue
  [scheduler job: seo_publish] get_due_articles -> publish_article -> Shopify (live)
       |  chained one-time job
  seo_auto_interlink (suggest / auto-link / related section)
  [scheduler job: seo_status_sync] reconciles draft/live from Shopify
```

### Two facts that shape everything below (both verified)

- **The pydantic-graph orchestrator (`orchestrator.py`) is dead code.** `run_seo_pipeline` /
  `resume_seo_pipeline` are referenced nowhere outside their own module. Production runs
  entirely through the threaded `SEOWorkflowService` path.
- **Autopilot publish is off unless `publish_enabled=true`** in `brand_content_policies`;
  default policy is off with `max_warnings_for_auto_publish=0` (zero tolerance).

---

## 2. Hardening backlog (full)

Severity reflects production impact. "Verified" = confirmed against current `main` code.

### P0 — silent data loss (verified)
- **B1. Phase output save is swallowed.** `content_generation_service._handle_api_mode`
  wraps the `seo_articles` update in `try/except` that logs and continues. Generation
  succeeds, the DB write fails, the function still returns the content as success and the
  job advances to `qa_passed` with an empty `phase_*_output`. Same failure class as the
  empty-body bug we fixed, one layer down — and it bypasses the empty-output guard (which
  checks the LLM text, not the write). Same pattern in `seo_image_service._save_image_data`
  (images uploaded to storage but never recorded → article renders imageless, regeneration
  can't find metadata). **Fix:** raise on save failure so the job fails and stays fixable.

### P1 — operational reliability (verified)
- **B2. No reaper for stuck `publishing` rows.** If the worker crashes between
  `mark_publishing` and `mark_published`, the queue row is stuck in `publishing` forever and
  is never retried. **Fix:** scheduled reaper resets `publishing` rows older than N minutes
  back to `queued` (with retry_count++).
- **B3. `cleanup_stale_jobs` only runs on Streamlit page load** (`53_🚀_SEO_Workflow.py:84`),
  never scheduled. A job orphaned at `running` (process restart mid-job) stays stuck until a
  human visits that page. **Fix:** run it as a recurring scheduler job.
- **B4. No crash/restart resume.** The threaded path holds all state in memory in a daemon
  thread; a restart orphans in-flight articles at partial status. **Light fix:** B2+B3 reaper
  + status reset. **Heavy fix:** per-phase checkpoint/resume (see §4).
- **B5. Publish retries have no backoff.** `mark_failed` re-queues with the same `publish_at`,
  so a transient Shopify outage produces hammer-retries within a run. **Fix:** advance
  `publish_at` on retry.

### P1 — eval correctness
- **B6. Two divergent word counts.** QA computes its own `len(plain_text.split())` while the
  stored `word_count` uses `_compute_word_count` (HTML-rendered). They can disagree. **Fix:**
  QA consumes `_compute_word_count`.
- **B7. Threshold inconsistency between QA and the pre-publish checklist** (reported by read,
  confirm during build): QA wants SEO title 50–60 / meta 150–160; checklist accepts 30–70 /
  70–200. An article can pass one and warn on the other. **Fix:** single brand-configurable
  source of truth.
- **B8. Image-eval fails open.** Image fetch/parse/API errors return `None` and the image is
  *skipped*, not failed — an article can publish with no image validation if the CDN hiccups.
  Empty `image_eval_rules` means images pass trivially even when eval is "enabled." **Fix:**
  treat fetch/parse failure as a blocking warning (or retry); warn when rules are empty but
  eval is on.

### P2 — observability (biggest structural gap)
- **B9. No autopilot health signal at all.** No "N articles stuck in `optimized`/`publishing`
  for >X hours," no heartbeat, no alert on repeated failures. This is what would have surfaced
  the P0 re-eval bug weeks earlier. **Fix:** a health query + daily/Slack summary (stuck
  counts, failed evals, failed publishes, orphaned jobs).
- **B10. Interlink failures are silent** — published article + failed interlink job = article
  with no internal links, no signal.
- **B11. Untracked spend** on embedding calls (interlinking) and cluster research.

### P2 — cleanup / correctness
- **B12. Delete the dead graph orchestrator** (or make it the real path — see §4; don't keep both).
- **B13. Keyword matching uses substring** (`"key"` matches `"keys"`) — add word boundaries.
- **B14. Concurrent `seo_content_eval` runs could double-process** the same `qa_passed`
  article (no claim/lock).

---

## 3. "Do now" — ships without eng review  ✅ DONE (branch: seo-pipeline-hardening)

Low-risk, independent, well-understood. One branch, one PR.

1. ✅ **B1 (raise-on-save):** `_handle_api_mode` (content_generation) and `_save_image_data`
   (seo_image) now raise on DB write failure instead of log-and-continue. Tests assert a failed
   save raises.
2. ✅ **B2 + B3 (reaper + auto-cleanup):** new `PublishQueueService.reap_stuck_publishing()`
   resets `publishing` rows older than 15 min back to `queued`. A worker helper
   `_run_seo_pipeline_maintenance()` runs it + `cleanup_stale_jobs()` at the start of BOTH the
   `seo_publish` and `seo_status_sync` recurring jobs — so it runs automatically wherever the
   autopilot is active, no separately-scheduled job required.
3. ✅ **B5 (publish retry backoff):** `mark_failed` advances `publish_at` (30 min × retry_count)
   on retry so transient outages don't cause hammer-retries.
4. ✅ **B6 (unified word count):** QA `_check_word_count` now delegates to
   `ContentGenerationService._compute_word_count` (single source of truth with the stored
   `word_count`).

Explicitly NOT in the do-now set: B4-heavy (resume), B7 (threshold consolidation — needs a
config decision), B8 (eval fail-open policy — needs a product call on fail-open vs fail-closed),
B9-B11 (observability layer — its own effort), B12/B14 (architectural — §4).

### Noted while here (NOT fixed — separate follow-up)
- `test_qa_validation_service.py` has 5 pre-existing failures (TestHeadingStructure x3,
  TestKeywordPlacement x2) that are red on `main`, unrelated to the do-now changes. Likely
  test-drift or related to B13 (substring keyword matching). Worth a focused pass; deliberately
  left out of this reliability PR to keep it reviewable.

---

## 4. Architectural decision — execution model + MCP-readiness (run /plan-eng-review on this)

### The question
We have one dead orchestration path (pydantic-graph) and one live one (threaded
`SEOWorkflowService`). Separately, the chat-first roadmap targets an **MCP tool** (later
phase) so OpenClaw / Claude can drive SEO work remotely. What execution model do we commit to?

### What MCP actually needs (and what it does NOT)
MCP is an *interface*. It needs the layer beneath it to provide:
1. Discrete, fast-returning operations: `start_run() -> job_id`, `get_status(job_id)`,
   `approve_checkpoint(...)`, `regenerate(...)`.
2. DB-persisted state so any stateless call can answer / resume.
3. Long work in the background; caller polls.

MCP does **not** require a pydantic graph. The threaded `SEOWorkflowService` is actually
closer to MCP-ready (it already persists `seo_workflow_jobs` and returns job IDs). So the
graph is not worth keeping "for MCP."

### The real fork
Neither path is ideal today. The live path runs work as an **in-process daemon thread**
inside the web process (`asyncio.run` in a spawned thread, semaphore-capped). It supports
human-pause checkpoints (`step_through` / `PAUSE_POINTS`) but has **no crash/restart resume**.
For a remote agent driving long jobs, you want **worker-driven durable execution**: the
"start" call writes a job row; the **scheduler worker** executes it (exactly how `seo_publish`
already works), with checkpoint/resume. Then a stateless MCP call can start, poll, and resume
across restarts.

### Options
- **Option A — Imperative, worker-driven (recommended).** Keep `SEOWorkflowService`'s
  imperative logic, but move execution from in-process daemon threads to scheduler-worker
  job rows, and add per-phase checkpointing (persist after each phase; resume from last
  completed phase). Delete the graph. Lowest risk, builds on what works and what `seo_publish`
  already proves.
- **Option B — Resurrect the pydantic graph** for its durable-resume + checkpoint-native
  semantics; run it on the worker; delete the threaded duplication. Nicer checkpoint model,
  bigger lift, currently unproven in prod.
- **Option C — Status quo + reapers only.** Keep daemon-thread execution, lean on B2/B3
  reapers. Cheapest, but never truly restart-safe; weakest MCP story.

### Recommendation
**Option A.** Delete the dead graph now (B12). When the API-foundation / MCP phase arrives,
move one-off + cluster execution onto worker-driven durable jobs with checkpoint/resume. This
keeps the imperative logic we've already hardened, reuses the proven `seo_publish` worker
pattern, and gives MCP exactly the start/poll/resume shape it wants — without carrying two
orchestration paths.

### Roadmap caveat
Per `docs/plans/chat-first-roadmap`, MCP is a later phase (Ops Copilot → API foundation →
Next.js → MCP). Do **not** build MCP now. Make the consolidation decision *aware* of it so we
don't paint ourselves into a corner, and do the actual worker-driven move as part of the
API-foundation phase.

### Open questions for the eng review
1. Option A vs B — is durable-resume worth resurrecting the graph, or is imperative +
   per-phase checkpoint enough?
2. Checkpoint granularity: per-phase (A/B/C/images) vs finer. Where are the natural resume
   points given LLM cost (don't re-run an expensive phase on resume)?
3. Execution host: do one-off/cluster jobs move fully to the scheduler worker, or stay
   in-process with a durable job row + reaper as the bridge?
4. Concurrency model on the worker (today: in-process semaphore of 3) — how does that
   translate to worker-driven jobs?
5. B8 fail-open vs fail-closed on image-eval errors — product decision.
6. B7 threshold consolidation — one config table for QA + checklist thresholds, brand- and
   intent-aware?

---

## 5. Sequencing

1. **This doc** (lock context). ← you are here
2. **Do-now reliability PR** (§3) — ships without review.
3. **/plan-eng-review on §4** — lock the execution-model decision.
4. **Observability layer** (B9–B11) — highest long-term value once the model is settled.
5. **Eval-correctness** (B7, B8) + config consolidation.
6. **Worker-driven execution + checkpoint/resume** (B4-heavy, B12, B14) — as part of / ahead
   of the API-foundation phase.
