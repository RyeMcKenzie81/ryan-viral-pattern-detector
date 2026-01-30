"""
Generation Service - Prompt construction and image generation execution.

Extracted from ad_creation_agent.py tools:
- generate_nano_banana_prompt (lines 1330-1637)
- execute_nano_banana (lines 1656-1745)
"""

import json
import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

from .content_service import match_benefit_to_hook

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any, **kwargs) -> str:
    """JSON dumps with UUID serialization support."""
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, UUID) else TypeError(f"Not serializable: {type(o)}"), **kwargs)


class AdGenerationService:
    """Handles prompt construction and image generation for ad creation."""

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
    ) -> Dict[str, Any]:
        """
        Generate structured JSON prompt for Gemini image generation.

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

        Returns:
            Dict with prompt_index, hook, json_prompt, full_prompt,
            template_reference_path, product_image_paths
        """
        logger.info(f"Generating JSON prompt for variation {prompt_index}")

        if prompt_index < 1 or prompt_index > 15:
            raise ValueError("prompt_index must be between 1 and 15")
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
            colors_config = {
                "mode": "brand",
                "palette": brand_colors.get('all', [brand_colors.get('primary'), brand_colors.get('secondary'), brand_colors.get('background')]),
                "primary": {"hex": brand_colors.get('primary', '#4747C9'), "name": brand_colors.get('primary_name', 'Primary')},
                "secondary": {"hex": brand_colors.get('secondary', '#FDBE2D'), "name": brand_colors.get('secondary_name', 'Secondary')},
                "background": {"hex": brand_colors.get('background', '#F5F5F5'), "name": brand_colors.get('background_name', 'Background')},
                "instruction": "Use official brand colors consistently throughout the ad"
            }
        elif color_mode == "complementary":
            colors_config = {
                "mode": "complementary",
                "palette": None,
                "instruction": "Generate a fresh, eye-catching complementary color scheme for Facebook ads"
            }
        else:
            colors_config = {
                "mode": "original",
                "palette": template_colors,
                "instruction": "Use the exact colors from the reference template"
            }

        # Build fonts configuration
        fonts_config = None
        if brand_fonts:
            fonts_config = {
                "heading": {
                    "family": brand_fonts.get('primary', 'System default'),
                    "weights": brand_fonts.get('primary_weights', []),
                    "style_notes": brand_fonts.get('primary_style_notes')
                },
                "body": {
                    "family": brand_fonts.get('secondary', 'System default'),
                    "weights": brand_fonts.get('secondary_weights', []),
                    "style_notes": brand_fonts.get('secondary_style_notes')
                }
            }

        # Build founders configuration
        has_founder_signature = ad_analysis.get('has_founder_signature', False)
        has_founder_mention = ad_analysis.get('has_founder_mention', False)
        founders_config = {
            "template_has_signature": has_founder_signature,
            "template_has_mention": has_founder_mention,
            "product_founders": product.get('founders'),
            "action": "omit"
        }
        if (has_founder_signature or has_founder_mention) and product.get('founders'):
            founders_config["action"] = "include"
            founders_config["signature_style"] = ad_analysis.get('founder_signature_style', 'personal sign-off')
            founders_config["signature_placement"] = ad_analysis.get('founder_signature_placement', 'bottom')
        elif (has_founder_signature or has_founder_mention) and not product.get('founders'):
            founders_config["action"] = "omit_with_warning"

        # Build image configurations
        product_images_config = []
        for i, path in enumerate(product_image_paths):
            product_images_config.append({
                "path": path,
                "role": "primary" if i == 0 else "secondary",
                "description": "Main product packaging" if i == 0 else "Product contents or alternate view"
            })

        # Build complete JSON prompt
        json_prompt = {
            "task": {
                "action": "create_facebook_ad",
                "variation_index": prompt_index,
                "total_variations": num_variations,
                "product_name": product.get('display_name', product.get('name'))
            },
            "special_instructions": {
                "priority": "HIGHEST",
                "text": product.get('combined_instructions'),
                "note": "These instructions override all other guidelines when there is a conflict"
            } if product.get('combined_instructions') else None,
            "product": {
                "id": product.get('id'),
                "name": product.get('name'),
                "display_name": product.get('display_name', product.get('name')),
                "target_audience": target_audience_for_prompt,
                "benefits": benefits_for_prompt,
                "unique_selling_points": usps_for_prompt,
                "current_offer": product.get('current_offer'),
                "brand_voice_notes": product.get('brand_voice_notes'),
                "prohibited_claims": product.get('prohibited_claims', []),
                "required_disclaimers": product.get('required_disclaimers'),
                "founders": product.get('founders'),
                "product_dimensions": product.get('product_dimensions'),
                "variant": product.get('variant'),
                "offer_variant": product.get('offer_variant') if using_offer_variant else None,
                "offer_pain_points": product.get('offer_pain_points', []) if using_offer_variant else None
            },
            "content": {
                "headline": {
                    "text": selected_hook.get('adapted_text'),
                    "source": "hook",
                    "hook_id": selected_hook.get('id'),
                    "persuasion_type": selected_hook.get('persuasion_type')
                },
                "subheadline": {
                    "text": matched_benefit,
                    "source": "matched_benefit"
                }
            },
            "style": {
                "format_type": ad_analysis.get('format_type'),
                "layout_structure": ad_analysis.get('layout_structure'),
                "canvas_size": ad_analysis.get('canvas_size', '1080x1080px'),
                "text_placement": ad_analysis.get('text_placement', {}),
                "colors": colors_config,
                "fonts": fonts_config,
                "authenticity_markers": ad_analysis.get('authenticity_markers', [])
            },
            "images": {
                "template": {
                    "path": reference_ad_path,
                    "role": "style_reference"
                },
                "product": product_images_config
            },
            "template_analysis": {
                "format_type": ad_analysis.get('format_type'),
                "layout_structure": ad_analysis.get('layout_structure'),
                "has_founder_signature": has_founder_signature,
                "has_founder_mention": has_founder_mention,
                "detailed_description": ad_analysis.get('detailed_description', '')
            },
            "rules": {
                "product_image": {
                    "preserve_exactly": True,
                    "no_modifications": True,
                    "text_preservation": {
                        "critical": True,
                        "requirement": "ALL text on packaging MUST be pixel-perfect legible",
                        "method": "composite_not_regenerate",
                        "rejection_condition": "blurry or illegible text"
                    },
                    "multi_image_handling": {
                        "primary_dominant": True,
                        "secondary_optional": num_product_images > 1,
                        "secondary_usage": "contents, inset view, or background element"
                    } if num_product_images > 1 else None
                },
                "offers": {
                    "use_only_provided": True,
                    "provided_offer": product.get('current_offer'),
                    "do_not_copy_from_template": True,
                    "max_count": 1,
                    "prohibited_template_offers": ["Free gift", "Buy 1 Get 1", "Bundle and save", "Autoship", "BOGO"]
                },
                "lighting": {
                    "match_scene": True,
                    "shadow_direction": "match_scene_elements",
                    "color_temperature": "match_scene",
                    "ambient_occlusion": True,
                    "requirement": "Product must look naturally IN the scene, not pasted on"
                },
                "scale": {
                    "realistic_sizing": True,
                    "relative_to": ["hands", "countertops", "furniture", "pets"],
                    "product_dimensions": product.get('product_dimensions'),
                    "requirement": "Product must appear proportionally correct"
                },
                "founders": founders_config,
                "prohibited_claims": product.get('prohibited_claims', []),
                "required_disclaimers": product.get('required_disclaimers')
            },
            "ad_brief": {
                "instructions": ad_brief_instructions
            }
        }

        # Remove None values
        json_prompt = _remove_none(json_prompt)

        full_prompt = _json_dumps(json_prompt, indent=2)

        prompt_dict = {
            "prompt_index": prompt_index,
            "hook": selected_hook,
            "json_prompt": json_prompt,
            "full_prompt": full_prompt,
            "template_reference_path": reference_ad_path,
            "product_image_paths": product_image_paths
        }

        logger.info(f"Generated JSON prompt for variation {prompt_index} ({len(full_prompt)} chars)")
        return prompt_dict

    async def execute_generation(
        self,
        nano_banana_prompt: Dict[str, Any],
        *,
        ad_creation_service: Any,
        gemini_service: Any,
    ) -> Dict[str, Any]:
        """
        Execute Gemini image generation from a constructed prompt.

        Args:
            nano_banana_prompt: Prompt dict from generate_prompt()
            ad_creation_service: AdCreationService for image download
            gemini_service: GeminiService for image generation

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


def _remove_none(d: Any) -> Any:
    """Recursively remove None values from dicts/lists."""
    if isinstance(d, dict):
        return {k: _remove_none(v) for k, v in d.items() if v is not None}
    elif isinstance(d, list):
        return [_remove_none(i) for i in d if i is not None]
    return d
