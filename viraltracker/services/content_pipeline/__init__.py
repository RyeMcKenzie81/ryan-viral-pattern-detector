"""
Content Pipeline Service Package.

This package provides the Trash Panda content creation pipeline,
a pydantic-graph workflow for end-to-end content production.

Main components:
- state.py: ContentPipelineState dataclass
- orchestrator.py: Graph definition and convenience functions
- nodes/: Thin node wrappers for each pipeline step
- services/: Business logic services

Usage:
    from viraltracker.services.content_pipeline import (
        ContentPipelineState,
        run_topic_discovery,
        resume_pipeline,
    )

    # Run topic discovery
    result = await run_topic_discovery(
        brand_id=my_brand_id,
        num_topics=10
    )

    # Resume from checkpoint
    result = await resume_pipeline(
        project_id=my_project_id,
        human_input={"action": "select", "topic_id": "..."}
    )
"""

from .state import ContentPipelineState, WorkflowPath, HumanCheckpoint
from .orchestrator import (
    content_pipeline_graph,
    content_pipeline_graph_mvp1,
    content_pipeline_graph_mvp2,
    run_topic_discovery,
    resume_pipeline,
)

__all__ = [
    # State
    "ContentPipelineState",
    "WorkflowPath",
    "HumanCheckpoint",
    # Graphs
    "content_pipeline_graph",
    "content_pipeline_graph_mvp1",
    "content_pipeline_graph_mvp2",
    # Functions
    "run_topic_discovery",
    "resume_pipeline",
]
