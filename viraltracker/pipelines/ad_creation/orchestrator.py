"""
Ad Creation Pipeline Orchestrator - Graph definition and convenience functions.

Defines the pydantic-graph pipeline for ad creation and provides
run_ad_creation() as the main entry point.
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

from pydantic_graph import Graph

from .state import AdCreationPipelineState
from .nodes.initialize import InitializeNode
from .nodes.fetch_context import FetchContextNode
from .nodes.analyze_template import AnalyzeTemplateNode
from .nodes.select_content import SelectContentNode
from .nodes.select_images import SelectImagesNode
from .nodes.generate_ads import GenerateAdsNode
from .nodes.review_ads import ReviewAdsNode
from .nodes.compile_results import CompileResultsNode

logger = logging.getLogger(__name__)

# ============================================================================
# Graph Definition
# ============================================================================

ad_creation_graph = Graph(
    nodes=(
        InitializeNode,
        FetchContextNode,
        AnalyzeTemplateNode,
        SelectContentNode,
        SelectImagesNode,
        GenerateAdsNode,
        ReviewAdsNode,
        CompileResultsNode,
    ),
    name="ad_creation_pipeline"
)


# ============================================================================
# Convenience Function
# ============================================================================

async def run_ad_creation(
    product_id: str,
    reference_ad_base64: str,
    *,
    reference_ad_filename: str = "reference.png",
    project_id: Optional[str] = None,
    num_variations: int = 5,
    content_source: str = "hooks",
    color_mode: str = "original",
    brand_colors: Optional[Dict[str, Any]] = None,
    brand_fonts: Optional[Dict[str, Any]] = None,
    image_selection_mode: str = "auto",
    selected_image_paths: Optional[List[str]] = None,
    persona_id: Optional[str] = None,
    variant_id: Optional[str] = None,
    offer_variant_id: Optional[str] = None,
    additional_instructions: Optional[str] = None,
    angle_data: Optional[Dict[str, Any]] = None,
    match_template_structure: bool = False,
    deps: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Run the complete ad creation pipeline.

    This is the main entry point for ad creation. It replaces the
    complete_ad_workflow agent tool with a structured graph pipeline.

    Args:
        product_id: UUID of product as string
        reference_ad_base64: Base64-encoded reference ad image
        reference_ad_filename: Filename for storage (default: reference.png)
        project_id: Optional UUID of project as string
        num_variations: Number of ad variations to generate (1-15)
        content_source: Content mode - "hooks", "recreate_template",
            "belief_first", "plan", "angles"
        color_mode: Color scheme - "original", "complementary", "brand"
        brand_colors: Brand color data when color_mode is "brand"
        brand_fonts: Brand font data (heading/body families)
        image_selection_mode: "auto" or "manual"
        selected_image_paths: Manual image paths (1-2 images)
        persona_id: Optional persona UUID for targeted copy
        variant_id: Optional product variant UUID
        offer_variant_id: Optional offer variant UUID for landing page congruence
        additional_instructions: Optional run-specific instructions
        angle_data: Dict with angle info for belief_first mode
        match_template_structure: Adapt beliefs to template structure
        deps: Optional AgentDependencies (creates if not provided)

    Returns:
        Dict with ad_run_id, product, ad_analysis, generated_ads,
        approved_count, rejected_count, flagged_count, summary
    """
    from viraltracker.agent.dependencies import AgentDependencies

    # Validate inputs
    if num_variations < 1 or num_variations > 15:
        raise ValueError(f"num_variations must be between 1 and 15, got {num_variations}")

    valid_content_sources = ["hooks", "recreate_template", "belief_first", "plan", "angles"]
    if content_source not in valid_content_sources:
        raise ValueError(f"content_source must be one of {valid_content_sources}, got {content_source}")

    logger.info(f"=== STARTING AD CREATION PIPELINE for product {product_id} ===")
    logger.info(f"Generating {num_variations} variations using content_source='{content_source}'")

    # Create dependencies if not provided
    if deps is None:
        deps = AgentDependencies.create()

    # Build initial state
    state = AdCreationPipelineState(
        product_id=product_id,
        reference_ad_base64=reference_ad_base64,
        reference_ad_filename=reference_ad_filename,
        project_id=project_id,
        num_variations=num_variations,
        content_source=content_source,
        color_mode=color_mode,
        brand_colors=brand_colors,
        brand_fonts=brand_fonts,
        image_selection_mode=image_selection_mode,
        selected_image_paths=selected_image_paths,
        persona_id=persona_id,
        variant_id=variant_id,
        offer_variant_id=offer_variant_id,
        additional_instructions=additional_instructions,
        angle_data=angle_data,
        match_template_structure=match_template_structure,
    )

    try:
        # Run the graph
        result = await ad_creation_graph.run(
            InitializeNode(),
            state=state,
            deps=deps,
        )

        return result.output

    except Exception as e:
        logger.error(f"Ad creation pipeline failed: {e}")

        # Try to mark the ad run as failed
        if state.ad_run_id:
            try:
                await deps.ad_creation.update_ad_run(
                    ad_run_id=UUID(state.ad_run_id),
                    status="failed",
                    error_message=str(e)
                )
            except Exception:
                pass

        raise Exception(f"Ad workflow failed: {e}")
