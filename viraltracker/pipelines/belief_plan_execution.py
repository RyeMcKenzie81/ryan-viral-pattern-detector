"""
Belief Plan Execution Pipeline - Pydantic Graph workflow for Phase 1-2.

Pipeline: LoadPlan → BuildPrompts → GenerateImages → ReviewAds → Complete

This pipeline executes Phase 1-2 belief testing plans where:
- Templates are STYLE references, not final images
- No product images are composited
- Only observational anchor text appears on images
- Copy scaffolds provide Meta headline/primary text (not on image)

The goal is to test beliefs (angles), not writing talent.
"""

import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import BeliefPlanExecutionState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def build_phase12_prompt(
    angle: Dict,
    template: Dict,
    persona_data: Optional[Dict],
    jtbd_data: Optional[Dict],
    variation_index: int,
    canvas_size: str
) -> Dict:
    """
    Build a single Phase 1-2 prompt.

    Args:
        angle: Angle dict with belief_statement, mechanism_hypothesis, copy_set
        template: Template dict with storage_path, layout_analysis
        persona_data: Persona context (snapshot, name)
        jtbd_data: Job-to-be-done context (progress_statement)
        variation_index: Which variation (for cycling through copy variants)
        canvas_size: Output dimensions (e.g., "1080x1080px")

    Returns:
        Prompt dict with json_prompt, full_prompt, and metadata
    """
    layout_analysis = template.get("layout_analysis", {}) or {}
    anchor_text = layout_analysis.get("anchor_text")
    template_type = layout_analysis.get("template_type", "observation_shot")

    # Get copy from angle's copy_set
    copy_set = angle.get("copy_set", {}) or {}
    headlines = copy_set.get("headline_variants", []) or []
    primary_texts = copy_set.get("primary_text_variants", []) or []

    # Cycle through copy variants
    headline = ""
    primary_text = ""
    if headlines:
        headline = headlines[variation_index % len(headlines)].get("text", "")
    if primary_texts:
        primary_text = primary_texts[variation_index % len(primary_texts)].get("text", "")

    # Build situation context from persona + JTBD
    persona_snapshot = "person"
    if persona_data:
        persona_snapshot = persona_data.get("snapshot") or persona_data.get("name") or "person"

    situation = f"A {persona_snapshot} experiencing the moment of recognition"
    if jtbd_data:
        progress = jtbd_data.get("progress_statement") or jtbd_data.get("name", "")
        if progress:
            situation += f" related to: {progress}"

    json_prompt = {
        "ad_type": "phase_1_2_belief_test",
        "style": {
            "canvas_size": canvas_size,
            "template_type": template_type,
            "reference": "Use attached template as STYLE GUIDE ONLY"
        },
        "content": {
            "situation": situation,
            "on_image_text": anchor_text,
            "belief_being_tested": angle.get("belief_statement")
        },
        "instructions": {
            "DO": [
                "Generate a NEW image showing the SITUATION (recognition moment)",
                "Match the visual style, lighting, and mood of the template",
                f"Place anchor text: '{anchor_text}'" if anchor_text else "No text on image",
                f"Persona context: {persona_snapshot}"
            ],
            "DO_NOT": [
                "Show any product or supplement bottle",
                "Include benefits, claims, or mechanisms",
                "Add text beyond the anchor text",
                "Show transformations or solutions"
            ]
        }
    }

    return {
        "json_prompt": json_prompt,
        "full_prompt": json.dumps(json_prompt, indent=2),
        "template_storage_path": template.get("storage_path"),
        "template_name": template.get("name"),
        "template_id": template.get("id"),
        "angle_id": angle.get("id"),
        "angle_name": angle.get("name"),
        "belief_statement": angle.get("belief_statement"),
        "anchor_text": anchor_text,
        "meta_headline": headline,
        "meta_primary_text": primary_text,
        "variation_index": variation_index
    }


async def review_phase12_ad(
    ctx: GraphRunContext,
    storage_path: str,
    prompt: Dict
) -> Dict:
    """
    Review a Phase 1-2 ad with appropriate criteria.

    Phase 1-2 ads should:
    - Show a situation/moment, NOT a product
    - Match template style
    - Only have anchor text (if any)
    - Not show products, benefits, or claims

    Args:
        ctx: Graph run context with dependencies
        storage_path: Path to generated image in storage
        prompt: The prompt used to generate the image

    Returns:
        Review dict with status, notes, and scores
    """
    try:
        # Get image for review
        image_base64 = await ctx.deps.ad_creation.get_image_as_base64(storage_path)

        anchor_text = prompt.get("anchor_text") or "None"

        # Phase 1-2 review criteria (different from standard)
        review_prompt = f"""Review this Phase 1-2 belief testing ad creative.

PASS CRITERIA:
1. Shows a situation/moment, NOT a product
2. Matches the template style (observation shot, situation closeup, etc.)
3. Text on image is ONLY: "{anchor_text}"
4. No product bottles, supplements, or solutions shown
5. No benefits, claims, or transformations

FAIL CRITERIA:
- Any product visible
- Extra text beyond anchor text
- Looks like a product ad instead of observation/recognition moment

Return JSON only: {{"status": "approved" or "rejected", "notes": "brief explanation", "scores": {{"style_match": 0-3, "situation_clarity": 0-3, "text_accuracy": 0-3}}}}
"""

        result = await ctx.deps.gemini.analyze_image(
            image_base64=image_base64,
            prompt=review_prompt
        )

        # Try to parse JSON from result
        if isinstance(result, str):
            try:
                # Find JSON in response
                import re
                json_match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = {"status": "pending", "notes": result, "scores": {}}
            except json.JSONDecodeError:
                result = {"status": "pending", "notes": str(result), "scores": {}}

        return result

    except Exception as e:
        logger.error(f"Review failed: {e}")
        return {
            "status": "review_failed",
            "error": str(e),
            "scores": {}
        }


# ============================================================================
# GRAPH NODES
# ============================================================================

@dataclass
class LoadPlanNode(BaseNode[BeliefPlanExecutionState]):
    """
    Step 1: Load belief plan with angles, templates, and copy sets.

    Validates that the plan is Phase 1-2 and loads all required data.
    """

    async def run(
        self,
        ctx: GraphRunContext[BeliefPlanExecutionState, AgentDependencies]
    ) -> Union["BuildPromptsNode", End]:
        logger.info(f"Step 1: Loading belief plan {ctx.state.belief_plan_id}")
        ctx.state.current_step = "loading_plan"

        try:
            # Get plan with all related data
            plan_data = await ctx.deps.ad_creation.get_belief_plan_with_copy(
                ctx.state.belief_plan_id
            )

            if not plan_data:
                ctx.state.error = "Plan not found"
                ctx.state.current_step = "failed"
                return End({"status": "error", "error": "Plan not found"})

            # Validate Phase 1-2
            phase_id = plan_data.get("plan", {}).get("phase_id", 1)
            if phase_id not in [1, 2]:
                ctx.state.error = f"This pipeline is for Phase 1-2 only. Plan is Phase {phase_id}."
                ctx.state.current_step = "failed"
                return End({"status": "error", "error": ctx.state.error})

            # Validate we have angles
            angles = plan_data.get("angles", [])
            if not angles:
                ctx.state.error = "Plan has no angles"
                ctx.state.current_step = "failed"
                return End({"status": "error", "error": ctx.state.error})

            # Validate we have templates
            templates = plan_data.get("templates", [])
            if not templates:
                ctx.state.error = "Plan has no templates"
                ctx.state.current_step = "failed"
                return End({"status": "error", "error": ctx.state.error})

            # Store plan data
            ctx.state.plan_data = plan_data
            ctx.state.phase_id = phase_id
            ctx.state.angles = angles
            ctx.state.templates = templates
            ctx.state.jtbd_data = plan_data.get("jtbd")

            # Load persona if available
            persona_id = plan_data.get("plan", {}).get("persona_id")
            if persona_id:
                try:
                    # get_persona_for_ad_generation is sync, not async
                    ctx.state.persona_data = ctx.deps.ad_creation.get_persona_for_ad_generation(
                        UUID(persona_id) if isinstance(persona_id, str) else persona_id
                    )
                except Exception as e:
                    logger.warning(f"Could not load persona: {e}")

            ctx.state.current_step = "plan_loaded"
            logger.info(f"Loaded plan with {len(angles)} angles, {len(templates)} templates")
            return BuildPromptsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to load plan: {e}")
            return End({"status": "error", "error": str(e), "step": "load_plan"})


@dataclass
class BuildPromptsNode(BaseNode[BeliefPlanExecutionState]):
    """
    Step 2: Build prompts for all angle × template × variation combos.

    Creates prompts that:
    - Use template as style reference (not final image)
    - Include only anchor text on image
    - Store copy scaffold text for Meta ad fields
    """

    async def run(
        self,
        ctx: GraphRunContext[BeliefPlanExecutionState, AgentDependencies]
    ) -> "GenerateImagesNode":
        logger.info("Step 2: Building prompts for all combinations")
        ctx.state.current_step = "building_prompts"

        try:
            prompts = []
            for angle in ctx.state.angles:
                for template in ctx.state.templates:
                    for v in range(ctx.state.variations_per_angle):
                        prompt = build_phase12_prompt(
                            angle=angle,
                            template=template,
                            persona_data=ctx.state.persona_data,
                            jtbd_data=ctx.state.jtbd_data,
                            variation_index=v,
                            canvas_size=ctx.state.canvas_size
                        )
                        prompts.append(prompt)

            ctx.state.prompts = prompts
            ctx.state.total_ads_planned = len(prompts)
            ctx.state.current_step = "prompts_built"

            logger.info(
                f"Built {len(prompts)} prompts: "
                f"{len(ctx.state.angles)} angles × "
                f"{len(ctx.state.templates)} templates × "
                f"{ctx.state.variations_per_angle} variations"
            )
            return GenerateImagesNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to build prompts: {e}")
            return End({"status": "error", "error": str(e), "step": "build_prompts"})


@dataclass
class GenerateImagesNode(BaseNode[BeliefPlanExecutionState]):
    """
    Step 3: Generate images one by one (resilient to individual failures).

    Key Phase 1-2 differences:
    - Only template as reference image (no product images)
    - Images show situations, not products
    """

    async def run(
        self,
        ctx: GraphRunContext[BeliefPlanExecutionState, AgentDependencies]
    ) -> "ReviewAdsNode":
        logger.info(f"Step 3: Generating {len(ctx.state.prompts)} images")
        ctx.state.current_step = "generating"

        try:
            # Get product_id from plan
            product_id = ctx.state.plan_data.get("plan", {}).get("product_id")
            if not product_id:
                ctx.state.error = "Plan has no product_id"
                ctx.state.current_step = "failed"
                return End({"status": "error", "error": ctx.state.error})

            product_uuid = UUID(product_id) if isinstance(product_id, str) else product_id

            # Create ad_run record
            ad_run_id = await ctx.deps.ad_creation.create_ad_run(
                product_id=product_uuid,
                reference_ad_storage_path="belief_plan_execution",
                parameters={
                    "content_source": "belief_plan",
                    "belief_plan_id": str(ctx.state.belief_plan_id),
                    "phase_id": ctx.state.phase_id,
                    "variations_per_angle": ctx.state.variations_per_angle,
                    "total_ads_planned": ctx.state.total_ads_planned
                }
            )
            ctx.state.ad_run_id = ad_run_id

            # Generate each image
            for i, prompt in enumerate(ctx.state.prompts):
                logger.info(f"  Generating image {i+1}/{len(ctx.state.prompts)}...")

                try:
                    # Get template image as style reference
                    template_path = prompt["template_storage_path"]
                    if not template_path:
                        raise ValueError("Template has no storage_path")

                    template_image = await ctx.deps.ad_creation.get_image_as_base64(template_path)

                    # Generate image with ONLY template as reference (no product)
                    result = await ctx.deps.gemini.generate_image(
                        prompt=prompt["full_prompt"],
                        reference_images=[template_image],
                        return_metadata=True
                    )

                    # Upload to storage
                    storage_path, ad_id = await ctx.deps.ad_creation.upload_generated_ad(
                        ad_run_id=ad_run_id,
                        prompt_index=i + 1,
                        image_base64=result["image_base64"],
                        product_id=product_uuid,
                        canvas_size=ctx.state.canvas_size
                    )

                    ctx.state.generated_ads.append({
                        "prompt_index": i + 1,
                        "storage_path": storage_path,
                        "ad_id": str(ad_id),
                        "prompt": prompt,
                        "generation_time_ms": result.get("generation_time_ms"),
                        "model_used": result.get("model_used")
                    })
                    ctx.state.ads_generated += 1

                    logger.info(f"  ✓ Generated {i+1}/{len(ctx.state.prompts)}")

                except Exception as e:
                    logger.error(f"  ✗ Generation failed for prompt {i+1}: {e}")
                    ctx.state.generated_ads.append({
                        "prompt_index": i + 1,
                        "error": str(e),
                        "status": "generation_failed",
                        "prompt": prompt
                    })

            ctx.state.current_step = "generated"
            logger.info(f"Generated {ctx.state.ads_generated}/{len(ctx.state.prompts)} images")
            return ReviewAdsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Generation step failed: {e}")
            return End({"status": "error", "error": str(e), "step": "generate"})


@dataclass
class ReviewAdsNode(BaseNode[BeliefPlanExecutionState]):
    """
    Step 4: Review generated ads with Phase 1-2 specific criteria.

    Phase 1-2 review checks:
    - Shows situation, not product
    - Matches template style
    - Only anchor text on image
    """

    async def run(
        self,
        ctx: GraphRunContext[BeliefPlanExecutionState, AgentDependencies]
    ) -> End:
        logger.info(f"Step 4: Reviewing {len(ctx.state.generated_ads)} ads")
        ctx.state.current_step = "reviewing"

        try:
            for ad in ctx.state.generated_ads:
                if ad.get("error") or ad.get("status") == "generation_failed":
                    continue  # Skip failed generations

                try:
                    review = await review_phase12_ad(
                        ctx=ctx,
                        storage_path=ad["storage_path"],
                        prompt=ad["prompt"]
                    )

                    ad["review"] = review
                    ad["final_status"] = review.get("status", "pending")

                    if review.get("status") == "approved":
                        ctx.state.approved_count += 1
                    elif review.get("status") == "rejected":
                        ctx.state.rejected_count += 1

                    ctx.state.ads_reviewed += 1

                    # Save review to database
                    if ad.get("ad_id"):
                        await ctx.deps.ad_creation.save_generated_ad(
                            ad_run_id=ctx.state.ad_run_id,
                            prompt_index=ad["prompt_index"],
                            prompt_text=ad["prompt"]["full_prompt"],
                            prompt_spec=ad["prompt"]["json_prompt"],
                            hook_id=None,  # No hooks in Phase 1-2
                            hook_text=ad["prompt"].get("anchor_text") or "",
                            storage_path=ad["storage_path"],
                            gemini_review=review,
                            final_status=ad["final_status"],
                            model_used=ad.get("model_used"),
                            generation_time_ms=ad.get("generation_time_ms"),
                            ad_id=UUID(ad["ad_id"])
                        )

                except Exception as e:
                    logger.error(f"Review failed for ad {ad['prompt_index']}: {e}")
                    ad["review_error"] = str(e)
                    ad["final_status"] = "review_failed"

            ctx.state.current_step = "complete"

            # Mark ad_run complete
            if ctx.state.ad_run_id:
                await ctx.deps.ad_creation.update_ad_run(
                    ad_run_id=ctx.state.ad_run_id,
                    status="complete"
                )

            logger.info(
                f"Review complete: {ctx.state.approved_count} approved, "
                f"{ctx.state.rejected_count} rejected"
            )

            return End({
                "status": "complete",
                "total_planned": ctx.state.total_ads_planned,
                "total_generated": ctx.state.ads_generated,
                "total_reviewed": ctx.state.ads_reviewed,
                "approved": ctx.state.approved_count,
                "rejected": ctx.state.rejected_count,
                "ad_run_id": str(ctx.state.ad_run_id) if ctx.state.ad_run_id else None,
                "belief_plan_id": str(ctx.state.belief_plan_id)
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Review step failed: {e}")
            return End({"status": "error", "error": str(e), "step": "review"})


# ============================================================================
# GRAPH DEFINITION
# ============================================================================

belief_plan_execution_graph = Graph(
    nodes=(
        LoadPlanNode,
        BuildPromptsNode,
        GenerateImagesNode,
        ReviewAdsNode
    ),
    name="belief_plan_execution"
)


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

async def run_belief_plan_execution(
    belief_plan_id: UUID,
    variations_per_angle: int = 3,
    canvas_size: str = "1080x1080px"
) -> dict:
    """
    Run the belief plan execution pipeline.

    This is a convenience function that creates dependencies,
    tracks the run in pipeline_runs table, and runs the full pipeline.

    Args:
        belief_plan_id: UUID of the belief plan to execute
        variations_per_angle: How many variations per angle×template combo
        canvas_size: Output image dimensions

    Returns:
        Pipeline result with status, counts, and ad_run_id

    Example:
        >>> result = await run_belief_plan_execution(
        ...     belief_plan_id=UUID("..."),
        ...     variations_per_angle=3
        ... )
        >>> print(result["status"])  # "complete"
        >>> print(result["approved"])  # 45
    """
    from ..agent.dependencies import AgentDependencies
    from ..core.database import get_supabase_client
    from datetime import datetime

    print(f"[PIPELINE] Starting belief plan execution for plan {belief_plan_id}", flush=True)
    logger.info(f"Starting belief plan execution for plan {belief_plan_id}")

    # Get database client for tracking
    db = get_supabase_client()
    run_id = None

    try:
        # Create pipeline_runs record
        print("[PIPELINE] Creating pipeline_runs record...", flush=True)
        run_record = {
            "pipeline_name": "belief_plan_execution",
            "belief_plan_id": str(belief_plan_id),
            "status": "running",
            "current_node": "LoadPlanNode",
            "started_at": datetime.utcnow().isoformat(),
            "state_snapshot": {
                "current_step": "starting",
                "variations_per_angle": variations_per_angle,
                "canvas_size": canvas_size
            }
        }
        insert_result = db.table("pipeline_runs").insert(run_record).execute()
        if insert_result.data:
            run_id = insert_result.data[0]["id"]
            print(f"[PIPELINE] Created pipeline_runs record: {run_id}", flush=True)
            logger.info(f"Created pipeline_runs record: {run_id}")

    except Exception as e:
        print(f"[PIPELINE] Failed to create pipeline_runs record: {e}", flush=True)
        logger.error(f"Failed to create pipeline_runs record: {e}")
        # Continue anyway - tracking failure shouldn't stop execution

    try:
        # Create dependencies
        print("[PIPELINE] Creating AgentDependencies...", flush=True)
        deps = AgentDependencies.create()
        print("[PIPELINE] AgentDependencies created", flush=True)
        logger.info("Created AgentDependencies")

        # Create initial state
        state = BeliefPlanExecutionState(
            belief_plan_id=belief_plan_id,
            variations_per_angle=variations_per_angle,
            canvas_size=canvas_size
        )

        # Run the graph
        print("[PIPELINE] Starting graph execution...", flush=True)
        logger.info("Starting graph execution...")
        result = await belief_plan_execution_graph.run(
            LoadPlanNode(),
            state=state,
            deps=deps
        )
        print(f"[PIPELINE] Graph execution complete: {result.output}", flush=True)
        logger.info(f"Graph execution complete: {result.output}")

        # Update pipeline_runs on success
        if run_id:
            try:
                db.table("pipeline_runs").update({
                    "status": "complete",
                    "current_node": "Complete",
                    "completed_at": datetime.utcnow().isoformat(),
                    "state_snapshot": {
                        "current_step": "complete",
                        "total_ads_planned": state.total_ads_planned,
                        "ads_generated": state.ads_generated,
                        "ads_reviewed": state.ads_reviewed,
                        "approved_count": state.approved_count,
                        "rejected_count": state.rejected_count,
                        "ad_run_id": str(state.ad_run_id) if state.ad_run_id else None
                    }
                }).eq("id", run_id).execute()
            except Exception as e:
                logger.error(f"Failed to update pipeline_runs: {e}")

        return result.output

    except Exception as e:
        print(f"[PIPELINE] Pipeline execution failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)

        # Update pipeline_runs on failure
        if run_id:
            try:
                db.table("pipeline_runs").update({
                    "status": "failed",
                    "current_node": "Failed",
                    "completed_at": datetime.utcnow().isoformat(),
                    "error_message": str(e),
                    "state_snapshot": {
                        "current_step": "failed",
                        "error": str(e)
                    }
                }).eq("id", run_id).execute()
            except Exception as update_err:
                logger.error(f"Failed to update pipeline_runs with error: {update_err}")

        return {
            "status": "error",
            "error": str(e),
            "run_id": run_id
        }
