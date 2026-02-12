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
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

from supabase import Client
from postgrest.exceptions import APIError

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
        disallowed_claims: Optional[List[str]] = None,
        required_disclaimers: Optional[str] = None,
        is_default: bool = False,
        notes: Optional[str] = None,
        mechanism_name: Optional[str] = None,
        mechanism_problem: Optional[str] = None,
        mechanism_solution: Optional[str] = None,
        sample_hooks: Optional[List[str]] = None,
        source: Optional[str] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
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
            disallowed_claims: Claims that must NOT appear in ads for this variant
            required_disclaimers: Legal disclaimers required for this variant
            is_default: Whether this is the default variant
            notes: Optional internal notes
            mechanism_name: Name of the unique mechanism
            mechanism_problem: UMP - the problem/root cause
            mechanism_solution: UMS - how the mechanism solves it
            sample_hooks: List of sample ad hooks
            source: How this variant was created (manual|ad_analysis|landing_page_analysis|meta_ad_analysis)
            source_metadata: Additional metadata about the source

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

        base_slug = self._slugify(name)

        data = {
            "product_id": str(product_id),
            "name": name,
            "landing_page_url": landing_page_url,
            "pain_points": pain_points or [],
            "desires_goals": desires_goals or [],
            "benefits": benefits or [],
            "disallowed_claims": disallowed_claims or [],
            "is_default": is_default,
            "is_active": True,
            "display_order": len(existing),
        }

        if target_audience:
            data["target_audience"] = target_audience
        if required_disclaimers:
            data["required_disclaimers"] = required_disclaimers
        if notes:
            data["notes"] = notes
        if mechanism_name:
            data["mechanism_name"] = mechanism_name
        if mechanism_problem:
            data["mechanism_problem"] = mechanism_problem
        if mechanism_solution:
            data["mechanism_solution"] = mechanism_solution
        if sample_hooks:
            data["sample_hooks"] = sample_hooks
        if source:
            data["source"] = source
        if source_metadata:
            data["source_metadata"] = source_metadata

        # Insert with retry on slug collision (race-safe)
        max_attempts = 10
        for attempt in range(max_attempts):
            if attempt == 0:
                data["slug"] = base_slug
            elif attempt < max_attempts - 1:
                data["slug"] = f"{base_slug}-{attempt}"
            else:
                data["slug"] = f"{base_slug}-{int(time.time()) % 10000}"

            try:
                result = self.supabase.table("product_offer_variants").insert(data).execute()
                variant_id = UUID(result.data[0]["id"])
                logger.info(f"Created offer variant: {name} for product {product_id}")
                return variant_id
            except APIError as e:
                if "product_offer_variants_product_id_slug_key" in str(e):
                    logger.info(f"Slug collision for '{name}', retrying with suffix -{attempt + 1}")
                    continue
                raise

        raise RuntimeError(f"Failed to create offer variant after {max_attempts} slug collision retries")

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
        needs_slug_retry = "name" in updates and "slug" not in updates
        if needs_slug_retry:
            base_slug = self._slugify(updates["name"])

        # Handle is_default specially
        if updates.get("is_default"):
            variant = self.get_offer_variant(variant_id)
            if variant:
                self._clear_defaults(UUID(variant["product_id"]))

        # Single write path with slug collision retry
        max_attempts = 10 if needs_slug_retry else 1
        for attempt in range(max_attempts):
            if needs_slug_retry:
                if attempt == 0:
                    updates["slug"] = base_slug
                elif attempt < max_attempts - 1:
                    updates["slug"] = f"{base_slug}-{attempt}"
                else:
                    updates["slug"] = f"{base_slug}-{int(time.time()) % 10000}"

            try:
                self.supabase.table("product_offer_variants").update(updates).eq(
                    "id", str(variant_id)
                ).execute()
                logger.info(f"Updated offer variant: {variant_id}")
                return True
            except APIError as e:
                if needs_slug_retry and "product_offer_variants_product_id_slug_key" in str(e):
                    logger.info(f"Slug collision on update for variant {variant_id}, retrying")
                    continue
                raise

        raise RuntimeError(f"Failed to update offer variant after {max_attempts} slug collision retries")

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
                disallowed_claims=v.get("disallowed_claims", []),
                required_disclaimers=v.get("required_disclaimers"),
                is_default=v.get("is_default", i == 0),  # First is default
                notes=v.get("notes"),
            )
            created_ids.append(variant_id)

        logger.info(f"Created {len(created_ids)} offer variants for product {product_id}")
        return created_ids

    # ============================================
    # LANDING PAGE ANALYSIS
    # ============================================

    def analyze_landing_page(self, url: str) -> Dict[str, Any]:
        """
        Scrape a landing page and extract offer variant fields.

        Uses WebScrapingService to extract structured data, then maps
        it to offer variant fields for review before saving.

        Args:
            url: Landing page URL to analyze

        Returns:
            Dict with extracted fields:
            - name: Suggested variant name (from headline)
            - pain_points: List of pain points addressed
            - desires_goals: List of desires/goals targeted
            - benefits: List of benefits highlighted
            - target_audience: Inferred target audience
            - raw_analysis: Full extraction for reference
            - success: Whether extraction succeeded
            - error: Error message if failed
        """
        from viraltracker.services.web_scraping_service import WebScrapingService

        extraction_prompt = """
        Analyze this landing page and extract marketing messaging data.

        Return a JSON object with these fields:

        1. "suggested_name": A short name for this offer angle (e.g., "Blood Pressure Support", "Hair Growth Formula")

        2. "pain_points": Array of 3-5 specific pain points or problems this page addresses.
           Focus on the customer's struggles, frustrations, or fears.
           Examples: "high blood pressure", "thinning hair", "low energy", "joint pain"

        3. "desires_goals": Array of 3-5 desires or goals the target customer wants to achieve.
           Focus on positive outcomes and aspirations.
           Examples: "heart health", "thick full hair", "all-day energy", "active lifestyle"

        4. "benefits": Array of 3-5 key benefits or claims made about the product.
           Focus on what the product does or provides.
           Examples: "supports healthy blood pressure", "promotes hair growth", "boosts energy naturally"

        5. "target_audience": A brief description of who this page targets (1-2 sentences).
           Example: "Adults 40+ concerned about cardiovascular health and looking for natural solutions"

        6. "headline": The main headline or value proposition from the page.

        Be specific and extract actual language/themes from the page, not generic descriptions.
        """

        try:
            scraper = WebScrapingService()
            result = scraper.extract_structured(url=url, prompt=extraction_prompt)

            if not result.success:
                logger.warning(f"Failed to analyze landing page {url}: {result.error}")
                return {
                    "success": False,
                    "error": result.error or "Extraction failed",
                    "name": "",
                    "pain_points": [],
                    "desires_goals": [],
                    "benefits": [],
                    "target_audience": "",
                }

            # Map extraction to offer variant fields
            data = result.data or {}
            return {
                "success": True,
                "error": None,
                "name": data.get("suggested_name", ""),
                "pain_points": data.get("pain_points", []),
                "desires_goals": data.get("desires_goals", []),
                "benefits": data.get("benefits", []),
                "target_audience": data.get("target_audience", ""),
                "raw_analysis": data,
            }

        except Exception as e:
            logger.error(f"Error analyzing landing page {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "name": "",
                "pain_points": [],
                "desires_goals": [],
                "benefits": [],
                "target_audience": "",
            }

    # ============================================
    # CREATE OR UPDATE (UPSERT BY URL)
    # ============================================

    def create_or_update_offer_variant(
        self,
        product_id: UUID,
        landing_page_url: str,
        **kwargs,
    ) -> Tuple[UUID, bool]:
        """
        Create or update an offer variant by product_id + landing_page_url.

        Checks for an existing variant matching the product and URL.
        If found, updates it. If not, creates a new one.

        Args:
            product_id: UUID of the product
            landing_page_url: Landing page URL to match
            **kwargs: All other params accepted by create_offer_variant

        Returns:
            Tuple of (variant_id, was_created)
        """
        existing = self.supabase.table("product_offer_variants").select("id, name").eq(
            "product_id", str(product_id)
        ).eq("landing_page_url", landing_page_url).limit(1).execute()

        if existing.data:
            variant_id = UUID(existing.data[0]["id"])
            # Build update dict from kwargs, excluding None values
            updates = {}
            for key in ["name", "pain_points", "desires_goals", "benefits",
                        "target_audience", "disallowed_claims", "required_disclaimers",
                        "notes", "mechanism_name", "mechanism_problem",
                        "mechanism_solution", "sample_hooks", "source", "source_metadata"]:
                if key in kwargs and kwargs[key] is not None:
                    updates[key] = kwargs[key]
            if "is_default" in kwargs:
                updates["is_default"] = kwargs["is_default"]

            if updates:
                self.update_offer_variant(variant_id, updates)

            logger.info(f"Updated existing offer variant: {variant_id} for URL {landing_page_url}")
            return variant_id, False
        else:
            name = kwargs.pop("name", landing_page_url.split("/")[-1] or "Unnamed Variant")
            variant_id = self.create_offer_variant(
                product_id=product_id,
                name=name,
                landing_page_url=landing_page_url,
                **kwargs,
            )
            return variant_id, True

    # ============================================
    # EXTRACT FROM LANDING PAGE (NO AI)
    # ============================================

    @staticmethod
    def _normalize_to_string_list(data: Any, max_items: int = 10) -> List[str]:
        """Flatten any input to a list of non-empty strings.

        Handles: List[str], List[Dict], Dict[str, List], str, None.
        """
        if data is None:
            return []
        if isinstance(data, str):
            return [data] if data.strip() else []
        if isinstance(data, dict):
            result = []
            for v in data.values():
                if isinstance(v, list):
                    result.extend(str(item) if not isinstance(item, str) else item for item in v)
                elif isinstance(v, str):
                    result.append(v)
            return [s for s in result if s.strip()][:max_items]
        if isinstance(data, list):
            result = []
            for item in data:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    for key in ("quote", "text", "explanation", "objection", "signal"):
                        if key in item and isinstance(item[key], str):
                            result.append(item[key])
                            break
                    else:
                        result.append(str(item))
                else:
                    result.append(str(item))
            return [s for s in result if s.strip()][:max_items]
        return []

    def extract_variant_from_landing_page(self, landing_page_id: UUID) -> Dict[str, Any]:
        """Extract offer variant fields from an already-analyzed brand_landing_pages record.

        Returns dict ready for review form. Does NOT create the variant.
        All list fields are normalized to List[str]. All scalar fields are str.

        Args:
            landing_page_id: UUID of the brand_landing_pages record

        Returns:
            Dict with extracted fields + success/error flags
        """
        result = self.supabase.table("brand_landing_pages").select("*").eq(
            "id", str(landing_page_id)
        ).execute()

        if not result.data:
            return {"success": False, "error": "Landing page not found"}

        page = result.data[0]

        if page.get("scrape_status") not in ("analyzed", "scraped"):
            return {"success": False, "error": f"Page not yet analyzed (status: {page.get('scrape_status', 'unknown')})"}

        normalize = self._normalize_to_string_list
        analysis_raw = page.get("analysis_raw") or {}
        belief_first = page.get("belief_first_analysis") or {}
        layers = belief_first.get("layers", {}) if isinstance(belief_first, dict) else {}
        persona_signals = analysis_raw.get("persona_signals") or {}
        copy_patterns = analysis_raw.get("copy_patterns") or {}

        # Build target audience from persona signals
        target_parts = []
        if isinstance(persona_signals, dict):
            demographics = persona_signals.get("target_demographics")
            if demographics:
                target_parts.append(str(demographics) if not isinstance(demographics, str) else demographics)
            psychographics = persona_signals.get("psychographics")
            if psychographics:
                target_parts.append(str(psychographics) if not isinstance(psychographics, str) else psychographics)
        target_audience = ". ".join(target_parts) if target_parts else ""

        # Mechanism from belief-first analysis
        unique_mechanism = layers.get("unique_mechanism", {}) if isinstance(layers, dict) else {}
        mechanism_name = ""
        mechanism_solution = ""
        if isinstance(unique_mechanism, dict):
            mechanism_name = unique_mechanism.get("explanation", "") or ""
            examples = unique_mechanism.get("examples", [])
            if examples and isinstance(examples, list):
                first = examples[0]
                mechanism_solution = first.get("quote", str(first)) if isinstance(first, dict) else str(first)

        problem_layer = layers.get("problem_pain_symptoms", {}) if isinstance(layers, dict) else {}
        mechanism_problem = ""
        if isinstance(problem_layer, dict):
            mechanism_problem = problem_layer.get("problem", "") or problem_layer.get("explanation", "") or ""

        # Suggested name
        name = page.get("page_title") or ""
        if not name:
            url = page.get("url", "")
            path = url.rstrip("/").split("/")[-1] if url else ""
            name = path.replace("-", " ").replace("_", " ").title() if path else "Unnamed Variant"

        extracted = {
            "success": True,
            "error": None,
            "name": name,
            "landing_page_url": page.get("url", ""),
            "product_id": page.get("product_id"),
            "pain_points": normalize(analysis_raw.get("pain_points_addressed")),
            "desires_goals": normalize(analysis_raw.get("desires_appealed_to")),
            "benefits": list(page.get("benefits") or []),
            "target_audience": target_audience,
            "mechanism_name": mechanism_name,
            "mechanism_problem": mechanism_problem,
            "mechanism_solution": mechanism_solution,
            "sample_hooks": normalize(copy_patterns.get("key_phrases"), max_items=5),
            "source": "landing_page_analysis",
            "source_metadata": {
                "landing_page_id": str(landing_page_id),
                "has_belief_first": bool(belief_first),
                "has_analysis_raw": bool(analysis_raw),
            },
        }

        return extracted
