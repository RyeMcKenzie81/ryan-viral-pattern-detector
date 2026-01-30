"""
CompileResultsNode - Compile final results and update ad_run status.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Dict, Any
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class CompileResultsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 8: Compile final results and mark workflow complete.

    Counts approved/rejected/flagged ads, builds summary, updates ad_run status.

    Reads: reviewed_ads, product_dict, ad_analysis, content_source, template_angle,
           selected_hooks, reference_ad_path, ad_run_id, angle_data, num_variations
    Writes: (none - returns End with result dict)
    Services: AdCreationService.update_ad_run()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reviewed_ads", "product_dict", "ad_run_id", "content_source"],
        outputs=[],
        services=["ad_creation.update_ad_run"],
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> End[Dict[str, Any]]:
        logger.info("Step 8: Compiling final results...")
        ctx.state.current_step = "compile_results"

        reviewed_ads = ctx.state.reviewed_ads

        # Count statuses
        approved_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'approved')
        rejected_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'rejected')
        flagged_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'flagged')
        generation_failed_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'generation_failed')
        review_failed_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'review_failed')

        # Build summary
        content_source_labels = {
            "hooks": "hooks",
            "recreate_template": "template recreation (benefits/USPs)",
            "belief_first": f"belief-first angle: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
            "plan": f"belief plan: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
            "angles": f"direct angles: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
        }
        content_source_label = content_source_labels.get(
            ctx.state.content_source, ctx.state.content_source
        )

        summary_parts = [
            f"Ad creation workflow completed for {ctx.state.product_dict.get('name')}.",
            "",
            f"**Content Source:** {content_source_label}",
            "",
            "**Results:**",
            f"- Total ads requested: {ctx.state.num_variations}",
            f"- Approved (production-ready): {approved_count}",
            f"- Rejected (both reviewers): {rejected_count}",
            f"- Flagged (reviewer disagreement): {flagged_count}",
            f"- Generation failed: {generation_failed_count}",
            f"- Review failed: {review_failed_count}",
            "",
            "**Next Steps:**",
        ]

        if approved_count > 0:
            summary_parts.append(f"- {approved_count} ads ready for immediate use")
        if (flagged_count + review_failed_count) > 0:
            summary_parts.append(f"- {flagged_count + review_failed_count} ads require human review")
        if (rejected_count + generation_failed_count) > 0:
            summary_parts.append(f"- {rejected_count + generation_failed_count} ads should be regenerated")

        summary = "\n".join(summary_parts)

        # Mark workflow complete
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ctx.state.ad_run_id),
            status="complete"
        )

        result = {
            "ad_run_id": ctx.state.ad_run_id,
            "product": ctx.state.product_dict,
            "reference_ad_path": ctx.state.reference_ad_path,
            "ad_analysis": ctx.state.ad_analysis,
            "content_source": ctx.state.content_source,
            "template_angle": ctx.state.template_angle,
            "selected_hooks": ctx.state.selected_hooks,
            "generated_ads": reviewed_ads,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "flagged_count": flagged_count,
            "summary": summary,
            "created_at": datetime.now().isoformat()
        }

        ctx.state.mark_step_complete("compile_results")
        logger.info(f"=== WORKFLOW COMPLETE: {approved_count} approved, "
                    f"{rejected_count} rejected, {flagged_count} flagged ===")

        return End(result)
