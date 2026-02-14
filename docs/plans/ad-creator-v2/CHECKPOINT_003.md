# Ad Creator V2 — Checkpoint 003: Codex Round 2 Fixes & Implementation-Ready

> **Date**: 2026-02-13
> **Status**: Superseded by CHECKPOINT_004 (PLAN.md now at v7)
> **Follows**: CHECKPOINT_002 (expert review + Codex round 1 integration)
> **PLAN.md**: Was v6 at time of this checkpoint; now v7 — see CHECKPOINT_004 for latest

---

## What Was Done This Session

### 1. Codex Round 2 Review (6 findings)

After PLAN.md v2 was reviewed by OpenAI Codex a second time, 6 additional issues were found and all verified against the codebase:

| # | Severity | Finding | Verified Against |
|---|----------|---------|-----------------|
| 1 | **P0** | Composite key migration incomplete — doesn't drop existing unique index before recreating | `sql/migration_ad_creation.sql:137` — index exists |
| 2 | **P0** | Template column names wrong — plan uses `storage_name` and `status = 'approved'`, actual schema has `storage_path` and `is_active` | `sql/migration_brand_research_pipeline.sql:171,182` |
| 3 | **P1** | Future job types not in CHECK — Phase 6-7 job types (`creative_genome_update`, etc.) missing from constraint | `sql/create_scheduler_tables.sql` |
| 4 | **P1** | `scheduled_job_runs.metadata` column doesn't exist — plan references it for progress tracking | `sql/create_scheduler_tables.sql:91-114` — no metadata column |
| 5 | **P2** | Review rubric count inconsistent — section header says "14 checks" but table shows 9 | PLAN.md Section 6 |
| 6 | **P2** | `meta_campaigns.objective` assumption should be validated | `migrations/2025-12-18_meta_ads_performance.sql:114` — column EXISTS but sync code doesn't populate it |

### 2. All 6 Fixes Applied to PLAN.md (v2 → v3)

Each fix was verified against the actual codebase schema before being written:

**Fix 1 — Complete composite key migration (P0):**
- Added `DROP INDEX IF EXISTS idx_generated_ads_run_index` before recreating
- Recreated as composite: `(ad_run_id, prompt_index, COALESCE(canvas_size, 'default'))`
- Relaxed `prompt_index` CHECK from `<= 5` to `<= 100` (multi-size × multi-color)

**Fix 2 — Correct column names (P0):**
- Changed backfill query from `st.storage_name` to `st.storage_path`
- Added note: "`scraped_templates` uses `storage_path` (not `storage_name`) and `is_active` boolean (not `status = 'approved'`)"
- Fixed "Roll the Dice" query: `st.is_active = TRUE` instead of `st.status = 'approved'`

**Fix 3 — Future job types in CHECK (P1):**
- Added to CHECK constraint: `creative_genome_update`, `genome_validation`, `quality_calibration`, `experiment_analysis`

**Fix 4 — Add `metadata` column migration (P1):**
- Added migration: `ALTER TABLE scheduled_job_runs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'`

**Fix 5 — Review rubric expanded to 15 checks (P2):**
- Expanded from 9 checks to 15 with full breakdown:
  - **V1-V9** (Visual): Product accuracy, text legibility, layout fidelity, color compliance, brand guidelines, asset accuracy, production quality, background coherence, product label accuracy
  - **C1-C4** (Content): Headline clarity, CTA effectiveness, awareness stage match, emotional driver alignment
  - **G1-G2** (Congruence): Headline congruence, visual-copy alignment

**Fix 6 — Campaign objective validation (P2):**
- Confirmed `meta_campaigns.objective` column exists in schema
- Added note that sync code (`meta_ads_service.py:~1035`) needs update to populate `campaign_objective` from `meta_campaigns.objective` via join
- **Not yet implemented in code** — deferred to Phase 0 implementation

---

## Codex Overall Assessment

**Round 2:**
> "Big picture: this is a major upgrade over v1 of the plan. Phase gates + prerequisites make it much more executable."
>
> "If you patch those, this plan is very likely to work and is implementation-ready."

**Round 3 (final):**
> "No clear P0 architecture blockers remain in the plan itself."
>
> "Likely to work with current updates. Highest residual risk is execution correctness in Phase 0 (routing fail-closed + objective enrichment)."

---

## Implementation-Critical Gaps (Code, Not Plan)

These are correctly described in PLAN.md but not yet implemented in code. Both are Phase 0 tasks:

| # | Gap | File | What's Needed |
|---|-----|------|---------------|
| 1 | Unknown `job_type` silently falls through to V1 | `scheduler_worker.py:577` | Must hard-fail (raise/log error), not default to `execute_ad_creation_job()` |
| 2 | `campaign_objective` not populated during perf sync | `meta_ads_service.py:~1035` | Join `meta_campaigns.objective` into performance record upsert |

### Phase 0 Acceptance Tests (from Codex)

Before proceeding to Phase 1, validate:
1. **Unknown job_type => failed run, no V1 fallback** — call `execute_job()` directly with a mocked job dict containing an unrecognized type; confirm it raises/logs an error and marks the run as `failed` (NOTE: the DB CHECK constraint blocks unknown types at insert time, so this must be a unit/integration test against the routing logic, not via job submission)
2. **Meta sync writes campaign_objective** — run a meta performance sync, confirm `meta_ads_performance.campaign_objective` is populated (requires `meta_campaigns` to be populated first — see P1-4 two-part fix)
3. **V2 stub routes correctly** — submit an `ad_creation_v2` job, confirm it routes to stub handler (not V1) and completes with `metadata.stub = true`
4. **Template backfill produces zero ambiguous mappings** — after P0-3 migration, zero rows in `product_template_usage` match multiple `scraped_templates` (or count is within documented tolerance)
5. **Non-Meta brand does not crash** — submit a V2 job for a brand without `brand_ad_accounts` link; confirm it completes stub run successfully (no meta-dependent failure)
6. **Campaign sync failure is non-fatal** — if Meta campaign API call fails, performance sync still completes with `campaign_objective = 'UNKNOWN'`

---

## Cumulative Review History

| Round | Source | Findings | Fixed In |
|-------|--------|----------|----------|
| 1 | 4 Expert Agents (RL/Bandit, CV/Quality, Causal Inference, Production ML) | 6 critical holes (no learning algorithm, no human feedback loop, no delayed reward, no experiment design, no cold-start, no monitoring) | CHECKPOINT_002 + PLAN.md v2 |
| 2 | OpenAI Codex (round 1) | 10 issues (3 P0, 5 P1, 2 P2) — schema/code mismatches, silent failures | PLAN.md v2 |
| 3 | OpenAI Codex (round 2) | 6 issues (2 P0, 2 P1, 2 P2) — migration gaps, column name errors, rubric count | PLAN.md v3 |
| 4 | OpenAI Codex (round 3) | 2 implementation gaps + 1 wording fix — confirmed no remaining plan-level blockers | CHECKPOINT_003 updated |
| 5 | OpenAI Codex (round 4) | 5 issues (2 P0, 3 P1) — false sync assumption, phase-order contradiction, invalid test, stale metadata, loose gates | PLAN.md v5 |
| 6 | Final hardening pass | 6 items — stub status, campaign sync spec, backfill ambiguity, promotion KPI, non-Meta mode, checkpoint test wording | PLAN.md v6 |

**Total issues found and resolved: 33 plan-level + implementation gaps identified for Phase 0**

---

## Current Plan State (v6)

### Structure (~1150 lines)

```
PLAN.md v6
├── Why V2 (8 problems)
├── V2 Principles (7 principles, +2 new: incremental & measurable, learn from outcomes)
├── Current V1 Pipeline
├── Prerequisites (P0-1 through P2-2) — 12 schema/infra fixes
├── V2 Feature Breakdown
│   ├── 1. Worker-First Execution
│   ├── 2. Multi-Size Generation
│   ├── 3. Asset-Aware Prompt Construction
│   ├── 4. Multi-Color Mode
│   ├── 5. Headline ↔ Offer Variant Congruence
│   ├── 6. Methodical Review (3-stage pipeline + human feedback loop)
│   ├── 7. Pydantic Prompt Models
│   ├── 8. "Roll the Dice" Template Selection
│   ├── 9. Creative Genome (Thompson Sampling + stratified attribution)
│   ├── 10. Reward Signal Architecture (maturation windows)
│   ├── 11. Experimentation Framework (Bayesian stopping rules)
│   ├── 12. Monitoring & Drift Detection
│   └── 13. V2 Pipeline Graph (11 nodes)
├── Implementation Phases (0-8 with success gates)
├── Database Schema Additions
├── New Services File Map
└── Cost Impact Summary
```

### Implementation Phases

| Phase | Name | Success Gate |
|-------|------|-------------|
| **0** | Prerequisites | All migrations pass, worker routing works, existing data intact |
| **1** | Core V2 Pipeline | V2 generates ads via worker with multi-size + multi-color, completion rate >= 95% |
| **2** | Asset-Aware + Congruence | Asset context wired to prompts, congruence scores populated, review scores improve |
| **3** | 3-Stage Review | Fast defect scan + full rubric + conditional 2nd opinion, cost savings ~30% |
| **4** | Human Feedback | Override tracking works, threshold calibration produces config versions |
| **5** | Creative Genome MVP | Thompson Sampling live, element scores updating, cold-start working |
| **6** | Reward Signals | Performance attribution via meta_ad_mapping, maturation windows respected |
| **7** | Experimentation | A/B test creation + Bayesian analysis, P(best) stopping rule works |
| **8** | Autonomous Intelligence | Few-shot exemplars, predictive fatigue, competitive whitespace |

---

## Files Changed

| File | Change | Status |
|------|--------|--------|
| `docs/plans/ad-creator-v2/PLAN.md` | v2 → v3: 6 Codex round 2 fixes | NOT committed |
| `docs/plans/ad-creator-v2/CHECKPOINT_002.md` | Added Codex round 1 review section | NOT committed |
| `docs/plans/ad-creator-v2/CHECKPOINT_003.md` | This file (Codex round 2 review) | NOT committed |

---

## Execution Protocol

Phase 0 execution will follow the **Execution Protocol** added to PLAN.md:

- **Chunk-capped at <= 50K tokens** per implementation chunk
- **Checkpoint after every chunk** using the standard template in PLAN.md
- **Post-phase review after Phase 0 completes** (`/post-plan-review`) — must produce PASS before Phase 1
- **No phase advancement** unless: success gate passes, acceptance tests pass, checkpoint written, review PASS
- Phase 0 chunks will be numbered `P0-C1`, `P0-C2`, etc.

### Recommended Next Action

Per Codex's final assessment: **Implement Phase 0 with explicit acceptance tests**, then proceed to Phase 1.

Phase 0 scope:
1. Schema migrations (all prerequisites from PLAN.md)
2. Worker routing fix — unknown `job_type` hard-fails (`scheduler_worker.py:577`)
3. Campaign objective enrichment — meta sync populates `campaign_objective` (`meta_ads_service.py:~1035`)
4. Acceptance tests for both code changes (see Phase 0 success gate in PLAN.md)
5. Chunk checkpoint(s) using standard template
6. Post-phase review → PASS

### Open Questions

1. **Migration file naming** — Single file (`migrations/YYYY-MM-DD_ad_creator_v2_prerequisites.sql`) or one file per fix?

2. **V2 pipeline file structure** — Plan specifies `viraltracker/pipelines/ad_creation_v2/` as a separate directory. Confirm this matches the existing pattern (V1 is at `viraltracker/pipelines/ad_creation/`).

---

## Key File Locations

| File | Purpose |
|------|---------|
| `docs/plans/ad-creator-v2/PLAN.md` | V2 technical architecture (v6, ~1150 lines) |
| `docs/plans/ad-creator-v2/CREATIVE_INTELLIGENCE.md` | Marketing science / review rubric |
| `docs/plans/ad-creator-v2/CHECKPOINT_001.md` | Session 1: V1 analysis + initial planning |
| `docs/plans/ad-creator-v2/CHECKPOINT_002.md` | Session 2: Expert review + Codex round 1 |
| `docs/plans/ad-creator-v2/CHECKPOINT_003.md` | Session 3: Codex round 2 + implementation-ready |
| `viraltracker/pipelines/ad_creation/` | V1 pipeline (unchanged) |
| `viraltracker/services/ad_creation_service.py` | V1 service (Phase 0 changes needed) |
| `viraltracker/worker/scheduler_worker.py` | Worker routing (Phase 0 changes needed) |
| `sql/migration_ad_creation.sql` | Existing schema (Phase 0 migration targets) |
