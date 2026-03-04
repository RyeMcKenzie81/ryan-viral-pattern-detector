"""
QA Validation, QA Approval, and Publish Nodes.

QAValidationNode → QAApprovalNode (HUMAN) → ImageGenerationNode → PublishNode → InterlinkingNode

Reads: article_id, qa_result, human_input, brand_id, organization_id
Writes: qa_result, published_url, cms_article_id, hero_image_url
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint

logger = logging.getLogger(__name__)


# =============================================================================
# QA VALIDATION
# =============================================================================

@dataclass
class QAValidationNode(BaseNode[SEOPipelineState]):
    """
    Step 9: Run QA validation checks on the article.

    Runs 10 quality checks (word count, title length, readability, etc.)
    then pauses for human QA approval.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id"],
        outputs=["qa_result"],
        services=["qa_validation.validate_article"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "QAApprovalNode":
        logger.info("Step 9: Running QA validation...")
        ctx.state.current_step = "qa_validation"

        try:
            from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
            service = QAValidationService()

            result = service.validate_article(str(ctx.state.article_id))
            ctx.state.qa_result = result
            ctx.state.mark_step_complete("qa_validation")
            logger.info(f"QA validation: {'PASSED' if result.get('passed') else 'FAILED'}")
            return QAApprovalNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "qa_validation"
            logger.error(f"QA validation failed: {e}")
            return End({"status": "error", "error": str(e), "step": "qa_validation"})


# =============================================================================
# QA APPROVAL (HUMAN CHECKPOINT)
# =============================================================================

@dataclass
class QAApprovalNode(BaseNode[SEOPipelineState]):
    """
    Step 10: HUMAN CHECKPOINT — Review QA results and approve for publishing.

    User can:
    - approve → proceed to publish
    - fix → go back to Phase C for fixes
    - override → publish despite QA failures
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["qa_result", "human_input"],
        outputs=[],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> Union["ImageGenerationNode", "ContentPhaseCNode", End]:
        from .image_generation import ImageGenerationNode
        ctx.state.current_step = "qa_approval"
        ctx.state.current_checkpoint = SEOHumanCheckpoint.QA_APPROVAL

        if ctx.state.human_input:
            human_input = ctx.state.human_input
            ctx.state.human_input = None

            action = human_input.get("action", "approve")

            if action == "approve":
                if ctx.state.qa_result and not ctx.state.qa_result.get("passed"):
                    return End({
                        "status": "error",
                        "error": "Cannot approve: QA checks failed. Use 'override' to publish anyway.",
                    })
                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("qa_approval")
                logger.info("QA approved, proceeding to image generation")
                return ImageGenerationNode()

            elif action == "override":
                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("qa_approval")
                logger.info("QA overridden, proceeding to image generation")
                return ImageGenerationNode()

            elif action == "fix":
                from .content_generation import ContentPhaseCNode
                ctx.state.awaiting_human = False
                logger.info("QA rejected, returning to Phase C for fixes")
                return ContentPhaseCNode()

            return End({"status": "error", "error": f"Invalid action: {action}"})

        # Pause for approval
        ctx.state.awaiting_human = True
        logger.info("Pausing for QA approval")
        return End({
            "status": "awaiting_human",
            "checkpoint": SEOHumanCheckpoint.QA_APPROVAL.value,
            "article_id": str(ctx.state.article_id),
            "qa_result": ctx.state.qa_result,
            "message": "Review QA results and approve for publishing.",
        })


# =============================================================================
# PUBLISH
# =============================================================================

@dataclass
class PublishNode(BaseNode[SEOPipelineState]):
    """
    Step 11: Publish article to CMS (Shopify).

    Publishes the article via the CMS publisher service,
    then proceeds to interlinking.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id", "brand_id", "organization_id"],
        outputs=["published_url", "cms_article_id"],
        services=["cms_publisher.publish_article"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "InterlinkingNode":
        from .interlinking import InterlinkingNode

        logger.info("Step 11: Publishing article to CMS...")
        ctx.state.current_step = "publishing"

        try:
            from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
            service = CMSPublisherService()

            result = service.publish_article(
                article_id=str(ctx.state.article_id),
                brand_id=str(ctx.state.brand_id),
                organization_id=str(ctx.state.organization_id),
            )

            ctx.state.published_url = result.get("published_url", "")
            ctx.state.cms_article_id = result.get("cms_article_id", "")
            ctx.state.mark_step_complete("publishing")
            logger.info(f"Published: {ctx.state.published_url}")
            return InterlinkingNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "publishing"
            logger.error(f"Publishing failed: {e}")
            return End({"status": "error", "error": str(e), "step": "publishing"})
