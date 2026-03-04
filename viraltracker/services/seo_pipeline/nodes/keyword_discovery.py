"""
Keyword Discovery Node — Discovers keywords using Google Autocomplete.

Reads: seed_keywords, min_word_count, max_word_count, project_id, organization_id
Writes: discovered_keywords
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint

logger = logging.getLogger(__name__)


@dataclass
class KeywordDiscoveryNode(BaseNode[SEOPipelineState]):
    """
    Step 1: Discover keywords via Google Autocomplete.

    Uses seed keywords to discover long-tail keyword opportunities.
    After discovery, pauses for human keyword selection.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["seed_keywords", "min_word_count", "max_word_count", "project_id"],
        outputs=["discovered_keywords"],
        services=["keyword_discovery.discover_keywords"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> "KeywordSelectionNode":
        from .keyword_selection import KeywordSelectionNode

        logger.info("Step 1: Discovering keywords...")
        ctx.state.current_step = "keyword_discovery"

        try:
            from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
            service = KeywordDiscoveryService()

            keywords = await service.discover_keywords(
                project_id=str(ctx.state.project_id),
                seeds=ctx.state.seed_keywords,
                min_word_count=ctx.state.min_word_count,
                max_word_count=ctx.state.max_word_count,
            )

            ctx.state.discovered_keywords = keywords
            ctx.state.mark_step_complete("keyword_discovery")
            logger.info(f"Discovered {len(keywords)} keywords")
            return KeywordSelectionNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "keyword_discovery"
            logger.error(f"Keyword discovery failed: {e}")
            return End({"status": "error", "error": str(e), "step": "keyword_discovery"})
