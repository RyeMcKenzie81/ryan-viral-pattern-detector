"""
Generation Service V2 - Pydantic prompt construction and image generation execution.

Replaces the V1 raw dict literal with validated Pydantic models.
Same input params, same output format, but internal construction
uses AdGenerationPrompt model with validation.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

from .content_service import match_benefit_to_hook
from ..models.prompt import (
    AdGenerationPrompt,
    TaskConfig,
    SpecialInstructions,
    ProductContext,
    ContentConfig,
    HeadlineConfig,
    SubheadlineConfig,
    ColorConfig,
    FontConfig,
    FontEntry,
    StyleConfig,
    ImageConfig,
    TemplateImageConfig,
    ProductImageEntry,
    TemplateAnalysis,
    AssetContext,
    TextAreaSpec,
    GenerationRules,
    ProductImageRules,
    MultiImageHandling,
    OfferRules,
    LightingRules,
    ScaleRules,
    FoundersConfig,
    AdBriefConfig,
)

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any, **kwargs) -> str:
    """JSON dumps with UUID serialization support."""
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, UUID) else TypeError(f"Not serializable: {type(o)}"), **kwargs)


class AdGenerationService:
    """Handles Pydantic prompt construction and image generation for V2 ad creation."""

    def generate_prompt(
        self,
        prompt_index: int,
        selected_hook: Dict[str, Any],
        product: Dict[str, Any],
        ad_analysis: Dict[str, Any],
        ad_brief_instructions: str,
        reference_ad_path: str,
        product_image_paths: List[str],
        color_mode: str = "original",
        brand_colors: Optional[Dict[str, Any]] = None,
        brand_fonts: Optional[Dict[str, Any]] = None,
        num_variations: int = 5,
        canvas_size: str = "1080x1080px",
        prompt_version: str = "v2.1.0",
        # Phase 3: asset-aware prompt params (all Optional for backward compat)
        template_elements: Optional[Dict[str, Any]] = None,
        brand_asset_info: Optional[Dict[str, Any]] = None,
        selected_image_tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON prompt for Gemini image generation using Pydantic models.

        Args:
            prompt_index: Index 1-N for this variation
            selected_hook: Selected hook dict with adapted_text
            product: Product dict with name, benefits, etc.
            ad_analysis: Ad analysis dict
            ad_brief_instructions: Instructions from ad brief template
            reference_ad_path: Storage path to reference ad
            product_image_paths: List of 1-2 product image paths
            color_mode: "original", "complementary", or "brand"
            brand_colors: Brand color data when color_mode is "brand"
            brand_fonts: Brand font data
            num_variations: Total number of variations
            canvas_size: Explicit canvas size (V2: not derived from analysis)
            prompt_version: Pydantic prompt schema version

        Returns:
            Dict with prompt_index, hook, json_prompt, full_prompt,
            template_reference_path, product_image_paths, prompt_version
        """
        logger.info(f"Generating Pydantic prompt for variation {prompt_index}")

        if prompt_index < 1 or prompt_index > 100:
            raise ValueError("prompt_index must be between 1 and 100")
        if not product_image_paths or len(product_image_paths) == 0:
            raise ValueError("product_image_paths cannot be empty")

        num_product_images = len(product_image_paths)

        # Check offer variant mode
        using_offer_variant = bool(product.get('offer_variant'))

        if using_offer_variant:
            benefits_for_prompt = product.get('offer_benefits', []) or []
            usps_for_prompt = []
            target_audience_for_prompt = product.get('offer_target_audience') or product.get('target_audience', 'general audience')
        else:
            benefits_for_prompt = product.get('benefits', []) or []
            usps_for_prompt = product.get('unique_selling_points', []) or []
            target_audience_for_prompt = product.get('target_audience', 'general audience')

        # Match benefit to hook
        matched_benefit = match_benefit_to_hook(
            selected_hook,
            benefits_for_prompt,
            usps_for_prompt if not using_offer_variant else None
        )

        # Build color configuration
        template_colors = ad_analysis.get('color_palette', ['#F5F0E8'])
        if color_mode == "brand" and brand_colors:
            colors_config = ColorConfig(
                mode="brand",
                palette=brand_colors.get('all', [brand_colors.get('primary'), brand_colors.get('secondary'), brand_colors.get('background')]),
                primary={"hex": brand_colors.get('primary', '#4747C9'), "name": brand_colors.get('primary_name', 'Primary')},
                secondary={"hex": brand_colors.get('secondary', '#FDBE2D'), "name": brand_colors.get('secondary_name', 'Secondary')},
                background={"hex": brand_colors.get('background', '#F5F5F5'), "name": brand_colors.get('background_name', 'Background')},
                instruction="Use official brand colors consistently throughout the ad",
            )
        elif color_mode == "complementary":
            colors_config = ColorConfig(
                mode="complementary",
                palette=None,
                instruction="Generate a fresh, eye-catching complementary color scheme for Facebook ads",
            )
        else:
            colors_config = ColorConfig(
                mode="original",
                palette=template_colors,
                instruction="Use the exact colors from the reference template",
            )

        # Build fonts configuration
        fonts_config = None
        if brand_fonts:
            fonts_config = FontConfig(
                heading=FontEntry(
                    family=brand_fonts.get('primary', 'System default'),
                    weights=brand_fonts.get('primary_weights', []),
                    style_notes=brand_fonts.get('primary_style_notes'),
                ),
                body=FontEntry(
                    family=brand_fonts.get('secondary', 'System default'),
                    weights=brand_fonts.get('secondary_weights', []),
                    style_notes=brand_fonts.get('secondary_style_notes'),
                ),
            )

        # Build founders configuration
        has_founder_signature = ad_analysis.get('has_founder_signature', False)
        has_founder_mention = ad_analysis.get('has_founder_mention', False)
        founders_config = FoundersConfig(
            template_has_signature=has_founder_signature,
            template_has_mention=has_founder_mention,
            product_founders=product.get('founders'),
            action="omit",
        )
        if (has_founder_signature or has_founder_mention) and product.get('founders'):
            founders_config.action = "include"
            founders_config.signature_style = ad_analysis.get('founder_signature_style', 'personal sign-off')
            founders_config.signature_placement = ad_analysis.get('founder_signature_placement', 'bottom')
        elif (has_founder_signature or has_founder_mention) and not product.get('founders'):
            founders_config.action = "omit_with_warning"

        # Build image configurations
        product_images_config = []
        for i, path in enumerate(product_image_paths):
            product_images_config.append(ProductImageEntry(
                path=path,
                role="primary" if i == 0 else "secondary",
                description="Main product packaging" if i == 0 else "Product contents or alternate view",
            ))

        # Build multi-image handling
        multi_image_handling = None
        if num_product_images > 1:
            multi_image_handling = MultiImageHandling(
                primary_dominant=True,
                secondary_optional=True,
                secondary_usage="contents, inset view, or background element",
            )

        # Build special instructions
        special_instructions = None
        if product.get('combined_instructions'):
            special_instructions = SpecialInstructions(
                text=product['combined_instructions'],
            )

        # Phase 3: Build AssetContext when template_elements is not None
        asset_context = None
        if template_elements is not None:
            asset_context = self._build_asset_context(
                template_elements=template_elements,
                brand_asset_info=brand_asset_info,
                selected_image_tags=selected_image_tags,
            )

        # Construct the Pydantic prompt model
        prompt_model = AdGenerationPrompt(
            task=TaskConfig(
                action="create_facebook_ad",
                variation_index=prompt_index,
                total_variations=num_variations,
                product_name=product.get('display_name', product.get('name', '')),
                canvas_size=canvas_size,
                color_mode=color_mode,
                prompt_version=prompt_version,
            ),
            special_instructions=special_instructions,
            product=ProductContext(
                id=str(product['id']) if product.get('id') else None,
                name=product.get('name', ''),
                display_name=product.get('display_name', product.get('name', '')),
                target_audience=target_audience_for_prompt,
                benefits=benefits_for_prompt,
                unique_selling_points=usps_for_prompt,
                current_offer=product.get('current_offer'),
                brand_voice_notes=product.get('brand_voice_notes'),
                prohibited_claims=product.get('prohibited_claims', []) or [],
                required_disclaimers=product.get('required_disclaimers'),
                founders=product.get('founders'),
                product_dimensions=product.get('product_dimensions'),
                variant=product.get('variant'),
                offer_variant=product.get('offer_variant') if using_offer_variant else None,
                offer_pain_points=product.get('offer_pain_points', []) if using_offer_variant else None,
            ),
            content=ContentConfig(
                headline=HeadlineConfig(
                    text=selected_hook.get('adapted_text'),
                    source="hook",
                    hook_id=str(selected_hook['id']) if selected_hook.get('id') else None,
                    persuasion_type=selected_hook.get('persuasion_type'),
                ),
                subheadline=SubheadlineConfig(
                    text=matched_benefit,
                    source="matched_benefit",
                ),
            ),
            style=StyleConfig(
                format_type=ad_analysis.get('format_type'),
                layout_structure=ad_analysis.get('layout_structure'),
                canvas_size=canvas_size,
                text_placement=ad_analysis.get('text_placement', {}),
                colors=colors_config,
                fonts=fonts_config,
                authenticity_markers=ad_analysis.get('authenticity_markers', []),
            ),
            images=ImageConfig(
                template=TemplateImageConfig(
                    path=reference_ad_path,
                    role="style_reference",
                ),
                product=product_images_config,
            ),
            template_analysis=TemplateAnalysis(
                format_type=ad_analysis.get('format_type'),
                layout_structure=ad_analysis.get('layout_structure'),
                has_founder_signature=has_founder_signature,
                has_founder_mention=has_founder_mention,
                detailed_description=ad_analysis.get('detailed_description', ''),
            ),
            asset_context=asset_context,
            rules=GenerationRules(
                product_image=ProductImageRules(
                    multi_image_handling=multi_image_handling,
                ),
                offers=OfferRules(
                    provided_offer=product.get('current_offer'),
                ),
                scale=ScaleRules(
                    product_dimensions=product.get('product_dimensions'),
                ),
                founders=founders_config,
                prohibited_claims=product.get('prohibited_claims', []) or [],
                required_disclaimers=product.get('required_disclaimers'),
            ),
            ad_brief=AdBriefConfig(
                instructions=ad_brief_instructions,
            ),
        )

        # Serialize using Pydantic's exclude_none
        json_prompt = prompt_model.model_dump(exclude_none=True)

        full_prompt = _json_dumps(json_prompt, indent=2)

        prompt_dict = {
            "prompt_index": prompt_index,
            "hook": selected_hook,
            "json_prompt": json_prompt,
            "full_prompt": full_prompt,
            "template_reference_path": reference_ad_path,
            "product_image_paths": product_image_paths,
            "prompt_version": prompt_version,
        }

        logger.info(f"Generated Pydantic prompt for variation {prompt_index} ({len(full_prompt)} chars)")
        return prompt_dict

    async def execute_generation(
        self,
        nano_banana_prompt: Dict[str, Any],
        *,
        ad_creation_service: Any,
        gemini_service: Any,
        image_resolution: str = "2K",
    ) -> Dict[str, Any]:
        """
        Execute Gemini image generation from a constructed prompt.

        Args:
            nano_banana_prompt: Prompt dict from generate_prompt()
            ad_creation_service: AdCreationService for image download
            gemini_service: GeminiService for image generation
            image_resolution: Image resolution for Gemini

        Returns:
            Dict with prompt_index, image_base64, model metadata
        """
        prompt_index = nano_banana_prompt.get('prompt_index')
        logger.info(f"Executing Nano Banana generation for variation {prompt_index}")

        # Download template reference image
        template_data = await ad_creation_service.download_image(
            nano_banana_prompt['template_reference_path']
        )

        # Download product images (1-2)
        product_image_paths = nano_banana_prompt.get('product_image_paths', [])
        product_images_data = []
        for path in product_image_paths:
            img_data = await ad_creation_service.download_image(path)
            product_images_data.append(img_data)

        # Build reference images: template + product images
        reference_images = [template_data] + product_images_data

        logger.info(f"Reference images: {len(reference_images)} total "
                    f"(1 template + {len(product_images_data)} product)")

        if "SECONDARY" in nano_banana_prompt.get('full_prompt', ''):
            logger.info("Prompt includes SECONDARY image instructions")

        # Call Gemini API
        generation_result = await gemini_service.generate_image(
            prompt=nano_banana_prompt['full_prompt'],
            reference_images=reference_images,
            image_size=image_resolution,
            return_metadata=True
        )

        generated_ad = {
            "prompt_index": prompt_index,
            "image_base64": generation_result["image_base64"],
            "storage_path": None,
            "model_requested": generation_result.get("model_requested"),
            "model_used": generation_result.get("model_used"),
            "generation_time_ms": generation_result.get("generation_time_ms"),
            "generation_retries": generation_result.get("retries", 0),
            "num_reference_images": len(reference_images)
        }

        logger.info(f"Generated ad image for variation {prompt_index} "
                    f"(model={generation_result.get('model_used')}, "
                    f"time={generation_result.get('generation_time_ms')}ms)")
        return generated_ad

    def _build_asset_context(
        self,
        template_elements: Dict[str, Any],
        brand_asset_info: Optional[Dict[str, Any]],
        selected_image_tags: Optional[List[str]],
    ) -> AssetContext:
        """Build AssetContext from template elements, brand info, and selected image tags.

        Called only when template_elements is not None (detection has run).
        Uses selected_image_tags (not all images) for accurate coverage.
        """
        brand_info = brand_asset_info or {}
        brand_has_logo = brand_info.get("has_logo", False)
        brand_has_badge = brand_info.get("has_badge", False)

        # Parse text areas
        text_areas_raw = template_elements.get("text_areas", [])
        text_areas = []
        for ta in (text_areas_raw if isinstance(text_areas_raw, list) else []):
            if isinstance(ta, dict):
                text_areas.append(TextAreaSpec(
                    type=ta.get("type", "unknown"),
                    position=ta.get("position"),
                    max_chars=ta.get("max_chars"),
                ))

        # Determine logo/person requirements from both required + optional + logo_areas
        required_assets = template_elements.get("required_assets", [])
        optional_assets = template_elements.get("optional_assets", [])
        logo_areas = template_elements.get("logo_areas", [])

        all_assets = set(required_assets + optional_assets)
        requires_logo = any("logo" in a for a in all_assets) or len(logo_areas) > 0
        requires_person = any("person" in a for a in all_assets)
        requires_badge = any("badge" in a for a in all_assets)

        # Logo placement from first logo_area
        logo_placement = None
        if logo_areas and isinstance(logo_areas, list) and len(logo_areas) > 0:
            first_logo = logo_areas[0] if isinstance(logo_areas[0], dict) else {}
            logo_placement = first_logo.get("position")

        # Recompute asset coverage against SELECTED image tags (not all images)
        selected_tags_set = set(selected_image_tags or [])
        required_set = set(required_assets)
        matched = sorted(required_set & selected_tags_set)
        missing = sorted(required_set - selected_tags_set)
        score = len(matched) / len(required_set) if required_set else 1.0

        # Person/logo gap detection using selected image tags + brand info
        has_person_in_selected = any(t.startswith("person:") for t in selected_tags_set)
        has_logo_in_selected = "logo" in selected_tags_set
        person_gap = requires_person and not has_person_in_selected
        logo_gap = requires_logo and not (brand_has_logo or has_logo_in_selected)

        # Available person tags from selected images
        available_person_tags = sorted(
            t for t in selected_tags_set if t.startswith("person:")
        )

        # Generate asset_instructions
        instructions = []
        if logo_gap:
            instructions.append(
                "Template has logo area but brand has no logo. "
                "Leave logo area empty or use brand name text."
            )
        if person_gap:
            instructions.append(
                "Template shows person but no person images in selected set. "
                "Use product-focused composition."
            )
        for ta in text_areas:
            if ta.max_chars:
                instructions.append(
                    f"The {ta.type} text area fits ~{ta.max_chars} characters. "
                    f"Keep within this limit."
                )
        for m in missing:
            instructions.append(
                f"Template requires '{m}' but it's not in the selected images."
            )

        return AssetContext(
            template_requires_logo=requires_logo,
            brand_has_logo=brand_has_logo,
            logo_placement=logo_placement,
            template_requires_badge=requires_badge,
            brand_has_badge=brand_has_badge,
            template_requires_person=requires_person,
            available_person_tags=available_person_tags,
            template_text_areas=text_areas,
            asset_match_score=score,
            matched_assets=matched,
            missing_assets=missing,
            asset_instructions=" | ".join(instructions) if instructions else "",
        )
