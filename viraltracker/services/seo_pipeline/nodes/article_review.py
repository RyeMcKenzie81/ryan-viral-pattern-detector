"""
Article Review Node — HUMAN CHECKPOINT.

Pauses the pipeline for the user to review the SEO-optimized article.

Reads: phase_c_output, article_id, human_input
Writes: (none — approval gate only)
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint

logger = logging.getLogger(__name__)


@dataclass
class ArticleReviewNode(BaseNode[SEOPipelineState]):
    """
    Step 8: HUMAN CHECKPOINT — Review SEO-optimized article.

    User can:
    - approve → proceed to QA
    - regenerate → go back to Phase C
    - restart → go back to Phase A
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["phase_c_output", "article_id", "human_input"],
        outputs=[],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> Union["QAValidationNode", End]:
        from .qa_publish import QAValidationNode

        ctx.state.current_step = "article_review"
        ctx.state.current_checkpoint = SEOHumanCheckpoint.ARTICLE_REVIEW

        if ctx.state.human_input:
            human_input = ctx.state.human_input
            ctx.state.human_input = None

            action = human_input.get("action", "approve")

            if action == "approve":
                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("article_review")
                logger.info("Article approved, proceeding to QA")
                return QAValidationNode()

            elif action == "regenerate":
                from .content_generation import ContentPhaseCNode
                ctx.state.awaiting_human = False
                logger.info("Article rejected, regenerating Phase C")
                return ContentPhaseCNode()

            elif action == "restart":
                from .content_generation import ContentPhaseANode
                ctx.state.awaiting_human = False
                logger.info("Article rejected, restarting from Phase A")
                return ContentPhaseANode()

            return End({"status": "error", "error": f"Invalid action: {action}"})

        # Pause for review
        ctx.state.awaiting_human = True
        logger.info("Pausing for article review")
        return End({
            "status": "awaiting_human",
            "checkpoint": SEOHumanCheckpoint.ARTICLE_REVIEW.value,
            "article_id": str(ctx.state.article_id),
            "phase_c_output": ctx.state.phase_c_output,
            "message": "Review the optimized article and approve or request changes.",
        })
