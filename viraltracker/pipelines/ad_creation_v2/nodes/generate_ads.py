"""
GenerateAdsNode V2 - Generate ad variations one at a time (resilient).

V2 changes from V1:
- Passes canvas_size from state to generation service
- Includes prompt_version in generated ad metadata

Phase 2: Triple-nested loop (hook x size x color) for multi-size/color generation.
"""

import logging
import uuid as uuid_module
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


def _is_dark_background(palette: list) -> bool:
    """Check average luminance across all palette colors."""
    if not palette:
        return False
    luminances = []
    for hex_color in palette:
        hex_color = str(hex_color).lstrip('#')
        try:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            luminances.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        except (ValueError, IndexError):
            continue
    return (sum(luminances) / len(luminances)) < 128 if luminances else False


async def _download_and_resize_logo(deps, path: str) -> str:
    """Download logo and resize to max 512x512."""
    import base64 as b64_mod
    from io import BytesIO
    from PIL import Image
    logo_b64 = await deps.ad_creation.get_image_as_base64(path)
    logo_bytes = b64_mod.b64decode(logo_b64)
    img = Image.open(BytesIO(logo_bytes))
    if img.width > 512 or img.height > 512:
        img.thumbnail((512, 512), Image.LANCZOS)
        buf = BytesIO()
        fmt = "PNG" if img.mode == "RGBA" else "JPEG"
        img.save(buf, format=fmt)
        logo_b64 = b64_mod.b64encode(buf.getvalue()).decode("utf-8")
    return logo_b64


@dataclass
class GenerateAdsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 6: Generate ad variations with triple-nested loop (hook x size x color).

    For each (hook, canvas_size, color_mode) combination:
    1. Generate structured Pydantic prompt
    2. Execute Gemini image generation
    3. Upload and save immediately

    If generation fails for one variation, continues with others.

    Phase 2: loops over canvas_sizes × color_modes for multi-size/color output.
    Each generated ad dict tracks its canvas_size and color_mode.

    Reads: selected_hooks, product_dict, ad_analysis, ad_brief_instructions,
           reference_ad_path, selected_images, canvas_sizes, color_modes,
           brand_colors, brand_fonts, num_variations, ad_run_id, prompt_version
    Writes: generated_ads, ads_generated
    Services: GenerationService.generate_prompt(), .execute_generation(),
              AdCreationService.upload_generated_ad()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["selected_hooks", "product_dict", "ad_analysis", "ad_brief_instructions",
                "reference_ad_path", "selected_images", "canvas_sizes", "color_modes",
                "brand_colors", "brand_fonts", "num_variations", "ad_run_id", "prompt_version"],
        outputs=["generated_ads", "ads_generated"],
        services=["generation_service.generate_prompt", "generation_service.execute_generation",
                   "ad_creation.upload_generated_ad"],
        llm="Gemini Image Gen",
        llm_purpose="Generate ad images from Pydantic prompts",
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "DefectScanNode":
        from .defect_scan import DefectScanNode
        from ..services.generation_service import AdGenerationService

        total_variants = (len(ctx.state.selected_hooks)
                          * len(ctx.state.canvas_sizes)
                          * len(ctx.state.color_modes))

        logger.info(f"Step 6: Generating {total_variants} ad variations "
                    f"({len(ctx.state.selected_hooks)} hooks x "
                    f"{len(ctx.state.canvas_sizes)} sizes x "
                    f"{len(ctx.state.color_modes)} colors) (V2 Pydantic prompts)...")
        ctx.state.current_step = "generate_ads"

        generation_service = AdGenerationService()
        selected_image_paths = [img["storage_path"] for img in ctx.state.selected_images]
        generated_ads = []
        variant_counter = 0

        # Phase 3: Collect selected_image_tags as union of asset_tags from selected images
        selected_image_tags = []
        for img in ctx.state.selected_images:
            for tag in (img.get("asset_tags") or []):
                if tag not in selected_image_tags:
                    selected_image_tags.append(tag)

        # Smart logo variant selection based on template background brightness
        logo_b64_override = ctx.state.logo_image_base64  # Default (primary)
        logo_variant_used = "logo" if logo_b64_override else None
        variants = (ctx.state.brand_asset_info or {}).get("logo_variants", {})
        if len(variants) > 1 and ctx.state.ad_analysis:
            palette = (ctx.state.ad_analysis or {}).get("color_palette", [])
            if palette and _is_dark_background(palette):
                white_path = variants.get("logo_white")
                if white_path:
                    try:
                        logo_b64_override = await _download_and_resize_logo(ctx.deps, white_path)
                        logo_variant_used = "logo_white"
                        logger.info("Smart logo: selected logo_white for dark background")
                    except Exception as e:
                        logger.warning(f"Smart logo: failed to download logo_white, using default: {e}")
            else:
                dark_path = variants.get("logo_dark")
                if dark_path:
                    try:
                        logo_b64_override = await _download_and_resize_logo(ctx.deps, dark_path)
                        logo_variant_used = "logo_dark"
                        logger.info("Smart logo: selected logo_dark for light background")
                    except Exception as e:
                        logger.warning(f"Smart logo: failed to download logo_dark, using default: {e}")

        for i, selected_hook in enumerate(ctx.state.selected_hooks, start=1):
            hook_list_index = i - 1  # 0-based index for congruence lookup
            for canvas_size in ctx.state.canvas_sizes:
                for color_mode in ctx.state.color_modes:
                    variant_counter += 1
                    logger.info(f"  Generating variation {variant_counter}/{total_variants} "
                                f"(hook {i}, {canvas_size}, {color_mode})...")

                    try:
                        # Generate Pydantic prompt (Phase 3: pass asset state fields)
                        prompt = generation_service.generate_prompt(
                            prompt_index=variant_counter,
                            selected_hook=selected_hook,
                            product=ctx.state.product_dict,
                            ad_analysis=ctx.state.ad_analysis,
                            ad_brief_instructions=ctx.state.ad_brief_instructions,
                            reference_ad_path=ctx.state.reference_ad_path,
                            product_image_paths=selected_image_paths,
                            color_mode=color_mode,
                            brand_colors=ctx.state.brand_colors,
                            brand_fonts=ctx.state.brand_fonts,
                            num_variations=total_variants,
                            canvas_size=canvas_size,
                            prompt_version=ctx.state.prompt_version,
                            template_elements=ctx.state.template_elements,
                            brand_asset_info=ctx.state.brand_asset_info,
                            selected_image_tags=selected_image_tags,
                            performance_context=ctx.state.performance_context,
                            logo_image_base64=logo_b64_override,
                            blueprint_context=ctx.state.blueprint_context,
                        )

                        # Execute generation
                        generated_ad = await generation_service.execute_generation(
                            nano_banana_prompt=prompt,
                            ad_creation_service=ctx.deps.ad_creation,
                            gemini_service=ctx.deps.gemini,
                            image_resolution=ctx.state.image_resolution,
                        )

                        # Pop logo blob to prevent ~400KB x N duplicate data in memory
                        prompt.pop('logo_image_base64', None)

                        # Upload image with structured naming
                        ad_uuid = uuid_module.uuid4()

                        product_id_for_naming = await ctx.deps.ad_creation.get_product_id_for_run(
                            UUID(ctx.state.ad_run_id)
                        )

                        storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
                            ad_run_id=UUID(ctx.state.ad_run_id),
                            prompt_index=variant_counter,
                            image_base64=generated_ad['image_base64'],
                            product_id=product_id_for_naming,
                            ad_id=ad_uuid,
                            canvas_size=canvas_size,
                        )

                        # Phase 6: Build element tags for Creative Genome tracking
                        element_tags = {
                            "hook_type": selected_hook.get("persuasion_type") or selected_hook.get("category"),
                            "persona_id": ctx.state.persona_id,
                            "color_mode": color_mode,
                            "template_category": (ctx.state.ad_analysis or {}).get("format_type"),
                            "awareness_stage": (ctx.state.product_dict or {}).get("awareness_stage"),
                            "canvas_size": canvas_size,
                            "template_id": ctx.state.template_id,
                            "prompt_version": ctx.state.prompt_version,
                            "content_source": ctx.state.content_source,
                            "creative_direction": ctx.state.creative_direction,
                            "logo_variant": logo_variant_used,
                        }

                        # Phase 6: Pre-gen score from genome posteriors (non-fatal)
                        pre_gen_score = None
                        if ctx.state.performance_context and ctx.state.product_dict:
                            try:
                                from viraltracker.services.creative_genome_service import CreativeGenomeService
                                genome_svc = CreativeGenomeService()
                                brand_id = ctx.state.product_dict.get("brand_id")
                                if brand_id:
                                    pre_gen_score = await genome_svc.get_pre_gen_score(
                                        UUID(brand_id) if isinstance(brand_id, str) else brand_id,
                                        element_tags,
                                    )
                            except Exception as pgs_err:
                                logger.debug(f"Pre-gen score failed (non-fatal): {pgs_err}")

                        generated_ads.append({
                            "prompt_index": variant_counter,
                            "prompt": prompt,
                            "generated_ad": generated_ad,
                            "storage_path": storage_path,
                            "ad_uuid": str(ad_uuid),
                            "hook": selected_hook,
                            "canvas_size": canvas_size,
                            "color_mode": color_mode,
                            "prompt_version": prompt.get("prompt_version", ctx.state.prompt_version),
                            "element_tags": element_tags,
                            "pre_gen_score": pre_gen_score,
                            "hook_list_index": hook_list_index,
                        })

                        ctx.state.ads_generated += 1
                        logger.info(f"  Variation {variant_counter} generated and uploaded: {storage_path}")

                    except Exception as gen_error:
                        logger.error(f"  Generation failed for variation {variant_counter}: {gen_error}")
                        generated_ads.append({
                            "prompt_index": variant_counter,
                            "prompt": None,
                            "generated_ad": None,
                            "storage_path": None,
                            "ad_uuid": None,
                            "hook": selected_hook,
                            "canvas_size": canvas_size,
                            "color_mode": color_mode,
                            "error": str(gen_error),
                            "final_status": "generation_failed",
                            "hook_list_index": hook_list_index,
                        })

        ctx.state.generated_ads = generated_ads
        ctx.state.mark_step_complete("generate_ads")
        logger.info(f"Generation complete: {ctx.state.ads_generated}/{total_variants} succeeded")

        return DefectScanNode()
