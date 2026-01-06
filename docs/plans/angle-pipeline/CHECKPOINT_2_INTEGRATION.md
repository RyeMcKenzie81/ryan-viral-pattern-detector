# Angle Pipeline - Checkpoint 2: Belief Reverse Engineer Integration

**Date**: 2026-01-05
**Phase**: 2 of 9
**Status**: COMPLETE

## Summary

Integrated the Angle Pipeline with the Belief Reverse Engineer pipeline. The pipeline now automatically extracts research signals from Reddit and creates `angle_candidates` for later promotion to `belief_angles`.

## What Was Built

### 1. InsightSynthesizer Class (`belief_analysis_service.py`)

New class that synthesizes reddit_bundle signals into angle candidates:

```python
class InsightSynthesizer:
    """Synthesizes Reddit research signals into angle candidates."""

    def synthesize_candidates_from_bundle(
        self,
        reddit_bundle: Dict[str, Any],
        product_id: UUID,
        source_run_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Extract angle candidates from a reddit_bundle."""
```

**Methods**:
- `synthesize_candidates_from_bundle()` - Main entry point
- `_extract_pain_candidates()` - Pain signals → pain_signal candidates
- `_extract_pattern_candidates()` - Patterns → pattern candidates
- `_extract_jtbd_candidates()` - JTBD → jtbd candidates
- `_extract_solution_failure_candidates()` - Solution failures → ump candidates

### 2. InsightSynthesisNode (`belief_reverse_engineer.py`)

New pipeline node (8.5) that runs after UMPUMSUpdaterNode:

```python
@dataclass
class InsightSynthesisNode(BaseNode[BeliefReverseEngineerState]):
    """Node 8.5: Synthesize extracted signals into angle candidates."""

    async def run(self, ctx) -> "ClaimRiskAndBoundaryNode":
        # Delegates to InsightSynthesizer.synthesize_candidates_from_bundle()
```

### 3. State Updates (`states.py`)

Added to `BeliefReverseEngineerState`:
- `candidates_created: int = 0`
- `candidates_updated: int = 0`
- `synthesis_results: Optional[Dict] = None`

### 4. Pipeline Output Enhancement

The RendererNode now includes `angle_pipeline` in its output:
```python
"angle_pipeline": {
    "candidates_created": ctx.state.candidates_created,
    "candidates_updated": ctx.state.candidates_updated,
    "synthesis_results": ctx.state.synthesis_results,
}
```

## Pipeline Flow (Updated)

```
Draft Mode (1-4):
  FetchProductContext → ParseMessages → LayerClassifier → DraftCanvasAssembler

Research Mode (5-8.5):
  → RedditResearchPlan → RedditScrape → ResearchExtractor → UMPUMSUpdater
  → InsightSynthesis (NEW - creates angle_candidates)

Final (9-11):
  → ClaimRiskAndBoundary → IntegrityCheck → Renderer
```

## Signal → Candidate Mapping

| reddit_bundle field | Candidate Type | Evidence Type |
|---------------------|----------------|---------------|
| `extracted_pain[]` | `pain_signal` | `pain_signal` |
| `pattern_detection.triggers[]` | `pattern` | `pattern` |
| `pattern_detection.worsens[]` | `pattern` | `pattern` |
| `pattern_detection.improves[]` | `pattern` | `pattern` |
| `pattern_detection.helps[]` | `pattern` | `pattern` |
| `pattern_detection.fails[]` | `pattern` | `pattern` |
| `jtbd_candidates.functional[]` | `jtbd` | `jtbd` |
| `jtbd_candidates.emotional[]` | `jtbd` | `jtbd` |
| `jtbd_candidates.identity[]` | `jtbd` | `jtbd` |
| `extracted_solutions_attempted[]` | `ump` | `solution` |

## Deduplication Behavior

The synthesizer handles duplicates automatically:

1. **First occurrence**: Creates new candidate
2. **Same signal again**: Finds existing candidate, adds evidence
3. **Frequency score**: Updates automatically based on evidence count

Tested and verified:
```
=== FIRST RUN ===
Created: 1, Updated: 0

=== SECOND RUN (same data) ===
Created: 0, Updated: 1

Candidates in DB: 1
Evidence count: 1 (from second run)
```

## Testing Results

Full integration test with sample reddit_bundle:
```
Candidates created: 13
By type: {'pain_signal': 2, 'pattern': 6, 'jtbd': 3, 'ump': 2}
```

All syntax checks pass:
```bash
python3 -m py_compile viraltracker/pipelines/belief_reverse_engineer.py
python3 -m py_compile viraltracker/services/belief_analysis_service.py
python3 -m py_compile viraltracker/pipelines/states.py
```

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/belief_analysis_service.py` | Added `InsightSynthesizer` class (~350 lines) |
| `viraltracker/pipelines/belief_reverse_engineer.py` | Added `InsightSynthesisNode`, updated graph |
| `viraltracker/pipelines/states.py` | Added synthesis tracking fields |

## What's Next (Phase 3)

Phase 3 will add the other 4 input sources to the pipeline:

1. **Reddit Research** (direct scraping) → `reddit_research` source
2. **Ad Performance Analysis** → `ad_performance` source
3. **Competitor Research** → `competitor_research` source
4. **Brand/Consumer Research** → `brand_research` source

Each source will use the same `AngleCandidateService.get_or_create_candidate()` pattern for automatic deduplication.

## Architecture Diagram

```
                    ┌─────────────────────────┐
                    │  Belief Reverse Engineer │
                    │       Pipeline           │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   InsightSynthesisNode   │
                    │       (Node 8.5)         │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   InsightSynthesizer     │
                    │  (belief_analysis_svc)   │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  AngleCandidateService   │
                    │  - get_or_create_candidate
                    │  - add_evidence          │
                    │  - find_similar_candidate│
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │     angle_candidates     │
                    │          (DB)            │
                    └─────────────────────────┘
```

## Notes

- The node is **non-fatal**: if synthesis fails, the pipeline continues to risk checking
- Source type is always `belief_reverse_engineer` for this integration
- Tags include `reddit_research` for filtering later
- The trace_map records synthesis results for audit trail
