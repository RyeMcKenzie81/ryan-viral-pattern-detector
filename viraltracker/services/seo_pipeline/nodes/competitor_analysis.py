"""
Competitor Analysis Node — Analyzes top-ranking competitor pages.

Reads: selected_keyword, competitor_urls, project_id, organization_id
Writes: competitor_results, winning_formula
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState

logger = logging.getLogger(__name__)


@dataclass
class CompetitorAnalysisNode(BaseNode[SEOPipelineState]):
    """
    Step 3: Analyze competitor pages for the selected keyword.

    Scrapes top-ranking pages and extracts content metrics,
    then calculates winning formula targets.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["selected_keyword", "competitor_urls", "project_id", "organization_id"],
        outputs=["competitor_results", "winning_formula"],
        services=["competitor_analysis.analyze_urls"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "ContentPhaseANode":
        from .content_generation import ContentPhaseANode

        logger.info(f"Step 3: Analyzing competitors for '{ctx.state.selected_keyword}'...")
        ctx.state.current_step = "competitor_analysis"

        try:
            from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService
            service = CompetitorAnalysisService()

            result = service.analyze_urls(
                keyword_id=str(ctx.state.selected_keyword_id) if ctx.state.selected_keyword_id else "",
                urls=ctx.state.competitor_urls,
            )
            ctx.state.competitor_results = result.get("results", [])
            ctx.state.winning_formula = result.get("winning_formula")

            ctx.state.mark_step_complete("competitor_analysis")
            logger.info(f"Analyzed {len(ctx.state.competitor_results)} competitor pages")
            return ContentPhaseANode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "competitor_analysis"
            logger.error(f"Competitor analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "competitor_analysis"})
