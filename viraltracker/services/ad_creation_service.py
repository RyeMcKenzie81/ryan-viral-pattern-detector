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
        storage_path = f"{ad_run_id}_{filename}"

        self.supabase.storage.from_("reference-ads").upload(
            storage_path,
            image_data,
            {"content-type": "image/png"}
        )

        logger.info(f"Uploaded reference ad: {storage_path}")
        return f"reference-ads/{storage_path}"

    async def upload_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        image_base64: str
    ) -> str:
        """
        Upload generated ad image to Supabase Storage.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            image_base64: Base64-encoded image

        Returns:
            Storage path: "generated-ads/{ad_run_id}/{prompt_index}.png"
        """
        image_data = base64.b64decode(image_base64)
        storage_path = f"{ad_run_id}/{prompt_index}.png"

        self.supabase.storage.from_("generated-ads").upload(
            storage_path,
            image_data,
            {"content-type": "image/png"}
        )

        logger.info(f"Uploaded generated ad: {storage_path}")
        return f"generated-ads/{storage_path}"

    async def download_image(self, storage_path: str) -> bytes:
        """
        Download image from Supabase Storage.

        Args:
            storage_path: Full storage path (e.g., "products/{id}/main.png")

        Returns:
            Binary image data
        """
        # Parse bucket and path
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        data = self.supabase.storage.from_(bucket).download(path)
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
        project_id: Optional[UUID] = None
    ) -> UUID:
        """
        Create new ad run record.

        Args:
            product_id: UUID of product
            reference_ad_storage_path: Storage path to reference ad
            project_id: Optional project UUID

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
        error_message: Optional[str] = None
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

        if status == "complete":
            updates["completed_at"] = datetime.now().isoformat()

        self.supabase.table("ad_runs").update(updates).eq("id", str(ad_run_id)).execute()
        logger.info(f"Updated ad run {ad_run_id}: {list(updates.keys())}")

    # ============================================
    # GENERATED AD CRUD
    # ============================================

    async def save_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        prompt_text: str,
        prompt_spec: Dict,
        hook_id: UUID,
        hook_text: str,
        storage_path: str,
        claude_review: Optional[Dict] = None,
        gemini_review: Optional[Dict] = None,
        final_status: str = "pending"
    ) -> UUID:
        """
        Save generated ad metadata to database.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            prompt_text: Full prompt sent to Nano Banana
            prompt_spec: JSON spec for image
            hook_id: UUID of hook used
            hook_text: Adapted hook text
            storage_path: Storage path to generated image
            claude_review: Claude review JSON (optional)
            gemini_review: Gemini review JSON (optional)
            final_status: Status (pending/approved/rejected/flagged)

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
            "hook_id": str(hook_id),
            "hook_text": hook_text,
            "storage_path": storage_path,
            "claude_review": claude_review,
            "gemini_review": gemini_review,
            "reviewers_agree": reviewers_agree,
            "final_status": final_status
        }

        result = self.supabase.table("generated_ads").insert(data).execute()
        generated_ad_id = UUID(result.data[0]["id"])

        logger.info(f"Saved generated ad: {generated_ad_id} (status: {final_status})")
        return generated_ad_id
