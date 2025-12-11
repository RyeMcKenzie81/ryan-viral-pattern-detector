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
    from viraltracker.services.content_pipeline.state import ContentPipelineState
    from viraltracker.services.content_pipeline.services.content_pipeline_service import ContentPipelineService
    from viraltracker.services.content_pipeline.services.topic_service import TopicDiscoveryService
"""

# Only import state classes to avoid circular imports
# orchestrator.py imports AgentDependencies which imports this package
from .state import ContentPipelineState, WorkflowPath, HumanCheckpoint

__all__ = [
    # State
    "ContentPipelineState",
    "WorkflowPath",
    "HumanCheckpoint",
]
