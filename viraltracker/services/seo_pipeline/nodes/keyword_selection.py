"""
Keyword Selection Node — HUMAN CHECKPOINT.

Pauses the pipeline for the user to select a target keyword from
the discovered keywords list.

Reads: discovered_keywords, human_input
Writes: selected_keyword_id, selected_keyword
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint

logger = logging.getLogger(__name__)


@dataclass
class KeywordSelectionNode(BaseNode[SEOPipelineState]):
    """
    Step 2: HUMAN CHECKPOINT — Select target keyword.

    Pauses execution for the user to pick a keyword from discovered list.
    On resume, sets selected_keyword_id and proceeds to competitor analysis.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["discovered_keywords", "human_input"],
        outputs=["selected_keyword_id", "selected_keyword"],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> Union["CompetitorAnalysisNode", End]:
        from .competitor_analysis import CompetitorAnalysisNode

        ctx.state.current_step = "keyword_selection"
        ctx.state.current_checkpoint = SEOHumanCheckpoint.KEYWORD_SELECTION

        # Check for human input (resume case)
        if ctx.state.human_input:
            human_input = ctx.state.human_input
            ctx.state.human_input = None

            action = human_input.get("action", "select")

            if action == "select":
                keyword_id = human_input.get("keyword_id")
                keyword_text = human_input.get("keyword")

                if keyword_id:
                    try:
                        ctx.state.selected_keyword_id = UUID(str(keyword_id))
                    except ValueError:
                        pass  # Non-UUID keyword ID (e.g., from discovery)
                if keyword_text:
                    ctx.state.selected_keyword = keyword_text
                elif keyword_id:
                    # Find keyword text from discovered list
                    for kw in ctx.state.discovered_keywords:
                        if str(kw.get("id")) == str(keyword_id):
                            ctx.state.selected_keyword = kw.get("keyword", "")
                            break

                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("keyword_selection")
                logger.info(f"Keyword selected: {ctx.state.selected_keyword}")

                # Also set competitor_urls from human input if provided
                if human_input.get("competitor_urls"):
                    ctx.state.competitor_urls = human_input["competitor_urls"]

                return CompetitorAnalysisNode()

            elif action == "rediscover":
                # User wants more keywords — loop back
                from .keyword_discovery import KeywordDiscoveryNode
                if human_input.get("seed_keywords"):
                    ctx.state.seed_keywords = human_input["seed_keywords"]
                ctx.state.awaiting_human = False
                return KeywordDiscoveryNode()

            return End({"status": "error", "error": f"Invalid action: {action}"})

        # No human input — pause for selection
        ctx.state.awaiting_human = True
        logger.info(f"Pausing for keyword selection ({len(ctx.state.discovered_keywords)} options)")
        return End({
            "status": "awaiting_human",
            "checkpoint": SEOHumanCheckpoint.KEYWORD_SELECTION.value,
            "keywords": ctx.state.discovered_keywords,
            "message": "Select a target keyword to continue.",
        })
