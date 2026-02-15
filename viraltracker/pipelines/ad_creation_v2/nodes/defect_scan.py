"""
DefectScanNode — Stage 1 defect detection for generated ads.

Phase 4 node inserted between GenerateAdsNode and ReviewAdsNode.
Scans each generated ad for visual defects using Gemini Flash.

Defect-rejected ads are saved to DB immediately and appended to reviewed_ads
(so RetryRejectedNode + CompileResultsNode see all ads).
Clean ads flow to defect_passed_ads for Stage 2-3 review.
"""

import logging
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ..utils import stringify_uuids
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class DefectScanNode(BaseNode[AdCreationPipelineState]):
    """
    Step 6b: Stage 1 defect scan of generated ads.

    Runs after GenerateAdsNode, before ReviewAdsNode.
    For each generated ad:
    - Defect found: save to DB with final_status='rejected' + defect_scan_result,
      append to reviewed_ads immediately (visible downstream).
    - No defect: append to defect_passed_ads for Stage 2-3 review.

    Reads: generated_ads, product_dict, ad_run_id, content_source
    Writes: defect_passed_ads, defect_scan_results, reviewed_ads
    Services: DefectScanService.scan_for_defects(), AdCreationService.save_generated_ad()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["generated_ads", "product_dict", "ad_run_id", "content_source"],
        outputs=["defect_passed_ads", "defect_scan_results", "reviewed_ads"],
        services=["defect_scan_service.scan_for_defects", "ad_creation.save_generated_ad"],
        llm="Gemini Flash",
        llm_purpose="Binary defect detection (5 defect types)",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "ReviewAdsNode":
        from .review_ads import ReviewAdsNode
        from ..services.defect_scan_service import DefectScanService

        logger.info(f"Step 6b: Scanning {len(ctx.state.generated_ads)} ads for defects...")
        ctx.state.current_step = "defect_scan"

        scan_service = DefectScanService()
        defect_passed = []
        defect_rejected = []
        scan_results = []

        product_name = ""
        if ctx.state.product_dict:
            product_name = ctx.state.product_dict.get("name", "")

        for ad_data in ctx.state.generated_ads:
            prompt_index = ad_data.get("prompt_index", 0)

            # Skip generation-failed ads (they have no image to scan)
            if ad_data.get("final_status") == "generation_failed":
                # Pass through to reviewed_ads for CompileResults to count
                ctx.state.reviewed_ads.append({
                    "prompt_index": prompt_index,
                    "prompt": None,
                    "storage_path": None,
                    "claude_review": None,
                    "gemini_review": None,
                    "reviewers_agree": None,
                    "final_status": "generation_failed",
                    "error": ad_data.get("error"),
                })
                continue

            storage_path = ad_data.get("storage_path", "")

            # Download image for scanning
            try:
                image_base64 = await ctx.deps.ad_creation.get_image_as_base64(storage_path)
            except Exception as e:
                logger.warning(f"  Failed to download image for scan (variation {prompt_index}): {e}")
                # Can't scan → treat as passed
                defect_passed.append(ad_data)
                scan_results.append({
                    "prompt_index": prompt_index,
                    "passed": True,
                    "error": str(e),
                })
                continue

            # Run defect scan
            result = await scan_service.scan_for_defects(
                image_base64=image_base64,
                product_name=product_name,
            )

            scan_result_dict = result.to_dict()
            scan_result_dict["prompt_index"] = prompt_index
            scan_results.append(scan_result_dict)

            if result.passed:
                # No defects → pass to Stage 2-3 review
                ad_data["defect_scan_result"] = scan_result_dict
                defect_passed.append(ad_data)
            else:
                # Defect found → reject immediately
                logger.info(
                    f"  Variation {prompt_index} REJECTED by defect scan: "
                    f"{[d.type for d in result.defects]}"
                )

                # Save to DB with rejected status + defect scan result
                hook = ad_data.get("hook", {})
                if ctx.state.content_source == "hooks":
                    hook_id = UUID(hook["hook_id"]) if hook.get("hook_id") else None
                else:
                    hook_id = None

                generated_ad = ad_data.get("generated_ad", {}) or {}
                prompt = ad_data.get("prompt", {}) or {}
                ad_uuid_str = ad_data.get("ad_uuid")
                ad_uuid = UUID(ad_uuid_str) if ad_uuid_str else None

                await ctx.deps.ad_creation.save_generated_ad(
                    ad_run_id=UUID(ctx.state.ad_run_id),
                    prompt_index=prompt_index,
                    prompt_text=prompt.get("full_prompt", ""),
                    prompt_spec=stringify_uuids(prompt.get("json_prompt", {})),
                    hook_id=hook_id,
                    hook_text=hook.get("adapted_text", ""),
                    storage_path=storage_path,
                    final_status="rejected",
                    model_requested=generated_ad.get("model_requested"),
                    model_used=generated_ad.get("model_used"),
                    generation_time_ms=generated_ad.get("generation_time_ms"),
                    generation_retries=generated_ad.get("generation_retries", 0),
                    ad_id=ad_uuid,
                    canvas_size=ad_data.get("canvas_size"),
                    color_mode=ad_data.get("color_mode"),
                    defect_scan_result=scan_result_dict,
                    prompt_version=ctx.state.prompt_version,
                )

                # Append to reviewed_ads immediately (visible to RetryRejected + CompileResults)
                ctx.state.reviewed_ads.append({
                    "prompt_index": prompt_index,
                    "prompt": prompt,
                    "storage_path": storage_path,
                    "claude_review": None,
                    "gemini_review": None,
                    "reviewers_agree": None,
                    "final_status": "rejected",
                    "defect_rejected": True,
                    "defect_scan_result": scan_result_dict,
                    "ad_uuid": ad_uuid_str,
                    "canvas_size": ad_data.get("canvas_size"),
                    "color_mode": ad_data.get("color_mode"),
                })
                defect_rejected.append(ad_data)

        ctx.state.defect_passed_ads = defect_passed
        ctx.state.defect_scan_results = scan_results

        logger.info(
            f"Defect scan complete: {len(defect_passed)} passed, "
            f"{len(defect_rejected)} rejected"
        )
        ctx.state.mark_step_complete("defect_scan")

        return ReviewAdsNode()
