# Template-Classifier Unification onto the Shared AWARENESS_RUBRIC (task #47)

**Status:** Eng-reviewed (plan-eng-review 2026-06-09, 5 decisions locked) + Codex outside voice (19 findings; 6 verified mechanics corrections + D4 expansion folded in, user-approved). Ready to build.
**Predecessors:** `docs/plans/static-awareness-calibration/PLAN.md` (#267), `docs/plans/static-awareness-completeness/PLAN.md` (#272). Memory: `awareness_rubric_platform_consistency`.

## Why
Templates are the LAST awareness consumer on a separate, un-calibrated definition. `template_queue_service.TEMPLATE_ANALYSIS_PROMPT` (L31-62) carries its own bare 5-level guide; one `gemini-flash-latest` call extracts 9 fields incl. `awareness_level` INT 1-5; stored on `scraped_templates` (no CHECK, no versioning, INSERT-only); consumed by `template_scoring_service.AwarenessAlignScorer` (distance math `1.0 - abs(t-p)/4`, SMART_SELECT weight 0.5) and UI filters/badges. The library (3,201 templates) is visibly skewed by the un-calibrated prompt: 64% rated 4, 18% rated 5. One platform, two awareness definitions = drift + meaningless congruence. The user flagged unification as the #1 follow-up.

## Locked decisions (plan-eng-review 2026-06-09)
- **D1 — Rubric into the EXISTING 9-field template prompt + model switch to `gemini-pro-latest`.** One Gemini call still extracts all 9 fields; the bare awareness guide is replaced by the shared `AWARENESS_RUBRIC`; the model is the SAME judge the rubric was hand-calibrated on (one definition AND one judgment). Approval-flow suggestion latency ~1-2s → ~4-8s (human-paced, acceptable). (Rejected: keeping flash — judgment drift persists; routing through ImageAnalysisService — 2 calls + structural surgery, and its ad-specific sub-rules don't fit template semantics.)
- **D2 — Keep the INT 1-5 column; model returns the STRING enum; ONE shared ordinal mapping at the write boundary.** The INT is exactly the enum ordinal (1=unaware … 5=most_aware); scorer math, UI filters/badges/selectbox, the index, and the persona-side `awareness_stage` INT all stay untouched. `awareness_level_name` keeps the human label. (Rejected: TEXT-enum column migration — wide consumer blast radius, zero behavior gain.)
- **D3 — Uniform backfill of ALL 3,201 templates, human overrides included (user decision: uniformity over preservation).** Old values remain auditable in `ai_analysis_raw`; the backfill logs the old→new distribution. Adds `awareness_prompt_version` column (idempotency/resume + future staleness queries) and the missing 1-5 CHECK; adds the UPDATE path that doesn't exist today. ~$25, chunked + resumable, modest parallelism (~1-2h).
- **D4 — Shared vocabulary moves to `awareness_rubric.py`** (the one-definition home): `VALID_AWARENESS_LEVELS`, `_normalize_awareness_level`, and the new `AWARENESS_LEVEL_ORDER` enum↔INT mapping. `image_analysis_service` re-imports for back-compat (its tests/callers untouched). No template→ads-image dependency.
- **D5 — Hash-pinned no-drift tripwire.** A unit test hashes `AWARENESS_RUBRIC` against a pin stored beside `TEMPLATE_ANALYSIS_PROMPT_VERSION`; any rubric edit fails CI until the template version is bumped, and the bump makes stale templates queryable (`WHERE awareness_prompt_version != current`). Same classify-once versioning discipline ads already have.

## Codex outside-voice corrections (2026-06-09, all user-approved)
1. **Map enum→INT at PARSE time, not the write boundary.** The suggestions dict flows through the approval UI selectbox (`index = value - 1` — a string or None CRASHES it, `28_📋_Template_Queue.py:446-452`) AND a machine-paced path: scheduler auto-approval (`scheduler_worker.py:3578`, default true) → `finalize_bulk_approval` (`template_queue_service.py:1020-1028`) passes suggestions straight to finalize. So `analyze_template_for_approval` must emit `awareness_level` as INT (mapped+normalized internally; keep the enum string + reasoning alongside in the suggestions for transparency).
2. **Kill the hardcoded `3` parse fallback** (`template_queue_service.py:789-796`): on JSON/normalize failure the suggestion must carry NO awareness key; UI renders selectbox without default (index-safe guard); bulk/auto-approval SKIPS finalizing awareness-less items (logs them) — never writes NULL or a fake "Solution Aware", never stamps v2 on a fallback.
3. **Version the suggestions themselves:** `ai_suggestions` JSONB embeds `awareness_prompt_version`; `finalize_approval` writes the version FROM the suggestions (not "current"), so stale v1 `pending_details` finalized after v2 ships are stamped honestly.
4. **Backfill audit snapshot (fixes D3's false audit claim):** `ai_analysis_raw` holds only the AI suggestion, NOT the human-confirmed value. The backfill writes the new raw response but nests `{"pre_v2_backfill": {"awareness_level": old_int, "awareness_level_name": old_name, "ai_analysis_raw": old_raw}}` — uniform overwrite stays, history survives.
5. **Backfill engineering reality:** GeminiService limiter is 9 req/min PER INSTANCE (`gemini_service.py:91-93`) and the existing bulk pattern (one instance per task, `asyncio.gather`) bypasses it. The backfill uses ONE shared instance, serial-ish (~6h honest estimate, not 1-2h), chunked + resumable; failed rows keep their old version (= durable retry ledger) + logged. PIL-decode/safety/storage failures are skip+log, not crash.
6. **Small verified fixes:** update `awareness_level_name` together with the INT everywhere (derived only at insert today); the 1-5 CHECK already EXISTS (`sql/2025-12-04_template_ai_analysis_fields.sql:25` — drop that migration item; verify prod during build); use `IS DISTINCT FROM 'v2'` for all stale queries (NULL-safe); model switch is per-call `GeminiService(model="gemini-pro-latest")` at the template call site — NEVER the global default (other callers depend on flash); the tripwire pin is keyed by version (`{version: rubric_hash}`) and the prompt test must actually CALL `.format(page_name=..., link_url=..., awareness_rubric=AWARENESS_RUBRIC)` (brace mechanics — the prompt's JSON braces are escaped, the rubric is brace-free by convention; the format-render test enforces both); rubric hashing is byte-stable BY DESIGN (a whitespace edit forces a bump — intentional, cheap).
7. **D4 EXPANDED (user-approved):** also derive the 4 hardcoded label islands from the shared constant — `template_queue_service.py:872-879` (names dict), `:621-629` (get_awareness_levels), `28_📋_Template_Queue.py:335-343` (filter options), `template_recommendation_service.py:340-346`. One vocabulary means zero islands.

## Persona side: NO change
`SelectionContext.awareness_stage` is a user-picked INT 1-5 at selection time (UI selectbox), which IS the enum ordinal. Once template labels are rubric-graded, the scorer's distance math speaks the unified language with zero changes.

## Build steps
1. **Vocabulary home (D4):** move `VALID_AWARENESS_LEVELS` + `_normalize_awareness_level` to `awareness_rubric.py`; add `AWARENESS_LEVEL_ORDER = {"unaware": 1, "problem_aware": 2, "solution_aware": 3, "product_aware": 4, "most_aware": 5}` (+ inverse); re-export from `image_analysis_service` for back-compat.
2. **Prompt + parse (D1/D2):** replace `TEMPLATE_ANALYSIS_PROMPT`'s awareness guide with `{awareness_rubric}` injection; output field becomes the string enum + keep `awareness_level_reasoning`; parse → `_normalize_awareness_level` → `AWARENESS_LEVEL_ORDER` → INT (+ name). Off-enum/garbage → None suggestion (approval UI selectbox renders without a default; verify). Switch the call to `gemini-pro-latest`. Add `TEMPLATE_ANALYSIS_PROMPT_VERSION = "v2"` + the rubric hash pin (D5).
3. **Migration:** `scraped_templates` ADD COLUMN `awareness_prompt_version TEXT` (nullable; NULL = legacy/v1) + ADD the missing CHECK (awareness_level BETWEEN 1 AND 5); write `awareness_prompt_version` on finalize_approval and the backfill.
4. **Backfill (D3):** chunked, resumable (`WHERE awareness_prompt_version IS DISTINCT FROM 'v2'`), uniform overwrite; re-downloads each template image from storage; logs old→new distribution + override count (stored vs ai_analysis_raw suggestion) for the report. Spot-check batch first (~20 templates, eyeball old→new) before the full run.
5. **Tests (full coverage diagram in review):** mapping-lock (exhaustive both directions); rubric-hash tripwire (D5); prompt-contains-rubric verbatim (no fork); parse happy/casing/garbage→None; model constant assert; backfill idempotency + uniform-overwrite semantics; scorer distance-math regression (locks consumer semantics); normalizer re-export back-compat.
6. **Bulk-analysis rate-limit fix (user-added to this PR):** `template_queue_service.py:995` gathers with a NEW `GeminiService()` per task (`:772`) — per-instance limiters mean N-way fanout bypasses the 9 req/min limit. Share ONE service instance across the gather (or a semaphore). Same-file change, fixes an existing footgun.
7. **Rollout:** ship code → spot-check batch → full backfill → verify distribution shift (expect the 64%-at-4 skew to flatten) → update memory `awareness_rubric_platform_consistency` (templates unified).

## Failure modes
- **Gemini returns off-enum label** → normalizer → None → suggestion empty; approval UI must handle a None default (test). Backfill: None → skip + log (do NOT write garbage / NULL over a real label), retry next run.
- **Rubric edited without template bump** → D5 tripwire fails CI (the entire point).
- **Backfill interrupted** → resume via `awareness_prompt_version` filter; idempotent.
- **Approval-flow latency regression** (pro vs flash) → acceptable (human-paced); note in UI if >10s becomes common.
- **Template image missing from storage** → skip + log (same graceful pattern as ads' deep-or-skip).

## NOT in scope
- TEXT-enum column migration for `scraped_templates` (D2 rejected — no behavior gain, wide blast radius).
- Re-scoring / re-ranking historical template recommendations (scorer reads live labels; next selection run picks up new grades automatically).
- The deep `ImageAnalysisService` path for templates (D1 rejected) and any low-res guard for templates (scraper downloads full creatives — different source than the Meta thumbnail problem; revisit only if low-res templates appear).
- Persona-side vocabulary changes (none needed).
- Congruence between templates and ads (future; this unification is its prerequisite).

## What already exists (reused)
- `AWARENESS_RUBRIC` (brace-safe, .format-ready), `VALID_AWARENESS_LEVELS`, `_normalize_awareness_level` (moving home per D4).
- The 9-field `TEMPLATE_ANALYSIS_PROMPT` + human-in-the-loop approval flow (kept intact; only the awareness section + model change).
- The classify-once versioning pattern (ads' prompt_version discipline) → `awareness_prompt_version`.
- `ai_analysis_raw` JSONB (audit trail that makes the uniform overwrite non-destructive in practice).

## Worktree parallelization
Sequential — every step funnels through `template_queue_service.py` + `awareness_rubric.py` (one shared pair). Order: vocabulary home → prompt/parse → migration → tests → spot-check → backfill.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 19 problems; 6 verified mechanics corrections + D4 expansion folded in (UI/bulk crash paths, false audit claim, rate-limit reality, label islands) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | 6 issues across Architecture/CodeQuality/Tests/Perf; 5 decisions locked (D1 pro+rubric-in-prompt, D2 INT+parse-time mapping, D3 uniform backfill+snapshot, D4 expanded vocabulary home, D5 hash tripwire); 0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (selectbox None-guard covered in plan) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | n/a |

- **CODEX:** caught the approval-UI/bulk-path crash (mapping had to move to parse time), the machine-paced auto-approval path, the false `ai_analysis_raw` audit assumption, the per-instance rate limiter, and 4 label islands D4 had missed.
- **CROSS-MODEL:** 2 substantive tensions, both resolved in Codex's favor with user approval; no disagreements remain.
- **UNRESOLVED:** 0
- **VERDICT:** ENG + CODEX CLEARED — 5 decisions locked + 7 corrections folded; ready to implement.
