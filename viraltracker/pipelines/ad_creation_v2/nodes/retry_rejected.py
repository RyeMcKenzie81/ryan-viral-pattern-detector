"""
RetryRejectedNode - Auto-retry rejected ads with fresh generation + review.
"""

import logging
import uuid as uuid_module
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ..utils import stringify_uuids
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class RetryRejectedNode(BaseNode[AdCreationPipelineState]):
    """
    Step 7b: Auto-retry rejected ads with fresh generation and review.

    Runs after ReviewAdsNode when auto_retry_rejected is enabled.
    For each rejected ad, generates a new image with the same hook,
    runs dual review, and appends the result to reviewed_ads.
    The original rejected ad stays in the list.

    Reads: reviewed_ads, auto_retry_rejected, max_retry_attempts,
           product_dict, ad_analysis, ad_brief_instructions,
           reference_ad_path, selected_images, color_mode,
           brand_colors, brand_fonts, ad_run_id, content_source
    Writes: reviewed_ads (appends retried ads)
    Services: GenerationService, ReviewService, AdCreationService
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reviewed_ads", "auto_retry_rejected", "max_retry_attempts",
                "product_dict", "ad_analysis", "ad_run_id"],
        outputs=["reviewed_ads"],
        services=["generation_service.generate_prompt", "generation_service.execute_generation",
                   "review_service.review_ad_claude", "review_service.review_ad_gemini",
                   "ad_creation.upload_generated_ad", "ad_creation.save_generated_ad"],
        llm="Gemini Image Gen + Claude Vision + Gemini Vision",
        llm_purpose="Retry rejected ads with fresh generation and dual review",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "CompileResultsNode":
        from .compile_results import CompileResultsNode
        from ..services.generation_service import AdGenerationService
        from ..services.review_service import AdReviewService

        # Pass through if auto-retry is disabled or no rejected ads
        if not ctx.state.auto_retry_rejected:
            logger.info("Step 7b: Auto-retry disabled, skipping.")
            return CompileResultsNode()

        rejected_ads = [
            ad for ad in ctx.state.reviewed_ads
            if ad.get('final_status') == 'rejected'
        ]

        if not rejected_ads:
            logger.info("Step 7b: No rejected ads to retry.")
            return CompileResultsNode()

        logger.info(
            f"Step 7b: Retrying {len(rejected_ads)} rejected ads "
            f"(max {ctx.state.max_retry_attempts} attempt(s) each)..."
        )
        ctx.state.current_step = "retry_rejected"

        generation_service = AdGenerationService()
        review_service = AdReviewService()
        selected_image_paths = [img["storage_path"] for img in ctx.state.selected_images]

        # Phase 3: Collect selected_image_tags (same as GenerateAdsNode)
        selected_image_tags = []
        for img in ctx.state.selected_images:
            for tag in (img.get("asset_tags") or []):
                if tag not in selected_image_tags:
                    selected_image_tags.append(tag)

        # Get the next prompt_index (after all existing ads)
        max_index = max(
            (ad.get('prompt_index', 0) for ad in ctx.state.reviewed_ads),
            default=0
        )
        next_index = max_index + 1

        for rejected_ad in rejected_ads:
            original_prompt = rejected_ad.get('prompt') or {}
            original_hook = original_prompt.get('hook', {})

            # Build hook data for regeneration
            if not original_hook:
                logger.warning(
                    f"Skipping retry for variation {rejected_ad.get('prompt_index')}: "
                    f"no hook data available"
                )
                continue

            selected_hook = {
                "adapted_text": original_hook.get('adapted_text', ''),
                "hook_id": original_hook.get('hook_id', str(uuid_module.uuid4())),
            }
            # Pass through any extra hook fields
            for key in ('name', 'source', 'belief_statement', 'explanation'):
                if original_hook.get(key):
                    selected_hook[key] = original_hook[key]

            # Read canvas_size/color_mode from the rejected ad (per-ad, not state)
            retry_canvas_size = rejected_ad.get("canvas_size", ctx.state.canvas_size)
            retry_color_mode = rejected_ad.get("color_mode", ctx.state.color_mode)

            try:
                # Generate prompt (same hook, fresh variation; Phase 3: asset state passthrough)
                prompt = generation_service.generate_prompt(
                    prompt_index=next_index,
                    selected_hook=selected_hook,
                    product=ctx.state.product_dict,
                    ad_analysis=ctx.state.ad_analysis,
                    ad_brief_instructions=ctx.state.ad_brief_instructions,
                    reference_ad_path=ctx.state.reference_ad_path,
                    product_image_paths=selected_image_paths,
                    color_mode=retry_color_mode,
                    brand_colors=ctx.state.brand_colors,
                    brand_fonts=ctx.state.brand_fonts,
                    num_variations=1,
                    canvas_size=retry_canvas_size,
                    prompt_version=ctx.state.prompt_version,
                    template_elements=ctx.state.template_elements,
                    brand_asset_info=ctx.state.brand_asset_info,
                    selected_image_tags=selected_image_tags,
                )

                # Execute generation
                generated_ad = await generation_service.execute_generation(
                    nano_banana_prompt=prompt,
                    ad_creation_service=ctx.deps.ad_creation,
                    gemini_service=ctx.deps.gemini,
                    image_resolution=ctx.state.image_resolution,
                )

                # Upload image
                ad_uuid = uuid_module.uuid4()
                canvas_size = retry_canvas_size

                product_id_for_naming = await ctx.deps.ad_creation.get_product_id_for_run(
                    UUID(ctx.state.ad_run_id)
                )

                storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=next_index,
                    image_base64=generated_ad['image_base64'],
                    product_id=product_id_for_naming,
                    ad_id=ad_uuid,
                    canvas_size=canvas_size,
                )

                # Dual review
                claude_review = None
                try:
                    claude_review = await review_service.review_ad_claude(
                        storage_path=storage_path,
                        product_name=ctx.state.product_dict.get('name'),
                        hook_text=selected_hook.get('adapted_text', ''),
                        ad_analysis=ctx.state.ad_analysis,
                        ad_creation_service=ctx.deps.ad_creation,
                    )
                except Exception as e:
                    logger.warning(f"Claude review failed for retry: {e}")
                    claude_review = review_service.make_failed_review("claude", str(e))

                gemini_review = None
                try:
                    gemini_review = await review_service.review_ad_gemini(
                        storage_path=storage_path,
                        product_name=ctx.state.product_dict.get('name'),
                        hook_text=selected_hook.get('adapted_text', ''),
                        ad_analysis=ctx.state.ad_analysis,
                        ad_creation_service=ctx.deps.ad_creation,
                        gemini_service=ctx.deps.gemini,
                    )
                except Exception as e:
                    logger.warning(f"Gemini review failed for retry: {e}")
                    gemini_review = review_service.make_failed_review("gemini", str(e))

                final_status, reviewers_agree = review_service.apply_dual_review_logic(
                    claude_review, gemini_review
                )

                logger.info(
                    f"  Retry of variation {rejected_ad.get('prompt_index')}: "
                    f"Claude={claude_review.get('status')}, "
                    f"Gemini={gemini_review.get('status')}, Final={final_status}"
                )

                # Determine hook_id for database
                if ctx.state.content_source == "hooks":
                    hook_id = UUID(selected_hook['hook_id'])
                else:
                    hook_id = None

                # Get original ad UUID for regenerate_parent_id
                original_ad_uuid_str = rejected_ad.get('ad_uuid')

                # Save to database
                original_ad_uuid = UUID(original_ad_uuid_str) if original_ad_uuid_str else None
                await ctx.deps.ad_creation.save_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=next_index,
                    prompt_text=prompt.get('full_prompt', ''),
                    prompt_spec=stringify_uuids(prompt.get('json_prompt', {})),
                    hook_id=hook_id,
                    hook_text=selected_hook.get('adapted_text', ''),
                    storage_path=storage_path,
                    claude_review=claude_review,
                    gemini_review=gemini_review,
                    final_status=final_status,
                    model_requested=generated_ad.get('model_requested'),
                    model_used=generated_ad.get('model_used'),
                    generation_time_ms=generated_ad.get('generation_time_ms'),
                    generation_retries=generated_ad.get('generation_retries', 0),
                    ad_id=ad_uuid,
                    regenerate_parent_id=original_ad_uuid,
                    canvas_size=retry_canvas_size,
                    color_mode=retry_color_mode,
                )

                # Append retry result to reviewed_ads
                ctx.state.reviewed_ads.append({
                    "prompt_index": next_index,
                    "prompt": prompt,
                    "storage_path": storage_path,
                    "claude_review": claude_review,
                    "gemini_review": gemini_review,
                    "reviewers_agree": reviewers_agree,
                    "final_status": final_status,
                    "ad_uuid": str(ad_uuid),
                    "canvas_size": retry_canvas_size,
                    "color_mode": retry_color_mode,
                    "is_retry": True,
                    "retry_of_index": rejected_ad.get('prompt_index'),
                })

                ctx.state.ads_reviewed += 1
                next_index += 1

            except Exception as e:
                logger.error(
                    f"  Retry failed for variation {rejected_ad.get('prompt_index')}: {e}"
                )

        logger.info(f"Retry complete: {ctx.state.ads_reviewed} total ads reviewed")
        return CompileResultsNode()
