# Checkpoint 10: Documentation & Logfire Integration (Final)

**Date:** 2026-01-05
**Phase:** 10 of 10
**Status:** Complete

## Summary

Completed the Angle Pipeline implementation with documentation updates, a pydantic-graph for Logfire visibility, and configurable settings in the Platform Settings page.

## Changes Made

### 1. CLAUDE.md Documentation

Added comprehensive "Angle Pipeline Feature" section including:
- Input sources table (5 sources → angle_candidates)
- Key services documentation (AngleCandidateService, PatternDiscoveryService)
- Database tables overview
- Scheduler integration examples
- UI pages reference
- Workflow summary

### 2. Extraction Pipeline Graph (`viraltracker/pipelines/angle_candidate_extraction.py`)

**New Pydantic Graph for Logfire Tracing:**

```
ExtractionState
├── product_id, source_type, source_data
├── extracted_candidates, similarity_results
├── saved_candidates, merged_candidates
└── stats, error tracking

Nodes:
1. ExtractFromSourceNode - Parse source data by type
2. SimilarityCheckNode - Find existing similar candidates
3. SaveCandidatesNode - Create new or merge evidence
```

**Features:**
- Extraction logic for all 5 source types
- Automatic similarity detection and merging
- Full Logfire trace visibility
- Helper function `extract_candidates()` for easy invocation

**Source Type Extractors:**
- `_extract_from_bre()` - Pain signals, JTBDs, hypotheses
- `_extract_from_reddit()` - Posts, patterns
- `_extract_from_competitor()` - UMPs, UMSs, angles
- `_extract_from_brand()` - Quotes, patterns
- `_extract_from_ad_performance()` - Winning hooks, hypotheses

### 3. Platform Settings (`viraltracker/ui/pages/64_⚙️_Platform_Settings.py`)

**New "Angle Pipeline" Tab with Configurable Settings:**

| Setting | Key | Default | Description |
|---------|-----|---------|-------------|
| Stale Threshold | `angle_pipeline.stale_threshold_days` | 30 | Days without evidence = stale |
| Evidence Decay | `angle_pipeline.evidence_decay_halflife_days` | 60 | Frequency scoring decay |
| Min Candidates | `angle_pipeline.min_candidates_pattern_discovery` | 10 | Threshold for pattern discovery |
| Max Ads/Run | `angle_pipeline.max_ads_per_scheduled_run` | 50 | Scheduler limit |
| Cluster Epsilon | `angle_pipeline.cluster_eps` | 0.3 | DBSCAN clustering sensitivity |
| Min Cluster Size | `angle_pipeline.cluster_min_samples` | 2 | Minimum pattern size |

**Storage:** Uses `system_settings` table with upsert on `key` column.

## Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| `CLAUDE.md` | MODIFIED | Added Angle Pipeline section |
| `viraltracker/pipelines/angle_candidate_extraction.py` | NEW | Extraction graph |
| `viraltracker/ui/pages/64_⚙️_Platform_Settings.py` | MODIFIED | Added Angle Pipeline tab |

## Logfire Integration

The extraction pipeline provides structured traces:

```
[Trace: angle_candidate_extraction]
├── ExtractFromSourceNode
│   └── source_type: "belief_reverse_engineer"
│   └── extracted: 5 candidates
├── SimilarityCheckNode
│   └── to_merge: 2
│   └── to_create: 3
└── SaveCandidatesNode
    └── saved: 3
    └── merged: 2
```

**To view in Logfire:**
1. Run extraction via UI or `extract_candidates()`
2. Open Logfire dashboard
3. Filter by `angle_candidate_extraction`
4. View node timings and stats

## Testing Notes

### Manual Testing:
1. Navigate to Platform Settings → Angle Pipeline tab
2. Verify all 6 settings display correctly
3. Change a setting and verify it saves
4. Verify settings summary updates

### Extraction Pipeline Testing:
```python
from viraltracker.pipelines.angle_candidate_extraction import extract_candidates
from uuid import UUID

result = await extract_candidates(
    product_id=UUID("your-product-id"),
    source_type="belief_reverse_engineer",
    source_data={
        "pain_signals": [{"signal": "Test pain", "explanation": "..."}],
        "jtbds": [],
        "hypotheses": []
    }
)
print(result)  # {"status": "success", "saved_count": 1, ...}
```

---

## Angle Pipeline - Complete Implementation Summary

### All Phases Completed:

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Infrastructure (tables, AngleCandidateService) | ✅ |
| 2 | BeliefReverseEngineer integration (InsightSynthesizer) | ✅ |
| 3 | Reddit Research integration | ✅ |
| 4 | Ad Performance integration | ✅ |
| 5 | Competitor Research integration | ✅ |
| 6 | Brand Research integration | ✅ |
| 7 | Research Insights UI | ✅ |
| 8 | Scheduler Belief-First Support | ✅ |
| 9 | Pattern Discovery Engine | ✅ |
| 10 | Documentation & Logfire Integration | ✅ |

### Key Deliverables:

1. **Unified Candidate Table** - All 5 research sources feed into `angle_candidates`
2. **Evidence Tracking** - Full trail in `angle_candidate_evidence`
3. **Pattern Discovery** - OpenAI embeddings + DBSCAN clustering
4. **Research Insights UI** - View, filter, promote candidates and patterns
5. **Scheduler Integration** - Belief-first modes (plan, angles)
6. **Configurable Settings** - All thresholds adjustable in UI
7. **Logfire Visibility** - Pydantic-graph for extraction tracing

### Database Tables Created:
- `angle_candidates` (with `embedding` column)
- `angle_candidate_evidence`
- `discovered_patterns`

### Services Created:
- `AngleCandidateService`
- `PatternDiscoveryService`

### UI Pages:
- `32_💡_Research_Insights.py` - Main insights UI
- `64_⚙️_Platform_Settings.py` - Added Angle Pipeline tab

### Pipeline:
- `angle_candidate_extraction.py` - Extraction graph

---

## Future Enhancements (Tech Debt)

See `docs/TECH_DEBT.md` for tracked improvements:
- Angle performance feedback loop
- Winner/loser automatic tagging
- Cross-product pattern discovery
- Embedding caching optimization
