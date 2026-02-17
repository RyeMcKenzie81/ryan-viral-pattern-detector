# Phase 7A: Winner Evolution — Plan Checkpoint

**Date:** 2026-02-15
**Branch:** `feat/ad-creator-v2-phase0`
**Status:** Plan approved (Phases 1-3). Starting Phase 4 (Build).

## Approved Scope

- `ad_lineage` table for parent→child evolution tracking
- `WinnerEvolutionService` with 3 modes: Winner Iteration (a), Anti-Fatigue Refresh (c), Cross-Size Expansion (d)
- Information-gain weighted Thompson Sampling for variable selection
- Iteration limits: max 5 per winner, max 3 rounds on ancestor
- `winner_evolution` scheduler job type + worker handler
- "Evolve This Ad" UI button
- Unit tests

## Architecture Decision

Python service + scheduler job (not pydantic-graph). Evolution service is a job builder wrapping `run_ad_creation_v2()`.

## Build Order

1. Migration: `ad_lineage` table + job type constraint
2. Service: `WinnerEvolutionService` (winner detection, variable selection, evolution execution, lineage)
3. Worker: `execute_winner_evolution_job()` + routing
4. Tests: Unit tests for all service methods
5. UI: "Evolve This Ad" button + mode selection

## Full Plan

See `PHASE7_PLAN.md` for complete details.
