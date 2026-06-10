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

**UPDATE 2026-06-10 — B7 + B8 SHIPPED (commit 9d664fae, direct to main per Ryan):**
- **B7** (decision: keep the SEO-optimal 50-60/150-160, single source of truth): new
  `seo_thresholds.py` (DEFAULT + resolve_seo_thresholds(policy)); QA, checklist, and auto-fix
  (prompt + validation) all read the resolved set; eval resolves once from policy. Brand-override
  column `brand_content_policies.seo_thresholds` (migration `2026-06-10_seo_thresholds_policy.sql`,
  OPTIONAL — code is graceful via select(*)). Auto-fix validation aligned to QA (reject only
  empty / >= hard_max). KNOWN follow-up: `phase_c_optimize.txt` generation prompt still hardcodes
  150-160 (matches the default; only diverges under a brand override — templating the static
  prompt is a separate change).
- **B8** (decision: split by failure mode): `_fetch_image` retries transient (timeout/5xx), fails
  fast on 4xx; a broken image (`fetch_failed`) BLOCKS (real defect, surfaces in Exceptions); an
  evaluator error (`eval_error`) is non-blocking (our flakiness, recorded + surfaced); empty rules
  while enabled records a `config_note`. All three rendered in the Exceptions image-eval card.
- Both shipped without a PR (committed to main directly by mistake; Ryan chose to leave it —
  it was Codex-reviewed + 429 tests green). B14's eval-claim and B13's word-boundary also shipped
  (PR #283).

### Noted while here (NOT fixed — separate follow-up)
- `test_qa_validation_service.py` has 5 pre-existing failures (TestHeadingStructure x3,
  TestKeywordPlacement x2) that are red on `main`, unrelated to the do-now changes. Likely
  test-drift or related to B13 (substring keyword matching). Worth a focused pass; deliberately
  left out of this reliability PR to keep it reviewable.

---

## 4. Architectural decision — execution model + MCP-readiness ✅ DECIDED (see §11, R1)

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
5. **Observability & verification (§7 + B9–B11)** — failure signals AND the
   correctness/outcome metrics that prove interlinking (§6) actually worked. Build (a)/(e)
   alongside §6 as its definition-of-done; (c) ranking-correlation accrues over weeks.
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

---

## 7. Observability & verification (how we KNOW it's working)

Added 2026-06-05. Distinguishes **failure observability** ("did it error" — covered by B9–B11)
from **correctness/outcome observability** ("is it actually producing linked, ranking
clusters"). The plan was strong on the former, thin on the latter. This section closes that.

### Principle: extend existing tools, do NOT build a new dashboard
A UI map (2026-06-05) found the homes already exist:
- **SEO Clusters page (`52_🗂️_SEO_Clusters.py`)** already renders a **"Link Health" audit**
  (lines ~366–490) backed by `ClusterManagementService.get_interlinking_audit()`
  (`link_coverage_pct` + `missing_links`) and `get_cluster_health()` (line 262;
  `completion_pct`, published/writing/planned, `link_coverage_pct`). So a per-cluster coverage
  view ALREADY exists — it's manual (open per cluster) and would already show the new cluster at
  ~0%. (Correction to §4 notes: `get_cluster_health()` IS surfaced in the UI; it's just unused
  by the autopilot / alerting.)
- **SEO Dashboard (`48_🔍_SEO_Dashboard.py`)** already shows a brand-level **"Internal Links"
  KPI** (lines ~467–486) and full **GSC analytics** per article (impressions/clicks/position,
  lines ~763–1105) via `SEOAnalyticsService` + `GSCService`.

So the gap is not "no UI" — it's that coverage is manual-only, there's no brand-level orphan
rollup, no proactive/autopilot signal, and no tie from interlink coverage to ranking outcome.

### What to add, and where it lives

| Metric | Home (extend existing) | Data source |
|---|---|---|
| **(a) Per-cluster coverage detail** — per-article inbound/outbound counts, pillar↔spoke vs spoke↔spoke split, bidirectional completeness, "fully interlinked: y/n", links-added-last-7d | SEO Clusters → extend the existing **Link Health** audit (`52`, ~366–490) | `get_interlinking_audit()` + `seo_internal_links` |
| **(b) Brand-level orphan / low-link report** — articles with 0 inbound (orphans), <2 links, clusters <X% covered; quick "suggest/implement links" actions | SEO Dashboard → **new "Content Health" tab** alongside Analytics (`48`) | `seo_internal_links` + `seo_articles` |
| **(c) Coverage → ranking correlation (the real outcome signal)** — scatter (link_count vs avg position, sized by impressions), table of top pages with link_count + pending-link count, "+N links ≈ +M positions" | SEO Dashboard → **new "Link Impact" card** in the Analytics section (`48`, after GSC ~1105) | `seo_article_analytics` (GSC) + link counts |
| **(d) Live-layer verification** — confirm `<a href>` tags exist in the **Shopify-rendered** body, not just `seo_internal_links` rows (DB record ≠ live link Google sees) | spot-check util / Exceptions surfacing | CMS fetch vs DB |
| **(e) Autopilot signal/alert** — orphan count, clusters with <X% coverage, interlink-job failures roll into the **B9 daily/Slack health summary**; alert on "published article with 0 inbound links after N days" (I10 orphan detector) | worker health job (B9) | same queries as (a)/(b) |

### Acceptance criteria (doubles as the §6 interlinking "definition of done")
After the §6 fix ships, for a freshly published cluster:
1. SEO Clusters → Link Health shows **~100% pillar↔spoke coverage** and 0 `missing_links` within
   N hours of the last member publishing.
2. Brand **orphan count trends to 0**; the Content Health tab lists no cluster members as orphans.
3. The **Link Impact** card shows a non-trivial positive relationship between link count and
   position over time (the actual "it's working" proof).
4. Live-HTML spot-check confirms the links are present in Shopify, not just the DB.

### Notes
- (a) and (e) are cheap — the audit/health services already return the numbers; this is mostly
  surfacing + rolling up, not new computation.
- (c) is the highest-value but needs a few weeks of post-fix GSC data to be meaningful; build
  the card early, expect signal to accrue over time.
- B9–B11 (failure observability) should be implemented together with (e) so health/verification
  live in one summary rather than scattered.

### Increment status (2026-06-08)

**Tier-1 SHIPPED (PR pending, branch `RyeMcKenzie81/seo-observability-tier1`):**
- **(a) Per-cluster coverage detail** — `ClusterManagementService.get_cluster_coverage_detail()`
  (per-article inbound/outbound counts, role, orphan flag, inbound-coverage %), surfaced in the
  Clusters Link Health panel. This is the **inbound (target-based)** view; the pre-existing
  `link_coverage_pct` was source-based and could read healthy while a spoke received nothing.
- **(b) Brand orphan report** — `SEOAnalyticsService.get_brand_orphans()`, surfaced as a new
  top-level **"Content Health"** section on the Dashboard (brand-wide, not project-gated).
- Shared primitive `InterlinkingService.count_inbound_links(article_ids, source_ids=...)`.
  Orphan = `status='published'` + `published_url` set + **0 implemented inbound** links *from a
  live in-scope source* (source-scoped because `seo_internal_links` has no brand column).
- Live validation (Yakety): 103 published, **37 orphans (36%)** — actionable as-is.

**Tier-2 DEFERRED to a combined `/plan-eng-review` with §4** (real data-model decisions):
- **(c) coverage→ranking correlation** ("Link Impact" card) — needs a coverage-over-time
  snapshot table + a defined window/lag vs GSC; otherwise it correlates nothing.
- **(e) autopilot orphan alert (B9)** — placement (new scheduled job vs piggyback
  `_run_seo_pipeline_maintenance`), threshold, dedup, channel.
- **(d) live-HTML verification** — spot-check that `<a href>` exists in the Shopify-rendered body.

---

## 8. Cleanup & simplification

Added 2026-06-05. Redundant / dead / computed-but-unused code found while evaluating the
interlinking + content path. Doing this alongside §6 keeps the interlinking surface small and
reviewable instead of building the fix on top of cruft. None of these are urgent on their own;
they should be folded into the §6 interlinking work and the §4 execution-model cleanup.

- **C1. Dead pydantic-graph orchestrator + its interlinking node** (`orchestrator.py`,
  `nodes/interlinking.py`). Same item as **B12** — the graph is unused; its
  `nodes/interlinking.py` calls `interlink_cluster` and is the only "correct" wiring, but it
  never runs. Delete with the graph (or make the graph real — §4 decision).
- **C2. Three overlapping interlinking entry points** that duplicate the same
  suggest→auto_link→related flow:
  - `execute_seo_auto_interlink_job` (worker, post-publish)
  - `SEOWorkflowService.rerun_interlinking` (UI "Re-run Links" button)
  - `interlink_cluster` (whole-cluster, bidirectional)
  Consolidate to ONE canonical service method that both the worker and the UI call, with a
  `scope` arg (single-article vs whole-cluster). Today the worker and `rerun_interlinking`
  hand-roll nearly identical sequences. (This is also where the §6 fix lands — fix once.)
- **C3. Anchor-text strategy computed but never applied** (`_varied_anchor`,
  `_generate_anchor_texts`). These produce varied anchors (incl. the ~10% "learn more"
  throwaways) but are only written to the `seo_internal_links.anchor_text` column; the actual
  inserted `<a>` text is the raw matched phrase. Either apply the strategy to the HTML (per §6
  I6) or delete the dead generators. Don't keep both.
- **C4. `_suggest_placement` / `LinkPlacement` computed but unused.** `suggest_links` returns a
  placement (MIDDLE/END) that `auto_link_article` ignores (it inserts at first paragraph match).
  Apply or remove.
- **C5. Stale docstrings (doc drift).** The `interlinking_service.py` module header and the
  "Tool 1" docstring still describe Jaccard word-overlap as the primary similarity method;
  embeddings have been primary since the `make_genai_client` fix. Update so the next reader
  isn't misled.
- **C6. Content body has no single source of truth — re-renders silently wipe interlinks.**
  Interlinks are written ONLY to `content_html` (post-publish). But `content_html` is
  regenerated from `phase_c_output` by `sync_content_html` and `_update_article_cms_data`
  (verified) — and `phase_c_output` never contains the interlinks. So any re-render after
  interlinking (rerun_phase_c / "Re-optimize Content" / re-publish / regenerate) **silently
  drops every internal link**. Pick one model: (i) re-apply interlinking after any re-render, or
  (ii) treat `content_html` as the post-interlink source and never blindly overwrite it. This
  interacts with §6 (links must survive) and §4 (execution model).

### Sequencing note
C2 and C6 are structural and should be settled as part of the §6 interlinking redesign +
`/plan-eng-review`. C1 rides with the §4 graph-deletion decision. C3/C4/C5 are small, low-risk
tidy-ups that can land with the §6 implementation PR.

---

## 9. Eng review — locked decisions (2026-06-05)

`/plan-eng-review` over §4/§6/§7/§8, plus a Codex outside-voice pass. Decisions are locked;
these govern the §6 implementation.

### Locked decisions
- **D1 — Interlink timing: re-interlink the whole cluster on each member publish.** The
  post-publish path runs the cluster interlink pass over all *published* members (gated to ≥2).
  Self-healing: links appear as soon as 2 members are live; earlier members gain inbound links
  as later ones publish. Interlinking is **additive only** — it wraps existing matched phrases
  in `<a>` tags and appends a Related block; **no prose rewrite, no LLM**. Enforce a **per-article
  link cap** (~3–5 contextual + the related block) so repeated passes don't over-link.
- **D2 — Re-render then re-interlink.** After any `content_html` re-render from `phase_c_output`
  (which has no links), re-run the interlink pass so links are reconstructed. Single rendering
  source stays `phase_c_output`; links are always derived, never the canonical copy.
- **D3 — Consolidate to one canonical entry point.** `InterlinkingService.interlink(scope=
  article|cluster)`; the post-publish worker job, `rerun_interlinking`, the D2 re-render hook,
  and the UI all route through it. Delete the duplicated sequences (the drift that caused the
  post-publish job to skip `interlink_cluster` in the first place).
- **D4 — Decouple from §4.** Ship D1–D3 on the existing imperative threaded path. The §4
  execution-model decision (delete dead graph vs resurrect) stays deferred and non-blocking.

### D5 — Minimum bar (Codex outside-voice; REQUIRED before D1/D2 ship)
D1/D2 turn interlinking into a repeated cross-article background write, which creates a new
race / write-amplification surface. These are in-scope sub-tasks of §6, NOT deferrable:
1. **Cluster-level lock / debounce** — near-simultaneous publishes must not race the same
   cluster (lost updates on DB + CMS). Coalesce/lock per cluster.
2. **Idempotent link records** — `seo_internal_links` writes must upsert / honor a unique
   constraint on (source, target, link_type). Today plain `insert()` runs every pass, inflating
   counts so `_batch_count_inbound_links` (and the §7 orphan/coverage metrics) would lie.
3. **Scope cluster-mode to cluster members** — `interlink_cluster` currently calls
   `auto_link_article`, which links against ALL published project articles, not the cluster.
   Restrict (or prioritize) to cluster members so the link cap isn't exhausted before
   pillar/spoke links land.
4. **Order: remove Related block BEFORE contextual matching** — auto-link skips a target whose
   URL already appears in the footer Related block, so the current order locks articles into
   footer-only links.
5. **Body-validate before recording "implemented"** — only write a link record when
   `_insert_links_in_paragraphs` actually wrapped a phrase. Today records can claim implemented
   while the body has no link (DB ≠ live).
6. **Hash-based only-changed CMS push** — `interlink_cluster` re-pushes every processed article
   regardless of change (the "only changed" mitigation claimed for D1 does not exist yet).
   Diff final HTML; skip unchanged; protects Shopify rate limit + manual edits.
7. **Stop swallowing CMS push failures** — `_push_html_to_cms` logs-and-continues, leaving DB
   updated but Shopify stale. Surface/retry (ties B1/I9).
8. **D2 trigger safety** — distinguish render-writes from interlink-writes so the reinterlink
   hook can't recurse (interlinking itself writes `content_html`); fire only at explicit points,
   not "any content_html change" (`sync_content_html` is called from ~5 flows); ensure ordering
   so a later `publish_article` re-render can't overwrite a just-added reinterlink.

### Test coverage required (implementation must include from the start)
- `interlink(scope=cluster)`: spoke→pillar AND pillar→spoke both present; idempotent re-run (no
  dup links/records, no dup Related block); per-article link cap enforced; <2 published = no-op;
  additive-only (body text unchanged).
- **CRITICAL regression (iron rule):** re-render (rerun_phase_c / republish / regenerate) then
  re-interlink → internal links survive (the C6 bug).
- D2 trigger: no recursion (interlink write doesn't re-trigger); render-write does.
- Concurrency: two near-simultaneous publishes on one cluster → lock/debounce prevents lost
  updates (no clobbered links, single coherent final state).
- Idempotent records: re-run does not inflate inbound counts (guards the §7 metrics).
- Body validation: a recorded "implemented" link implies a real `<a>` in the body.
- Observability: orphan query flags a published article with 0 inbound; audit reflects ~100%
  intra-cluster coverage post-fix.

### NOT in scope (deferred, with rationale)
- **§4 execution-model decision** (imperative-worker-driven vs graph; delete dead graph) —
  decoupled per D4; interlinking fix doesn't need it.
- **GSC coverage→ranking correlation card (§7c)** — needs weeks of post-fix data to be
  meaningful; build the card later, after coverage is real.
- **HTML-parser rewrite of `_insert_links_in_paragraphs`** (regex → BeautifulSoup) — real
  hardening (C-series), but not required for the P0; do it if the link cap + validation aren't
  enough to contain the regex blast radius.
- **Anchor-text strategy applied to HTML (I6/C3)** — contextual anchors stay the matched phrase
  for now; apply real variation in a follow-up. (Plan should stop *claiming* anchor control
  until then.)
- **MCP / API-foundation work** — later roadmap phase; only informs, doesn't gate.

### What already exists (reuse, don't rebuild)
- `interlink_cluster()` — whole-cluster pillar/spoke + contextual + related (the bidirectional
  builder; just never called at publish time). D1/D3 wire it correctly; D5 hardens it.
- `get_cluster_health()` + `get_interlinking_audit()` — coverage % + missing links, already
  surfaced in SEO Clusters UI → §7a extends these.
- SEO Dashboard Internal Links KPI + GSC analytics → §7b/§7c homes.
- `find_linking_opportunities` (GSC striking-distance) → §7e autopilot loop.

---

## 10. Shopify edit protection (one-directional sync gap)

Added 2026-06-08 after a verified audit (12/12 load-bearing claims confirmed).

### The gap
Content sync is **one-directional**: `phase_c_output → content_html → Shopify`. Nothing
pulls a user's Shopify-side body edit back into our DB:
- `sync_article_statuses` syncs **status only** (never `body_html`).
- `import_from_shopify` writes `body_html` but is **insert-only for brand-new** articles
  (skips anything already tracked by `cms_article_id`).
- No `manually_edited` flag, content hash, or `updated_at`/`last_pushed_at` comparison — the
  system **cannot detect** a human edited the Shopify copy.

So every push (`publish_article`, the autopilot publish job, `rerun_phase_c(republish=True)`,
`repair_markdown_html`, and the interlink `_push_html_to_cms`) is a **blind overwrite**. A
manual Shopify edit is silently lost on the next push. (The markdown repair in this effort was
exactly this — it overwrote hand-fixes; fine only because our repaired version was correct.)

### Increment 1 — content lock (SHIPPED with this section)
A `content_locked BOOLEAN` flag on `seo_articles`
(`migrations/2026-06-08_seo_article_content_lock.sql`). When true, the body is human-owned;
every body-write path skips it (but the article stays a valid link TARGET):
- `publish_article` early-returns `skipped: content_locked`.
- `sync_content_html` returns the existing `content_html` without re-rendering.
- `repair_markdown_html` skips locked rows.
- `interlink_cluster` skips locked members; `auto_link_article` / `add_related_section` /
  `_push_html_to_cms` early-return.
- `_remove_related_section` leaves a locked body untouched — chokepoint that also covers the
  `interlink(scope="article")` and `rerun_interlinking` paths, which strip the Related block
  *before* the lock-aware `add_related_section` runs.
- `regenerate_article` refuses (raises) on a locked article — the regen wipe in
  `_execute_one_off` would blank `phase_c_output`/`content_html`; the user must unlock first.
  Stops a bulk "regenerate failed" sweep from clobbering a manual edit.
- Autopilot publish worker honours `skipped: content_locked` — does not mark the article newly
  published or chain an interlink job (retires the queue entry only if already live).
Code degrades gracefully if the column is absent: every body-write path reads it via
`select("*")`, so a missing column is simply treated as not-locked — safe to deploy before or
after the migration. Tested (independent review pass).

### Increment 2 — auto-detect + UI (SHIPPED 2026-06-10, PR #283)
Migration `2026-06-10_seo_push_baseline.sql` (manual): `last_pushed_at` +
`last_pushed_body_hash` on `seo_articles`.
- **(b) auto-detection** — `CMSPublisherService.detect_manual_edit(article, publisher)`: before
  re-pushing an already-published article, fetch the live copy and compare a **body hash** to
  `last_pushed_body_hash` (the hash of what Shopify STORED on our last push, captured from the
  push response). Differs ⇒ a human edited it ⇒ **skip + auto-set `content_locked`**. The hash
  IS the decision (not `updated_at`): our own non-body writes (metafields/author/status) don't
  change the stored body so they hash-match; and a `TIMESTAMPTZ`-vs-store-offset string compare
  could misorder the same instant and overwrite an edit (codex). Every body-write path
  (`publish_article` update branch, interlink `_push_html_to_cms`, `repair_markdown_html`)
  detects-then-pushes and refreshes the baseline via `record_push_baseline` (non-fatal, separate
  from the critical cms-id writeback — graceful pre-migration). Conservative: proceeds on every
  uncertainty (no cms_id / no baseline / fetch error) so it never blocks publishing or
  auto-locks on noise.
- **Worker + UI:** the autopilot publish loop honours `skipped: manual_edit` (doesn't mark
  published, emits `seo_manual_edit_protected`); Activity Feed card + a "Locked articles" unlock
  list in Dashboard → Content Health.
- **(d) eventual (NOT built):** treat Shopify as source-of-truth for published articles
  (read-modify-write interlinks), retiring the "phase_c is master, content_html disposable"
  model. Ties to §8 C6.

### Not chosen
- **(c) pull-back body sync** as a standalone fix — does NOT stop a `phase_c` re-render
  (Source-A overwrites bypass it); only useful layered behind (a)/(b).

---

## 11. Eng review round 2 — locked decisions (§4 + §7 Tier-2, 2026-06-09)

`/plan-eng-review` over §4 + §7 Tier-2, with a Codex outside-voice pass (20 findings: 3
tensions resolved by decision, the hardening folded in below, 2 rejected with reasons).
Decisions are locked; prefixed R to avoid colliding with §9's D-series.

### Live-system evidence that shaped the review (verified in prod 2026-06-09)
- `analytics_sync` job: ACTIVE, **never executed once** (0 run rows).
- `seo_article_rankings` (miner's input): stale since **2026-03-14**.
- `seo_article_analytics` (GSC): stale since **2026-04-13** (last manual Sync All).
- `seo_opportunity_scan`: "completes" weekly, **0 opportunities ever written**.
- One `seo_publish` row: active + last run failed ("parent row not found") + `next_run_at` NULL.

A job reporting success while producing zero output for months is the §7 thesis live:
failure observability ≠ correctness observability.

### Locked decisions
- **R1 — §4 = Option A (imperative worker-driven).** Delete the dead graph now
  (`seo_pipeline/orchestrator.py`, 263 lines + 9 `nodes/` files — zero callers; the
  `pydantic-graph` dependency stays, `ad_creation`/`brand_onboarding` use it live). The
  execution move to scheduler-worker durable jobs happens at the API-foundation phase.
  Sub-answers: per-phase checkpoints (A/B/C/images — matches PAUSE_POINTS + LLM cost
  boundaries); `Semaphore(3)` becomes a per-brand cap enforced at claim time; the bridge until
  then is the durable `seo_workflow_jobs` row + B2/B3 reapers (shipped). **Deliverable now
  (Codex):** a durable-job CONTRACT doc — phase names, checkpoint payload shape, idempotency
  keys, retry/cancellation/approval semantics, lease/heartbeat for the per-brand cap — written
  alongside the graph deletion so the API-foundation build isn't designed from scratch.
- **R2 — Tier-2 host = extend the existing weekly `seo_opportunity_scan`.** No new jobs,
  services, or alert channels. The scan (Feedback Loop Phase 1: `opportunity_miner_service`,
  `seo_opportunities`, 3 Activity Feed events) gains: `seo_link_coverage_snapshots` writes, an
  interlink-health section in the weekly report event, and the sampled live-link check.
  Rationale: a second weekly analytics pipeline is the §6 two-paths-drift pattern. Each
  sub-section is non-fatally wrapped with partial-success status (Codex failure-budget) so a
  flaky fetch can't block opportunity mining.
- **R3 — Feed health FIRST; increment 0 fixes the dead feeds.** Fix `analytics_sync`
  never-dispatched (audit the scheduler dispatch path as one system, not row-by-row), the
  stuck `seo_publish` row (reaper case: active + failed + `next_run_at` NULL), and the scan's
  silent no-op. Add per-source feed freshness (data age) to the weekly health section. STALE
  keys on **input** age — zero output with fresh input and genuinely no opportunities is
  healthy (Codex). The Link Impact card ships after, gated: stale feeds ⇒ red badge AND the
  correlation claim suppressed (not just badged).
- **R4 — Orphan alarm = regression-triggered + baseline burn-down.** Alarm fires only for a
  NEW orphan ≥7 days post-publish (identity-level, I10's definition); the existing 37 render
  as a burn-down metric. Weekly cadence dedups the report; lifecycle dedups the alarm (R6).
- **R5 — Publish-time self-check + weekly net (Codex tension 1).** The post-publish interlink
  job checks its own output (article still 0-inbound after the cluster pass ⇒ immediate
  alarm-styled event), non-fatal to the publish itself. The weekly scan remains the drift net.
  Detection: minutes for breakage, ≤7 days for drift.
- **R6 — Alert lifecycle + exemption (Codex tension 2).** Orphan alerts carry status
  (identified/acknowledged/resolved, mirroring `seo_opportunities.status`) so an acknowledged
  orphan doesn't re-alarm; `seo_articles.interlink_exempt` flag exempts intentional standalone
  pages from BOTH the alarm and the interlinker.
- **R7 — Card framing = directional telemetry + labeled approximate backfill (Codex
  tension 3).** No "+N links ≈ +M positions" causal coefficient — movement deltas grouped by
  link-gain, framed as directional. Cold start: approximate history reconstructed from AUTO
  link `created_at` (idempotent writes preserved them; Related-block records churn and
  undercount — labeled "approximate"), visibly switching to "measured" as real snapshots accrue.
- **R8 — Snapshot design.** `seo_link_coverage_snapshots(id, brand_id, article_id,
  captured_at, inbound_count, outbound_count, is_orphan)`; unique on `(article_id,
  captured_at::date)` (idempotent re-runs, D5.2 lesson); counts via the #271 source-scoped
  primitive against the brand's live set, materialized at capture time; index
  `(brand_id, captured_at DESC)`; card defaults to a 90-day window.
- **R9 — Live-check design.** Fetch by `cms_article_id` via the Shopify API (no URL
  scraping — kills canonicalization false-negatives, Codex); targeted sample =
  recently-interlinked + coverage-flagged, capped ~10/brand/scan, `cms_delay`-paced; network
  error ≠ missing link; `content_locked` ⇒ flag-not-fail. Output feeds the health section's
  "verified vs recorded" split (DB `implemented` rows are recorded; live-check upgrades a
  sample to verified).

### Codex findings rejected (with reasons)
- Intra-day snapshot timing loss — capture cadence is weekly; daily grain loses nothing the
  system possesses.
- Burn-down "no owner/SLA" — solo operator; the weekly report's burn-down list IS the queue.

### Test coverage required (from the review's coverage trace — all 21 specified; 2 CRITICAL)
- **CRITICAL (iron rule):** extended scan leaves existing outputs unchanged (opportunities +
  3 events) both when the health section runs AND when it throws (non-fatal wrap).
- **CRITICAL:** snapshot idempotency — same-day re-run upserts, no dup rows.
- Increment 0: root-cause test per fixed bug (analytics_sync dispatches via claim path;
  zero-output+fresh-input ≠ STALE; stale-input ⇒ STALE; stuck-publish-row reaped).
- R4/R6: new-orphan-post-publish alarms; baseline orphan doesn't; acknowledged doesn't;
  re-orphaned (fixed-then-broken) alarms again; `interlink_exempt` suppresses alarm + interlinker.
- R5: publish-time self-check emits on 0-inbound; never blocks publish.
- R7/R8: join correctness (snapshot week × analytics, aligned dates); stale ⇒ red badge +
  suppressed claim; zero snapshots ⇒ explicit empty state; backfill labeled approximate.
- R9: missing-live-link flagged; network error distinct; locked flag-not-fail; cap respected.
- R1: import-clean suite post graph deletion.

### Increments (sequencing)
0. **Feed health + fixes** (worker/) — the three live bugs + freshness in the weekly report.
   ✅ SHIPPED: PR #273 (heal sweep, dispatch reschedule, feed freshness) + PR #275 hotfix
   (recovery owner → daemon thread; the asyncio loop was starved by long sync handlers —
   verified live, healed 6 orphaned jobs incl. Daily Meta Ads Sync).
   Lane B in parallel: graph deletion + contract doc (R1) — ✅ SHIPPED: orchestrator.py,
   nodes/ (9 files), and the graph test suite deleted (zero callers; full suite green,
   failure set identical to main); `DURABLE_JOBS_CONTRACT.md` written (phase names,
   checkpoint payload, idempotency keys, retry/cancel/approval semantics, claim-time caps,
   and the sync-handler `asyncio.to_thread` constraint the starvation incident proved).
1. **Snapshot + health section + lifecycle** (worker/, services/, migrations/) — R2, R4, R5,
   R6, R8. ✅ BUILT (PR #276, pending merge): `seo_link_coverage_snapshots` +
   `seo_orphan_alerts` lifecycle + `interlink_exempt` (migration
   `2026-06-09_seo_interlink_health.sql`, manual); scan health pass (non-fatal) + alarm
   events; R5 publish-time self-check; hubless cyclic-ring Related fallback; Activity Feed +
   Dashboard UI. Codex round: 6 findings (2 P1) fixed with regression tests.
2. **Link Impact card + backfill** (ui/, services/) — R7; live-check R9. ✅ BUILT
   (2026-06-09, same day as increment 1 rather than waiting for snapshots — the labeled
   approximate backfill makes the card honest on day one): `SEOAnalyticsService.
   get_link_impact` (gained-links vs no-gain buckets + median position deltas, NO causal
   coefficient; provenance measured/mixed/approximate; stale-GSC gate suppresses the
   reading per R3); `InterlinkingService.verify_live_links` (R9: targeted sample by
   recency, fetch by cms_article_id, path-match, locked=flag-not-fail, error≠missing)
   riding the weekly scan; Dashboard "Link Impact" section; live-check line in the weekly
   Activity Feed card. **Review due ~2026-06-23** (TODOS.md): validate approximate-vs-
   measured agreement, provenance switch, bucket stability, live-check hit rate.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR (PLAN) | Round 2 (2026-06-09): 9 decisions locked (R1–R9), 8 issues raised, 0 critical gaps remaining, 21 test specs added |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| Outside Voice | `codex-plan-review` | Independent challenge | 2 | issues_found → resolved | Round 2: 20 findings — 3 tensions resolved by decision (R5/R6/R7), hardening folded into R1–R3/R8/R9, 2 rejected with reasons |

- **CODEX:** round 2 found the weekly-cadence blind window, missing alert lifecycle/exemptions, correlation overclaim + cold start, failure-budget and contract-doc gaps — all adopted (adapted) into R1–R9.
- **CROSS-MODEL:** 3 tension points, each resolved by explicit user decision (D6–D8 in review session); no unresolved tension.
- **UNRESOLVED:** 0 — all 9 questions answered during the session.
- **VERDICT:** ENG CLEARED — §4 decided (R1); §7 Tier-2 ready to implement with R2–R9 as the spec and §11's increments as the sequence. Live-bug increment 0 is the entry point.
