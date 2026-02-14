"""
InitializeNode - Create ad_run and upload reference ad.

First node in the ad creation pipeline.
"""

import base64
import logging
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class InitializeNode(BaseNode[AdCreationPipelineState]):
    """
    Step 1: Create ad run record and upload reference ad to storage.

    Reads: product_id, reference_ad_base64, reference_ad_filename, project_id,
           num_variations, content_source, color_mode, offer_variant_id
    Writes: ad_run_id, reference_ad_path
    Services: AdCreationService.create_ad_run(), .upload_reference_ad(), .update_ad_run()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["product_id", "reference_ad_base64", "reference_ad_filename", "project_id"],
        outputs=["ad_run_id", "reference_ad_path"],
        services=["ad_creation.create_ad_run", "ad_creation.upload_reference_ad", "ad_creation.update_ad_run"],
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "FetchContextNode":
        from .fetch_context import FetchContextNode

        logger.info("Step 1: Creating ad run and uploading reference ad...")
        ctx.state.current_step = "initialize"

        try:
            # Validate required inputs
            if not ctx.state.product_id:
                raise ValueError("product_id is required")
            if not ctx.state.reference_ad_base64:
                raise ValueError("reference_ad_base64 is required")

            # Build parameters dict for tracking
            run_parameters = {
                "num_variations": ctx.state.num_variations,
                "content_source": ctx.state.content_source,
                "color_mode": ctx.state.color_mode,
                "image_selection_mode": ctx.state.image_selection_mode,
                "selected_image_paths": ctx.state.selected_image_paths,
                "brand_colors": ctx.state.brand_colors,
                "persona_id": ctx.state.persona_id,
                "variant_id": ctx.state.variant_id,
                "additional_instructions": ctx.state.additional_instructions,
                "offer_variant_id": ctx.state.offer_variant_id,
                "image_resolution": ctx.state.image_resolution
            }

            # Create ad run with temporary path
            product_uuid = UUID(ctx.state.product_id)
            project_uuid = UUID(ctx.state.project_id) if ctx.state.project_id else None

            ad_run_id = await ctx.deps.ad_creation.create_ad_run(
                product_id=product_uuid,
                reference_ad_storage_path="temp",
                project_id=project_uuid,
                parameters=run_parameters
            )
            ctx.state.ad_run_id = str(ad_run_id)

            # Decode and upload reference ad
            image_data = base64.b64decode(ctx.state.reference_ad_base64)

            # Detect image format
            filename = ctx.state.reference_ad_filename
            media_type = "image/png"
            if image_data[:3] == b'\xff\xd8\xff':
                media_type = "image/jpeg"
                if not filename.lower().endswith(('.jpg', '.jpeg')):
                    filename = filename.rsplit('.', 1)[0] + '.jpg' if '.' in filename else filename + '.jpg'
            elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
                media_type = "image/png"
            elif image_data[:6] in (b'GIF87a', b'GIF89a'):
                media_type = "image/gif"
            elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
                media_type = "image/webp"

            reference_ad_path = await ctx.deps.ad_creation.upload_reference_ad(
                ad_run_id=ad_run_id,
                image_data=image_data,
                filename=filename
            )
            ctx.state.reference_ad_path = reference_ad_path

            # Update ad run with correct reference path
            await ctx.deps.ad_creation.update_ad_run(
                ad_run_id=ad_run_id,
                status="analyzing",
                reference_ad_storage_path=reference_ad_path
            )

            ctx.state.mark_step_complete("initialize")
            logger.info(f"Ad run created: {ad_run_id}, reference uploaded: {reference_ad_path}")

            return FetchContextNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "initialize"
            logger.error(f"Initialize failed: {e}")
            raise
