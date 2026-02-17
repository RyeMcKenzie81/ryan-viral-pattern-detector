"""
Ad Creation Pipeline V2 Orchestrator - Graph definition and convenience functions.

Defines the pydantic-graph pipeline for V2 ad creation and provides
run_ad_creation_v2() as the main entry point.

V2 differences from V1:
- Accepts template_id and canvas_size as explicit params
- Uses Pydantic prompt construction (prompt_version tracked)
- Pipeline version always "v2" in output
- V1 pipeline is NOT modified — V2 runs in parallel
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID

from pydantic_graph import Graph

from .state import AdCreationPipelineState
from .nodes.initialize import InitializeNode
from .nodes.fetch_context import FetchContextNode
from .nodes.analyze_template import AnalyzeTemplateNode
from .nodes.select_content import SelectContentNode
from .nodes.headline_congruence import HeadlineCongruenceNode
from .nodes.select_images import SelectImagesNode
from .nodes.generate_ads import GenerateAdsNode
from .nodes.defect_scan import DefectScanNode
from .nodes.review_ads import ReviewAdsNode
from .nodes.retry_rejected import RetryRejectedNode
from .nodes.compile_results import CompileResultsNode

logger = logging.getLogger(__name__)

# ============================================================================
# Graph Definition
# ============================================================================

ad_creation_v2_graph = Graph(
    nodes=(
        InitializeNode,
        FetchContextNode,
        AnalyzeTemplateNode,
        SelectContentNode,
        HeadlineCongruenceNode,
        SelectImagesNode,
        GenerateAdsNode,
        DefectScanNode,
        ReviewAdsNode,
        RetryRejectedNode,
        CompileResultsNode,
    ),
    name="ad_creation_v2_pipeline"
)


# ============================================================================
# Convenience Function
# ============================================================================

async def run_ad_creation_v2(
    product_id: str,
    reference_ad_base64: str,
    *,
    reference_ad_filename: str = "reference.png",
    project_id: Optional[str] = None,
    template_id: Optional[str] = None,
    # Phase 2: multi-size/color (preferred)
    canvas_sizes: Optional[List[str]] = None,
    color_modes: Optional[List[str]] = None,
    # Backward compat (scalar -> wrapped in list)
    canvas_size: Optional[str] = None,
    color_mode: Optional[str] = None,
    num_variations: int = 5,
    content_source: str = "hooks",
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
    image_resolution: str = "2K",
    auto_retry_rejected: bool = False,
    max_retry_attempts: int = 1,
    # Phase 8B: selection transport (scorer weight learning)
    selection_weights_used: Optional[Dict[str, float]] = None,
    selection_scorer_breakdown: Optional[Dict[str, float]] = None,
    selection_composite_score: Optional[float] = None,
    selection_mode: Optional[str] = None,
    deps: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Run the complete V2 ad creation pipeline.

    This is the main entry point for V2 ad creation. It runs in parallel
    with V1 — the V1 pipeline is NOT modified.

    Args:
        product_id: UUID of product as string
        reference_ad_base64: Base64-encoded reference ad image
        reference_ad_filename: Filename for storage (default: reference.png)
        project_id: Optional UUID of project as string
        template_id: Optional scraped_templates.id UUID for scoring
        canvas_sizes: List of canvas sizes for multi-size generation (Phase 2)
        color_modes: List of color modes for multi-color generation (Phase 2)
        canvas_size: Deprecated scalar (backward compat, wrapped in list)
        color_mode: Deprecated scalar (backward compat, wrapped in list)
        num_variations: Number of hook variations per template (1-100)
        content_source: Content mode - "hooks", "recreate_template",
            "belief_first", "plan", "angles"
        brand_colors: Brand color data when color_mode includes "brand"
        brand_fonts: Brand font data (heading/body families)
        image_selection_mode: "auto" or "manual"
        selected_image_paths: Manual image paths (1-2 images)
        persona_id: Optional persona UUID for targeted copy
        variant_id: Optional product variant UUID
        offer_variant_id: Optional offer variant UUID for landing page congruence
        additional_instructions: Optional run-specific instructions
        angle_data: Dict with angle info for belief_first mode
        match_template_structure: Adapt beliefs to template structure
        image_resolution: Image resolution for Gemini (1K, 2K, 4K)
        auto_retry_rejected: If True, auto-retry rejected ads with fresh generation
        max_retry_attempts: Max retries per rejected ad (default: 1)
        selection_weights_used: Scorer weights at selection time (Phase 8B)
        selection_scorer_breakdown: Per-scorer raw scores at selection time (Phase 8B)
        selection_composite_score: Composite score at selection time (Phase 8B)
        selection_mode: Selection mode at selection time (Phase 8B)
        deps: Optional AgentDependencies (creates if not provided)

    Returns:
        Dict with ad_run_id, product, ad_analysis, generated_ads,
        approved_count, rejected_count, flagged_count, summary,
        pipeline_version, prompt_version
    """
    from viraltracker.agent.dependencies import AgentDependencies

    # Normalize: prefer list params, fall back to scalar, then defaults
    _canvas_sizes = canvas_sizes or ([canvas_size] if canvas_size else ["1080x1080px"])
    _color_modes = color_modes or ([color_mode] if color_mode else ["original"])

    # Validate inputs
    if num_variations < 1 or num_variations > 50:
        raise ValueError(f"num_variations must be between 1 and 50, got {num_variations}")

    valid_content_sources = ["hooks", "recreate_template", "belief_first", "plan", "angles"]
    if content_source not in valid_content_sources:
        raise ValueError(f"content_source must be one of {valid_content_sources}, got {content_source}")

    logger.info(f"=== STARTING AD CREATION V2 PIPELINE for product {product_id} ===")
    logger.info(f"Generating {num_variations} variations using content_source='{content_source}'")
    logger.info(f"Canvas sizes: {_canvas_sizes}, Color modes: {_color_modes}, Template ID: {template_id or 'None'}")

    # Create dependencies if not provided
    if deps is None:
        deps = AgentDependencies.create()

    # Build initial state with V2-specific fields
    state = AdCreationPipelineState(
        product_id=product_id,
        reference_ad_base64=reference_ad_base64,
        reference_ad_filename=reference_ad_filename,
        project_id=project_id,
        template_id=template_id,
        canvas_sizes=_canvas_sizes,
        num_variations=num_variations,
        content_source=content_source,
        color_modes=_color_modes,
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
        image_resolution=image_resolution,
        auto_retry_rejected=auto_retry_rejected,
        max_retry_attempts=max_retry_attempts,
        # Phase 8B: selection transport
        selection_weights_used=selection_weights_used,
        selection_scorer_breakdown=selection_scorer_breakdown,
        selection_composite_score=selection_composite_score,
        selection_mode=selection_mode,
    )

    # Phase 8B: Derive experiment seed and check for active generation experiment
    seed_input = f"{product_id}:{template_id or 'none'}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    state.experiment_seed = hashlib.sha256(seed_input.encode()).hexdigest()

    try:
        from viraltracker.services.generation_experiment_service import GenerationExperimentService
        # Look up brand_id from product for experiment lookup
        brand_id_for_exp = None
        try:
            product_result = deps.ad_creation.supabase.table("products").select(
                "brand_id"
            ).eq("id", product_id).single().execute()
            if product_result.data:
                brand_id_for_exp = product_result.data["brand_id"]
        except Exception:
            pass

        if brand_id_for_exp:
            gen_exp_service = GenerationExperimentService()
            assignment = gen_exp_service.assign_arm(brand_id_for_exp, state.experiment_seed)
            if assignment:
                state.generation_experiment_id = assignment["experiment_id"]
                state.generation_experiment_arm = assignment["arm"]
                state.generation_experiment_config = assignment["config"]
                logger.info(
                    f"Experiment assignment: {assignment['arm']} for experiment "
                    f"{assignment['experiment_id']}"
                )
    except ImportError:
        pass  # Service not yet available
    except Exception as e:
        logger.debug(f"Generation experiment assignment skipped: {e}")

    try:
        # Run the graph
        result = await ad_creation_v2_graph.run(
            InitializeNode(),
            state=state,
            deps=deps,
        )

        return result.output

    except Exception as e:
        logger.error(f"Ad creation V2 pipeline failed: {e}")

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

        raise Exception(f"Ad V2 workflow failed: {e}")
