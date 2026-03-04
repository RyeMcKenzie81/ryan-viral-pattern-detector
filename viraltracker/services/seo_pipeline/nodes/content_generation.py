"""
Content Generation Nodes — Three phases of content creation + human checkpoints.

Phase A: Research & Outline → HUMAN: Outline Review
Phase B: Free-write draft
Phase C: SEO optimization → HUMAN: Article Review

Reads: selected_keyword, winning_formula, author_id, article_id, generation_mode
Writes: phase_a_output, phase_b_output, phase_c_output
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint

logger = logging.getLogger(__name__)


# =============================================================================
# PHASE A: RESEARCH & OUTLINE
# =============================================================================

@dataclass
class ContentPhaseANode(BaseNode[SEOPipelineState]):
    """
    Step 4: Generate research & outline (Phase A).

    Creates article record if needed, then runs Phase A generation.
    After Phase A, pauses for human outline review.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["selected_keyword", "winning_formula", "author_id", "project_id", "generation_mode"],
        outputs=["article_id", "phase_a_output"],
        services=["content_generation.create_article", "content_generation.generate_phase_a"],
        llm="Claude Opus 4.5",
        llm_purpose="Research topic and create article outline",
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "OutlineReviewNode":
        logger.info("Step 4: Generating research & outline (Phase A)...")
        ctx.state.current_step = "content_phase_a"

        try:
            from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
            service = ContentGenerationService()

            # Create article if we don't have one yet
            if not ctx.state.article_id:
                article = service.create_article(
                    project_id=str(ctx.state.project_id),
                    keyword=ctx.state.selected_keyword,
                    organization_id=str(ctx.state.organization_id),
                    brand_id=str(ctx.state.brand_id),
                    author_id=str(ctx.state.author_id) if ctx.state.author_id else None,
                )
                from uuid import UUID
                ctx.state.article_id = UUID(article["id"])

            # Run Phase A
            result = service.generate_phase_a(
                article_id=str(ctx.state.article_id),
                keyword=ctx.state.selected_keyword,
                competitor_data={"winning_formula": ctx.state.winning_formula, "results": ctx.state.competitor_results},
                author_id=str(ctx.state.author_id) if ctx.state.author_id else None,
                mode=ctx.state.generation_mode,
                organization_id=str(ctx.state.organization_id),
            )

            ctx.state.phase_a_output = result.get("content") or result.get("prompt_file")
            ctx.state.mark_step_complete("content_phase_a")
            logger.info("Phase A complete")
            return OutlineReviewNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "content_phase_a"
            logger.error(f"Phase A failed: {e}")
            return End({"status": "error", "error": str(e), "step": "content_phase_a"})


# =============================================================================
# OUTLINE REVIEW (HUMAN CHECKPOINT)
# =============================================================================

@dataclass
class OutlineReviewNode(BaseNode[SEOPipelineState]):
    """
    Step 5: HUMAN CHECKPOINT — Review outline from Phase A.

    User can approve to continue to Phase B, or request changes.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["phase_a_output", "human_input"],
        outputs=[],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> Union["ContentPhaseBNode", "ContentPhaseANode", End]:
        ctx.state.current_step = "outline_review"
        ctx.state.current_checkpoint = SEOHumanCheckpoint.OUTLINE_REVIEW

        if ctx.state.human_input:
            human_input = ctx.state.human_input
            ctx.state.human_input = None

            action = human_input.get("action", "approve")

            if action == "approve":
                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("outline_review")
                logger.info("Outline approved, proceeding to Phase B")
                return ContentPhaseBNode()

            elif action == "regenerate":
                ctx.state.awaiting_human = False
                logger.info("Outline rejected, regenerating Phase A")
                return ContentPhaseANode()

            return End({"status": "error", "error": f"Invalid action: {action}"})

        # Pause for review
        ctx.state.awaiting_human = True
        logger.info("Pausing for outline review")
        return End({
            "status": "awaiting_human",
            "checkpoint": SEOHumanCheckpoint.OUTLINE_REVIEW.value,
            "article_id": str(ctx.state.article_id),
            "phase_a_output": ctx.state.phase_a_output,
            "message": "Review the outline and approve or request regeneration.",
        })


# =============================================================================
# PHASE B: FREE-WRITE
# =============================================================================

@dataclass
class ContentPhaseBNode(BaseNode[SEOPipelineState]):
    """
    Step 6: Generate free-write draft (Phase B).

    Takes the approved outline and writes a full article draft.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id", "phase_a_output", "generation_mode"],
        outputs=["phase_b_output"],
        services=["content_generation.generate_phase_b"],
        llm="Claude Opus 4.5",
        llm_purpose="Write full article from outline",
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "ContentPhaseCNode":
        logger.info("Step 6: Generating free-write draft (Phase B)...")
        ctx.state.current_step = "content_phase_b"

        try:
            from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
            service = ContentGenerationService()

            result = service.generate_phase_b(
                article_id=str(ctx.state.article_id),
                keyword=ctx.state.selected_keyword,
                phase_a_output=ctx.state.phase_a_output or "",
                author_id=str(ctx.state.author_id) if ctx.state.author_id else None,
                mode=ctx.state.generation_mode,
                organization_id=str(ctx.state.organization_id),
            )

            ctx.state.phase_b_output = result.get("content") or result.get("prompt_file")
            ctx.state.mark_step_complete("content_phase_b")
            logger.info("Phase B complete")
            return ContentPhaseCNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "content_phase_b"
            logger.error(f"Phase B failed: {e}")
            return End({"status": "error", "error": str(e), "step": "content_phase_b"})


# =============================================================================
# PHASE C: SEO OPTIMIZATION
# =============================================================================

@dataclass
class ContentPhaseCNode(BaseNode[SEOPipelineState]):
    """
    Step 7: SEO-optimize article (Phase C).

    Takes the free-write draft and optimizes for SEO.
    After optimization, pauses for human article review.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id", "phase_b_output", "generation_mode"],
        outputs=["phase_c_output"],
        services=["content_generation.generate_phase_c"],
        llm="Claude Opus 4.5",
        llm_purpose="SEO-optimize article for target keyword",
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "ArticleReviewNode":
        from .article_review import ArticleReviewNode

        logger.info("Step 7: SEO-optimizing article (Phase C)...")
        ctx.state.current_step = "content_phase_c"

        try:
            from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
            service = ContentGenerationService()

            result = service.generate_phase_c(
                article_id=str(ctx.state.article_id),
                keyword=ctx.state.selected_keyword,
                phase_b_output=ctx.state.phase_b_output or "",
                competitor_data={"winning_formula": ctx.state.winning_formula},
                author_id=str(ctx.state.author_id) if ctx.state.author_id else None,
                mode=ctx.state.generation_mode,
                organization_id=str(ctx.state.organization_id),
            )

            ctx.state.phase_c_output = result.get("content") or result.get("prompt_file")
            ctx.state.mark_step_complete("content_phase_c")
            logger.info("Phase C complete")
            return ArticleReviewNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "content_phase_c"
            logger.error(f"Phase C failed: {e}")
            return End({"status": "error", "error": str(e), "step": "content_phase_c"})
