# Ad Creator V2 — Checkpoint 004: Final Consistency Pass

> **Date**: 2026-02-13
> **Status**: Implementation-ready (PLAN.md v14 — Template Scoring Pipeline fully specified)
> **Follows**: CHECKPOINT_003 (Codex rounds 2-4 + hardening pass)
> **PLAN.md**: Updated to v14 (~1340 lines) — round 5-6 fixes + Template Scoring Pipeline + 21 hardening fixes

---

## What Was Done This Session

### Codex Round 5 Review (5 findings)

| # | Severity | Finding | Fix Applied |
|---|----------|---------|-------------|
| 1 | **P1** | `system_alerts` referenced in P1-4 error handling (line 239) but table not created until Phase 6 (line 1098) | Changed to `logger.warning()` + `scheduled_job_runs.metadata` for error tracking; added note that `system_alerts` is Phase 6 |
| 2 | **P1** | Unknown job_type test says "marks run as failed" but mocked dict has no persisted run record | Rewritten: pass criteria are (a) error logged, (b) no V1 execution, (c) exception/error return — not a DB status change |
| 3 | **P1** | Non-Meta mode says experiments unavailable, but Phase 7 gate requires >= 5 experiments per active brand | Scoped to "per active **Meta-connected** brand"; non-Meta brands exempt from experiment count |
| 4 | **P2** | Migration Path says "promote when approval rates match" but Phase 5 gate now requires CTR non-inferiority | Aligned Migration Path with Phase 5 gate: Meta brands need CTR + approval, non-Meta need approval only |
| 5 | **P2** | CHECKPOINT_003 says non-Meta test "completes generation" but Phase 0 uses stub handler | Changed to "completes stub run successfully" |

### Codex Round 6 Review (2 findings)

| # | Severity | Finding | Fix Applied |
|---|----------|---------|-------------|
| 1 | **P1** | `diagnostic_engine.py` reads `ad_data.get("objective")` (lines 170, 175, 987, 1003) but plan adds column as `campaign_objective` — objective-aware logic silently returns `None` | Added field naming consistency note to P1-4: choose Option B (update `diagnostic_engine.py` to read `campaign_objective`), added to Phase 0 scope |
| 2 | **P2** | Section 12 success metric says "per brand" but Phase 7 gate correctly scoped to "per Meta-connected brand" | Changed to "per **Meta-connected** brand" |

### Architecture Enhancement: Template Scoring Pipeline

**Problem:** Three existing template-aware services (`template_element_service`, `template_recommendation_service`, `template_evaluation_service`) score templates on different dimensions, but none feed into template selection. Feature 8 ("Roll the Dice") was pure random. These are fundamentally the same operation — `(template, context) → score` — but were treated as separate systems.

**Solution:** Replaced Section 8 with a **pluggable scoring pipeline** that unifies all template selection behind one interface:

- `TemplateScorer` interface with `score(template, context) → float`
- `select_templates()` function: score → gate → weighted random sample
- 8 scorers added progressively across phases (3 in Phase 1, 2 in Phase 3, 1 in Phase 4, 1 in Phase 6, 1 in Phase 8)
- "Roll the Dice" and "Smart Select" become weight presets, not separate features
- Weights start hardcoded, transition to Creative Genome-learned in Phase 6-8
- Asset match doubles as a configurable gate (per brand tier)
- Each scorer wraps an existing service — no rewrites needed

**Files updated:**
- PLAN.md Section 8: Full rewrite (was ~30 lines, now ~100 lines)
- PLAN.md File Structure: Added `template_scoring_service.py`
- Phases 1, 3, 4, 5, 6, 8: Updated to reference scorer additions and scoring pipeline milestones

### Scoring Pipeline Hardening (5 findings)

| # | Severity | Finding | Fix Applied |
|---|----------|---------|-------------|
| 1 | **P1** | `UnusedBonusScorer` input underspecified — candidate query returns `st.*` but scorer needs usage state, causing N+1 per-template queries | Expanded candidate query to include `is_unused`, `times_used`, `has_detection` columns via LEFT JOIN; all scorers read from row dict, zero additional DB queries |
| 2 | **P1** | Awareness/Audience scorers mapped to `template_recommendation_service` which computes scores via per-template Gemini calls — too slow/costly for worker | Changed to pure column comparison: `scraped_templates.awareness_level` (INTEGER 1-5, indexed) and `scraped_templates.target_sex` (TEXT, indexed) — no AI calls |
| 3 | **P1** | Asset gate bypassable: `match_assets_to_template()` returns score=1.0 when detection is missing, so "strict" tiers don't filter unanalyzed templates | Added detection coverage guard: if gate is active (`min_asset_score > 0`) AND `has_detection = false`, template is excluded from candidates |
| 4 | **P1** | `brands.template_selection_config` JSONB referenced but no migration in Phase 0 prerequisites | Added P0-4 migration: `ALTER TABLE brands ADD COLUMN IF NOT EXISTS template_selection_config JSONB DEFAULT '{"min_asset_score": 0.0}'` |
| 5 | **P2** | Algorithm says "weighted random sample" then "return top N" — contradictory; no guard for `sum(weights)==0` | Clarified: weighted random sample WITHOUT replacement via `numpy.random.choice(p=...)`, returns in selection order; `w_total == 0` → uniform random fallback |

### Codex Final Assessment

> "If you patch these, I don't see meaningful planning holes left."

---

## Cumulative Review History

| Round | Source | Findings | Fixed In |
|-------|--------|----------|----------|
| 1 | 4 Expert Agents | 6 critical holes | CHECKPOINT_002 + PLAN.md v2 |
| 2 | Codex round 1 | 10 issues (3 P0, 5 P1, 2 P2) | PLAN.md v2 |
| 3 | Codex round 2 | 6 issues (2 P0, 2 P1, 2 P2) | PLAN.md v3 |
| 4 | Codex round 3 | 2 impl gaps + 1 wording | CHECKPOINT_003 |
| 5 | Codex round 4 | 5 issues (2 P0, 3 P1) | PLAN.md v5 |
| 6 | Hardening pass | 6 items | PLAN.md v6 |
| 7 | Codex round 5 | 5 issues (3 P1, 2 P2) | PLAN.md v7 |
| 8 | Codex round 6 | 2 issues (1 P1, 1 P2) | PLAN.md v8 |
| 9 | Architecture review | Template Scoring Pipeline — unified pluggable scorer architecture replaces "Roll the Dice" | PLAN.md v9 |
| 10 | Scoring pipeline hardening | 5 issues (4 P1, 1 P2) — N+1 query, AI-heavy scorers, detection bypass, missing migration, algorithm spec | PLAN.md v10 |
| 11 | Scoring pipeline round 2 | 6 issues (3 P1, 3 P2) — times_used source, detection_version, AssetMatch prefetch, Phase 3 AI ref, sampling spec, zero-composite | PLAN.md v11 |
| 12 | Scoring pipeline round 3 | 5 issues (4 P1, 1 P2 w/3 sub-items) — empty candidates, SelectionContext contract, null-safe scorers, partial JSONB, doc contradictions | PLAN.md v12 |
| 13 | Scoring pipeline final | 3 issues (2 P1, 1 P2) — nonzero-prob guard, weight validation, empty-selection fallback contract | PLAN.md v13 |
| 14 | Return type + validation | 2 issues (1 P1, 1 P2) — SelectionResult union type, assert → runtime check | PLAN.md v14 |

**Total: 63 issues + 1 architecture enhancement across 14 review rounds**

---

## Current Plan State (v14, ~1340 lines)

### Phase 0 Success Gate (Final Form)

All must pass:
1. All migrations applied without error, existing data intact
2. Worker routes `ad_creation_v2` to stub handler; stub completes with `metadata.stub = true`
3. Unknown `job_type` hard-fails: error logged + no V1 execution + exception/error return (mocked dict test, no DB status change expected)
4. Meta sync persists `campaign_objective` from `meta_campaigns.objective`
5. Campaign sync failure is non-fatal: perf sync completes with `campaign_objective = 'UNKNOWN'`
6. Template backfill: zero ambiguous mappings or documented tolerance
7. Non-Meta brand: V2 job completes stub run (no meta-dependent crash)
8. `python3 -m py_compile` passes on all changed files
9. Checkpoint written + post-phase review PASS

---

## Files Changed

| File | Change | Status |
|------|--------|--------|
| `docs/plans/ad-creator-v2/PLAN.md` | v6 → v14: consistency fixes + Template Scoring Pipeline + 5 rounds hardening | NOT committed |
| `docs/plans/ad-creator-v2/CHECKPOINT_003.md` | Fixed "completes generation" → "completes stub run" | NOT committed |
| `docs/plans/ad-creator-v2/CHECKPOINT_004.md` | This file | NOT committed |

---

## Recommended Next Action

**Begin Phase 0 implementation.** Plan has passed 8 rounds of review with no remaining meaningful holes. Follow the Execution Protocol:

1. **P0-C1**: Schema migrations (job type CHECK, composite key, template_id backfill, campaign_objective column, metadata column)
2. **P0-C2**: Code changes (worker routing + hard-fail, stub handler, campaign sync + enrichment, save_generated_ad canvas_size)
3. **P0-C3**: Acceptance tests against all 9 gate criteria
4. Post-phase review → PASS → Phase 1

---

## Key File Locations

| File | Purpose |
|------|---------|
| `docs/plans/ad-creator-v2/PLAN.md` | V2 technical architecture (v14, ~1340 lines) |
| `docs/plans/ad-creator-v2/CREATIVE_INTELLIGENCE.md` | Marketing science / review rubric |
| `docs/plans/ad-creator-v2/CHECKPOINT_001.md` | Session 1: V1 analysis + initial planning |
| `docs/plans/ad-creator-v2/CHECKPOINT_002.md` | Session 2: Expert review + Codex round 1 |
| `docs/plans/ad-creator-v2/CHECKPOINT_003.md` | Session 3: Codex rounds 2-4 + hardening |
| `docs/plans/ad-creator-v2/CHECKPOINT_004.md` | Session 4: Final consistency pass |
