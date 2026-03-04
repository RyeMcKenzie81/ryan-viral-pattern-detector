"""
SelectContentNode - Branch by content_source to select hooks or generate variations.
"""

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
class SelectContentNode(BaseNode[AdCreationPipelineState]):
    """
    Step 4: Select content based on content_source mode.

    Branches:
    - hooks: AI-selects diverse hooks from database
    - recreate_template: Extracts template angle + generates benefit variations
    - belief_first/plan/angles: Uses provided angle data

    Reads: content_source, hooks_list, ad_analysis, product_dict, persona_data,
           angle_data, match_template_structure, reference_ad_path
    Writes: selected_hooks, template_angle
    Services: ContentService.select_hooks(), .generate_benefit_variations(),
              .adapt_belief_to_template(), AnalysisService.extract_template_angle()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["content_source", "hooks_list", "ad_analysis", "product_dict",
                "persona_data", "angle_data", "match_template_structure"],
        outputs=["selected_hooks", "template_angle"],
        services=["content_service.select_hooks", "content_service.generate_benefit_variations",
                   "content_service.adapt_belief_to_template",
                   "analysis_service.extract_template_angle"],
        llm="Claude Opus 4.5",
        llm_purpose="Select/adapt hooks or generate benefit variations",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "HeadlineCongruenceNode":
        from .headline_congruence import HeadlineCongruenceNode
        from ..services.content_service import AdContentService
        from ..services.analysis_service import AdAnalysisService

        logger.info(f"Step 4: Selecting content ({ctx.state.content_source} mode)...")
        ctx.state.current_step = "select_content"

        try:
            content_source = ctx.state.content_source
            content_service = AdContentService()

            # Get docs service for knowledge base (may be None)
            docs_service = getattr(ctx.deps, 'docs', None)

            if content_source == "hooks":
                # Extract offer variant data for offer-aware hook selection
                offer_variant_data = None
                if ctx.state.product_dict:
                    offer_variant_data = ctx.state.product_dict.get('offer_variant')

                # Select diverse hooks from database
                logger.info(f"Selecting {ctx.state.num_variations} diverse hooks with AI...")
                selected_hooks = await content_service.select_hooks(
                    hooks=ctx.state.hooks_list,
                    ad_analysis=ctx.state.ad_analysis,
                    product_name=ctx.state.product_dict.get('name', ''),
                    target_audience=(
                        ctx.state.product_dict.get('offer_target_audience')
                        or ctx.state.product_dict.get('target_audience', '')
                    ),
                    count=ctx.state.num_variations,
                    persona_data=ctx.state.persona_data,
                    docs_service=docs_service,
                    offer_variant_data=offer_variant_data,
                    current_offer=ctx.state.product_dict.get('current_offer') if ctx.state.product_dict else None,
                )
                ctx.state.selected_hooks = selected_hooks
                if len(selected_hooks) < ctx.state.num_variations:
                    logger.warning(
                        f"Offer sanitization reduced hooks from {ctx.state.num_variations} to {len(selected_hooks)}"
                    )

            elif content_source == "recreate_template":
                # Extract template angle if not cached
                if not ctx.state.template_angle:
                    logger.info("Extracting template angle...")
                    analysis_service = AdAnalysisService()

                    image_base64 = await ctx.deps.ad_creation.get_image_as_base64(
                        ctx.state.reference_ad_path
                    )
                    template_angle = await analysis_service.extract_template_angle(
                        image_base64=image_base64,
                        ad_analysis=ctx.state.ad_analysis,
                    )
                    ctx.state.template_angle = template_angle

                    # Save to cache
                    logger.info("Saving template analysis to cache...")
                    await ctx.deps.ad_creation.save_template_analysis(
                        storage_path=ctx.state.reference_ad_path,
                        ad_analysis=ctx.state.ad_analysis,
                        template_angle=template_angle
                    )

                # Generate benefit variations
                logger.info(f"Generating {ctx.state.num_variations} benefit variations...")
                selected_hooks = await content_service.generate_benefit_variations(
                    product=ctx.state.product_dict,
                    template_angle=ctx.state.template_angle,
                    ad_analysis=ctx.state.ad_analysis,
                    count=ctx.state.num_variations,
                    persona_data=ctx.state.persona_data,
                    docs_service=docs_service,
                )
                ctx.state.selected_hooks = selected_hooks

            elif content_source in ["belief_first", "plan", "angles"]:
                # Use provided angle data
                angle_data = ctx.state.angle_data
                if not angle_data:
                    raise ValueError(f"angle_data is required for {content_source} content source")

                logger.info(f"Using belief-first mode with angle: {angle_data.get('name', 'Unknown')}")

                # Extract template if match_template_structure
                template_angle = None
                if ctx.state.match_template_structure:
                    logger.info("Match template structure enabled - extracting template...")
                    analysis_service = AdAnalysisService()

                    image_base64 = await ctx.deps.ad_creation.get_image_as_base64(
                        ctx.state.reference_ad_path
                    )
                    template_angle = await analysis_service.extract_template_angle(
                        image_base64=image_base64,
                        ad_analysis=ctx.state.ad_analysis,
                    )
                    ctx.state.template_angle = template_angle

                # Build hook-like structures from angle data
                selected_hooks = []
                belief_text = angle_data.get("belief_statement", "")

                for i in range(ctx.state.num_variations):
                    if template_angle and ctx.state.match_template_structure:
                        adapted_text = await content_service.adapt_belief_to_template(
                            belief_statement=belief_text,
                            template_angle=template_angle,
                            product=ctx.state.product_dict,
                            variation_number=i + 1
                        )
                        content_type = "belief_angle_templated"
                    else:
                        from ..services.content_service import _sanitize_dashes
                        adapted_text = _sanitize_dashes(belief_text)
                        content_type = "belief_angle"

                    selected_hooks.append({
                        "hook_id": angle_data.get("id", ""),
                        "hook_text": belief_text,
                        "adapted_text": adapted_text,
                        "angle_name": angle_data.get("name", ""),
                        "explanation": angle_data.get("explanation", ""),
                        "variation_number": i + 1,
                        "content_type": content_type
                    })

                ctx.state.selected_hooks = selected_hooks
                logger.info(f"Created {len(selected_hooks)} belief-based variations")

            else:
                raise ValueError(f"Unknown content_source: {content_source}")

            # Save selected hooks to ad run
            await ctx.deps.ad_creation.update_ad_run(
                ad_run_id=UUID(ctx.state.ad_run_id),
                selected_hooks=ctx.state.selected_hooks
            )

            ctx.state.mark_step_complete("select_content")
            logger.info(f"Content selected: {len(ctx.state.selected_hooks)} variations")

            return HeadlineCongruenceNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "select_content"
            logger.error(f"Select content failed: {e}")

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
