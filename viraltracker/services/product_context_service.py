"""
Product Context Service for Belief-First Reverse Engineer Pipeline.

Aggregates product truth from the database including:
- Basic product info (name, category, format)
- Ingredients with purpose and notes
- Allowed/disallowed claims
- Promise boundaries
- Pre-built mechanisms
- Proof assets
- Contraindications

This service produces ProductContext objects with evidence_status=OBSERVED
since all data comes from the verified database.
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

from viraltracker.core.database import get_supabase_client
from viraltracker.services.models import ProductContext

logger = logging.getLogger(__name__)


class ProductContextService:
    """
    Service for fetching comprehensive product context for belief analysis.

    Aggregates data from multiple tables to build a complete ProductContext
    that can be used to fill the Belief-First Canvas with OBSERVED data.
    """

    def __init__(self, supabase=None):
        """Initialize with optional Supabase client injection."""
        self.supabase = supabase or get_supabase_client()

    def get_product_context(self, product_id: UUID) -> Optional[ProductContext]:
        """
        Fetch complete product context for belief canvas assembly.

        Aggregates:
        - products table: name, category, format, macros
        - product_ingredients: ingredients with purpose
        - product_claims: allowed/disallowed claims
        - product_mechanisms: pre-built mechanism library
        - product_proof_assets: existing proof assets
        - product_variants: variant-specific info

        Args:
            product_id: UUID of the product

        Returns:
            ProductContext model or None if product not found
        """
        try:
            # Fetch base product
            product = self._fetch_product(product_id)
            if not product:
                logger.warning(f"Product {product_id} not found")
                return None

            # Fetch related data in parallel (where possible)
            ingredients = self._fetch_ingredients(product_id)
            claims = self._fetch_claims(product_id)
            mechanisms = self._fetch_mechanisms(product_id)
            proof_assets = self._fetch_proof_assets(product_id)

            # Build ProductContext
            return ProductContext(
                product_id=product_id,
                name=product.get("name", ""),
                category=product.get("category", ""),
                format=product.get("format"),
                macros=self._extract_macros(product),
                ingredients=ingredients,
                allowed_claims=claims.get("allowed", []),
                disallowed_claims=claims.get("disallowed", []),
                promise_boundary_default=product.get("promise_boundary"),
                mechanisms=mechanisms,
                proof_assets=proof_assets,
                contraindications=product.get("contraindications", []),
            )

        except Exception as e:
            logger.error(f"Failed to get product context for {product_id}: {e}")
            return None

    def _fetch_product(self, product_id: UUID) -> Optional[Dict[str, Any]]:
        """Fetch base product from products table."""
        try:
            result = self.supabase.table("products").select(
                "id, name, category, format, target_audience, "
                "current_offer, promise_boundary, contraindications, "
                "macros, brand_id, brands(id, name)"
            ).eq("id", str(product_id)).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch product {product_id}: {e}")
            return None

    def _fetch_ingredients(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch product ingredients with purpose and notes.

        Checks product_ingredients table if it exists, otherwise
        extracts from product macros/ingredients field.
        """
        try:
            # Try product_ingredients table first
            result = self.supabase.table("product_ingredients").select(
                "name, purpose, notes, quantity, unit"
            ).eq("product_id", str(product_id)).execute()

            if result.data:
                return [
                    {
                        "name": row.get("name", ""),
                        "purpose": row.get("purpose", ""),
                        "notes": row.get("notes", ""),
                        "quantity": row.get("quantity"),
                        "unit": row.get("unit"),
                    }
                    for row in result.data
                ]

            # Fallback: Check if product has ingredients in JSONB
            product = self._fetch_product(product_id)
            if product and product.get("ingredients"):
                return product.get("ingredients", [])

            return []
        except Exception as e:
            # Table might not exist yet - that's okay
            logger.debug(f"No ingredients found for {product_id}: {e}")
            return []

    def _fetch_claims(self, product_id: UUID) -> Dict[str, List[str]]:
        """
        Fetch allowed and disallowed claims for the product.

        Returns dict with 'allowed' and 'disallowed' lists.
        """
        claims = {"allowed": [], "disallowed": []}

        try:
            # Try product_claims table
            result = self.supabase.table("product_claims").select(
                "claim_text, claim_type, is_allowed"
            ).eq("product_id", str(product_id)).execute()

            if result.data:
                for row in result.data:
                    if row.get("is_allowed"):
                        claims["allowed"].append(row.get("claim_text", ""))
                    else:
                        claims["disallowed"].append(row.get("claim_text", ""))
                return claims

            # Fallback: Check product JSONB fields
            product = self._fetch_product(product_id)
            if product:
                if product.get("allowed_claims"):
                    claims["allowed"] = product.get("allowed_claims", [])
                if product.get("disallowed_claims"):
                    claims["disallowed"] = product.get("disallowed_claims", [])

            return claims
        except Exception as e:
            logger.debug(f"No claims found for {product_id}: {e}")
            return claims

    def _fetch_mechanisms(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch pre-built mechanism library entries for the product.

        These can be used to pre-populate UMP/UMS sections.
        """
        try:
            # Try product_mechanisms table
            result = self.supabase.table("product_mechanisms").select(
                "name, mechanism_type, description, root_cause, "
                "why_it_works, proof_types, status"
            ).eq("product_id", str(product_id)).execute()

            if result.data:
                return [
                    {
                        "name": row.get("name", ""),
                        "type": row.get("mechanism_type", ""),
                        "description": row.get("description", ""),
                        "root_cause": row.get("root_cause", ""),
                        "why_it_works": row.get("why_it_works", ""),
                        "proof_types": row.get("proof_types", []),
                        "status": row.get("status", "draft"),
                    }
                    for row in result.data
                ]

            # Fallback: Check belief_angles table for mechanism hints
            angle_result = self.supabase.table("belief_angles").select(
                "name, belief_statement, explanation"
            ).eq("product_id", str(product_id)).limit(10).execute()

            if angle_result.data:
                return [
                    {
                        "name": row.get("name", ""),
                        "type": "angle",
                        "description": row.get("belief_statement", ""),
                        "explanation": row.get("explanation", ""),
                    }
                    for row in angle_result.data
                ]

            return []
        except Exception as e:
            logger.debug(f"No mechanisms found for {product_id}: {e}")
            return []

    def _fetch_proof_assets(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch existing proof assets for the product.

        Includes testimonials, studies, data points, etc.
        """
        try:
            # Try product_proof_assets table
            result = self.supabase.table("product_proof_assets").select(
                "name, proof_type, content, source_url, "
                "persona_tags, outcome_type, verified"
            ).eq("product_id", str(product_id)).execute()

            if result.data:
                return [
                    {
                        "name": row.get("name", ""),
                        "type": row.get("proof_type", ""),
                        "content": row.get("content", ""),
                        "source_url": row.get("source_url"),
                        "persona_tags": row.get("persona_tags", []),
                        "outcome_type": row.get("outcome_type"),
                        "verified": row.get("verified", False),
                    }
                    for row in result.data
                ]

            # Fallback: Check verified_social_proof table
            social_result = self.supabase.table("verified_social_proof").select(
                "quote, source, proof_type, date_verified"
            ).eq("product_id", str(product_id)).execute()

            if social_result.data:
                return [
                    {
                        "name": "Social Proof",
                        "type": row.get("proof_type", "testimonial"),
                        "content": row.get("quote", ""),
                        "source_url": row.get("source"),
                        "verified": True,
                    }
                    for row in social_result.data
                ]

            return []
        except Exception as e:
            logger.debug(f"No proof assets found for {product_id}: {e}")
            return []

    def _extract_macros(self, product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract nutrition macros from product data.

        Handles both JSONB macros field and individual columns.
        """
        # Check JSONB macros field first
        if product.get("macros"):
            return product["macros"]

        # Check individual columns (some products might have these)
        macros = {}
        macro_fields = [
            "protein_g", "fiber_g", "sugar_g", "calories",
            "carbs_g", "fat_g", "sodium_mg"
        ]

        for field in macro_fields:
            if product.get(field) is not None:
                macros[field] = product[field]

        return macros if macros else None

    def get_product_with_brand(self, product_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetch product with brand info for context.

        Simpler version that just returns raw product + brand data.
        """
        try:
            result = self.supabase.table("products").select(
                "*, brands(id, name, category)"
            ).eq("id", str(product_id)).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch product with brand {product_id}: {e}")
            return None

    def get_products_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch all products for a brand.

        Used for UI dropdowns and batch operations.
        """
        try:
            result = self.supabase.table("products").select(
                "id, name, category, format, target_audience"
            ).eq("brand_id", str(brand_id)).order("name").execute()

            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch products for brand {brand_id}: {e}")
            return []
