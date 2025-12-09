"""
AdCreationService - Handles Facebook ad creation workflows.

Manages:
- Product and hook data retrieval from Supabase
- Supabase Storage operations (upload/download images)
- Database CRUD for ad runs and generated ads
- Image format conversions (base64 ↔ bytes)
"""

import logging
import base64
import json
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client
from .models import (
    Product, Hook, AdBriefTemplate, AdAnalysis, SelectedHook,
    NanoBananaPrompt, GeneratedAd, ReviewResult, GeneratedAdWithReviews,
    AdCreationResult
)

logger = logging.getLogger(__name__)


class AdCreationService:
    """Service for Facebook ad creation operations"""

    def __init__(self):
        """Initialize with Supabase client"""
        self.supabase: Client = get_supabase_client()
        logger.info("AdCreationService initialized")

    # ============================================
    # PRODUCT & HOOK RETRIEVAL
    # ============================================

    async def get_product(self, product_id: UUID) -> Product:
        """
        Fetch product by ID with all metadata.

        Args:
            product_id: UUID of product

        Returns:
            Product model with all fields

        Raises:
            ValueError: If product not found
        """
        result = self.supabase.table("products").select("*").eq("id", str(product_id)).execute()

        if not result.data:
            raise ValueError(f"Product not found: {product_id}")

        return Product(**result.data[0])

    async def search_products_by_name(self, product_name: str) -> List[Product]:
        """
        Search products by name using case-insensitive partial matching.

        Args:
            product_name: Product name (or partial name) to search for

        Returns:
            List of matching Product models, sorted by name

        Examples:
            >>> search_products_by_name("Wonder Paws")
            [Product(name="Wonder Paws Collagen 3x"), Product(name="Wonder Paws Omega")]
        """
        # Use ilike for case-insensitive partial matching
        result = self.supabase.table("products").select("*").ilike("name", f"%{product_name}%").order("name").execute()

        return [Product(**row) for row in result.data]

    async def get_hooks(
        self,
        product_id: UUID,
        limit: int = 50,
        active_only: bool = True
    ) -> List[Hook]:
        """
        Fetch hooks for a product.

        Args:
            product_id: UUID of product
            limit: Maximum hooks to return
            active_only: Only return active hooks

        Returns:
            List of Hook models, sorted by impact_score DESC
        """
        query = self.supabase.table("hooks").select("*").eq("product_id", str(product_id))

        if active_only:
            query = query.eq("active", True)

        query = query.order("impact_score", desc=True).limit(limit)
        result = query.execute()

        return [Hook(**row) for row in result.data]

    async def get_ad_brief_template(
        self,
        brand_id: Optional[UUID] = None
    ) -> AdBriefTemplate:
        """
        Fetch ad brief template for brand (or global).

        Args:
            brand_id: UUID of brand (None = global)

        Returns:
            AdBriefTemplate model

        Raises:
            ValueError: If no template found
        """
        # Try brand-specific first
        if brand_id:
            result = self.supabase.table("ad_brief_templates")\
                .select("*")\
                .eq("brand_id", str(brand_id))\
                .eq("active", True)\
                .execute()

            if result.data:
                return AdBriefTemplate(**result.data[0])

        # Fall back to global
        result = self.supabase.table("ad_brief_templates")\
            .select("*")\
            .is_("brand_id", "null")\
            .eq("active", True)\
            .execute()

        if not result.data:
            raise ValueError("No ad brief template found")

        return AdBriefTemplate(**result.data[0])

    # ============================================
    # PERSONA OPERATIONS
    # ============================================

    def get_personas_for_product(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all personas linked to a product for UI dropdown.

        Args:
            product_id: UUID of the product

        Returns:
            List of persona summaries with id, name, snapshot
        """
        try:
            # Query junction table with persona data
            result = self.supabase.table("product_personas").select(
                "persona_id, is_primary, personas_4d(id, name, snapshot, persona_type)"
            ).eq("product_id", str(product_id)).execute()

            personas = []
            for row in result.data or []:
                persona_data = row.get("personas_4d", {})
                if persona_data:
                    personas.append({
                        "id": persona_data.get("id"),
                        "name": persona_data.get("name"),
                        "snapshot": persona_data.get("snapshot", ""),
                        "persona_type": persona_data.get("persona_type"),
                        "is_primary": row.get("is_primary", False)
                    })

            # Sort by is_primary (primary first), then name
            personas.sort(key=lambda p: (not p.get("is_primary", False), p.get("name", "")))
            return personas

        except Exception as e:
            logger.error(f"Failed to get personas for product {product_id}: {e}")
            return []

    def get_persona_for_ad_generation(self, persona_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get persona data formatted for ad generation prompts.

        Delegates to PersonaService.export_for_ad_generation() for
        consistent formatting across the codebase.

        Args:
            persona_id: UUID of the persona

        Returns:
            Dict with persona data optimized for ad generation, or None if not found
        """
        try:
            from .persona_service import PersonaService
            persona_service = PersonaService()
            return persona_service.export_for_ad_generation(persona_id)
        except ValueError as e:
            logger.warning(f"Persona not found: {persona_id} - {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get persona for ad generation: {e}")
            return None

    # ============================================
    # SUPABASE STORAGE OPERATIONS
    # ============================================

    async def upload_reference_ad(
        self,
        ad_run_id: UUID,
        image_data: bytes,
        filename: str = "reference.png"
    ) -> str:
        """
        Upload reference ad image to Supabase Storage.

        Args:
            ad_run_id: UUID of ad run
            image_data: Binary image data
            filename: Filename (default: reference.png)

        Returns:
            Storage path: "reference-ads/{ad_run_id}_{filename}"
        """
        import asyncio

        storage_path = f"{ad_run_id}_{filename}"

        # Run sync Supabase call in thread pool to avoid blocking event loop
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_("reference-ads").upload(
                storage_path,
                image_data,
                {"content-type": "image/png"}
            )
        )

        logger.info(f"Uploaded reference ad: {storage_path}")
        return f"reference-ads/{storage_path}"

    # ============================================
    # AD FILENAME GENERATION
    # ============================================

    def get_format_code(self, canvas_size: str) -> str:
        """
        Convert canvas dimensions to format code.

        Args:
            canvas_size: Canvas size string (e.g., "1080x1080px", "1080x1920px")

        Returns:
            Format code: SQ (square), ST (story), PT (portrait), LS (landscape)
        """
        # Parse dimensions from canvas_size (e.g., "1080x1080px" or "1080x1920")
        import re
        match = re.search(r'(\d+)\s*x\s*(\d+)', canvas_size.lower())
        if not match:
            return "SQ"  # Default to square

        width = int(match.group(1))
        height = int(match.group(2))

        # Determine aspect ratio
        ratio = width / height if height > 0 else 1

        if 0.95 <= ratio <= 1.05:  # Square (1:1)
            return "SQ"
        elif ratio < 0.7:  # Story/Portrait tall (9:16 = 0.5625, 4:5 = 0.8)
            if ratio < 0.65:
                return "ST"  # Story (9:16)
            else:
                return "PT"  # Portrait (4:5)
        else:  # Landscape (16:9 = 1.78)
            return "LS"

    async def get_brand_product_codes(self, product_id: UUID) -> tuple[str, str]:
        """
        Get brand_code and product_code for a product.

        Args:
            product_id: UUID of the product

        Returns:
            Tuple of (brand_code, product_code)
            Returns ("XX", "XX") if codes not set
        """
        # Get product with brand info
        result = self.supabase.table("products").select(
            "product_code, brand_id, brands(brand_code)"
        ).eq("id", str(product_id)).execute()

        if not result.data:
            return ("XX", "XX")

        product = result.data[0]
        product_code = product.get("product_code") or "XX"
        brand_code = "XX"

        if product.get("brands"):
            brand_code = product["brands"].get("brand_code") or "XX"

        return (brand_code.upper(), product_code.upper())

    def generate_ad_filename(
        self,
        brand_code: str,
        product_code: str,
        ad_run_id: UUID,
        ad_id: UUID,
        format_code: str,
        extension: str = "png"
    ) -> str:
        """
        Generate structured ad filename.

        Format: {brand_code}-{product_code}-{run_id_short}-{ad_id_short}-{format}.{ext}
        Example: WP-C3-a1b2c3-d4e5f6-SQ.png

        Args:
            brand_code: Brand code (e.g., "WP")
            product_code: Product code (e.g., "C3")
            ad_run_id: UUID of the ad run
            ad_id: UUID of the generated ad
            format_code: Format code (SQ, ST, PT, LS)
            extension: File extension (default: png)

        Returns:
            Structured filename
        """
        run_short = str(ad_run_id).replace("-", "")[:6]
        ad_short = str(ad_id).replace("-", "")[:6]

        return f"{brand_code}-{product_code}-{run_short}-{ad_short}-{format_code}.{extension}"

    # ============================================
    # IMAGE UPLOAD
    # ============================================

    async def upload_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        image_base64: str,
        # New optional params for structured naming
        product_id: Optional[UUID] = None,
        ad_id: Optional[UUID] = None,
        canvas_size: Optional[str] = None
    ) -> tuple[str, Optional[UUID]]:
        """
        Upload generated ad image to Supabase Storage.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            image_base64: Base64-encoded image
            product_id: Optional product UUID for structured naming
            ad_id: Optional pre-generated ad UUID (will generate one if not provided)
            canvas_size: Optional canvas size for format detection (e.g., "1080x1080px")

        Returns:
            Tuple of (storage_path, ad_id)
            - storage_path: Full path like "generated-ads/WP-C3-a1b2c3-d4e5f6-SQ.png"
            - ad_id: UUID to use for the generated_ads record
        """
        import asyncio
        import uuid as uuid_module

        image_data = base64.b64decode(image_base64)

        # Generate ad_id if not provided
        generated_ad_id = ad_id if ad_id else uuid_module.uuid4()

        # Use structured naming if product_id is provided
        if product_id and canvas_size:
            brand_code, product_code = await self.get_brand_product_codes(product_id)
            format_code = self.get_format_code(canvas_size)
            filename = self.generate_ad_filename(
                brand_code=brand_code,
                product_code=product_code,
                ad_run_id=ad_run_id,
                ad_id=generated_ad_id,
                format_code=format_code
            )
            # Store in a folder structure: {ad_run_id}/{filename}
            storage_path = f"{ad_run_id}/{filename}"
        else:
            # Fall back to legacy naming for backwards compatibility
            storage_path = f"{ad_run_id}/{prompt_index}.png"
            generated_ad_id = None  # Don't return ad_id for legacy mode

        # Run sync Supabase call in thread pool to avoid blocking event loop
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_("generated-ads").upload(
                storage_path,
                image_data,
                {"content-type": "image/png"}
            )
        )

        logger.info(f"Uploaded generated ad: {storage_path}")
        return (f"generated-ads/{storage_path}", generated_ad_id)

    async def download_image(self, storage_path: str) -> bytes:
        """
        Download image from Supabase Storage.

        Args:
            storage_path: Full storage path (e.g., "products/{id}/main.png")

        Returns:
            Binary image data
        """
        import asyncio

        # Parse bucket and path
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        # Run sync Supabase call in thread pool to avoid blocking event loop
        data = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        return data

    async def get_image_as_base64(self, storage_path: str) -> str:
        """
        Download image and convert to base64 string.

        Args:
            storage_path: Full storage path

        Returns:
            Base64-encoded image string
        """
        image_data = await self.download_image(storage_path)
        return base64.b64encode(image_data).decode('utf-8')

    # ============================================
    # AD RUN CRUD
    # ============================================

    async def create_ad_run(
        self,
        product_id: UUID,
        reference_ad_storage_path: str,
        project_id: Optional[UUID] = None,
        parameters: Optional[Dict] = None
    ) -> UUID:
        """
        Create new ad run record.

        Args:
            product_id: UUID of product
            reference_ad_storage_path: Storage path to reference ad
            project_id: Optional project UUID
            parameters: Optional generation parameters (num_variations, content_source, etc.)

        Returns:
            UUID of created ad run
        """
        data = {
            "product_id": str(product_id),
            "reference_ad_storage_path": reference_ad_storage_path,
            "status": "pending"
        }

        if project_id:
            data["project_id"] = str(project_id)

        if parameters:
            data["parameters"] = parameters

        result = self.supabase.table("ad_runs").insert(data).execute()
        ad_run_id = UUID(result.data[0]["id"])

        logger.info(f"Created ad run: {ad_run_id}")
        return ad_run_id

    async def update_ad_run(
        self,
        ad_run_id: UUID,
        status: Optional[str] = None,
        ad_analysis: Optional[Dict] = None,
        selected_hooks: Optional[List[Dict]] = None,
        selected_product_images: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        reference_ad_storage_path: Optional[str] = None
    ) -> None:
        """
        Update ad run with stage outputs.

        Args:
            ad_run_id: UUID of ad run
            status: New status
            ad_analysis: Ad analysis JSON
            selected_hooks: Selected hooks JSON array
            selected_product_images: Storage paths to product images
            error_message: Error message if failed
            reference_ad_storage_path: Storage path to reference ad
        """
        updates = {}

        if status:
            updates["status"] = status
        if ad_analysis:
            updates["ad_analysis"] = ad_analysis
        if selected_hooks:
            updates["selected_hooks"] = selected_hooks
        if selected_product_images:
            updates["selected_product_images"] = selected_product_images
        if error_message:
            updates["error_message"] = error_message
        if reference_ad_storage_path:
            updates["reference_ad_storage_path"] = reference_ad_storage_path

        if status == "complete":
            updates["completed_at"] = datetime.now().isoformat()

        self.supabase.table("ad_runs").update(updates).eq("id", str(ad_run_id)).execute()
        logger.info(f"Updated ad run {ad_run_id}: {list(updates.keys())}")

    async def get_product_id_for_run(self, ad_run_id: UUID) -> Optional[UUID]:
        """Get product_id for an ad run (needed for structured naming)."""
        try:
            result = self.supabase.table("ad_runs").select("product_id").eq("id", str(ad_run_id)).execute()
            if result.data and result.data[0].get("product_id"):
                return UUID(result.data[0]["product_id"])
            return None
        except Exception as e:
            logger.error(f"Failed to get product_id for run {ad_run_id}: {e}")
            return None

    # ============================================
    # GENERATED AD CRUD
    # ============================================

    async def save_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        prompt_text: str,
        prompt_spec: Dict,
        hook_id: Optional[UUID],
        hook_text: str,
        storage_path: str,
        claude_review: Optional[Dict] = None,
        gemini_review: Optional[Dict] = None,
        final_status: str = "pending",
        # Model tracking metadata
        model_requested: Optional[str] = None,
        model_used: Optional[str] = None,
        generation_time_ms: Optional[int] = None,
        generation_retries: Optional[int] = None,
        # Pre-generated ID for structured naming
        ad_id: Optional[UUID] = None
    ) -> UUID:
        """
        Save generated ad metadata to database.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            prompt_text: Full prompt sent to Nano Banana
            prompt_spec: JSON spec for image
            hook_id: UUID of hook used (None for benefit-based variations)
            hook_text: Adapted hook text
            storage_path: Storage path to generated image
            claude_review: Claude review JSON (optional)
            gemini_review: Gemini review JSON (optional)
            final_status: Status (pending/approved/rejected/flagged)
            model_requested: Model we requested for image generation
            model_used: Model that actually generated the image (may differ due to fallback)
            generation_time_ms: Time taken to generate the image
            generation_retries: Number of retries needed
            ad_id: Optional pre-generated UUID (for structured naming)

        Returns:
            UUID of generated ad record
        """
        # Determine if reviewers agree
        reviewers_agree = None
        if claude_review and gemini_review:
            claude_approved = claude_review.get("status") == "approved"
            gemini_approved = gemini_review.get("status") == "approved"
            reviewers_agree = (claude_approved == gemini_approved)

        data = {
            "ad_run_id": str(ad_run_id),
            "prompt_index": prompt_index,
            "prompt_text": prompt_text,
            "prompt_spec": prompt_spec,
            "hook_text": hook_text,
            "storage_path": storage_path,
            "claude_review": claude_review,
            "gemini_review": gemini_review,
            "reviewers_agree": reviewers_agree,
            "final_status": final_status
        }

        # Use pre-generated ID if provided (for structured naming)
        if ad_id is not None:
            data["id"] = str(ad_id)

        # Only include hook_id if it's a valid UUID (not for benefit-based variations)
        if hook_id is not None:
            data["hook_id"] = str(hook_id)

        # Add model tracking metadata if provided
        if model_requested is not None:
            data["model_requested"] = model_requested
        if model_used is not None:
            data["model_used"] = model_used
        if generation_time_ms is not None:
            data["generation_time_ms"] = generation_time_ms
        if generation_retries is not None:
            data["generation_retries"] = generation_retries

        result = self.supabase.table("generated_ads").insert(data).execute()
        generated_ad_id = UUID(result.data[0]["id"])

        # Log with model info if available
        model_info = f", model={model_used}" if model_used else ""
        logger.info(f"Saved generated ad: {generated_ad_id} (status: {final_status}{model_info})")
        return generated_ad_id

    # ============================================
    # SIZE VARIANTS
    # ============================================

    async def get_ad_for_variant(self, ad_id: UUID) -> Optional[Dict]:
        """
        Get ad data needed for creating size variants.

        Returns ad with storage_path, prompt_spec, hook_text, ad_run info.
        """
        try:
            result = self.supabase.table("generated_ads").select(
                "id, storage_path, prompt_spec, prompt_text, hook_text, hook_id, "
                "ad_run_id, ad_runs(product_id)"
            ).eq("id", str(ad_id)).execute()

            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get ad for variant: {e}")
            return None

    async def save_size_variant(
        self,
        parent_ad_id: UUID,
        ad_run_id: UUID,
        variant_size: str,
        storage_path: str,
        prompt_text: str,
        prompt_spec: Dict,
        hook_text: str,
        hook_id: Optional[UUID] = None,
        model_used: Optional[str] = None,
        generation_time_ms: Optional[int] = None,
        variant_id: Optional[UUID] = None
    ) -> UUID:
        """
        Save a size variant of an existing ad.

        Args:
            parent_ad_id: UUID of the source ad being resized
            ad_run_id: UUID of the ad run (same as parent)
            variant_size: Size label (e.g., "1:1", "4:5", "9:16")
            storage_path: Storage path to the new variant image
            prompt_text: Prompt used for generation
            prompt_spec: Updated prompt spec with new dimensions
            hook_text: Same hook text as parent
            hook_id: Same hook_id as parent (if applicable)
            model_used: Model that generated the variant
            generation_time_ms: Generation time
            variant_id: Optional pre-generated UUID (for structured naming)

        Returns:
            UUID of created variant ad
        """
        data = {
            "ad_run_id": str(ad_run_id),
            "parent_ad_id": str(parent_ad_id),
            "variant_size": variant_size,
            # prompt_index omitted - NULL for variants (CHECK constraint requires >= 1 for regular ads)
            "prompt_text": prompt_text,
            "prompt_spec": prompt_spec,
            "hook_text": hook_text,
            "storage_path": storage_path,
            "final_status": "approved"  # Auto-approved (inherits from approved source ad)
        }

        # Use pre-generated ID if provided (for structured naming)
        if variant_id:
            data["id"] = str(variant_id)
        if hook_id:
            data["hook_id"] = str(hook_id)
        if model_used:
            data["model_used"] = model_used
        if generation_time_ms:
            data["generation_time_ms"] = generation_time_ms

        result = self.supabase.table("generated_ads").insert(data).execute()
        variant_id = UUID(result.data[0]["id"])

        logger.info(f"Saved size variant: {variant_id} ({variant_size}) of parent {parent_ad_id}")
        return variant_id

    async def get_existing_variants(self, parent_ad_id: UUID) -> List[str]:
        """Get list of variant sizes that already exist for an ad."""
        try:
            result = self.supabase.table("generated_ads").select(
                "variant_size"
            ).eq("parent_ad_id", str(parent_ad_id)).execute()

            return [r["variant_size"] for r in result.data if r.get("variant_size")]
        except Exception as e:
            logger.error(f"Failed to get existing variants: {e}")
            return []

    # ============================================
    # SIZE VARIANT GENERATION
    # ============================================

    # Meta ad size configurations
    META_AD_SIZES = {
        "1:1": {"dimensions": "1080x1080", "name": "Square", "use_case": "Feed posts"},
        "4:5": {"dimensions": "1080x1350", "name": "Portrait", "use_case": "Feed (optimal)"},
        "9:16": {"dimensions": "1080x1920", "name": "Story", "use_case": "Stories, Reels"},
        "16:9": {"dimensions": "1920x1080", "name": "Landscape", "use_case": "Video, links"},
    }

    async def create_size_variant(
        self,
        source_ad_id: UUID,
        target_size: str,
        source_image_base64: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a size variant of an existing ad using Gemini Nano Banana Pro 3.

        Takes an approved ad and creates a version at a different aspect ratio,
        keeping all visual elements as similar as possible. Uses the same
        GeminiService.generate_image() method as main ad generation.

        Args:
            source_ad_id: UUID of the source ad to resize
            target_size: Target size ratio ("1:1", "4:5", "9:16", "16:9")
            source_image_base64: Optional pre-loaded source image (if not provided, will fetch)

        Returns:
            Dict with variant info: variant_id, storage_path, variant_size, generation_time_ms

        Raises:
            ValueError: If target_size is invalid or source ad not found
            Exception: If generation fails
        """
        from .gemini_service import GeminiService

        # Validate target size
        if target_size not in self.META_AD_SIZES:
            raise ValueError(f"Invalid target_size: {target_size}. Must be one of {list(self.META_AD_SIZES.keys())}")

        size_config = self.META_AD_SIZES[target_size]
        target_dimensions = size_config["dimensions"]

        logger.info(f"Creating {target_size} variant for ad {source_ad_id}")

        # Get source ad data
        source_ad = await self.get_ad_for_variant(source_ad_id)
        if not source_ad:
            raise ValueError(f"Source ad not found: {source_ad_id}")

        ad_run_id = source_ad.get("ad_run_id")
        original_spec = source_ad.get("prompt_spec", {})
        hook_text = source_ad.get("hook_text", "")
        hook_id = source_ad.get("hook_id")

        # Get source image if not provided
        if not source_image_base64:
            source_image_base64 = await self.get_image_as_base64(source_ad["storage_path"])

        # Build the resize prompt - includes canvas size in Technical Specifications
        # This follows the same pattern as generate_nano_banana_prompt

        # Add letterboxing instructions for tall aspect ratios (9:16) to avoid stretching
        letterbox_instructions = ""
        if target_size == "9:16":
            letterbox_instructions = """
**LETTERBOXING FOR TALL FORMAT (CRITICAL):**
- DO NOT stretch or distort the original ad content to fill the 9:16 canvas
- Use LETTERBOXING: place the original ad content in the center/upper portion
- Fill the extra vertical space (top and/or bottom) with colors that match the ad's color palette
- The letterbox areas should use solid colors or subtle gradients from the ad's existing colors
- Keep all original content at proper proportions - NO stretching or warping
- You may extend background colors/patterns naturally into the letterbox areas
- The content should look native to Stories/Reels format, not stretched
"""

        prompt_text = f"""Recreate this EXACT ad at a different canvas size.

**Technical Specifications:**
- Canvas: {target_dimensions}px ({target_size} aspect ratio)
- Target use case: {size_config['use_case']}
{letterbox_instructions}
**CRITICAL INSTRUCTIONS:**
- Keep ALL text exactly the same (same words, same fonts, same styling)
- DO NOT duplicate any text - each text element should appear only ONCE
- Keep ALL colors exactly the same
- Keep the product image(s) exactly the same - do not modify the product
- Keep the overall visual style and layout matching the original
- Only reposition/resize elements as needed to fit the new {target_size} canvas
- The hook text MUST be: "{hook_text}" (appear exactly ONCE, not repeated)
- Maintain the same visual hierarchy and composition
- Ensure text remains legible at the new dimensions

**Reference Image:**
The attached image is the source ad to recreate at {target_dimensions}px.

This is a SIZE VARIANT - the content should be IDENTICAL, only the canvas dimensions change to {target_dimensions}px ({target_size})."""

        # Create updated prompt spec for new dimensions
        variant_spec = original_spec.copy() if original_spec else {}
        variant_spec["canvas"] = {
            "dimensions": target_dimensions,
            "aspect_ratio": target_size
        }

        # Use GeminiService.generate_image() - same as main ad generation
        # This uses models/gemini-3-pro-image-preview with proper reference image handling
        gemini_service = GeminiService()

        # generate_image expects reference_images as a list
        generation_result = await gemini_service.generate_image(
            prompt=prompt_text,
            reference_images=[source_image_base64],
            return_metadata=True
        )

        generated_image_base64 = generation_result["image_base64"]
        generation_time_ms = generation_result.get("generation_time_ms", 0)
        model_used = generation_result.get("model_used", "models/gemini-3-pro-image-preview")

        # Generate variant ID upfront for structured naming
        import uuid as uuid_module
        variant_id = uuid_module.uuid4()

        # Get product_id from source ad's ad_run for structured naming
        product_id = None
        if source_ad.get("ad_runs") and source_ad["ad_runs"].get("product_id"):
            product_id = UUID(source_ad["ad_runs"]["product_id"])

        # Build structured filename or fall back to legacy format
        if product_id:
            brand_code, product_code = await self.get_brand_product_codes(product_id)
            format_code = self.get_format_code(size_config["dimensions"])
            filename = self.generate_ad_filename(
                brand_code=brand_code,
                product_code=product_code,
                ad_run_id=ad_run_id,
                ad_id=variant_id,
                format_code=format_code,
                extension="png"
            )
            storage_filename = f"{ad_run_id}/{filename}"
        else:
            # Fallback for ads without product_id
            storage_filename = f"{ad_run_id}/variant_{target_size.replace(':', 'x')}_{uuid_module.uuid4().hex[:8]}.png"

        image_data = base64.b64decode(generated_image_base64)
        self.supabase.storage.from_("generated-ads").upload(
            storage_filename,
            image_data,
            {"content-type": "image/png"}
        )

        full_storage_path = f"generated-ads/{storage_filename}"

        # Save to database with pre-generated variant_id
        variant_id = await self.save_size_variant(
            parent_ad_id=source_ad_id,
            ad_run_id=ad_run_id,
            variant_size=target_size,
            storage_path=full_storage_path,
            prompt_text=prompt_text,
            prompt_spec=variant_spec,
            hook_text=hook_text,
            hook_id=hook_id,
            model_used=model_used,
            generation_time_ms=generation_time_ms,
            variant_id=variant_id
        )

        logger.info(f"Created {target_size} variant: {variant_id} ({generation_time_ms}ms)")

        return {
            "variant_id": str(variant_id),
            "storage_path": full_storage_path,
            "variant_size": target_size,
            "generation_time_ms": generation_time_ms
        }

    async def create_size_variants_batch(
        self,
        source_ad_id: UUID,
        target_sizes: List[str],
        source_image_base64: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create multiple size variants for an ad.

        Args:
            source_ad_id: UUID of the source ad
            target_sizes: List of target sizes (e.g., ["1:1", "4:5"])
            source_image_base64: Optional pre-loaded source image

        Returns:
            Dict with "successful" and "failed" lists
        """
        results = {"successful": [], "failed": []}

        # Get source image once if not provided
        if not source_image_base64:
            source_ad = await self.get_ad_for_variant(source_ad_id)
            if source_ad:
                source_image_base64 = await self.get_image_as_base64(source_ad["storage_path"])

        for size in target_sizes:
            try:
                result = await self.create_size_variant(
                    source_ad_id=source_ad_id,
                    target_size=size,
                    source_image_base64=source_image_base64
                )
                results["successful"].append(result)
            except Exception as e:
                logger.error(f"Failed to create {size} variant: {e}")
                results["failed"].append({"size": size, "error": str(e)})

        return results

    # ============================================
    # AD DELETION
    # ============================================

    async def delete_generated_ad(
        self,
        ad_id: UUID,
        delete_variants: bool = True
    ) -> Dict[str, Any]:
        """
        Delete a generated ad and optionally its variants.

        Removes the ad from the database and deletes the image from storage.
        If delete_variants is True, also deletes any size variants of this ad.

        Args:
            ad_id: UUID of the ad to delete
            delete_variants: If True, also delete any variants of this ad

        Returns:
            Dict with deletion results:
            {
                "deleted_ad_id": str,
                "deleted_variants": int,
                "storage_deleted": bool
            }

        Raises:
            ValueError: If ad not found
        """
        import asyncio

        logger.info(f"Deleting ad {ad_id} (delete_variants={delete_variants})")

        # Get the ad to find storage path
        result = self.supabase.table("generated_ads").select(
            "id, storage_path, parent_ad_id"
        ).eq("id", str(ad_id)).execute()

        if not result.data:
            raise ValueError(f"Ad not found: {ad_id}")

        ad = result.data[0]
        storage_path = ad.get("storage_path", "")

        deleted_variants = 0

        # Delete variants first if requested
        if delete_variants:
            # Find all variants of this ad
            variants_result = self.supabase.table("generated_ads").select(
                "id, storage_path"
            ).eq("parent_ad_id", str(ad_id)).execute()

            for variant in variants_result.data:
                # Delete variant from storage
                variant_path = variant.get("storage_path", "")
                if variant_path:
                    try:
                        parts = variant_path.split("/", 1)
                        bucket = parts[0]
                        path = parts[1] if len(parts) > 1 else variant_path
                        await asyncio.to_thread(
                            lambda p=path: self.supabase.storage.from_(bucket).remove([p])
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete variant storage {variant_path}: {e}")

                # Delete variant from database
                self.supabase.table("generated_ads").delete().eq(
                    "id", variant["id"]
                ).execute()
                deleted_variants += 1
                logger.info(f"Deleted variant {variant['id']}")

        # Delete main ad from storage
        storage_deleted = False
        if storage_path:
            try:
                parts = storage_path.split("/", 1)
                bucket = parts[0]
                path = parts[1] if len(parts) > 1 else storage_path
                await asyncio.to_thread(
                    lambda: self.supabase.storage.from_(bucket).remove([path])
                )
                storage_deleted = True
                logger.info(f"Deleted storage: {storage_path}")
            except Exception as e:
                logger.warning(f"Failed to delete storage {storage_path}: {e}")

        # Delete ad from database
        self.supabase.table("generated_ads").delete().eq("id", str(ad_id)).execute()
        logger.info(f"Deleted ad {ad_id} from database")

        return {
            "deleted_ad_id": str(ad_id),
            "deleted_variants": deleted_variants,
            "storage_deleted": storage_deleted
        }

    # ============================================
    # TEMPLATE ANALYSIS CACHING
    # ============================================

    async def get_cached_template_analysis(
        self,
        storage_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached analysis for a template if it exists.

        Checks the ad_templates table for previously analyzed templates
        to skip expensive Opus 4.5 vision analysis (saves 4-8 minutes).

        Args:
            storage_path: Storage path of the template (e.g., "reference-ads/uuid_file.png")

        Returns:
            Dict with cached analysis or None if not cached:
            {
                "ad_analysis": {...},      # Stage 5 results
                "template_angle": {...},   # Stage 6a results
                "analysis_model": "...",
                "analysis_created_at": "..."
            }
        """
        try:
            result = self.supabase.table("ad_templates").select(
                "ad_analysis, template_angle, analysis_model, analysis_created_at"
            ).eq("storage_path", storage_path).execute()

            if result.data and len(result.data) > 0:
                template = result.data[0]
                # Only return if both analyses are cached
                if template.get("ad_analysis") and template.get("template_angle"):
                    logger.info(f"Found cached analysis for template: {storage_path}")
                    return {
                        "ad_analysis": template["ad_analysis"],
                        "template_angle": template["template_angle"],
                        "analysis_model": template.get("analysis_model"),
                        "analysis_created_at": template.get("analysis_created_at")
                    }

            logger.info(f"No cached analysis for template: {storage_path}")
            return None

        except Exception as e:
            # Table might not exist yet - that's OK
            logger.warning(f"Could not check template cache (table may not exist): {e}")
            return None

    async def save_template_analysis(
        self,
        storage_path: str,
        ad_analysis: Dict[str, Any],
        template_angle: Dict[str, Any],
        original_filename: Optional[str] = None,
        analysis_model: str = "claude-opus-4-5-20251101"
    ) -> bool:
        """
        Save template analysis to cache for future reuse.

        Stores the expensive Opus 4.5 vision analysis results so subsequent
        uses of the same template can skip Stages 5 and 6a.

        Args:
            storage_path: Storage path of the template
            ad_analysis: Results from analyze_reference_ad (Stage 5)
            template_angle: Results from extract_template_angle (Stage 6a)
            original_filename: Display name for the template
            analysis_model: Model used for analysis

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Extract original filename from storage path if not provided
            if not original_filename:
                # Format: reference-ads/uuid_original.jpg
                path_parts = storage_path.split("/")
                if len(path_parts) > 1:
                    filename = path_parts[-1]
                    # Remove UUID prefix if present
                    name_parts = filename.split("_", 1)
                    if len(name_parts) == 2 and len(name_parts[0]) == 36:
                        original_filename = name_parts[1]
                    else:
                        original_filename = filename

            # Upsert - insert or update if exists
            data = {
                "storage_path": storage_path,
                "original_filename": original_filename,
                "ad_analysis": ad_analysis,
                "template_angle": template_angle,
                "analysis_model": analysis_model,
                "analysis_created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            self.supabase.table("ad_templates").upsert(
                data,
                on_conflict="storage_path"
            ).execute()

            logger.info(f"Saved template analysis cache for: {storage_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save template analysis cache: {e}")
            return False

