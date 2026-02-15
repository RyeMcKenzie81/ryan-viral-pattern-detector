"""
HeadlineCongruenceNode - Score headline ↔ offer/LP/belief congruence.

Phase 4 node inserted between SelectContentNode and SelectImagesNode.
For each selected hook, checks congruence against offer variant, LP hero,
and belief data. Replaces hooks below threshold with adapted headlines.
Pass-through when no offer_variant_id (neutral score 1.0).
"""

import logging
from dataclasses import dataclass
from typing import ClassVar

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class HeadlineCongruenceNode(BaseNode[AdCreationPipelineState]):
    """
    Step 4b: Score headline congruence against offer variant, LP hero, and belief.

    Runs after SelectContentNode, before SelectImagesNode.
    If no offer_variant_id: pass-through (all hooks score 1.0).
    If below threshold AND adapted headline returned: replaces hook text.

    Reads: selected_hooks, offer_variant_id, lp_hero_data, angle_data,
           product_dict (for offer_variant sub-dict)
    Writes: congruence_results, selected_hooks (may update hook_text)
    Services: CongruenceService.check_congruence_batch()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["selected_hooks", "offer_variant_id", "lp_hero_data",
                "angle_data", "product_dict"],
        outputs=["congruence_results", "selected_hooks"],
        services=["congruence_service.check_congruence_batch"],
        llm="Claude Sonnet",
        llm_purpose="Score headline ↔ offer/LP/belief congruence",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "SelectImagesNode":
        from .select_images import SelectImagesNode
        from ..services.congruence_service import CongruenceService

        logger.info("Step 4b: Checking headline congruence...")
        ctx.state.current_step = "headline_congruence"

        # Pass-through if no offer variant (nothing to compare against)
        if not ctx.state.offer_variant_id:
            logger.info("No offer_variant_id — skipping congruence (pass-through)")
            ctx.state.congruence_results = [
                {
                    "headline": h.get("hook_text", ""),
                    "overall_score": 1.0,
                    "dimensions_scored": 0,
                    "skipped": True,
                }
                for h in ctx.state.selected_hooks
            ]
            ctx.state.mark_step_complete("headline_congruence")
            return SelectImagesNode()

        try:
            service = CongruenceService()

            # Gather context
            offer_variant_data = None
            if ctx.state.product_dict:
                offer_variant_data = ctx.state.product_dict.get("offer_variant")

            lp_hero_data = ctx.state.lp_hero_data
            belief_data = ctx.state.angle_data

            # Batch check all hooks
            results = await service.check_congruence_batch(
                hooks=ctx.state.selected_hooks,
                offer_variant_data=offer_variant_data,
                lp_hero_data=lp_hero_data,
                belief_data=belief_data,
            )

            # Process results: replace hooks below threshold with adapted headlines
            congruence_dicts = []
            adapted_count = 0
            for i, cr in enumerate(results):
                result_dict = {
                    "headline": cr.headline,
                    "offer_alignment": cr.offer_alignment,
                    "hero_alignment": cr.hero_alignment,
                    "belief_alignment": cr.belief_alignment,
                    "overall_score": cr.overall_score,
                    "adapted_headline": cr.adapted_headline,
                    "dimensions_scored": cr.dimensions_scored,
                }

                if cr.adapted_headline and i < len(ctx.state.selected_hooks):
                    original = ctx.state.selected_hooks[i].get("hook_text", "")
                    ctx.state.selected_hooks[i]["hook_text"] = cr.adapted_headline
                    ctx.state.selected_hooks[i]["original_hook_text"] = original
                    ctx.state.selected_hooks[i]["congruence_adapted"] = True
                    adapted_count += 1
                    result_dict["was_adapted"] = True
                    logger.info(
                        f"Hook {i+1} adapted (score={cr.overall_score:.2f}): "
                        f"\"{original[:40]}...\" → \"{cr.adapted_headline[:40]}...\""
                    )

                congruence_dicts.append(result_dict)

            ctx.state.congruence_results = congruence_dicts

            scores = [cr.overall_score for cr in results]
            avg_score = sum(scores) / len(scores) if scores else 1.0
            logger.info(
                f"Congruence complete: {len(results)} hooks scored, "
                f"avg={avg_score:.2f}, {adapted_count} adapted"
            )

            ctx.state.mark_step_complete("headline_congruence")
            return SelectImagesNode()

        except Exception as e:
            # Non-fatal: log warning and pass through
            logger.warning(f"Congruence check failed (non-fatal, passing through): {e}")
            ctx.state.congruence_results = [
                {
                    "headline": h.get("hook_text", ""),
                    "overall_score": 1.0,
                    "dimensions_scored": 0,
                    "error": str(e),
                }
                for h in ctx.state.selected_hooks
            ]
            ctx.state.mark_step_complete("headline_congruence")
            return SelectImagesNode()
