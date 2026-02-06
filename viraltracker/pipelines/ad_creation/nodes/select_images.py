"""
SelectImagesNode - Select product images for ad generation.
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class SelectImagesNode(BaseNode[AdCreationPipelineState]):
    """
    Step 5: Select product images for ad generation.

    Fetches product images from database, scores them against the reference ad,
    and selects the best 1-2 images (auto or manual mode).

    Reads: product_id, ad_analysis, image_selection_mode, selected_image_paths
    Writes: selected_images
    Services: ContentService.select_product_images()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["product_id", "ad_analysis", "image_selection_mode", "selected_image_paths"],
        outputs=["selected_images"],
        services=["content_service.select_product_images"],
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "GenerateAdsNode":
        from .generate_ads import GenerateAdsNode
        from ..services.content_service import AdContentService

        logger.info(f"Step 5: Selecting product images (mode: {ctx.state.image_selection_mode})...")
        ctx.state.current_step = "select_images"

        try:
            # Fetch product images from database
            image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
            product_image_paths = []
            image_analyses = {}

            db = ctx.deps.ad_creation.supabase
            images_result = db.table("product_images").select(
                "storage_path, image_analysis, is_main"
            ).eq("product_id", ctx.state.product_id).order("is_main", desc=True).execute()

            for img in images_result.data or []:
                path = img.get('storage_path', '')
                if path.lower().endswith(image_extensions):
                    product_image_paths.append(path)
                    if img.get('image_analysis'):
                        image_analyses[path] = img['image_analysis']

            logger.info(f"Found {len(product_image_paths)} images, {len(image_analyses)} with analysis")

            if not product_image_paths:
                raise ValueError(
                    f"No images found for product {ctx.state.product_id}. "
                    f"Please add images in Brand Manager before creating ads."
                )

            # Prepare manual selection
            manual_selection = None
            if ctx.state.image_selection_mode == "manual" and ctx.state.selected_image_paths:
                manual_selection = ctx.state.selected_image_paths[:2]
                logger.info(f"Using manually selected images: {manual_selection}")

            # Determine count
            if ctx.state.image_selection_mode == "auto":
                auto_count = min(2, len(product_image_paths))
            else:
                auto_count = len(manual_selection) if manual_selection else 1

            # Select images
            content_service = AdContentService()
            selected = content_service.select_product_images(
                product_image_paths=product_image_paths,
                ad_analysis=ctx.state.ad_analysis,
                count=auto_count,
                selection_mode=ctx.state.image_selection_mode,
                image_analyses=image_analyses,
                manual_selection=manual_selection,
            )
            ctx.state.selected_images = selected

            # Update ad run status
            selected_paths = [img["storage_path"] for img in selected]
            await ctx.deps.ad_creation.update_ad_run(
                ad_run_id=UUID(ctx.state.ad_run_id),
                status="generating",
                selected_product_images=selected_paths
            )

            ctx.state.mark_step_complete("select_images")
            logger.info(f"Selected {len(selected)} image(s): "
                        f"{', '.join(img['storage_path'] for img in selected)}")

            return GenerateAdsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "select_images"
            logger.error(f"Select images failed: {e}")

            if ctx.state.ad_run_id:
                try:
                    await ctx.deps.ad_creation.update_ad_run(
                        ad_run_id=UUID(ctx.state.ad_run_id),
                        status="failed",
                        error_message=str(e)
                    )
                except Exception:
                    pass

            raise
