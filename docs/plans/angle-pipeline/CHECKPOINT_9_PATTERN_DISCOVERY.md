# Checkpoint 9: Pattern Discovery Engine

**Date:** 2026-01-05
**Phase:** 9 of 10
**Status:** Complete

## Summary

Added Pattern Discovery Engine that uses AI embeddings and clustering to automatically discover recurring patterns across angle candidates, enabling identification of emerging themes.

## Changes Made

### 1. Migration (`migrations/2026-01-05_discovered_patterns.sql`)

**New Table: `discovered_patterns`**
```sql
- id, product_id, brand_id
- name, theme_description, pattern_type
- candidate_count, evidence_count, source_breakdown (JSONB)
- confidence_score, novelty_score (0-1 floats)
- status (discovered, reviewed, promoted, dismissed)
- centroid_embedding (VECTOR(1536))
- cluster_radius, candidate_ids (UUID[])
- promoted_angle_id (reference to belief_angles)
```

**Extended: `angle_candidates`**
- Added `embedding VECTOR(1536)` column for similarity search
- Added ivfflat index for fast vector search (if pgvector available)

### 2. PatternDiscoveryService (`viraltracker/services/pattern_discovery_service.py`)

**Embedding Generation:**
- `generate_embedding(text)` - Single text embedding via OpenAI
- `generate_embeddings_batch(texts)` - Batch embedding with rate limiting
- `ensure_candidate_embeddings(product_id)` - Backfill missing embeddings

**Clustering:**
- `cluster_candidates(product_id)` - DBSCAN clustering on embeddings
- Parameters: `eps=0.3`, `min_samples=2`
- Returns cluster dicts with centroids, radius, source breakdown

**Novelty Scoring:**
- `calculate_novelty_score(embedding, product_id)` - Compare to existing angles
- Returns (novelty_score, most_similar_angle)
- Novelty = 1 - max_similarity to existing angles

**Pattern Discovery:**
- `discover_patterns(product_id)` - Full discovery pipeline
- Generates embeddings → Clusters → Calculates novelty → Returns patterns
- Minimum 10 candidates required for discovery

**Pattern CRUD:**
- `save_discovered_pattern(pattern)`
- `get_patterns_for_product(product_id, status)`
- `update_pattern_status(pattern_id, status)`
- `promote_pattern_to_angle(pattern_id, jtbd_framed_id)`

**Status Helpers:**
- `get_discovery_status(product_id)` - Readiness check with counts

### 3. Research Insights UI (`viraltracker/ui/pages/32_💡_Research_Insights.py`)

**New Session State:**
- `ri_view_mode` - "candidates" or "patterns"
- `ri_selected_pattern_id` - For pattern detail view
- `ri_promote_pattern_id` - For pattern promotion workflow

**New UI Components:**
- `render_discovery_status()` - Shows candidate/embedding/pattern counts
- `render_run_discovery()` - Button to trigger pattern discovery
- `render_pattern_card()` - Individual pattern display with actions
- `render_pattern_list()` - Grouped by status (discovered/promoted/dismissed)
- `render_promote_pattern_workflow()` - Promote pattern to angle

**UI Structure:**
- Added tabs: "Candidates" | "Patterns"
- Patterns tab shows discovery status, run button, pattern list
- Pattern cards show confidence, novelty, source breakdown
- Promote and Dismiss actions for discovered patterns

## Technical Details

### Embedding Model
- **Model:** OpenAI `text-embedding-3-small`
- **Dimensions:** 1536
- **Batch Size:** 100 texts per API call

### Clustering Algorithm
- **Algorithm:** DBSCAN (density-based)
- **Distance Metric:** 1 - cosine_similarity
- **Parameters:**
  - `eps=0.3` (max distance between samples)
  - `min_samples=2` (minimum cluster size)

### Novelty Scoring
- Compares pattern centroid to all existing belief_angles
- Generates embeddings for angles on-demand
- Novelty = 1.0 - max(cosine_similarity)
- Score of 1.0 = completely novel, 0.0 = duplicate

### Discovery Thresholds
- **MIN_CANDIDATES_FOR_DISCOVERY:** 10
- **NOVELTY_THRESHOLD_SIMILAR:** 0.85 (considered duplicate)
- **NOVELTY_THRESHOLD_RELATED:** 0.70 (considered related)

## Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| `migrations/2026-01-05_discovered_patterns.sql` | NEW | Pattern storage table |
| `viraltracker/services/pattern_discovery_service.py` | NEW | Discovery service |
| `viraltracker/ui/pages/32_💡_Research_Insights.py` | MODIFIED | Added patterns tab |

## Dependencies

**Python Packages (already installed):**
- `openai` - For embedding generation
- `numpy` - For vector operations
- `scikit-learn` - For DBSCAN clustering

**Database Extensions:**
- `pgvector` - Optional, for fast vector similarity search
- Falls back gracefully if not installed

## Usage Flow

1. **Gather Candidates** - Extract from Belief RE, Reddit, Competitors, Brand Research
2. **Run Discovery** - Click "Run Discovery" in Patterns tab
3. **Review Patterns** - See clustered themes with confidence/novelty scores
4. **Promote or Dismiss** - Convert patterns to angles or dismiss

## Testing Notes

### Manual Testing:
1. Navigate to Research Insights page
2. Select product with 10+ candidates
3. Click "Patterns" tab
4. Click "Run Discovery"
5. Review discovered patterns
6. Test promote workflow (select persona → JTBD → create)
7. Test dismiss action

### Expected Behavior:
- Discovery should find 2-5 clusters from 20+ candidates
- High novelty patterns are genuinely new themes
- Low novelty patterns overlap with existing angles
- Promotion creates angle and marks pattern as promoted

## Next Phase

**Phase 10: Documentation & Logfire Integration**
- Update CLAUDE.md with Angle Pipeline section
- Create pydantic-graph for extraction (Logfire tracing)
- Add configurable settings to Settings page
- Verify Logfire traces show extraction flow

## Notes

- Embeddings are cached in `angle_candidates.embedding` column
- Patterns are re-discoverable (can run multiple times)
- OpenAI API costs: ~$0.0001 per 1K tokens for embeddings
- Clustering is deterministic given same embeddings
