"""
ReviewAdsNode - Dual AI review (Claude + Gemini) with OR logic.
"""

import logging
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


def _stringify_uuids(obj: Any) -> Any:
    """Recursively convert UUID values to strings in dicts/lists."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _stringify_uuids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_uuids(v) for v in obj]
    return obj


@dataclass
class ReviewAdsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 7: Dual AI review of all generated ads.

    For each successfully generated ad:
    1. Claude Vision review
    2. Gemini Vision review
    3. Apply OR logic (either approving = approved)
    4. Save review results to database

    Reads: generated_ads, product_dict, ad_analysis, content_source, ad_run_id
    Writes: reviewed_ads, ads_reviewed
    Services: ReviewService.review_ad_claude(), .review_ad_gemini(),
              .apply_dual_review_logic(), AdCreationService.save_generated_ad()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["generated_ads", "product_dict", "ad_analysis", "content_source", "ad_run_id"],
        outputs=["reviewed_ads", "ads_reviewed"],
        services=["review_service.review_ad_claude", "review_service.review_ad_gemini",
                   "review_service.apply_dual_review_logic", "ad_creation.save_generated_ad"],
        llm="Claude Vision + Gemini Vision",
        llm_purpose="Quality review of generated ads",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "RetryRejectedNode":
        from .retry_rejected import RetryRejectedNode
        from ..services.review_service import AdReviewService

        logger.info(f"Step 7: Reviewing {len(ctx.state.generated_ads)} ads with dual AI review...")
        ctx.state.current_step = "review_ads"

        review_service = AdReviewService()
        reviewed_ads = []

        for ad_data in ctx.state.generated_ads:
            prompt_index = ad_data["prompt_index"]

            # Skip failed generations
            if ad_data.get("final_status") == "generation_failed":
                reviewed_ads.append({
                    "prompt_index": prompt_index,
                    "prompt": None,
                    "storage_path": None,
                    "claude_review": None,
                    "gemini_review": None,
                    "reviewers_agree": None,
                    "final_status": "generation_failed",
                    "error": ad_data.get("error")
                })
                continue

            storage_path = ad_data["storage_path"]
            hook = ad_data["hook"]
            logger.info(f"  Reviewing variation {prompt_index}...")

            # Claude review
            claude_review = None
            try:
                claude_review = await review_service.review_ad_claude(
                    storage_path=storage_path,
                    product_name=ctx.state.product_dict.get('name'),
                    hook_text=hook.get('adapted_text', ''),
                    ad_analysis=ctx.state.ad_analysis,
                    ad_creation_service=ctx.deps.ad_creation,
                )
            except Exception as e:
                logger.warning(f"  Claude review failed for variation {prompt_index}: {e}")
                claude_review = review_service.make_failed_review("claude", str(e))

            # Gemini review
            gemini_review = None
            try:
                gemini_review = await review_service.review_ad_gemini(
                    storage_path=storage_path,
                    product_name=ctx.state.product_dict.get('name'),
                    hook_text=hook.get('adapted_text', ''),
                    ad_analysis=ctx.state.ad_analysis,
                    ad_creation_service=ctx.deps.ad_creation,
                    gemini_service=ctx.deps.gemini,
                )
            except Exception as e:
                logger.warning(f"  Gemini review failed for variation {prompt_index}: {e}")
                gemini_review = review_service.make_failed_review("gemini", str(e))

            # Apply dual review OR logic
            final_status, reviewers_agree = review_service.apply_dual_review_logic(
                claude_review, gemini_review
            )

            logger.info(f"  Reviews: Claude={claude_review.get('status')}, "
                        f"Gemini={gemini_review.get('status')}, Final={final_status}")

            # Determine hook_id for database
            if ctx.state.content_source == "hooks":
                hook_id = UUID(hook['hook_id'])
            else:
                hook_id = None

            # Save to database with reviews
            generated_ad = ad_data.get("generated_ad", {}) or {}
            prompt = ad_data.get("prompt", {}) or {}
            ad_uuid_str = ad_data.get("ad_uuid")
            ad_uuid = UUID(ad_uuid_str) if ad_uuid_str else None

            await ctx.deps.ad_creation.save_generated_ad(
                ad_run_id=UUID(ctx.state.ad_run_id),
                prompt_index=prompt_index,
                prompt_text=prompt.get('full_prompt', ''),
                prompt_spec=_stringify_uuids(prompt.get('json_prompt', {})),
                hook_id=hook_id,
                hook_text=hook.get('adapted_text', ''),
                storage_path=storage_path,
                claude_review=claude_review,
                gemini_review=gemini_review,
                final_status=final_status,
                model_requested=generated_ad.get('model_requested'),
                model_used=generated_ad.get('model_used'),
                generation_time_ms=generated_ad.get('generation_time_ms'),
                generation_retries=generated_ad.get('generation_retries', 0),
                ad_id=ad_uuid,
            )

            reviewed_ads.append({
                "prompt_index": prompt_index,
                "prompt": prompt,
                "storage_path": storage_path,
                "claude_review": claude_review,
                "gemini_review": gemini_review,
                "reviewers_agree": reviewers_agree,
                "final_status": final_status,
                "ad_uuid": ad_uuid_str,
            })

            ctx.state.ads_reviewed += 1

        ctx.state.reviewed_ads = reviewed_ads
        ctx.state.mark_step_complete("review_ads")
        logger.info(f"Review complete: {ctx.state.ads_reviewed} ads reviewed")

        return RetryRejectedNode()
