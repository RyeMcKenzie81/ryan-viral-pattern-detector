"""
ReviewAdsNode — Phase 4 staged review (Stage 2-3) with structured rubric scores.

Phase 4: Uses review_ad_staged() for 15-check rubric scoring via Claude Vision,
with conditional Gemini Vision Stage 3 for borderline ads.
"""

import base64
import logging
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
class ReviewAdsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 7: Phase 4 staged review of generated ads.

    For each successfully generated ad (from defect_passed_ads):
    1. Stage 2: Claude Vision 15-check rubric review
    2. Stage 3: Conditional Gemini Vision (if borderline)
    3. Save structured review scores to database

    Reads: defect_passed_ads (or generated_ads fallback), product_dict,
           ad_analysis, content_source, ad_run_id, congruence_results
    Writes: reviewed_ads, ads_reviewed
    Services: ReviewService.review_ad_staged(), AdCreationService.save_generated_ad()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["defect_passed_ads", "product_dict", "ad_analysis", "content_source",
                "ad_run_id", "congruence_results"],
        outputs=["reviewed_ads", "ads_reviewed"],
        services=["review_service.review_ad_staged", "ad_creation.save_generated_ad"],
        llm="Claude Vision + Gemini Vision",
        llm_purpose="15-check rubric review with conditional Stage 3",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "RetryRejectedNode":
        from .retry_rejected import RetryRejectedNode
        from ..services.review_service import AdReviewService, load_quality_config

        # Phase 4: Review only defect-passed ads (defect-rejected already in reviewed_ads)
        ads_to_review = ctx.state.defect_passed_ads if ctx.state.defect_passed_ads else ctx.state.generated_ads
        logger.info(f"Step 7: Reviewing {len(ads_to_review)} ads with staged review...")
        ctx.state.current_step = "review_ads"

        review_service = AdReviewService()

        # Load quality config from DB (org-specific or global fallback)
        quality_config = None
        try:
            quality_config = await load_quality_config()
        except Exception as e:
            logger.warning(f"Could not load quality config, using defaults: {e}")

        # Phase 8A: Prepare exemplar service for review calibration
        exemplar_service = None
        visual_service = None
        brand_id = ctx.state.product_dict.get("brand_id")
        try:
            from ..services.exemplar_service import ExemplarService
            from ..services.visual_descriptor_service import VisualDescriptorService
            exemplar_service = ExemplarService()
            visual_service = VisualDescriptorService()
        except Exception as e:
            logger.debug(f"Phase 8A exemplar services unavailable: {e}")

        # Build congruence lookup from state
        congruence_lookup = {}
        for cr in (ctx.state.congruence_results or []):
            headline = cr.get("headline", "")
            congruence_lookup[headline] = cr.get("overall_score")

        reviewed_ads = []

        for ad_data in ads_to_review:
            prompt_index = ad_data["prompt_index"]

            # Skip failed generations
            if ad_data.get("final_status") == "generation_failed":
                reviewed_ads.append({
                    "prompt_index": prompt_index,
                    "prompt": None,
                    "storage_path": None,
                    "review_check_scores": None,
                    "final_status": "generation_failed",
                    "error": ad_data.get("error")
                })
                continue

            storage_path = ad_data["storage_path"]
            hook = ad_data["hook"]
            logger.info(f"  Reviewing variation {prompt_index}...")

            # Get image data for staged review
            image_data = None
            try:
                image_base64 = await ctx.deps.ad_creation.get_image_as_base64(storage_path)
                image_data = base64.b64decode(image_base64)
            except Exception as e:
                logger.warning(f"  Could not load image for review, variation {prompt_index}: {e}")

            # Staged review (Stage 2 Claude + conditional Stage 3 Gemini)
            review_result = None
            final_status = "review_failed"
            review_check_scores = None

            if image_data:
                # Phase 8A: Build exemplar context for review calibration
                exemplar_context = None
                if exemplar_service and visual_service and brand_id:
                    try:
                        from uuid import UUID as _UUID
                        ad_uuid_for_embed = ad_data.get("ad_uuid")
                        ad_embedding = None
                        if ad_uuid_for_embed:
                            ad_embedding = await visual_service.get_embedding(
                                _UUID(ad_uuid_for_embed)
                            )
                        if ad_embedding is None:
                            # Extract embedding on-the-fly
                            descriptors = await visual_service.extract_descriptors(image_data)
                            ad_embedding = await visual_service.embed_descriptors(descriptors)

                        if ad_embedding:
                            exemplar_context = await exemplar_service.build_exemplar_context(
                                _UUID(brand_id) if isinstance(brand_id, str) else brand_id,
                                ad_embedding,
                            )
                    except Exception as e:
                        logger.debug(f"Exemplar context unavailable for variation {prompt_index}: {e}")

                try:
                    review_result = await review_service.review_ad_staged(
                        image_data=image_data,
                        product_name=ctx.state.product_dict.get('name', ''),
                        hook_text=hook.get('adapted_text', ''),
                        ad_analysis=ctx.state.ad_analysis or {},
                        config=quality_config,
                        exemplar_context=exemplar_context,
                    )
                    final_status = review_result.get("final_status", "review_failed")
                    review_check_scores = review_result.get("review_check_scores")
                except Exception as e:
                    logger.warning(f"  Staged review failed for variation {prompt_index}: {e}")
                    final_status = "review_failed"

            logger.info(f"  Variation {prompt_index}: {final_status}")

            # Phase 8A: Store visual embedding for this ad (non-blocking)
            if image_data and visual_service and brand_id:
                ad_uuid_for_ve = ad_data.get("ad_uuid")
                if ad_uuid_for_ve:
                    try:
                        from uuid import UUID as _UUID
                        await visual_service.extract_and_store(
                            generated_ad_id=_UUID(ad_uuid_for_ve),
                            brand_id=_UUID(brand_id) if isinstance(brand_id, str) else brand_id,
                            image_data=image_data,
                        )
                    except Exception as e:
                        logger.warning(f"Visual embedding storage failed for {ad_uuid_for_ve}: {e}")

            # Look up congruence score from state
            hook_text = hook.get('adapted_text', '') or hook.get('hook_text', '')
            congruence_score = congruence_lookup.get(hook_text)

            # Determine hook_id for database
            if ctx.state.content_source == "hooks":
                hook_id = UUID(hook['hook_id'])
            else:
                hook_id = None

            # Save to database with structured review data
            generated_ad = ad_data.get("generated_ad", {}) or {}
            prompt = ad_data.get("prompt", {}) or {}
            ad_uuid_str = ad_data.get("ad_uuid")
            ad_uuid = UUID(ad_uuid_str) if ad_uuid_str else None

            await ctx.deps.ad_creation.save_generated_ad(
                ad_run_id=UUID(ctx.state.ad_run_id),
                prompt_index=prompt_index,
                prompt_text=prompt.get('full_prompt', ''),
                prompt_spec=stringify_uuids(prompt.get('json_prompt', {})),
                hook_id=hook_id,
                hook_text=hook.get('adapted_text', ''),
                storage_path=storage_path,
                claude_review=review_result,
                gemini_review=None,
                final_status=final_status,
                model_requested=generated_ad.get('model_requested'),
                model_used=generated_ad.get('model_used'),
                generation_time_ms=generated_ad.get('generation_time_ms'),
                generation_retries=generated_ad.get('generation_retries', 0),
                ad_id=ad_uuid,
                canvas_size=ad_data.get("canvas_size"),
                color_mode=ad_data.get("color_mode"),
                # Phase 4: structured scores, defect result, congruence
                defect_scan_result=ad_data.get("defect_scan_result"),
                review_check_scores=review_check_scores,
                congruence_score=congruence_score,
                # Phase 5: prompt versioning
                prompt_version=ctx.state.prompt_version,
                # Phase 6: Creative Genome element tags + pre-gen score
                element_tags=ad_data.get("element_tags"),
                pre_gen_score=ad_data.get("pre_gen_score"),
            )

            reviewed_ads.append({
                "prompt_index": prompt_index,
                "prompt": prompt,
                "storage_path": storage_path,
                "review_check_scores": review_check_scores,
                "final_status": final_status,
                "ad_uuid": ad_uuid_str,
                "canvas_size": ad_data.get("canvas_size"),
                "color_mode": ad_data.get("color_mode"),
                "weighted_score": review_result.get("weighted_score") if review_result else None,
                "congruence_score": congruence_score,
            })

            ctx.state.ads_reviewed += 1

        # Phase 4: Append to reviewed_ads (defect-rejected ads already there from DefectScanNode)
        ctx.state.reviewed_ads.extend(reviewed_ads)
        ctx.state.mark_step_complete("review_ads")
        logger.info(f"Review complete: {ctx.state.ads_reviewed} ads reviewed")

        return RetryRejectedNode()
