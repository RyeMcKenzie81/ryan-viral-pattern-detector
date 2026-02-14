"""
GenerateAdsNode V2 - Generate ad variations one at a time (resilient).

V2 changes from V1:
- Passes canvas_size from state to generation service
- Includes prompt_version in generated ad metadata
"""

import logging
import uuid as uuid_module
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class GenerateAdsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 6: Generate ad variations one at a time for resilience.

    For each selected hook/variation:
    1. Generate structured Pydantic prompt
    2. Execute Gemini image generation
    3. Upload and save immediately

    If generation fails for one variation, continues with others.

    V2 additions: canvas_size passed explicitly, prompt_version tracked.

    Reads: selected_hooks, product_dict, ad_analysis, ad_brief_instructions,
           reference_ad_path, selected_images, color_mode, brand_colors,
           brand_fonts, num_variations, ad_run_id, canvas_size, prompt_version
    Writes: generated_ads, ads_generated
    Services: GenerationService.generate_prompt(), .execute_generation(),
              AdCreationService.upload_generated_ad()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["selected_hooks", "product_dict", "ad_analysis", "ad_brief_instructions",
                "reference_ad_path", "selected_images", "color_mode", "brand_colors",
                "brand_fonts", "num_variations", "ad_run_id", "canvas_size", "prompt_version"],
        outputs=["generated_ads", "ads_generated"],
        services=["generation_service.generate_prompt", "generation_service.execute_generation",
                   "ad_creation.upload_generated_ad"],
        llm="Gemini Image Gen",
        llm_purpose="Generate ad images from Pydantic prompts",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "ReviewAdsNode":
        from .review_ads import ReviewAdsNode
        from ..services.generation_service import AdGenerationService

        logger.info(f"Step 6: Generating {len(ctx.state.selected_hooks)} ad variations (V2 Pydantic prompts)...")
        ctx.state.current_step = "generate_ads"

        generation_service = AdGenerationService()
        selected_image_paths = [img["storage_path"] for img in ctx.state.selected_images]
        generated_ads = []

        for i, selected_hook in enumerate(ctx.state.selected_hooks, start=1):
            logger.info(f"  Generating variation {i}/{len(ctx.state.selected_hooks)}...")

            try:
                # Generate Pydantic prompt (V2: pass canvas_size and prompt_version)
                prompt = generation_service.generate_prompt(
                    prompt_index=i,
                    selected_hook=selected_hook,
                    product=ctx.state.product_dict,
                    ad_analysis=ctx.state.ad_analysis,
                    ad_brief_instructions=ctx.state.ad_brief_instructions,
                    reference_ad_path=ctx.state.reference_ad_path,
                    product_image_paths=selected_image_paths,
                    color_mode=ctx.state.color_mode,
                    brand_colors=ctx.state.brand_colors,
                    brand_fonts=ctx.state.brand_fonts,
                    num_variations=ctx.state.num_variations,
                    canvas_size=ctx.state.canvas_size,
                    prompt_version=ctx.state.prompt_version,
                )

                # Execute generation
                generated_ad = await generation_service.execute_generation(
                    nano_banana_prompt=prompt,
                    ad_creation_service=ctx.deps.ad_creation,
                    gemini_service=ctx.deps.gemini,
                    image_resolution=ctx.state.image_resolution,
                )

                # Upload image with structured naming
                ad_uuid = uuid_module.uuid4()
                canvas_size = ctx.state.canvas_size

                product_id_for_naming = await ctx.deps.ad_creation.get_product_id_for_run(
                    UUID(ctx.state.ad_run_id)
                )

                storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=i,
                    image_base64=generated_ad['image_base64'],
                    product_id=product_id_for_naming,
                    ad_id=ad_uuid,
                    canvas_size=canvas_size
                )

                generated_ads.append({
                    "prompt_index": i,
                    "prompt": prompt,
                    "generated_ad": generated_ad,
                    "storage_path": storage_path,
                    "ad_uuid": str(ad_uuid),
                    "hook": selected_hook,
                    "prompt_version": prompt.get("prompt_version", ctx.state.prompt_version),
                })

                ctx.state.ads_generated += 1
                logger.info(f"  Variation {i} generated and uploaded: {storage_path}")

            except Exception as gen_error:
                logger.error(f"  Generation failed for variation {i}: {gen_error}")
                generated_ads.append({
                    "prompt_index": i,
                    "prompt": None,
                    "generated_ad": None,
                    "storage_path": None,
                    "ad_uuid": None,
                    "hook": selected_hook,
                    "error": str(gen_error),
                    "final_status": "generation_failed",
                })

        ctx.state.generated_ads = generated_ads
        ctx.state.mark_step_complete("generate_ads")
        logger.info(f"Generation complete: {ctx.state.ads_generated}/{len(ctx.state.selected_hooks)} succeeded")

        return ReviewAdsNode()
