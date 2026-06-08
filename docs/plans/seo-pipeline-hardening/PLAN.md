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
2. **Do-now reliability PR** (§3) — ships without review. ✅ shipped (PR #258).
3. **Interlinking workstream (§6)** — P0 for ranking; currently clusters publish with ZERO
   internal links. Highest product-impact item. Do ahead of or alongside §4 (it depends on
   the publish-timing model, so the two interact).
4. **/plan-eng-review on §4** — lock the execution-model decision.
5. **Observability layer** (B9–B11) — highest long-term reliability value once the model is settled.
6. **Eval-correctness** (B7, B8) + config consolidation.
7. **Worker-driven execution + checkpoint/resume** (B4-heavy, B12, B14) — as part of / ahead
   of the API-foundation phase.

---

## 6. Interlinking workstream (P0 for ranking)

Added 2026-06-05 after evaluating the interlinking tools. **This is the highest
product-impact gap in the SEO system**: a freshly-built cluster currently publishes with
**zero internal links**, so the hub-and-spoke topical structure that makes clusters rank
never forms.

### Live evidence
The 8-article "gaming apps and technology for middle schoolers" cluster (pillar + 7 spokes),
generated 2026-06-05, has **0 inbound and 0 outbound** internal links across all 8 articles
(`seo_internal_links` is empty for them).

### Root-cause chain (why clusters end up linkless)
1. `interlink_cluster()` is the only method that builds bidirectional pillar↔spoke links. The
   batch calls it at the end (`seo_workflow_service.py:1580`, the "Cross-linking articles…"
   step), BUT it filters to **published** articles (`published_url IS NOT NULL`) and bails if
   fewer than 2 are published (`interlinking_service.py:428`). At batch end all articles are
   `publish_queued` (publishing is staggered 1–2/day), so it finds 0 published members and
   no-ops.
2. As articles publish one-by-one, the post-publish job `execute_seo_auto_interlink_job`
   **does not call `interlink_cluster`** (it looks up `cluster_id` at scheduler_worker.py:6566
   and never uses it). It only does egocentric linking on the new article:
   `auto_link_article` (outbound from the new article to already-published ones) +
   `add_related_section` (a block on the new article).
3. It **never adds inbound links** to the new article on existing pages, and never reciprocates.
   So the pillar / early-published spokes end up orphaned (≈0 inbound), and linking is
   one-directional and publish-order-dependent. The hub-and-spoke structure never forms.

### Flaw list (I-series)
- **I1 (P0). Clusters publish linkless / no hub-and-spoke.** Root-cause chain above. Inbound
  internal links are the primary internal ranking/authority signal; orphans rank poorly.
- **I2 (P1). "Bidirectional" mode isn't bidirectional.** `add_related_section` edits only the
  source article; targets are never updated with a reciprocal link.
- **I3 (P1). `interlink_cluster` timing mismatch.** It requires published articles but is only
  invoked at generation time (batch) and from a manual UI button — never after the cluster's
  members go live, which is the only time it could work.
- **I4 (P2). Related-section placement is brittle.** Inserts before an `FAQ` heading or a literal
  `<div style="background: #f8f9fa…">` author-bio marker that the current renderer no longer
  emits (bio is plain markdown after the Phase C prompt fix) → nearly always appends at end. A
  footer link list is also weak SEO vs. in-content contextual links.
- **I5 (P2). Auto-link only targets already-published articles** (`_get_project_articles`
  requires `published_url`) → sparse, back-loaded linking during a staggered rollout; the first
  article links to nothing.
- **I6 (P2). Anchor-text strategy computed but not applied.** Inserted anchor is the exact
  matched phrase (over-optimization risk); the `_varied_anchor` logic (incl. ~10% useless
  "learn more"/"this guide") is written only to the DB `anchor_text` column, never the HTML.
- **I7 (P2). Embedding lookup not project-scoped** (`_get_keyword_embedding` matches
  `seo_keywords` by keyword text, `limit 1`) → can grab a different project's vector for a
  same-text keyword.
- **I8 (P2). Relative-URL fallback can 404.** Derives `/blogs/articles/{slug}` from the keyword;
  the real Shopify handle may differ (title-based or deduped).
- **I9 (P2). Silent failure + no observability** (ties to B9/B10). Each step is
  try/except-log-continue, so a cluster with 0 links yields no error and no alert.
- **I10 (opportunity). `find_linking_opportunities` (GSC striking-distance, position 8–30, few
  inbound links) is a strong tool but manual-only** — the ongoing "feed inbound links to
  striking-distance pages" loop is not automated.

### Fix shape (to be locked via /plan-eng-review — interacts with §4 publish timing)
The core correction: **interlinking must run after publish, over the whole cluster, and re-run
as each member publishes**, so earlier articles gain inbound links to newcomers.
- On each publish, re-interlink the **whole cluster** (call `interlink_cluster` once ≥2 members
  are live) instead of egocentric linking on just the new article. Equivalent: a recurring
  "re-interlink clusters that gained a published member" pass.
- Make linking **genuinely bidirectional** (A→B implies B→A), with explicit pillar↔spoke
  guarantees (every spoke links up to the pillar; pillar links down to every spoke).
- Lead with **in-content contextual** links (`auto_link`); treat the Related-Articles block as
  secondary, and fix its placement to match the current renderer.
- Apply real **anchor-text variation** to the HTML; drop "click here"-style anchors; avoid
  100% exact-match.
- Project-scope the embedding lookup; validate derived URLs against the real CMS handle.
- Wire `find_linking_opportunities` into autopilot; add an alert for "published article with
  < N inbound internal links after X days" (orphan detector).

### Open questions for the eng review
1. **Timing model.** Re-interlink the whole cluster on every member publish (simple, more CMS
   writes) vs. a periodic cluster-sweep job vs. waiting until the cluster is fully published?
   This depends on the §4 publish/execution model.
2. **CMS write volume.** Re-pushing every cluster member on each publish multiplies Shopify
   writes (rate limit 2 req/s). Batch the re-push? Only re-push changed articles?
3. **Bidirectional storage.** Enforce reciprocity at write time (insert both A→B and B→A) vs.
   derive it from a single record at render time?
4. **Anchor over-optimization.** Target distribution of exact / partial / semantic / branded
   anchors, applied to the actual HTML.
5. **Money-page links.** Should interlinking also link blog → product/PDP for commercial
   pages? (Respect the rule: do NOT add internal links to advertorials / paid-traffic landing
   pages; this is about editorial blog content only.)
6. **Backfill.** The existing live cluster(s) are already linkless — a one-off whole-cluster
   re-interlink pass over published clusters is needed once the fix lands.
