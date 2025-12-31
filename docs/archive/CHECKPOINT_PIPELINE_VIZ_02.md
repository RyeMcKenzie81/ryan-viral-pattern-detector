# Checkpoint: Pipeline Visualizer - Tasks 2-4 Complete

**Date:** 2025-12-31
**Status:** Complete

## Summary

Enhanced the Pipeline Visualizer with rich node metadata and improved UI display.

## Completed Tasks

### Task 2: Create NodeMetadata Class

Created `viraltracker/pipelines/metadata.py` with:

```python
@dataclass
class NodeMetadata:
    inputs: List[str]      # State fields read
    outputs: List[str]     # State fields written
    services: List[str]    # ctx.deps.X calls
    llm: Optional[str]     # Model used (if any)
    llm_purpose: Optional[str]  # What LLM does

    @property
    def uses_llm(self) -> bool:
        return self.llm is not None
```

### Task 3: Add Metadata to All 27 Nodes

Added `metadata: ClassVar[NodeMetadata]` to all pipeline nodes:

| File | Nodes | LLM Nodes |
|------|-------|-----------|
| `brand_onboarding.py` | 5 | 3 (Claude Vision, Gemini, Claude) |
| `template_ingestion.py` | 3 | 0 |
| `belief_plan_execution.py` | 4 | 2 (Gemini 3 Pro) |
| `reddit_sentiment.py` | 8 | 4 (Claude Sonnet x3, Claude Opus 4.5) |
| `content_pipeline/orchestrator.py` | 7 | 4 (ChatGPT 5.1 x2, Claude Opus 4.5 x2) |
| **Total** | **27** | **13** |

### Task 4: Update Pipeline Visualizer UI

Enhanced `viraltracker/ui/pages/67_📊_Pipeline_Visualizer.py`:

**Overview Tab:**
- Added LLM usage summary per pipeline (model names, node count)
- Added "Triggered From" column showing which UI pages call each pipeline

**Pipeline Details Tab:**
- Rich node breakdown with metadata:
  - Inputs (state fields read)
  - Outputs (state fields written)
  - Services called
  - LLM model and purpose (with robot emoji indicator)
- Caller info section at top of details

**New Functions in graph_viz.py:**
- `get_node_metadata(graph_name)` - Returns rich metadata for all nodes
- `get_pipeline_llm_summary(graph_name)` - LLM usage summary
- `get_graph_callers(graph_name)` - UI pages that trigger the pipeline

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/pipelines/metadata.py` | Created NodeMetadata class |
| `viraltracker/pipelines/brand_onboarding.py` | Added metadata to 5 nodes |
| `viraltracker/pipelines/template_ingestion.py` | Added metadata to 3 nodes |
| `viraltracker/pipelines/belief_plan_execution.py` | Added metadata to 4 nodes |
| `viraltracker/pipelines/reddit_sentiment.py` | Added metadata to 8 nodes |
| `viraltracker/services/content_pipeline/orchestrator.py` | Added metadata to 7 nodes |
| `viraltracker/utils/graph_viz.py` | Added 3 new functions |
| `viraltracker/ui/pages/67_📊_Pipeline_Visualizer.py` | Enhanced UI display |

## Testing

All files verified with `python3 -m py_compile`:
- `metadata.py` - OK
- `brand_onboarding.py` - OK
- `template_ingestion.py` - OK
- `belief_plan_execution.py` - OK
- `reddit_sentiment.py` - OK
- `orchestrator.py` - OK
- `graph_viz.py` - OK
- `67_📊_Pipeline_Visualizer.py` - OK

## Usage

Open the Pipeline Visualizer page in Streamlit to see:
1. **Overview tab** - All pipelines with LLM usage and callers
2. **Pipeline Details tab** - Select a pipeline to see rich node metadata
3. **Logfire Integration tab** - Runtime observability info

## Example Node Metadata Display

```
+------------------------------------------+
| 3. RelevanceFilterNode  (Claude Sonnet)  |
+------------------------------------------+
| Step 3: Score and filter by relevance... |
|                                          |
| Inputs:                 Services:        |
|   • engagement_filtered   • reddit...    |
|   • persona_context     LLM:             |
|   • topic_context         • Claude Sonnet|
|   • relevance_threshold   Purpose: Score |
|                           posts for...   |
| Outputs:                                 |
|   • relevance_filtered                   |
|   • posts_after_relevance                |
+------------------------------------------+
```
