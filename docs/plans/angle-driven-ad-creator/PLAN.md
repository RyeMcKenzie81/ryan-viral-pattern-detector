# Plan: Angle-Driven Ad Creator V1

**Status:** APPROVED via /office-hours + /plan-eng-review (2026-05-25)
**Branch:** `RyeMcKenzie81/angle-driven-ad-creator`
**Design doc:** `~/.gstack/projects/RyeMcKenzie81-ryan-viral-pattern-detector/ryemckenzie-RyeMcKenzie81-angle-driven-ad-creator-design-20260525-132236.md`
**Test plan:** `~/.gstack/projects/RyeMcKenzie81-ryan-viral-pattern-detector/ryemckenzie-RyeMcKenzie81-angle-driven-ad-creator-eng-review-test-plan-20260525-134500.md`
**Estimated effort:** 2.5–3 weeks (1 engineer) / 12–16 hours (CC)

---

## Summary

Invert AC2 from template-first to angle-first. New `AngleGeneratorService` produces N=5 angles from (persona, offer_variant, landing_page). Angles persist as `belief_angles` rows. AC2 selects saved angles and generates M=50 ads per angle via the existing scheduler `content_source='angles'` path. `HookDiversityChecker` prevents intra-batch hook collapse. Every ad records `angle_id` + `hook_embedding` + `ad_creation_run_id` for the 30-day falsifiability report that decides whether V2 needs angle→template fit logic.

The single most important behavioral change: **strategy drives ad creation, with built-in falsifiability so we know whether it's working.**

---

## Architectural Decisions (locked via /plan-eng-review)

| ID | Decision | Rationale |
|----|----------|-----------|
| **1A** (revised by OV-1) | `belief_angles.jtbd_framed_id` becomes nullable. Generated angles store JTBD as text in a new `belief_angles.jtbd_text` column. No `belief_jtbd_framed` rows created by the generator. | Codex's outside voice flagged that auto-creating `belief_jtbd_framed` rows would pollute that table's curated-jobs semantics within months. Nullable FK preserves both the curated layer and the generation flow. |
| **1B** | Sequential hook generation, batched embedding calls (groups of 10). Retry semantics ("up to 3, then best-of-3") preserved. | Cuts embedding round-trips 10x without changing design semantics. M=50 batch finishes in ~1 min instead of ~5. |
| **1C** | TWO distinct run IDs: `belief_angles.angle_generation_run_id` (FK to new `angle_generation_runs` table) and `generated_ads.ad_creation_run_id` (FK to existing `scheduled_jobs.id`). | The falsifiability report must group ads created in the same scheduler run; angles have their own lifecycle. Two concepts → two columns. |
| **1D** | HNSW index on `generated_ads.hook_embedding` (not ivfflat). | Better for incremental inserts. No future REINDEX time bomb. |
| **1E** | Separate Streamlit page `22_🎯_Generate_Angles.py`. On save, "Continue to AC2" deep-links via `?preselect_angle_ids=<ids>`. AC2 reads param and pre-selects. | Keeps AC2 from growing further. Strategy-creation and ad-creation are different mental modes. |
| **2A** | Retry/best-of-3 loop lives in `HookDiversityChecker.generate_with_diversity(generate_fn, accepted_embeddings, max_retries=3)`. Scheduler passes a callable. | Keeps the diversity rule and its enforcement in one file. Scheduler stays thin. Unit-testable. |
| **2A.1** | `INTRA_ANGLE_THRESHOLD` = hardcoded default 0.85, overridable via `system_settings.angle_pipeline.intra_angle_threshold`. | Mirrors the existing `DEFAULT_MAX_ADS_PER_SCHEDULED_RUN` pattern. Tune via single UPDATE, no deploy. |
| **2B** | `AngleGeneratorService` writes directly to `belief_angles`. Does NOT route through `angle_candidates`. | The 5 existing candidate sources stay unchanged. The new generation flow has a different UX (review inline, not promote-from-staging). |
| **3A** | No LLM eval suite for V1. Manual review via the office-hours assignment (handwrite 5 angles for one combo, compare). Eval suite is fast-follow once V1 has produced reference data. | You can't build a good eval without golden examples. V1 produces them. |
| **3B** | One E2E test for the happy path (generate → save → run ads → verify `angle_id` + `hook_embedding` populated). Diversity-rejection and re-generation E2Es are fast-follows. | Catches 80% of wiring bugs at the seams. Right-sized for V1. |
| **OV-4** | Migration preamble includes `CREATE EXTENSION IF NOT EXISTS vector;`. | Don't assume pgvector is installed in every env. Belt-and-braces given the worker would crash on first insert otherwise. |
| **M1** | AngleGeneratorService uses **Claude Opus 4.7** (matches `ad_creation_service.py:1303` and 15+ other strategic services in the repo). Reads the constant from `viraltracker/core/config.py`, does not hardcode the model string. | Same model as AC2's hook generator → cross-angle hook similarity isolates the angle's effect rather than confounding it with model differences. Central constant means future model upgrades are a one-line change. |
| **UX-1** | Consolidate AC2 content_source dropdown from 4 modes to 3. Deprecate `belief_first` (semantics fold into `angles`). Final modes: `angles` (relabel as "Strategic Angles"), `plan`, `recreate_template`. Migration updates any existing `scheduled_jobs.parameters` rows where `content_source='belief_first'` to `content_source='angles'` (compatible payload — both used belief context). | Three angle-flavored modes (`belief_first` + `plan` + `angles`) was the AC2-too-complex risk in dropdown form. Cleaning up while we're already in this file is cheap; doing it later requires migrating accumulated job history. |

---

## Implementation Order

Strict sequencing matters. Each step depends on the previous one being merged.

### Step 1 — Baseline measurements (BEFORE migration)

**Two distinct baseline jobs.** Both run before any code ships. Both feed the generator's eval and threshold calibration.

#### Step 1a — Hook similarity baseline (for `INTRA_ANGLE_THRESHOLD` calibration)

**File:** `scripts/measure_hook_similarity_baseline.py` (NEW)

- Reads last 30 days of `generated_ads.hook_text` for runs grouped by `(persona_id, offer_variant_id)`.
- Embeds via existing OpenAI infrastructure (text-embedding-3-small).
- Computes mean pairwise cosine similarity per group.
- Outputs CSV: `docs/plans/angle-driven-ad-creator/BASELINE_SIMILARITY.csv` with `(persona_id, offer_variant_id, n_hooks, mean_pairwise_similarity)`.
- Handles empty result set; skips NULL hook_text rows.

Output drives `INTRA_ANGLE_THRESHOLD` initial value (~0.05 below the mean for current AC2 output).

#### Step 1b — Winning-angle extraction (for generator quality baseline)

**File:** `scripts/extract_winning_angle_baselines.py` (NEW)

For one chosen (persona, offer_variant), pull TWO populations of top performers from existing `generated_ads JOIN ad_intelligence`:

1. **Top 5 by ROAS** (filter: ad spend ≥ $150, window: last 60 days). Captures premium-intent winners.
2. **Top 5 by spend** (window: last 60 days, no ROAS filter). Captures proven-to-scale ads even if ROAS is modest (these often run further down the awareness funnel where conversion is harder but volume justifies the cost).

For each ad in both lists, extract the `hook_text` and have a one-shot LLM call infer the underlying angle (belief / pain point / desired outcome) from the hook + ad creative metadata.

Dedupe (an ad qualifying for both lists shows once). Output: `docs/plans/angle-driven-ad-creator/BASELINE_WINNERS.md` — 5–10 reverse-engineered angles with the source ad's metrics attached.

This is the **reference set the generator must at least match**. On V1 launch, run the generator against the same (persona, offer) and compare its 5 angles against the 5–10 baselines on (a) coverage of the same beliefs and (b) reach beyond what existing winners already cover.

**Both scripts are zero-dependency on the rest of the build.** Run them in parallel with Step 2 migration prep. Spend floor and ROAS rule for Step 1b can be relaxed if too few ads qualify on first run for the chosen (persona, offer).

### Step 2 — Migration

**File:** `migrations/2026-05-XX_angle_driven_ads.sql` (NEW)

```sql
-- Preamble
CREATE EXTENSION IF NOT EXISTS vector;

-- belief_angles extensions
ALTER TABLE belief_angles
  ALTER COLUMN jtbd_framed_id DROP NOT NULL;
ALTER TABLE belief_angles
  ADD COLUMN IF NOT EXISTS jtbd_text TEXT,
  ADD COLUMN IF NOT EXISTS generation_method TEXT,
  ADD COLUMN IF NOT EXISTS source_persona_id UUID REFERENCES personas_4d(id),
  ADD COLUMN IF NOT EXISTS source_offer_variant_id UUID REFERENCES product_offer_variants(id),
  ADD COLUMN IF NOT EXISTS source_landing_page_url TEXT,
  ADD COLUMN IF NOT EXISTS pain_points JSONB,
  ADD COLUMN IF NOT EXISTS desired_outcome TEXT,
  ADD COLUMN IF NOT EXISTS angle_generation_run_id UUID;

-- generated_ads extensions
ALTER TABLE generated_ads
  ADD COLUMN IF NOT EXISTS hook_embedding VECTOR(1536),
  ADD COLUMN IF NOT EXISTS ad_creation_run_id UUID;

-- HNSW index for incremental writes
CREATE INDEX IF NOT EXISTS idx_generated_ads_hook_embedding_hnsw
  ON generated_ads
  USING hnsw (hook_embedding vector_cosine_ops);

-- New table
CREATE TABLE IF NOT EXISTS angle_generation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by_user_id UUID,
  persona_id UUID REFERENCES personas_4d(id),
  offer_variant_id UUID REFERENCES product_offer_variants(id),
  landing_page_url TEXT,
  n_angles_requested INT NOT NULL,
  generator_prompt_version TEXT NOT NULL,
  angle_ids UUID[]
);

-- FK from belief_angles to angle_generation_runs (added after table exists)
ALTER TABLE belief_angles
  ADD CONSTRAINT belief_angles_angle_generation_run_id_fkey
  FOREIGN KEY (angle_generation_run_id) REFERENCES angle_generation_runs(id) ON DELETE SET NULL;

-- UX-1 data migration: fold belief_first into angles (both used belief context, compatible payload)
UPDATE scheduled_jobs
   SET parameters = jsonb_set(parameters, '{content_source}', '"angles"')
 WHERE parameters->>'content_source' = 'belief_first';
```

Verify idempotency (re-run on a copy first). Confirm no data loss on existing rows.

### Step 3 — Services (no scheduler/UI dependency)

**Files (NEW):**
- `viraltracker/services/hook_diversity_checker.py`
- `viraltracker/services/angle_generator_service.py`

Each has unit tests (`tests/services/test_hook_diversity_checker.py`, `tests/services/test_angle_generator_service.py`). Build in this order:

1. `HookDiversityChecker.check()` + `generate_with_diversity()` + `batched_embed()` — pure logic, fully unit-testable.
2. `AngleGeneratorService.generate_angles()` — LLM call returns `List[ProposedAngle]`. Mock the LLM in tests.
3. `AngleGeneratorService.save_angles()` — persists to belief_angles (jtbd_text TEXT, NOT a jtbd_framed row) and creates an angle_generation_runs row. Transaction-wrapped.

Both services depend on Step 2 migration but nothing else. Can be built in parallel by two engineers.

### Step 4 — Scheduler extension

**File:** `viraltracker/worker/scheduler_worker.py` (MODIFY)

Extend the existing `content_source='angles'` execution path (~line 570+) to:
- Invoke `HookDiversityChecker.generate_with_diversity()` on each hook.
- Populate `generated_ads.angle_id`, `generated_ads.hook_embedding`, and `generated_ads.ad_creation_run_id` (= `scheduled_jobs.id`).
- Log per-batch stats (mean intra-angle similarity, rejections, retries) to app logger.
- At end of run, compute and log mean cross-angle similarity for the `ad_creation_run_id`.

Depends on Step 3 services. Regression test: existing `content_source='angles'` and `content_source='plan'` paths still work for callers that don't supply diversity-relevant params.

### Step 5 — UI

**Files:**
- `viraltracker/ui/pages/22_🎯_Generate_Angles.py` (NEW)
- `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` (MODIFY)

Generate Angles page:
- Persona + offer variant selectors.
- Readiness panel reuses `AdCreatorReadinessService` for LP warnings.
- "Generate" → spinner → 5 editable angles displayed.
- Save Selected persists checked rows.
- "Continue to AC2" → `st.switch_page` with `?preselect_angle_ids=<comma-list>`.

AC2 modification (`viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py:1150`):
- **Content_source dropdown consolidation (UX-1):** options become `["angles", "plan", "recreate_template"]`. Relabel: `angles` → "Strategic Angles (NEW)", `plan` → "Plan execution", `recreate_template` → "Recreate Template (legacy)". Remove `belief_first` entirely. Any session_state default pointing at `belief_first` migrates to `angles`.
- **Deep-link from Generate Angles auto-sets** `st.session_state.v2_content_source = "angles"` so the strategic flow lands on the right mode.
- New "Angle" multiselect (under the `angles` mode), filtered by `(persona_id, offer_variant_id, status != 'loser')`.
- Read `?preselect_angle_ids=` query param on page load; pre-populate the multiselect.
- Per-angle batch size input (default 50, cap 200 from `DEFAULT_MAX_ADS_PER_SCHEDULED_RUN`).
- Regression: existing `recreate_template` and `plan` flows unchanged. Existing `belief_first` flow's behavior is preserved under the renamed `angles` mode (since the data migration mapped old jobs forward).

### Step 6 — E2E test + final wiring

**Status: not being built for V1 (decision 2026-05-26).**

Original intent: `tests/e2e/test_angle_driven_flow.py` simulating the happy
path — open Generate Angles → fill inputs → generate → save 3 of 5 → click
Continue → AC2 opens with 3 pre-selected → run ads with M=3 each → assert
9 `generated_ads` rows with `angle_id` + `hook_embedding` + `ad_creation_run_id`
populated.

**Why we're skipping:**
- Streamlit E2E tests are expensive to build (need Playwright/browser driver),
  slow to run, flaky in CI, and either hit real Opus (cost) or mock it (loses
  most of the integration value).
- All session-1 bugs (UnboundLocalError, LP schema mismatch, duplicate hooks,
  missing angle_id stamping) were caught manually within ~5-15 min each. The
  cost of NOT having E2E is "occasional manual debug sessions like 2026-05-26,"
  which is acceptable for V1.
- Two cheaper alternatives are documented as future options if regressions
  become a real problem:
  - **Option A (service-level integration test, ~10 sec runtime):** skip
    Streamlit entirely, call AngleGeneratorService directly with a mocked
    Opus, invoke the scheduler `content_source='angles'` path, assert on the
    three new generated_ads columns. Covers the wiring bugs without the UI
    test infrastructure.
  - **Option B (nightly SQL smoke check):** single query that asserts "in
    the last 24h, every ad with content_source='angles' has the three new
    columns populated." Alerts via Slack/logfire on failure. ~20 lines.

Revisit if production regressions start happening monthly or more.

---

## What Already Exists (Reused, Not Rebuilt)

| Component | Reuse strategy |
|-----------|----------------|
| `belief_angles` table | Extending with new columns + nullable jtbd_framed_id. Not rebuilding. |
| `AngleCandidateService` | Untouched. 5 existing candidate sources keep working. |
| `scheduler_worker.py content_source='angles'` path | Extending (Step 4). Not replacing. |
| `generated_ads.angle_id` | Already exists; we just populate it. |
| `AdCreatorReadinessService` | Reusing existing LP-readiness signal. No new readiness logic. |
| Landing page analyzer | Reusing for generator prompt input. |
| OpenAI embedding infrastructure | Reusing the existing call path. |
| `personas_4d`, `product_offer_variants` | Read-only consumers. |
| `system_settings` pattern (per `MAX_ADS`) | Reusing for `INTRA_ANGLE_THRESHOLD` override. |
| `scheduled_jobs` table | Reusing `.id` as `ad_creation_run_id` FK target. |

---

## NOT in Scope (Deferred with Rationale)

- **Angle → template fit logic (P4 from design doc).** Templates remain selected by existing scorers. Deferred until the 30-day falsifiability report says whether hooks collapse across angles. If they do, V2 adds taxonomy (fear→testimonial, aspiration→story, etc.). If they don't, the deferral was right.
- **Angle Performance dashboard.** Manual SQL / scripted ad-intel joins are sufficient for the first few weeks. UI can come once volume warrants it.
- **LLM eval suite for the generator prompt.** Fast-follow. Needs golden examples that don't exist yet.
- **Diversity-rejection E2E and re-generation E2E.** Manual verification is fine for these. Add tests once volume of edge-case observations justifies them.
- **Active avoidance of historical hooks.** Generator could be given embeddings of previously-tested hooks for this (persona, offer) and asked to avoid collapsing onto them. P6.5 future enhancement; cheap to add once V1 ships.
- **`belief_plans` integration.** If you later want to bundle 5 generated angles into a plan, that's a one-action save into existing belief_plans infra. Not in V1.
- **Multi-method angle generation expansion.** The 5 existing candidate sources (BRE, Reddit, ad perf, competitor, brand research) already work via promotion. V1 adds ONE new method.
- **Bulk regenerate / re-rank existing angles using new context.** YAGNI for V1.

---

## Failure Modes (and Coverage)

Every new codepath, one realistic production failure scenario, whether tests + error handling exist:

| Codepath | Failure mode | Test? | Error handling? | User visibility |
|----------|--------------|-------|-----------------|-----------------|
| `AngleGeneratorService.generate_angles` | LLM returns malformed JSON | YES (unit) | YES (catch, surface to UI) | Clear error, can retry |
| `AngleGeneratorService.save_angles` | DB write fails mid-transaction | YES (unit) | YES (transaction rollback) | Clear error, no half-state |
| `HookDiversityChecker.generate_with_diversity` | All 3 retries rejected | YES (unit) | Best-of-3 fallback | Logged warning; user sees the ad |
| `HookDiversityChecker.batched_embed` | OpenAI rate limit | NO (fast-follow) | Propagates exception | **CRITICAL GAP**: ad gen aborts mid-batch. Mitigation: catch in scheduler loop, log, mark batch incomplete. |
| Scheduler extension | hook_embedding insert fails (e.g., vector dim mismatch) | YES (unit) | Propagates | Batch fails loudly; logged |
| Migration | pgvector extension missing | N/A | `CREATE EXTENSION IF NOT EXISTS` (OV-4) | Migration succeeds idempotently |
| Generate Angles UI | LP analyzer times out | NO (gap) | Falls back to no-LP mode | Generation succeeds with weaker context |
| AC2 deep-link | Invalid `preselect_angle_ids` UUID format | NO (gap) | Ignore param, render empty | Multiselect just empty |

**Critical gap flagged:** OpenAI rate-limit on `batched_embed`. Add a try/except in the scheduler loop that catches embedding-API failures and marks the batch as `status='incomplete'` rather than crashing the entire scheduled job. This is the one production failure mode that could lose hours of work.

---

## Worktree Parallelization

| Step | Modules touched | Depends on |
|------|----------------|------------|
| 1. Baseline script | `scripts/` | — |
| 2. Migration | `migrations/` | — |
| 3a. HookDiversityChecker | `viraltracker/services/`, `tests/services/` | Step 2 |
| 3b. AngleGeneratorService | `viraltracker/services/`, `tests/services/` | Step 2 |
| 4. Scheduler extension | `viraltracker/worker/` | Step 3a, 3b |
| 5a. Generate Angles page | `viraltracker/ui/pages/` (new file) | Step 3b |
| 5b. AC2 modification | `viraltracker/ui/pages/` (existing file) | Step 4 |
| 6. E2E test | `tests/e2e/` | Step 5a, 5b |

**Lanes:**
- **Lane A:** Step 1 (independent, run day 1)
- **Lane B:** Step 2 → Step 3a → Step 4 → Step 5b → Step 6 (scheduler + AC2 mod track)
- **Lane C:** Step 2 → Step 3b → Step 5a → Step 6 (services + new page track)

**Execution order:** Launch Lane A immediately (no dependencies, output feeds threshold calibration). After Step 2 merges, Lane B and Lane C run in parallel worktrees. Both converge on Step 6.

**Conflict flag:** Lanes B and C both touch `viraltracker/services/` and `viraltracker/ui/pages/`. Different files, low real conflict risk, but coordinate test-fixture imports.

---

## Open Risks (acknowledged, not blocking)

1. **Adoption risk (from OV-3):** the new flow adds operator steps (open new page → review → save → deep-link → run). If you fall back to direct AC2 use without angles, V1 doesn't accumulate data. Mitigation: the office-hours assignment (handwrite 5 angles for one combo, compare) commits you to actually using the new flow during week 1.

2. **Diversity ≠ quality (from OV-1):** the cross-angle similarity metric measures whether hooks differ across angles, NOT whether angles are good. The actual quality gate is qualitative ("5 distinct strategic angles visibly present") judged by you + clients. Treat the similarity report as P4 experiment-validity, not as a success scorecard.

3. **Generator prompt is load-bearing:** if the LLM produces same-shaped slop angles, the entire experiment fails. Manual review (Step 3A) catches this; eval suite fast-follow catches regressions once you have golden examples.

---

## Unresolved Decisions

None. All 10 issues raised in this review were resolved (7 in section reviews, 2 in outside-voice cross-model tension, 1 in scope challenge).

---

## Completion Summary

- Step 0: Scope Challenge — scope accepted as-is
- Architecture Review: 5 issues found, 5 resolved
- Code Quality Review: 2 issues found (incl 1 sub-question), 3 decisions resolved
- Test Review: diagram produced (52 paths), 2 gaps converted to decisions
- Performance Review: 0 blocking issues, 1 advisory note (multiselect filter)
- NOT in scope: written
- What already exists: written
- TODOS.md updates: pending below
- Failure modes: 1 critical gap flagged (OpenAI rate-limit handling)
- Outside voice: Codex ran, 2 cross-model tensions, 1 caused premise revision (1A → nullable FK)
- Parallelization: 3 lanes, 2 parallel, baseline standalone
- Lake Score: 8/10 recommendations chose complete option (deferred dashboard, eval, and 2 of 3 E2Es as intentional fast-follows, not shortcuts)

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | (not run — scope was debated in /office-hours) |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | ISSUES (resolved) | 5 challenges, 1 caused premise revision (1A → nullable FK) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 10 issues, 10 resolved, 1 critical gap flagged for impl |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | (not recommended — utilitarian internal panel) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | (not applicable — internal tool) |

- **CODEX:** ran via outside voice; found 5 issues, 1 incorporated (1A reversal — `belief_jtbd_framed` now nullable on AI-generated angles), 4 acknowledged (diversity≠quality, pgvector preflight, adoption risk, simpler-V1 rejected on user-stated grounds).
- **CROSS-MODEL:** Eng Review and Codex agreed on 4 of 5 challenges. The disagreement (simpler V1 throws away saved-angle persistence) was resolved by Ryan in favor of keeping the strategic infrastructure.
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready to implement. 1 critical gap (OpenAI rate-limit handling on `batched_embed`) must be addressed in Step 4 scheduler extension.

