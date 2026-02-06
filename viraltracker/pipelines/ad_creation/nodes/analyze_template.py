"""
AnalyzeTemplateNode - Vision AI analysis of reference ad (with cache check).
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeTemplateNode(BaseNode[AdCreationPipelineState]):
    """
    Step 3: Analyze reference ad using Vision AI.

    For recreate_template mode, checks cache first (saves 4-8 minutes).
    For all modes, runs Vision AI analysis to extract format, layout, colors.

    Reads: reference_ad_path, reference_ad_base64, content_source
    Writes: ad_analysis, template_angle (if cached)
    Services: AnalysisService.analyze_reference_ad(),
              AdCreationService.get_cached_template_analysis()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reference_ad_path", "reference_ad_base64", "content_source"],
        outputs=["ad_analysis", "template_angle"],
        services=["analysis_service.analyze_reference_ad",
                   "ad_creation.get_cached_template_analysis"],
        llm="Gemini Vision",
        llm_purpose="Analyze reference ad format, layout, colors, authenticity markers",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "SelectContentNode":
        from .select_content import SelectContentNode
        from ..services.analysis_service import AdAnalysisService

        logger.info("Step 3: Analyzing reference ad with Vision AI...")
        ctx.state.current_step = "analyze_template"

        try:
            used_cache = False

            # Check cache for recreate_template mode
            if ctx.state.content_source == "recreate_template":
                logger.info("Checking for cached template analysis...")
                cached = await ctx.deps.ad_creation.get_cached_template_analysis(
                    ctx.state.reference_ad_path
                )
                if cached:
                    logger.info("CACHE HIT! Using cached analysis (skipping Vision AI call)")
                    ctx.state.ad_analysis = cached["ad_analysis"]
                    ctx.state.template_angle = cached["template_angle"]
                    used_cache = True
                else:
                    logger.info("Cache miss - running full analysis...")

            if not used_cache:
                # Run Vision AI analysis
                analysis_service = AdAnalysisService()

                # Get image as base64 from storage
                image_base64 = await ctx.deps.ad_creation.get_image_as_base64(
                    ctx.state.reference_ad_path
                )

                ad_analysis = await analysis_service.analyze_reference_ad(
                    image_base64=image_base64,
                    ad_creation_service=ctx.deps.ad_creation,
                )
                ctx.state.ad_analysis = ad_analysis

            # Save analysis to ad run
            await ctx.deps.ad_creation.update_ad_run(
                ad_run_id=UUID(ctx.state.ad_run_id),
                ad_analysis=ctx.state.ad_analysis
            )

            ctx.state.mark_step_complete("analyze_template")
            logger.info(f"Analysis complete: format={ctx.state.ad_analysis.get('format_type')}, "
                        f"layout={ctx.state.ad_analysis.get('layout_structure')}")

            return SelectContentNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "analyze_template"
            logger.error(f"Analyze template failed: {e}")

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
