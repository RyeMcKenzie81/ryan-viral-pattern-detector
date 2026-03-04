"""
Image Generation Node.

QAApproval (H) → ImageGeneration → Publish → Interlinking → End

Generates images for [IMAGE: desc] markers in article content,
uploads to Supabase Storage, and replaces markers with <img> tags.

Non-fatal: on any failure, logs warning and proceeds to PublishNode.
"""

import logging
from dataclasses import dataclass
from typing import ClassVar

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState

logger = logging.getLogger(__name__)


@dataclass
class ImageGenerationNode(BaseNode[SEOPipelineState]):
    """
    Step 10.5: Generate and upload article images.

    Extracts [IMAGE: desc] markers from Phase C output,
    generates images via Gemini, uploads to Supabase Storage,
    and replaces markers with responsive <img> tags.

    Non-fatal: failures log a warning and proceed to publish.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id", "phase_c_output", "brand_id", "organization_id"],
        outputs=["hero_image_url", "image_results"],
        services=["seo_image.generate_article_images"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "PublishNode":
        from .qa_publish import PublishNode

        logger.info("Step 10.5: Generating article images...")
        ctx.state.current_step = "image_generation"

        markdown = ctx.state.phase_c_output
        if not markdown:
            logger.info("No Phase C output, skipping image generation")
            ctx.state.mark_step_complete("image_generation")
            return PublishNode()

        try:
            from viraltracker.services.seo_pipeline.services.seo_image_service import SEOImageService
            service = SEOImageService()

            # Get keyword for slug generation
            keyword = ctx.state.selected_keyword or "article"

            result = await service.generate_article_images(
                article_id=str(ctx.state.article_id),
                markdown=markdown,
                brand_id=str(ctx.state.brand_id),
                organization_id=str(ctx.state.organization_id),
                keyword=keyword,
            )

            # Update state
            ctx.state.hero_image_url = result.get("hero_image_url")
            ctx.state.image_results = result.get("stats")
            ctx.state.phase_c_output = result.get("updated_markdown", markdown)
            ctx.state.mark_step_complete("image_generation")

            stats = result.get("stats", {})
            logger.info(
                f"Image generation complete: {stats.get('success', 0)}/{stats.get('total', 0)} "
                f"succeeded, {stats.get('failed', 0)} failed"
            )

        except Exception as e:
            # Non-fatal: log and proceed to publish
            logger.warning(f"Image generation failed (non-fatal): {e}")
            ctx.state.mark_step_complete("image_generation")

        return PublishNode()
