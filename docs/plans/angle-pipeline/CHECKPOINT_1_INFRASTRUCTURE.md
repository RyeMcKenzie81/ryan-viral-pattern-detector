# Angle Pipeline - Checkpoint 1: Infrastructure Complete

**Date**: 2026-01-05
**Status**: Phase 1 Complete

---

## Completed

- [x] Configured Logfire MCP server with correct read token
- [x] Created database migration: `migrations/2026-01-05_angle_candidates.sql`
- [x] Added Pydantic models to `viraltracker/services/models.py`:
  - `CandidateType` enum
  - `CandidateSourceType` enum
  - `CandidateStatus` enum
  - `CandidateConfidence` enum
  - `EvidenceType` enum
  - `AngleCandidateEvidence` model
  - `AngleCandidate` model
- [x] Created `viraltracker/services/angle_candidate_service.py` with methods:
  - `create_candidate()` - Create new candidate
  - `get_candidate()` - Get candidate with evidence
  - `get_candidates_for_product()` - List candidates with filtering
  - `update_candidate()` - Update candidate fields
  - `delete_candidate()` - Delete candidate (cascades to evidence)
  - `add_evidence()` - Add evidence and update frequency
  - `get_evidence_for_candidate()` - List evidence
  - `find_similar_candidate()` - Simple text-matching for deduplication
  - `merge_candidates()` - Merge candidates and move evidence
  - `update_frequency_score()` - Recalculate from evidence count
  - `promote_to_angle()` - Promote to belief_angles
  - `reject_candidate()` - Mark as rejected
  - `create_candidate_with_evidence()` - Bulk create
  - `get_or_create_candidate()` - Dedup-aware creation
  - `get_candidate_stats()` - Statistics for product
- [x] Ran migration in Supabase (user ran manually)
- [x] All tests passed

---

## Test Results

```
Using product: Core Deck (911896fc-6b80-4c99-aa91-7fc828df8549)
✓ Created candidate: 9adcb4f7-12e4-4db1-9c76-da501c784a75
✓ Added evidence: 63f7065d-c183-40b0-bab4-e192932c4e46
✓ Get candidates returns 1 items (1 test)
✓ Frequency score: 1, Confidence: LOW
✓ Stats: {'total': 1, 'by_status': {'candidate': 1}, 'by_source': {'test': 1}, 'by_confidence': {'LOW': 1}}
✓ Cleaned up test candidate

✅ All Phase 1 tests passed!
```

---

## Files Created/Modified

| File | Change |
|------|--------|
| `migrations/2026-01-05_angle_candidates.sql` | NEW - Database migration |
| `viraltracker/services/models.py` | Added Angle Pipeline models (~140 lines) |
| `viraltracker/services/angle_candidate_service.py` | NEW - Service (~550 lines) |
| `~/.claude/settings.json` | Updated Logfire read token |

---

## Database Tables Created

### `angle_candidates`
- Unified staging table for research insights
- Links to `products`, `brands`, `belief_angles`
- Tracks source, frequency, confidence, status

### `angle_candidate_evidence`
- Evidence supporting candidates
- Links to candidates (cascading delete)
- Tracks source, engagement, LLM confidence

---

## Next Phase: Phase 2 - Connect Belief Reverse Engineer

**Files to modify:**
- `viraltracker/pipelines/belief_reverse_engineer.py` - Add `InsightSynthesisNode`
- `viraltracker/services/belief_analysis_service.py` - Add synthesis methods

**Goal:** Extract signals from `reddit_bundle` and create angle candidates automatically after each Belief RE run.

---

## Resume Prompt

```
Please read the Angle Pipeline checkpoints and continue with Phase 2:

1. /Users/ryemckenzie/.claude/plans/starry-dazzling-hamming.md (main plan)
2. /Users/ryemckenzie/projects/viraltracker/docs/plans/angle-pipeline/CHECKPOINT_1_INFRASTRUCTURE.md

Phase 1 (Infrastructure) is complete. Continue with Phase 2:
- Add InsightSynthesisNode to belief_reverse_engineer.py pipeline
- Add synthesis methods to belief_analysis_service.py
- Extract signals from reddit_bundle → angle_candidates
- Test end-to-end flow

Key context:
- AngleCandidateService is ready at viraltracker/services/angle_candidate_service.py
- Models are in viraltracker/services/models.py (AngleCandidate, AngleCandidateEvidence)
- Follow thin-tools pattern: nodes call service methods
```
