# Angle Pipeline - Planning Complete Checkpoint

**Date**: 2026-01-05
**Status**: Planning complete, ready to implement Phase 1

## Plan Location
`/Users/ryemckenzie/.claude/plans/starry-dazzling-hamming.md`

## Summary

We created a comprehensive plan for the **Unified Angle Pipeline + Scheduler Belief-First Integration** with:

- **10 phases** with checkpoints after each
- **5 input sources**: Belief RE, Reddit Research, Ad Performance, Competitor Research, Brand/Consumer Research
- **2 new tables**: `angle_candidates`, `angle_candidate_evidence`
- **Pattern Discovery Engine** with embeddings and clustering
- **Unique Mechanism support** (UMP/UMS) for mature markets
- **Pydantic-Graph integration** for Logfire visibility
- **Configurable settings** for thresholds

## Key Decisions Made

1. **LLM Models**: Haiku for similarity/comparison, Sonnet for synthesis, OpenAI embeddings
2. **Auto-Promote**: No - require human approval but FLAG high-confidence candidates
3. **Scheduler Limit**: 50 ads max per run (configurable)
4. **Evidence Weighting**: 2x for quotes, 0.5x for inferred (test later)
5. **Stale Threshold**: 30 days default (configurable)

## Files to Create/Modify

### New Files
- `migrations/2026-01-XX_angle_candidates.sql`
- `viraltracker/services/angle_candidate_service.py`
- `viraltracker/services/pattern_discovery_service.py`
- `viraltracker/ui/pages/32_💡_Research_Insights.py`
- `viraltracker/pipelines/angle_candidate_extraction.py`

### Modified Files
- 12+ files across pipelines, services, and UI pages

## Pre-Implementation Setup
Before starting Phase 1, install Logfire MCP:
```bash
npx @anthropic-ai/mcp-cli install logfire
```

## Next Step
Start Phase 1: Database + Service (foundation)
- Create migration
- Create AngleCandidateService
- Add Pydantic models

---

## Prompt for New Context

Use this prompt to resume:

```
Please read the Angle Pipeline plan and checkpoint:
1. /Users/ryemckenzie/.claude/plans/starry-dazzling-hamming.md
2. /Users/ryemckenzie/projects/viraltracker/docs/plans/angle-pipeline/CHECKPOINT_0_PLANNING_COMPLETE.md

We are ready to start implementation. Begin with Phase 1: Database + Service (foundation).

Key context:
- This creates a unified system where research insights flow into testable angles
- 5 input sources → angle_candidates table → Research Insights UI → belief_angles → Ad Creator/Scheduler
- Follow testing protocols in each phase before moving on
- Create checkpoint files after each phase
```
