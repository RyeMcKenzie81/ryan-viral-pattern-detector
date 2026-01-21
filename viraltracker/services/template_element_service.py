"""
TemplateElementService - Template element detection and asset matching.

Provides:
- Template element detection (people, objects, logos, text areas)
- Product image tagging with semantic tags
- Asset-to-template matching for recommendations

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from supabase import Client

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


# Current detection algorithm version
DETECTION_VERSION = "1.0"


# Element detection prompt for Gemini Vision
ELEMENT_DETECTION_PROMPT = """Analyze this Facebook ad template image and identify ALL visual elements that would need to be provided to recreate this ad.

Identify and categorize:

1. **PEOPLE** - Any human figures in the image
   - Type: professional (doctor, vet, expert), casual (everyday person), athletic, elderly, parent, child
   - Role: testimonial giver, product user, authority figure, model
   - Description: Brief visual description
   - Importance: "required" if central to the ad, "optional" if supplementary

2. **OBJECTS** - Products, props, and items
   - Type: product (the main product being advertised), prop (supporting items), equipment
   - Description: What the object is
   - Importance: "required" or "optional"

3. **TEXT_AREAS** - Regions where text appears
   - Type: headline, subheadline, body_text, cta (call-to-action), testimonial_quote, price
   - Position: top, middle, bottom, left, right, center, overlay
   - Estimated max characters (if visible)

4. **LOGO_AREAS** - Where logos appear
   - Position: top_left, top_right, bottom_left, bottom_right, center
   - Size: small, medium, large

Based on your analysis, also provide:
- **required_assets**: List of asset tags that MUST be provided (e.g., "person:vet", "product:bottle", "logo")
- **optional_assets**: List of asset tags that are nice to have

Return ONLY valid JSON with this exact structure:
{{
  "people": [
    {{"type": "professional", "role": "vet", "description": "veterinarian in white coat", "importance": "required"}}
  ],
  "objects": [
    {{"type": "product", "description": "supplement bottle with label", "importance": "required"}}
  ],
  "text_areas": [
    {{"type": "headline", "position": "top", "max_chars": 40}},
    {{"type": "cta", "position": "bottom", "max_chars": 20}}
  ],
  "logo_areas": [
    {{"position": "bottom_right", "size": "small"}}
  ],
  "required_assets": ["person:vet", "product:bottle"],
  "optional_assets": ["logo"]
}}

If an element category has no items, use an empty array [].
Be thorough - missing a required element will cause generation problems."""


# Image tagging prompt for auto-tagging product images
IMAGE_TAGGING_PROMPT = """Analyze this product image and generate semantic tags for asset matching.

Generate tags in these categories:
1. **Person tags** (if a person is visible):
   - Format: "person:TYPE" where TYPE is: vet, doctor, professional, mom, dad, parent, elderly, athlete, casual, child
   - Also add role tags like: "authority", "testimonial", "user"

2. **Product tags** (if a product is visible):
   - Format: "product:TYPE" where TYPE describes the product: bottle, jar, bag, box, tube, container
   - Add category: "supplement", "skincare", "food", "equipment"

3. **Content tags**:
   - "logo" if a brand logo is visible
   - "lifestyle" if it shows product in use
   - "studio" if it's a clean product shot
   - "before_after" if it shows transformation
   - "comparison" if it compares products

4. **Quality tags**:
   - "high_quality" if professional photography
   - "transparent_bg" if on transparent background
   - "white_bg" if on white background

Return ONLY a JSON array of string tags:
["person:vet", "product:bottle", "professional", "authority", "high_quality"]

Be thorough but only include tags that clearly apply."""


class TemplateElementService:
    """Service for template element detection and asset matching."""

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize TemplateElementService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("TemplateElementService initialized")

    def _extract_json_from_response(self, response: str) -> Dict[str, Any]:
        """
        Extract JSON from a Gemini response that may contain markdown or text.

        Handles various response formats:
        - Pure JSON
        - JSON in markdown code blocks
        - JSON with text before/after
        - Double-escaped braces ({{ and }})

        Args:
            response: Raw response string from Gemini

        Returns:
            Parsed JSON as dict

        Raises:
            ValueError: If no valid JSON found
        """
        import re

        text = response.strip()

        # Fix double braces that Gemini sometimes returns
        text = text.replace('{{', '{').replace('}}', '}')

        # Try 1: Direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try 2: Extract from markdown code block
        if "```" in text:
            # Find content between ``` markers
            pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    return json.loads(match.strip())
                except json.JSONDecodeError:
                    continue

        # Try 3: Find JSON object by matching braces
        # Find the first { and last }
        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx:end_idx + 1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Try 4: More aggressive - find balanced braces
        if start_idx != -1:
            depth = 0
            for i, char in enumerate(text[start_idx:], start_idx):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = text[start_idx:i + 1]
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            break

        # Log the response for debugging
        logger.warning(f"Could not extract JSON from response. First 300 chars: {text[:300]}")
        raise ValueError(f"No valid JSON found in response")

    def _extract_array_from_response(self, response: str) -> List[str]:
        """
        Extract JSON array from a Gemini response.

        Args:
            response: Raw response string from Gemini

        Returns:
            Parsed JSON array

        Raises:
            ValueError: If no valid JSON array found
        """
        import re

        text = response.strip()

        # Fix double braces that Gemini sometimes returns
        text = text.replace('{{', '{').replace('}}', '}')

        # Try 1: Direct JSON parse
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Try 2: Extract from markdown code block
        if "```" in text:
            pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    result = json.loads(match.strip())
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    continue

        # Try 3: Find JSON array by matching brackets
        start_idx = text.find('[')
        end_idx = text.rfind(']')

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx:end_idx + 1]
            try:
                result = json.loads(json_str)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not extract JSON array from response. First 300 chars: {text[:300]}")
        raise ValueError(f"No valid JSON array found in response")

    # =========================================================================
    # Template Element Detection
    # =========================================================================

    async def analyze_template_elements(
        self,
        template_id: UUID,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze a template to detect visual elements.

        Uses Gemini Vision to identify people, objects, text areas, and logos
        in the template image. Results are cached in the database.

        Args:
            template_id: UUID of the scraped_template
            force: If True, re-analyze even if cached results exist

        Returns:
            Dict with detected elements:
            {
                "people": [...],
                "objects": [...],
                "text_areas": [...],
                "logo_areas": [...],
                "required_assets": [...],
                "optional_assets": [...]
            }

        Raises:
            ValueError: If template not found
        """
        from .gemini_service import GeminiService

        # Get template
        result = self.supabase.table("scraped_templates").select(
            "id, name, storage_path, template_elements, element_detection_version"
        ).eq("id", str(template_id)).execute()

        if not result.data:
            raise ValueError(f"Template not found: {template_id}")

        template = result.data[0]

        # Check if we have cached results and don't need to re-analyze
        if not force:
            if (template.get("template_elements") and
                template.get("element_detection_version") == DETECTION_VERSION):
                logger.info(f"Using cached element detection for template {template_id}")
                return template["template_elements"]

        # Get template image
        storage_path = template.get("storage_path")
        if not storage_path:
            raise ValueError(f"Template {template_id} has no storage_path")

        # Download image
        parts = storage_path.split("/", 1)
        bucket = parts[0] if len(parts) > 1 else "scraped-templates"
        path = parts[1] if len(parts) > 1 else storage_path

        import base64
        import asyncio
        image_bytes = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Analyze with Gemini Vision
        gemini = GeminiService()
        response = await gemini.analyze_image(image_base64, ELEMENT_DETECTION_PROMPT)

        # Parse JSON response
        try:
            elements = self._extract_json_from_response(response)
        except Exception as e:
            logger.error(f"Failed to parse element detection response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            # Return empty structure rather than failing
            elements = {
                "people": [],
                "objects": [],
                "text_areas": [],
                "logo_areas": [],
                "required_assets": [],
                "optional_assets": []
            }

        # Cache results
        self.supabase.table("scraped_templates").update({
            "template_elements": elements,
            "element_detection_version": DETECTION_VERSION,
            "element_detection_at": datetime.utcnow().isoformat()
        }).eq("id", str(template_id)).execute()

        logger.info(f"Analyzed template {template_id}: {len(elements.get('required_assets', []))} required assets")
        return elements

    async def batch_analyze_templates(
        self,
        template_ids: Optional[List[UUID]] = None,
        batch_size: int = 10,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Batch analyze multiple templates.

        Args:
            template_ids: List of template UUIDs. If None, analyze all active templates.
            batch_size: Number to process in parallel
            force: If True, re-analyze even if cached

        Returns:
            Dict with "successful" and "failed" counts and details
        """
        import asyncio

        # Get templates to analyze
        if template_ids:
            query = self.supabase.table("scraped_templates").select(
                "id"
            ).in_("id", [str(t) for t in template_ids])
        else:
            # Get all active templates without current detection version
            query = self.supabase.table("scraped_templates").select(
                "id"
            ).eq("is_active", True)
            if not force:
                query = query.or_(
                    f"element_detection_version.is.null,"
                    f"element_detection_version.neq.{DETECTION_VERSION}"
                )

        result = query.execute()
        templates = result.data or []

        logger.info(f"Batch analyzing {len(templates)} templates")

        results = {"successful": [], "failed": [], "skipped": 0}

        # Process in batches
        for i in range(0, len(templates), batch_size):
            batch = templates[i:i + batch_size]

            for template in batch:
                try:
                    await self.analyze_template_elements(
                        UUID(template["id"]),
                        force=force
                    )
                    results["successful"].append(template["id"])
                except Exception as e:
                    logger.error(f"Failed to analyze template {template['id']}: {e}")
                    results["failed"].append({
                        "template_id": template["id"],
                        "error": str(e)
                    })

            # Small delay between batches to avoid rate limits
            if i + batch_size < len(templates):
                await asyncio.sleep(1)

        logger.info(f"Batch analysis complete: {len(results['successful'])} successful, "
                   f"{len(results['failed'])} failed")
        return results

    def get_template_elements(self, template_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get cached template elements (no analysis).

        Args:
            template_id: UUID of the template

        Returns:
            Dict with elements or None if not analyzed
        """
        result = self.supabase.table("scraped_templates").select(
            "template_elements"
        ).eq("id", str(template_id)).execute()

        if result.data and result.data[0].get("template_elements"):
            return result.data[0]["template_elements"]
        return None

    # =========================================================================
    # Product Image Tagging
    # =========================================================================

    def tag_product_image(
        self,
        image_id: UUID,
        tags: List[str]
    ) -> bool:
        """
        Manually tag a product image with semantic tags.

        Args:
            image_id: UUID of the product_image
            tags: List of semantic tags (e.g., ["person:vet", "professional"])

        Returns:
            True if successful
        """
        self.supabase.table("product_images").update({
            "asset_tags": tags
        }).eq("id", str(image_id)).execute()

        logger.info(f"Tagged image {image_id} with {len(tags)} tags")
        return True

    async def auto_tag_product_image(
        self,
        image_id: UUID,
        force: bool = False
    ) -> List[str]:
        """
        Auto-tag a product image using Gemini Vision.

        Args:
            image_id: UUID of the product_image
            force: If True, re-tag even if already tagged

        Returns:
            List of generated tags
        """
        from .gemini_service import GeminiService

        # Get image
        result = self.supabase.table("product_images").select(
            "id, storage_path, asset_tags"
        ).eq("id", str(image_id)).execute()

        if not result.data:
            raise ValueError(f"Product image not found: {image_id}")

        image = result.data[0]

        # Check if already tagged
        if not force and image.get("asset_tags") and len(image["asset_tags"]) > 0:
            logger.info(f"Image {image_id} already tagged, skipping")
            return image["asset_tags"]

        # Get image data
        storage_path = image.get("storage_path")
        if not storage_path:
            raise ValueError(f"Image {image_id} has no storage_path")

        parts = storage_path.split("/", 1)
        bucket = parts[0] if len(parts) > 1 else "product-images"
        path = parts[1] if len(parts) > 1 else storage_path

        import base64
        import asyncio
        image_bytes = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Analyze with Gemini
        gemini = GeminiService()
        response = await gemini.analyze_image(image_base64, IMAGE_TAGGING_PROMPT)

        # Parse JSON response (expecting an array)
        try:
            tags = self._extract_array_from_response(response)
        except Exception as e:
            logger.error(f"Failed to parse tagging response: {e}")
            tags = []

        # Save tags
        if tags:
            self.supabase.table("product_images").update({
                "asset_tags": tags
            }).eq("id", str(image_id)).execute()

        logger.info(f"Auto-tagged image {image_id} with {len(tags)} tags: {tags}")
        return tags

    async def auto_tag_product_images(
        self,
        product_id: UUID,
        force: bool = False
    ) -> int:
        """
        Auto-tag all images for a product.

        Args:
            product_id: UUID of the product
            force: If True, re-tag all images

        Returns:
            Number of images tagged
        """
        import asyncio

        # Get product images
        query = self.supabase.table("product_images").select("id").eq(
            "product_id", str(product_id)
        )

        if not force:
            # Only get un-tagged images
            query = query.or_("asset_tags.is.null,asset_tags.eq.[]")

        result = query.execute()
        images = result.data or []

        logger.info(f"Auto-tagging {len(images)} images for product {product_id}")

        tagged_count = 0
        for img in images:
            try:
                await self.auto_tag_product_image(UUID(img["id"]), force=force)
                tagged_count += 1
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to tag image {img['id']}: {e}")

        return tagged_count

    # =========================================================================
    # Asset Matching
    # =========================================================================

    def match_assets_to_template(
        self,
        template_id: UUID,
        product_id: UUID
    ) -> Dict[str, Any]:
        """
        Match a product's assets against a template's requirements.

        Args:
            template_id: UUID of the template
            product_id: UUID of the product

        Returns:
            Dict with matching results:
            {
                "asset_match_score": 0.0-1.0,
                "matched_assets": ["person:vet", "product:bottle"],
                "missing_assets": ["logo"],
                "optional_missing": ["background"],
                "warnings": ["Missing: Logo image"],
                "available_images": [{...}]  # Images that can fulfill requirements
            }
        """
        # Get template elements
        elements = self.get_template_elements(template_id)
        if not elements:
            # No element detection done - assume all assets available
            return {
                "asset_match_score": 1.0,
                "matched_assets": [],
                "missing_assets": [],
                "optional_missing": [],
                "warnings": [],
                "available_images": [],
                "detection_status": "not_analyzed"
            }

        required_assets = set(elements.get("required_assets", []))
        optional_assets = set(elements.get("optional_assets", []))

        # Get product images with tags
        result = self.supabase.table("product_images").select(
            "id, storage_path, asset_tags, image_type, alt_text"
        ).eq("product_id", str(product_id)).execute()

        product_images = result.data or []

        # Collect all available tags from product images
        available_tags = set()
        tag_to_images = {}  # Map tag -> list of images that have it

        for img in product_images:
            tags = img.get("asset_tags") or []
            for tag in tags:
                available_tags.add(tag)
                if tag not in tag_to_images:
                    tag_to_images[tag] = []
                tag_to_images[tag].append(img)

        # Match required assets
        matched = required_assets.intersection(available_tags)
        missing = required_assets - available_tags

        # Match optional assets
        optional_matched = optional_assets.intersection(available_tags)
        optional_missing = optional_assets - available_tags

        # Calculate score
        if len(required_assets) == 0:
            score = 1.0
        else:
            score = len(matched) / len(required_assets)

        # Generate warnings for missing required assets
        warnings = []
        missing_details = []
        for asset in missing:
            # Generate human-readable warning
            if asset.startswith("person:"):
                person_type = asset.split(":")[1].replace("_", " ").title()
                warnings.append(f"Missing: {person_type} image")
                missing_details.append({
                    "tag": asset,
                    "description": f"Professional {person_type} image",
                    "type": "person"
                })
            elif asset.startswith("product:"):
                product_type = asset.split(":")[1].replace("_", " ").title()
                warnings.append(f"Missing: {product_type} image")
                missing_details.append({
                    "tag": asset,
                    "description": f"Product {product_type} image",
                    "type": "product"
                })
            elif asset == "logo":
                warnings.append("Missing: Brand logo")
                missing_details.append({
                    "tag": asset,
                    "description": "Brand logo (transparent background preferred)",
                    "type": "logo"
                })
            else:
                warnings.append(f"Missing: {asset}")
                missing_details.append({
                    "tag": asset,
                    "description": asset,
                    "type": "other"
                })

        # Get available images that fulfill requirements
        available_images = []
        for tag in matched:
            for img in tag_to_images.get(tag, []):
                if img not in available_images:
                    available_images.append(img)

        return {
            "asset_match_score": score,
            "matched_assets": list(matched),
            "missing_assets": list(missing),
            "missing_details": missing_details,
            "optional_matched": list(optional_matched),
            "optional_missing": list(optional_missing),
            "warnings": warnings,
            "available_images": available_images,
            "detection_status": "analyzed"
        }

    def get_product_asset_summary(self, product_id: UUID) -> Dict[str, Any]:
        """
        Get a summary of available assets for a product.

        Args:
            product_id: UUID of the product

        Returns:
            Dict with asset summary:
            {
                "total_images": int,
                "tagged_images": int,
                "all_tags": [...],
                "by_type": {
                    "person": [...],
                    "product": [...],
                    "logo": [...]
                }
            }
        """
        result = self.supabase.table("product_images").select(
            "id, asset_tags, image_type"
        ).eq("product_id", str(product_id)).execute()

        images = result.data or []

        all_tags = set()
        by_type = {"person": [], "product": [], "logo": [], "other": []}
        tagged_count = 0

        for img in images:
            tags = img.get("asset_tags") or []
            if tags:
                tagged_count += 1
            for tag in tags:
                all_tags.add(tag)
                if tag.startswith("person:"):
                    by_type["person"].append(tag)
                elif tag.startswith("product:"):
                    by_type["product"].append(tag)
                elif tag == "logo":
                    by_type["logo"].append(tag)
                else:
                    by_type["other"].append(tag)

        return {
            "total_images": len(images),
            "tagged_images": tagged_count,
            "all_tags": list(all_tags),
            "by_type": {k: list(set(v)) for k, v in by_type.items()}
        }
