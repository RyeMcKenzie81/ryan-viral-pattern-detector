# Ad Creator V2 — Phase 0 Execution Prompt

> Paste this into a new Claude Code context window to begin Phase 0 implementation.

---

## Prompt

```
I need you to implement Phase 0 of the Ad Creator V2 plan.

## Required Reading (load these first)

1. `docs/plans/ad-creator-v2/PLAN.md` — the full V2 plan (v14, ~1340 lines). Read the entire file. Pay special attention to:
   - **Prerequisites section** (P0-1 through P2-1, plus P0-4) — these are the schema/code changes
   - **Phase 0 task list and success gate** (9 criteria, all must pass)
   - **Execution Protocol** — chunk caps, checkpoint template, post-phase review requirement
   - **P1-4 Campaign Sync** — three-part fix (populate meta_campaigns, enrich perf records, historical backfill)
   - **Template Scoring Pipeline (Section 8)** — P0-4 adds `brands.template_selection_config` JSONB

2. `docs/plans/ad-creator-v2/CHECKPOINT_004.md` — latest checkpoint, has the recommended Phase 0 chunk breakdown

3. `CLAUDE.md` — project development guidelines (architecture, patterns, testing workflow)

## Phase 0 Scope (from CHECKPOINT_004)

**P0-C1: Schema Migrations**
- P0-1: Add `ad_creation_v2` (and future Phase 6-7 job types) to `scheduled_jobs.job_type` CHECK constraint
- P0-2: Add `canvas_size` column to `generated_ads` + composite key migration (drop + recreate unique index)
- P0-3: Add `template_id` UUID FK to `product_template_usage` + backfill from `scraped_templates.storage_path` (use DISTINCT ON tie-breaking) + audit queries
- P0-4: Add `template_selection_config` JSONB to `brands` table (default: `{"min_asset_score": 0.0}`)
- P1-4: Add `campaign_objective` column to `meta_ads_performance`
- Add `metadata` JSONB column to `scheduled_job_runs`

**P0-C2: Code Changes**
- Worker routing: add `ad_creation_v2` case to `scheduler_worker.py` job dispatch
- Hard-fail: unknown `job_type` must raise error + log, not silently fall through to V1
- Stub handler: `execute_ad_creation_v2_job()` — marks run as `completed` with `metadata={"stub": true, "reason": "V2 pipeline not yet implemented"}`
- Campaign sync Part A: populate `meta_campaigns` table from Meta API during performance sync
- Campaign sync Part B: enrich `meta_ads_performance` records with `campaign_objective` from `meta_campaigns.objective` via join
- Campaign sync error handling: if Meta `/campaigns` API call fails, set `campaign_objective = 'UNKNOWN'` and continue (non-fatal)
- Field naming: update `diagnostic_engine.py` to read `campaign_objective` instead of `objective` (lines 170, 175, 987, 1003)
- Fix `save_generated_ad()` to persist `canvas_size`

**P0-C3: Acceptance Tests**
All 9 Phase 0 gate criteria must pass (see PLAN.md Phase 0 success gate).

## Execution Rules

1. Follow the Execution Protocol in PLAN.md exactly — chunk-capped at 50K tokens, checkpoint after every chunk
2. Single migration file: `migrations/YYYY-MM-DD_ad_creator_v2_phase0.sql`
3. `python3 -m py_compile` on every changed Python file
4. After all chunks complete, run `/post-plan-review` for the PASS verdict
5. Do NOT start Phase 1. Phase 0 ends at the post-phase review PASS.

## Key Files You'll Modify

| File | Changes |
|------|---------|
| `viraltracker/worker/scheduler_worker.py` | Job routing, hard-fail, stub handler |
| `viraltracker/services/meta_ads_service.py` | Campaign sync (populate meta_campaigns + enrich perf records) |
| `viraltracker/services/ad_creation_service.py` | `save_generated_ad()` canvas_size |
| `viraltracker/services/ad_intelligence/diagnostic_engine.py` | `objective` → `campaign_objective` |
| `sql/create_scheduler_tables.sql` | Reference for CHECK constraint syntax |
| New: `migrations/YYYY-MM-DD_ad_creator_v2_phase0.sql` | All schema migrations |

Start with P0-C1 (migrations). Read the plan first.
```
