# Ad Creator V2 — Phase 1 Prompt

> Paste this into a new Claude Code context window to begin Phase 1.

---

## Prompt

```
I'm starting Phase 1 of the Ad Creator V2 plan: Foundation (Worker + Pydantic Prompts + Scoring Pipeline).

## Required Reading

1. `docs/plans/ad-creator-v2/PLAN.md` — full V2 plan (Phase 1 section starts at line ~1223)
2. `docs/plans/ad-creator-v2/CHECKPOINT_005.md` — Phase 0 completion state
3. `CLAUDE.md` — project guidelines

## Branch

Continue on `feat/ad-creator-v2-phase0` (or create a new branch if you prefer — ask me).

## Phase 0 Context (already done)

- Schema migrations applied (canvas_size, template_id FK, template_selection_config, campaign_objective, metadata on job runs, scraped_template_ids, template_source)
- Worker routing: `ad_creation_v2` → stub handler (marks run completed with `metadata.stub = true`)
- Campaign sync + objective enrichment working
- All browser tests passed
- Branch: `feat/ad-creator-v2-phase0`, fully pushed

## Phase 1 Scope

### 1. Create `ad_creation_v2/` directory structure
New pipeline directory under `viraltracker/pipelines/` (or wherever V1 lives — check first).

### 2. Port V1 pipeline to V2 directory
Copy V1 pipeline files into V2 directory. Do NOT modify V1 — it must keep working in parallel.

### 3. Replace dict-literal prompts with Pydantic models
V1 builds prompts as raw dicts/strings. V2 should use Pydantic models for structured, validated prompt generation.

### 4. Implement full `execute_ad_creation_v2_job()` logic
Replace the Phase 0 stub in `scheduler_worker.py` with real V2 pipeline execution. The stub is at the `ad_creation_v2` case in the job type routing.

### 5. Build `template_scoring_service.py`
- `TemplateScorer` interface (base class for all scorers)
- `select_templates()` function that runs all scorers and returns a scored list
- Scores are draw-order (not ranked) with composite + per-scorer breakdown

### 6. Implement Phase 1 scorers
- `AssetMatchScorer` — inline set intersection (see Section 8f in PLAN.md for prefetch pattern)
- `UnusedBonusScorer` — binary: 1.0 if unused for this product, 0.3 if used
- `CategoryMatchScorer` — 1.0 if template.category matches request, 0.5 if "All"

### 7. Build minimal V2 UI page
- Submit V2 job (with template scoring)
- View results
- "Roll the dice" and "Smart select" presets

### 8. Verify V2 matches V1 quality

## Success Gate

V2 generates ads end-to-end via worker. Approval rate within 5% of V1 on same templates (N >= 30 paired comparisons, same brand/product/template combos). Job completion rate >= 95% (measured over >= 20 consecutive jobs). Template scoring pipeline returns scored list with composite + per-scorer breakdown for all three Phase 1 scorers.

## Approach

Start with /plan-workflow to break this into chunks. This is a large phase — plan carefully before coding. Read the V1 pipeline code first to understand what you're porting.
```
