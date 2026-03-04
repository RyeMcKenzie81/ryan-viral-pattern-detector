# Phase 7A: Winner Evolution — Implementation Checkpoint

**Date:** 2026-02-15
**Branch:** `feat/ad-creator-v2-phase0`
**Status:** Code complete — pending post-plan review + UI validation

## What Was Implemented

Phase 7A adds the Winner Evolution System: identify winning ads and systematically generate improved variants via three evolution modes.

### New Files (3)

| File | Purpose |
|------|---------|
| `migrations/2026-02-15_winner_evolution.sql` | Schema: `ad_lineage` table + `winner_evolution` job type in CHECK constraint |
| `viraltracker/services/winner_evolution_service.py` | Core service: winner detection, info-gain weighted variable selection, 3 evolution modes, lineage recording, performance comparison |
| `tests/services/test_winner_evolution_service.py` | 39 unit tests covering all pure functions and async methods |

### Modified Files (2)

| File | Changes |
|------|---------|
| `viraltracker/worker/scheduler_worker.py` | +`execute_winner_evolution_job()` handler, +routing for `'winner_evolution'` job type |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | +"Evolve This Ad" button for approved ads with mode selection modal, session state for evolution workflow |

### Test Results

- **39 new tests** — all passing
- **120 related tests** (genome + scoring + evolution) — all passing
- **0 regressions**

### Key Design Decisions

1. **Service as job builder**: `WinnerEvolutionService` wraps `run_ad_creation_v2()` — no new pydantic-graph needed
2. **ad_lineage table** tracks parent→child with evolution_mode, variable_changed, iteration_round, ancestor chain
3. **Information-gain weighted variable selection**: uncertainty(Beta variance) × priority_weight → pick highest gain
4. **Priority weights**: hook_type (0.9) > awareness_stage (0.85) > template_category (0.6) > color_mode (0.4)
5. **Winner criteria**: reward_score >= 0.65 OR top-quartile CTR/ROAS, with >= 1000 impressions
6. **Iteration limits**: max 5 per winner, max 3 rounds on ancestor
7. **Anti-fatigue uses FatigueDetector signals**: frequency >= 2.5 OR CTR declining > 10% WoW
8. **Cross-size expansion** checks existing lineage to avoid duplicate sizes
9. **Evolution outcomes tracking**: `update_evolution_outcomes()` compares child vs parent reward after maturation
10. **UI pattern**: follows existing "Create Sizes" and "Smart Edit" button patterns in Ad History page

### Evolution Modes

| Mode | What Changes | Variants | Trigger |
|------|-------------|----------|---------|
| **Winner Iteration (a)** | ONE element (highest info gain) | 1 | Manual via UI |
| **Anti-Fatigue Refresh (c)** | Template + color (same psychology) | 3 | Fatigue signals detected |
| **Cross-Size Expansion (d)** | Canvas size only | 1-2 per untested size | Manual via UI |

### UI Validation Tests (TODO before merge)

| # | Test | Where | Priority | Pass? |
|---|------|-------|----------|-------|
| 1 | Run migration `2026-02-15_winner_evolution.sql` | Supabase SQL editor | **MUST** | |
| 2 | "Evolve This Ad" button appears on approved ads in Ad History | Ad History page | HIGH | |
| 3 | Evolution options show winner/non-winner status correctly | Ad History page | HIGH | |
| 4 | Winner iteration submits and generates evolved ad | Ad History → worker | HIGH | |
| 5 | Cross-size expansion generates untested sizes | Ad History → worker | MEDIUM | |
| 6 | Iteration limits block evolution after max attempts | Ad History page | MEDIUM | |

### Plan Source

`docs/plans/ad-creator-v2/PLAN.md` Section 11 (modes a, c, d)
`docs/plans/ad-creator-v2/PHASE7_PLAN.md` detailed implementation plan
