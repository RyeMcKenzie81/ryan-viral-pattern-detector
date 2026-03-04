"""
SEO Pipeline Orchestrator — Graph definition and entry points.

Assembles the pipeline graph from all nodes and provides:
- run_seo_pipeline() — Start a new pipeline run
- resume_seo_pipeline() — Resume from a human checkpoint
- State persistence to seo_projects.workflow_data

Pipeline flow:
    KeywordDiscovery → KeywordSelection (H) → CompetitorAnalysis
    → PhaseA → OutlineReview (H) → PhaseB → PhaseC
    → ArticleReview (H) → QAValidation → QAApproval (H)
    → Publish → Interlinking → End

(H) = Human checkpoint — pipeline pauses, state saved, UI prompts user.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from uuid import UUID

from pydantic_graph import Graph

from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint
from viraltracker.services.seo_pipeline.nodes import (
    KeywordDiscoveryNode,
    KeywordSelectionNode,
    CompetitorAnalysisNode,
    ContentPhaseANode,
    OutlineReviewNode,
    ContentPhaseBNode,
    ContentPhaseCNode,
    ArticleReviewNode,
    QAValidationNode,
    QAApprovalNode,
    PublishNode,
    InterlinkingNode,
)

logger = logging.getLogger(__name__)


# =============================================================================
# GRAPH DEFINITION
# =============================================================================

seo_pipeline_graph = Graph(
    nodes=(
        KeywordDiscoveryNode,
        KeywordSelectionNode,
        CompetitorAnalysisNode,
        ContentPhaseANode,
        OutlineReviewNode,
        ContentPhaseBNode,
        ContentPhaseCNode,
        ArticleReviewNode,
        QAValidationNode,
        QAApprovalNode,
        PublishNode,
        InterlinkingNode,
    ),
    name="seo_content_pipeline",
)


# Checkpoint → Node mapping for resume
CHECKPOINT_TO_NODE = {
    SEOHumanCheckpoint.KEYWORD_SELECTION: KeywordSelectionNode,
    SEOHumanCheckpoint.OUTLINE_REVIEW: OutlineReviewNode,
    SEOHumanCheckpoint.ARTICLE_REVIEW: ArticleReviewNode,
    SEOHumanCheckpoint.QA_APPROVAL: QAApprovalNode,
}


# =============================================================================
# ENTRY POINTS
# =============================================================================

async def run_seo_pipeline(
    project_id: str,
    brand_id: str,
    organization_id: str,
    seed_keywords: list[str],
    generation_mode: str = "api",
    min_word_count: int = 3,
    max_word_count: int = 10,
    author_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Start a new SEO pipeline run.

    Creates initial state and runs the graph from KeywordDiscoveryNode.
    The pipeline will pause at the first human checkpoint (keyword selection)
    and return with status "awaiting_human".

    Args:
        project_id: SEO project UUID
        brand_id: Brand UUID
        organization_id: Organization UUID
        seed_keywords: Initial keywords for discovery
        generation_mode: "api" (Anthropic SDK) or "cli" (prompt file output)
        min_word_count: Minimum keyword word count filter
        max_word_count: Maximum keyword word count filter
        author_id: Optional author UUID for content generation

    Returns:
        Dict with pipeline result (status, checkpoint data, or completion data)
    """
    state = SEOPipelineState(
        project_id=UUID(project_id),
        brand_id=UUID(brand_id),
        organization_id=UUID(organization_id),
        seed_keywords=seed_keywords,
        generation_mode=generation_mode,
        min_word_count=min_word_count,
        max_word_count=max_word_count,
        author_id=UUID(author_id) if author_id else None,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(f"Starting SEO pipeline: project={project_id}, seeds={seed_keywords}")

    result = await seo_pipeline_graph.run(
        KeywordDiscoveryNode(),
        state=state,
    )

    # Save state for resume
    _save_pipeline_state(project_id, organization_id, state)

    return result.output


async def resume_seo_pipeline(
    project_id: str,
    organization_id: str,
    human_input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resume the SEO pipeline from a human checkpoint.

    Loads saved state, applies human input, and resumes execution
    from the appropriate node.

    Args:
        project_id: SEO project UUID
        organization_id: Organization UUID
        human_input: User's decision at the checkpoint.
            Must include "action" key (e.g., "select", "approve", "regenerate").
            Additional keys depend on the checkpoint type.

    Returns:
        Dict with pipeline result (next checkpoint or completion)
    """
    # Load saved state
    state = _load_pipeline_state(project_id, organization_id)
    if not state:
        raise ValueError(f"No saved pipeline state for project {project_id}")

    if not state.current_checkpoint:
        raise ValueError("Pipeline is not at a human checkpoint")

    # Apply human input
    state.human_input = human_input

    # Get the node to resume from
    node_class = CHECKPOINT_TO_NODE.get(state.current_checkpoint)
    if not node_class:
        raise ValueError(f"Unknown checkpoint: {state.current_checkpoint}")

    logger.info(
        f"Resuming SEO pipeline: project={project_id}, "
        f"checkpoint={state.current_checkpoint.value}, action={human_input.get('action')}"
    )

    result = await seo_pipeline_graph.run(
        node_class(),
        state=state,
    )

    # Save updated state
    _save_pipeline_state(project_id, organization_id, state)

    return result.output


# =============================================================================
# STATE PERSISTENCE
# =============================================================================

def _save_pipeline_state(
    project_id: str,
    organization_id: str,
    state: SEOPipelineState,
) -> None:
    """Save pipeline state to seo_projects.workflow_data."""
    try:
        from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
        service = SEOProjectService()

        service.update_project(
            project_id=project_id,
            organization_id=organization_id,
            workflow_data=state.to_dict(),
        )
        logger.info(f"Saved pipeline state: step={state.current_step}")
    except Exception as e:
        logger.error(f"Failed to save pipeline state: {e}")


def _load_pipeline_state(
    project_id: str,
    organization_id: str,
) -> Optional[SEOPipelineState]:
    """Load pipeline state from seo_projects.workflow_data."""
    try:
        from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
        service = SEOProjectService()

        project = service.get_project(project_id, organization_id)
        if not project:
            return None

        workflow_data = project.get("workflow_data")
        if not workflow_data:
            return None

        return SEOPipelineState.from_dict(workflow_data)
    except Exception as e:
        logger.error(f"Failed to load pipeline state: {e}")
        return None


def get_pipeline_status(
    project_id: str,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Get the current pipeline status for a project.

    Returns:
        Dict with current_step, checkpoint, awaiting_human,
        steps_completed, error info
    """
    state = _load_pipeline_state(project_id, organization_id)
    if not state:
        return {"status": "not_started"}

    return {
        "status": state.current_step,
        "checkpoint": state.current_checkpoint.value if state.current_checkpoint else None,
        "awaiting_human": state.awaiting_human,
        "steps_completed": state.steps_completed,
        "error": state.error,
        "error_step": state.error_step,
        "started_at": state.started_at,
        "completed_at": state.completed_at,
        "article_id": str(state.article_id) if state.article_id else None,
        "published_url": state.published_url,
    }
