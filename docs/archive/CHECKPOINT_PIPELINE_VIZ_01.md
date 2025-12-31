# Checkpoint: Pipeline Visualizer - Task 1 Complete

**Date:** 2025-12-31
**Branch:** feature/antigravity-setup
**Commit:** f2f4d73

## Completed: Auto-Discovery System

### What Was Done

1. **Created `GRAPH_REGISTRY` in `pipelines/__init__.py`**
   - Centralized registry for all pipeline graphs
   - Includes: graph object, start node, description, node list, callers
   - New pipelines auto-appear when added to registry

2. **Updated `graph_viz.py`**
   - Removed hardcoded registry
   - Now imports `GRAPH_REGISTRY` from pipelines
   - Single source of truth for pipeline metadata

3. **Added caller tracking**
   - Each pipeline shows which UI page triggers it
   - `brand_onboarding` marked as unused (no callers)

### Current Pipeline Registry

| Pipeline | Nodes | Triggered From |
|----------|-------|----------------|
| brand_onboarding | 5 | (unused) |
| template_ingestion | 3 | 28_Template_Queue.py |
| belief_plan_execution | 4 | 27_Plan_Executor.py |
| reddit_sentiment | 8 | 15_Reddit_Research.py |
| content_pipeline_mvp1 | 3 | 41_Content_Pipeline.py |
| content_pipeline_mvp2 | 7 | 41_Content_Pipeline.py |

### Files Modified

- `viraltracker/pipelines/__init__.py` - Added GRAPH_REGISTRY, content pipeline exports
- `viraltracker/utils/graph_viz.py` - Simplified to use registry
- `viraltracker/services/content_pipeline/orchestrator.py` - Fixed AgentDependencies import

---

## Remaining Tasks

- [ ] Task 2: Create NodeMetadata class (pipelines/metadata.py)
- [ ] Task 3: Add metadata to all 27 nodes across 6 files
- [ ] Task 4: Update Pipeline Visualizer UI with rich display

---

## How to Add New Pipelines

1. Create your graph in a pipeline file
2. Add to `GRAPH_REGISTRY` in `pipelines/__init__.py`:

```python
GRAPH_REGISTRY = {
    # ... existing entries ...
    "my_new_pipeline": {
        "graph": my_new_graph,
        "start_node": MyStartNode,
        "run_function": "run_my_pipeline",
        "description": "What this pipeline does",
        "nodes": ["Node1", "Node2", "Node3"],
        "callers": [{"type": "ui", "page": "XX_My_Page.py"}],
    },
}
```

3. Pipeline automatically appears in visualizer
