"""
RetryRejectedNode - Auto-retry rejected ads with fresh generation + review.

Phase 5: Uses DefectScanService + review_ad_staged() (15-check rubric)
instead of V1 dual review. Consistent with ReviewAdsNode flow.
"""

import base64
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
    runs defect scan + staged review, and appends the result to reviewed_ads.
    The original rejected ad stays in the list.

    Phase 5: Uses DefectScanService + review_ad_staged() (15-check rubric)
    instead of V1 dual review (review_ad_claude + review_ad_gemini).

    Reads: reviewed_ads, auto_retry_rejected, max_retry_attempts,
           product_dict, ad_analysis, ad_brief_instructions,
           reference_ad_path, selected_images, color_mode,
           brand_colors, brand_fonts, ad_run_id, content_source,
           congruence_results
    Writes: reviewed_ads (appends retried ads)
    Services: GenerationService, DefectScanService, ReviewService, AdCreationService
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reviewed_ads", "auto_retry_rejected", "max_retry_attempts",
                "product_dict", "ad_analysis", "ad_run_id", "congruence_results"],
        outputs=["reviewed_ads"],
        services=["generation_service.generate_prompt", "generation_service.execute_generation",
                   "defect_scan_service.scan_for_defects",
                   "review_service.review_ad_staged",
                   "ad_creation.upload_generated_ad", "ad_creation.save_generated_ad"],
        llm="Gemini Image Gen + Gemini Flash (defect) + Claude Vision + Gemini Vision (staged)",
        llm_purpose="Retry rejected ads with fresh generation, defect scan, and staged review",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "CompileResultsNode":
        from .compile_results import CompileResultsNode
        from ..services.generation_service import AdGenerationService
        from ..services.review_service import AdReviewService, load_quality_config
        from ..services.defect_scan_service import DefectScanService

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
        defect_service = DefectScanService()
        selected_image_paths = [img["storage_path"] for img in ctx.state.selected_images]

        # Phase 3: Collect selected_image_tags (same as GenerateAdsNode)
        selected_image_tags = []
        for img in ctx.state.selected_images:
            for tag in (img.get("asset_tags") or []):
                if tag not in selected_image_tags:
                    selected_image_tags.append(tag)

        # Load quality config once (same pattern as ReviewAdsNode)
        quality_config = None
        try:
            quality_config = await load_quality_config()
        except Exception as e:
            logger.warning(f"Could not load quality config, using defaults: {e}")

        # Build congruence lookup from state
        congruence_lookup = {}
        for cr in (ctx.state.congruence_results or []):
            headline = cr.get("headline", "")
            congruence_lookup[headline] = cr.get("overall_score")

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

                product_id_for_naming = await ctx.deps.ad_creation.get_product_id_for_run(
                    UUID(ctx.state.ad_run_id)
                )

                storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=next_index,
                    image_base64=generated_ad['image_base64'],
                    product_id=product_id_for_naming,
                    ad_id=ad_uuid,
                    canvas_size=retry_canvas_size,
                )

                # Stage 1: Defect scan
                defect_result = await defect_service.scan_for_defects(
                    image_base64=generated_ad['image_base64'],
                    product_name=ctx.state.product_dict.get('name', ''),
                )
                defect_scan_result = defect_result.to_dict()

                # Determine hook_id for database
                if ctx.state.content_source == "hooks":
                    hook_id = UUID(selected_hook['hook_id'])
                else:
                    hook_id = None

                # Get original ad UUID for regenerate_parent_id
                original_ad_uuid_str = rejected_ad.get('ad_uuid')
                original_ad_uuid = UUID(original_ad_uuid_str) if original_ad_uuid_str else None

                # Look up congruence score from state
                hook_text = selected_hook.get('adapted_text', '')
                congruence_score = congruence_lookup.get(hook_text)

                if not defect_result.passed:
                    # Defect found → reject immediately (same as DefectScanNode)
                    logger.info(
                        f"  Retry of variation {rejected_ad.get('prompt_index')}: "
                        f"REJECTED by defect scan: {[d.type for d in defect_result.defects]}"
                    )

                    await ctx.deps.ad_creation.save_generated_ad(
                        ad_run_id=UUID(ctx.state.ad_run_id),
                        prompt_index=next_index,
                        prompt_text=prompt.get('full_prompt', ''),
                        prompt_spec=stringify_uuids(prompt.get('json_prompt', {})),
                        hook_id=hook_id,
                        hook_text=hook_text,
                        storage_path=storage_path,
                        final_status="rejected",
                        model_requested=generated_ad.get('model_requested'),
                        model_used=generated_ad.get('model_used'),
                        generation_time_ms=generated_ad.get('generation_time_ms'),
                        generation_retries=generated_ad.get('generation_retries', 0),
                        ad_id=ad_uuid,
                        regenerate_parent_id=original_ad_uuid,
                        canvas_size=retry_canvas_size,
                        color_mode=retry_color_mode,
                        defect_scan_result=defect_scan_result,
                        congruence_score=congruence_score,
                        prompt_version=ctx.state.prompt_version,
                    )

                    ctx.state.reviewed_ads.append({
                        "prompt_index": next_index,
                        "prompt": prompt,
                        "storage_path": storage_path,
                        "review_check_scores": None,
                        "final_status": "rejected",
                        "defect_rejected": True,
                        "defect_scan_result": defect_scan_result,
                        "ad_uuid": str(ad_uuid),
                        "canvas_size": retry_canvas_size,
                        "color_mode": retry_color_mode,
                        "weighted_score": None,
                        "congruence_score": congruence_score,
                        "is_retry": True,
                        "retry_of_index": rejected_ad.get('prompt_index'),
                    })

                    ctx.state.ads_reviewed += 1
                    next_index += 1
                    continue

                # Stage 2-3: Staged review (defect scan passed)
                image_data = base64.b64decode(generated_ad['image_base64'])
                review_result = None
                final_status = "review_failed"
                review_check_scores = None

                try:
                    review_result = await review_service.review_ad_staged(
                        image_data=image_data,
                        product_name=ctx.state.product_dict.get('name', ''),
                        hook_text=hook_text,
                        ad_analysis=ctx.state.ad_analysis or {},
                        config=quality_config,
                    )
                    final_status = review_result.get("final_status", "review_failed")
                    review_check_scores = review_result.get("review_check_scores")
                except Exception as e:
                    logger.warning(f"  Staged review failed for retry: {e}")
                    final_status = "review_failed"

                logger.info(
                    f"  Retry of variation {rejected_ad.get('prompt_index')}: "
                    f"Final={final_status}"
                )

                # Save to database with structured review data
                await ctx.deps.ad_creation.save_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=next_index,
                    prompt_text=prompt.get('full_prompt', ''),
                    prompt_spec=stringify_uuids(prompt.get('json_prompt', {})),
                    hook_id=hook_id,
                    hook_text=hook_text,
                    storage_path=storage_path,
                    claude_review=review_result,
                    gemini_review=None,
                    final_status=final_status,
                    model_requested=generated_ad.get('model_requested'),
                    model_used=generated_ad.get('model_used'),
                    generation_time_ms=generated_ad.get('generation_time_ms'),
                    generation_retries=generated_ad.get('generation_retries', 0),
                    ad_id=ad_uuid,
                    regenerate_parent_id=original_ad_uuid,
                    canvas_size=retry_canvas_size,
                    color_mode=retry_color_mode,
                    defect_scan_result=defect_scan_result,
                    review_check_scores=review_check_scores,
                    congruence_score=congruence_score,
                    prompt_version=ctx.state.prompt_version,
                )

                # Append retry result to reviewed_ads (match ReviewAdsNode dict shape)
                ctx.state.reviewed_ads.append({
                    "prompt_index": next_index,
                    "prompt": prompt,
                    "storage_path": storage_path,
                    "review_check_scores": review_check_scores,
                    "final_status": final_status,
                    "ad_uuid": str(ad_uuid),
                    "canvas_size": retry_canvas_size,
                    "color_mode": retry_color_mode,
                    "weighted_score": review_result.get("weighted_score") if review_result else None,
                    "congruence_score": congruence_score,
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
