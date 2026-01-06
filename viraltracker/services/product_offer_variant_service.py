"""
ProductOfferVariantService - Manages product offer variants.

Product Offer Variants link products to specific landing pages with messaging context.
Each variant includes:
- Landing page URL (required)
- Pain points specific to this offer
- Desires/goals specific to this offer
- Benefits/messaging bullets
- Target audience override (optional)

This enables a single product (e.g., Sea Moss) to have multiple marketing angles:
- Blood Pressure landing page with cardiovascular messaging
- Hair Loss landing page with hair growth messaging
- Skincare landing page with clear skin messaging

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

from supabase import Client

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ProductOfferVariantService:
    """
    Service for managing product offer variants.

    Provides methods for:
    - CRUD operations for offer variants
    - Default variant lookup and management
    - Validation for ad scheduling
    """

    def __init__(self):
        """Initialize ProductOfferVariantService."""
        self.supabase: Client = get_supabase_client()
        logger.info("ProductOfferVariantService initialized")

    # ============================================
    # HELPER METHODS
    # ============================================

    def _slugify(self, text: str) -> str:
        """
        Convert text to URL-safe slug.

        Args:
            text: Text to slugify

        Returns:
            URL-safe slug string
        """
        slug = text.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug

    # ============================================
    # CRUD OPERATIONS
    # ============================================

    def create_offer_variant(
        self,
        product_id: UUID,
        name: str,
        landing_page_url: str,
        pain_points: Optional[List[str]] = None,
        desires_goals: Optional[List[str]] = None,
        benefits: Optional[List[str]] = None,
        target_audience: Optional[str] = None,
        is_default: bool = False,
        notes: Optional[str] = None,
    ) -> UUID:
        """
        Create a new offer variant for a product.

        If this is the first variant for the product, it will be set as default.

        Args:
            product_id: UUID of the product
            name: Display name (e.g., "Blood Pressure Angle")
            landing_page_url: Required destination URL
            pain_points: List of pain points this offer addresses
            desires_goals: List of desires/goals this offer targets
            benefits: List of benefits to highlight
            target_audience: Optional target audience override
            is_default: Whether this is the default variant
            notes: Optional internal notes

        Returns:
            UUID of created offer variant
        """
        # Check if this is the first variant for the product
        existing = self.get_offer_variants(product_id)
        if not existing:
            is_default = True  # First variant is always default

        # If setting as default, clear other defaults
        if is_default and existing:
            self._clear_defaults(product_id)

        data = {
            "product_id": str(product_id),
            "name": name,
            "slug": self._slugify(name),
            "landing_page_url": landing_page_url,
            "pain_points": pain_points or [],
            "desires_goals": desires_goals or [],
            "benefits": benefits or [],
            "is_default": is_default,
            "is_active": True,
            "display_order": len(existing),
        }

        if target_audience:
            data["target_audience"] = target_audience
        if notes:
            data["notes"] = notes

        result = self.supabase.table("product_offer_variants").insert(data).execute()
        variant_id = UUID(result.data[0]["id"])

        logger.info(f"Created offer variant: {name} for product {product_id}")
        return variant_id

    def get_offer_variants(
        self,
        product_id: UUID,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all offer variants for a product.

        Args:
            product_id: UUID of the product
            active_only: If True, only return active variants

        Returns:
            List of offer variant dicts, ordered by display_order
        """
        query = (
            self.supabase.table("product_offer_variants")
            .select("*")
            .eq("product_id", str(product_id))
            .order("display_order")
        )

        if active_only:
            query = query.eq("is_active", True)

        result = query.execute()
        return result.data or []

    def get_offer_variant(self, variant_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get a single offer variant by ID.

        Args:
            variant_id: UUID of the offer variant

        Returns:
            Offer variant dict or None if not found
        """
        result = (
            self.supabase.table("product_offer_variants")
            .select("*")
            .eq("id", str(variant_id))
            .execute()
        )

        if result.data:
            return result.data[0]
        return None

    def get_default_offer_variant(self, product_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get the default offer variant for a product.

        If no default is set, returns the first active variant.

        Args:
            product_id: UUID of the product

        Returns:
            Default offer variant dict or None if no variants exist
        """
        # Try to get explicit default
        result = (
            self.supabase.table("product_offer_variants")
            .select("*")
            .eq("product_id", str(product_id))
            .eq("is_default", True)
            .eq("is_active", True)
            .execute()
        )

        if result.data:
            return result.data[0]

        # Fall back to first active variant
        variants = self.get_offer_variants(product_id, active_only=True)
        if variants:
            return variants[0]

        return None

    def update_offer_variant(
        self,
        variant_id: UUID,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Update an offer variant.

        Args:
            variant_id: UUID of the offer variant
            updates: Dict of fields to update

        Returns:
            True if successful
        """
        # Handle slug regeneration if name changed
        if "name" in updates and "slug" not in updates:
            updates["slug"] = self._slugify(updates["name"])

        # Handle is_default specially
        if updates.get("is_default"):
            variant = self.get_offer_variant(variant_id)
            if variant:
                self._clear_defaults(UUID(variant["product_id"]))

        self.supabase.table("product_offer_variants").update(updates).eq(
            "id", str(variant_id)
        ).execute()

        logger.info(f"Updated offer variant: {variant_id}")
        return True

    def set_as_default(self, variant_id: UUID) -> bool:
        """
        Set a variant as the default for its product.

        Clears default flag from other variants of the same product.

        Args:
            variant_id: UUID of the offer variant

        Returns:
            True if successful
        """
        variant = self.get_offer_variant(variant_id)
        if not variant:
            logger.warning(f"Offer variant not found: {variant_id}")
            return False

        # Clear other defaults
        self._clear_defaults(UUID(variant["product_id"]))

        # Set this one as default
        self.supabase.table("product_offer_variants").update(
            {"is_default": True}
        ).eq("id", str(variant_id)).execute()

        logger.info(f"Set offer variant {variant_id} as default")
        return True

    def _clear_defaults(self, product_id: UUID) -> None:
        """
        Clear default flag from all variants of a product.

        Args:
            product_id: UUID of the product
        """
        self.supabase.table("product_offer_variants").update(
            {"is_default": False}
        ).eq("product_id", str(product_id)).execute()

    def delete_offer_variant(self, variant_id: UUID) -> bool:
        """
        Delete an offer variant.

        Cannot delete if it's the only active variant for the product.

        Args:
            variant_id: UUID of the offer variant

        Returns:
            True if successful

        Raises:
            ValueError: If this is the only active variant
        """
        variant = self.get_offer_variant(variant_id)
        if not variant:
            logger.warning(f"Offer variant not found: {variant_id}")
            return False

        # Check if this is the only active variant
        all_variants = self.get_offer_variants(UUID(variant["product_id"]), active_only=True)
        if len(all_variants) <= 1:
            raise ValueError("Cannot delete the only offer variant for a product")

        # If deleting the default, set another as default
        if variant.get("is_default"):
            other_variants = [v for v in all_variants if v["id"] != str(variant_id)]
            if other_variants:
                self.set_as_default(UUID(other_variants[0]["id"]))

        self.supabase.table("product_offer_variants").delete().eq(
            "id", str(variant_id)
        ).execute()

        logger.info(f"Deleted offer variant: {variant_id}")
        return True

    def deactivate_offer_variant(self, variant_id: UUID) -> bool:
        """
        Deactivate an offer variant instead of deleting.

        Args:
            variant_id: UUID of the offer variant

        Returns:
            True if successful
        """
        return self.update_offer_variant(variant_id, {"is_active": False})

    # ============================================
    # VALIDATION
    # ============================================

    def validate_offer_variant_selection(
        self,
        product_id: UUID,
        offer_variant_id: Optional[UUID],
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validate offer variant selection for ad creation.

        Returns whether the selection is valid and the variant data if valid.

        Args:
            product_id: UUID of the product
            offer_variant_id: UUID of the selected offer variant (or None)

        Returns:
            Tuple of (is_valid, error_message, variant_data)
            - is_valid: True if selection is valid
            - error_message: Error message if invalid, empty string if valid
            - variant_data: Offer variant dict if valid, None if invalid
        """
        # Check if product has any offer variants
        variants = self.get_offer_variants(product_id, active_only=True)

        if not variants:
            # No variants defined - valid (use product.product_url)
            return True, "", None

        # Product has variants - selection is required
        if not offer_variant_id:
            return (
                False,
                f"Product has {len(variants)} offer variant(s). Please select one.",
                None,
            )

        # Validate selected variant exists and belongs to this product
        variant = self.get_offer_variant(offer_variant_id)
        if not variant:
            return False, f"Offer variant not found: {offer_variant_id}", None

        if variant["product_id"] != str(product_id):
            return False, "Offer variant does not belong to this product", None

        if not variant.get("is_active"):
            return False, "Selected offer variant is not active", None

        return True, "", variant

    def has_offer_variants(self, product_id: UUID) -> bool:
        """
        Check if a product has any active offer variants.

        Args:
            product_id: UUID of the product

        Returns:
            True if product has at least one active offer variant
        """
        variants = self.get_offer_variants(product_id, active_only=True)
        return len(variants) > 0

    # ============================================
    # BULK OPERATIONS
    # ============================================

    def create_offer_variants_from_list(
        self,
        product_id: UUID,
        variants: List[Dict[str, Any]],
    ) -> List[UUID]:
        """
        Create multiple offer variants from a list of dicts.

        Used during import from onboarding session.

        Args:
            product_id: UUID of the product
            variants: List of variant dicts with name, landing_page_url, etc.

        Returns:
            List of created variant UUIDs
        """
        created_ids = []
        for i, v in enumerate(variants):
            variant_id = self.create_offer_variant(
                product_id=product_id,
                name=v.get("name", f"Variant {i + 1}"),
                landing_page_url=v.get("landing_page_url", ""),
                pain_points=v.get("pain_points", []),
                desires_goals=v.get("desires_goals", []),
                benefits=v.get("benefits", []),
                target_audience=v.get("target_audience"),
                is_default=v.get("is_default", i == 0),  # First is default
                notes=v.get("notes"),
            )
            created_ids.append(variant_id)

        logger.info(f"Created {len(created_ids)} offer variants for product {product_id}")
        return created_ids
