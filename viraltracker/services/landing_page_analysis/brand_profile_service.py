"""
BrandProfileService — Aggregates brand/product data into a unified profile for blueprint generation.

Pulls from multiple tables to build a comprehensive brand context with gap detection.
Pattern follows product_context_service.py: sequential fetches with graceful fallbacks.

Data Sources:
- brands: name, voice/tone, colors, disallowed claims
- products: name, guarantee, ingredients, results_timeline, faq_items, social proof
- product_offer_variants: pain_points, desires_goals, benefits (for selected variant)
- product_mechanisms: mechanism library
- personas_4d: customer personas
- product_variants: pricing
- amazon_review_analysis: customer voice, quotes
- competitors: competitor USPs for differentiation
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BrandProfileService:
    """Aggregates brand data into a unified profile for Skill 5 blueprint generation.

    Usage:
        service = BrandProfileService()
        profile = service.get_brand_profile(brand_id, product_id, offer_variant_id=None)
        # profile["gaps"] contains missing fields with severity + instructions
    """

    def __init__(self, supabase=None):
        from viraltracker.core.database import get_supabase_client
        self.supabase = supabase or get_supabase_client()

    def get_brand_profile(
        self,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build unified brand profile with gap annotations.

        Args:
            brand_id: Brand UUID
            product_id: Product UUID
            offer_variant_id: Specific offer variant UUID (defaults to is_default=True)

        Returns:
            Dict with sections: brand_basics, product, mechanism, pain_points,
            social_proof, pricing, guarantee, claims, personas, competitors, gaps
        """
        brand = self._fetch_brand(brand_id)
        product = self._fetch_product(product_id)
        offer_variant = self._fetch_offer_variant(product_id, offer_variant_id)
        mechanisms = self._fetch_mechanisms_from_variants(product_id)
        personas = self._fetch_personas(product_id)
        pricing = self._fetch_pricing(product_id)
        reviews = self._fetch_review_analysis(product_id)
        competitors = self._fetch_competitors(brand_id)

        profile = {
            "brand_basics": {
                "name": brand.get("name", ""),
                "brand_code": brand.get("brand_code", ""),
                "voice_tone": brand.get("brand_voice_tone", ""),
                "colors": brand.get("brand_colors") or {},
                "description": brand.get("description", ""),
            },
            "product": {
                "name": product.get("name", ""),
                "target_audience": product.get("target_audience", ""),
                "key_benefits": product.get("key_benefits") or [],
                "key_problems_solved": product.get("key_problems_solved") or [],
                "features": product.get("features") or [],
            },
            "mechanism": self._build_mechanism_section(mechanisms, offer_variant),
            "pain_points": self._build_pain_points_section(offer_variant, personas),
            "social_proof": {
                "review_platforms": product.get("review_platforms") or {},
                "media_features": product.get("media_features") or [],
                "awards_certifications": product.get("awards_certifications") or [],
                "top_positive_quotes": reviews.get("top_positive_quotes") or [],
                "top_negative_quotes": reviews.get("top_negative_quotes") or [],
                "transformation_quotes": reviews.get("transformation_quotes") or [],
                "language_patterns": reviews.get("language_patterns") or {},
            },
            "pricing": pricing,
            "guarantee": {
                "text": product.get("guarantee", ""),
            },
            "claims": {
                "disallowed_claims": brand.get("disallowed_claims") or [],
                "prohibited_claims": product.get("prohibited_claims") or [],
                "required_disclaimers": product.get("required_disclaimers") or [],
            },
            "ingredients": product.get("ingredients") or [],
            "results_timeline": product.get("results_timeline") or [],
            "faq_items": product.get("faq_items") or [],
            "personas": [self._summarize_persona(p) for p in personas],
            "competitors": competitors,
            "offer_variant": {
                "name": offer_variant.get("name", ""),
                "landing_page_url": offer_variant.get("landing_page_url", ""),
                "pain_points": offer_variant.get("pain_points") or [],
                "desires_goals": offer_variant.get("desires_goals") or [],
                "benefits": offer_variant.get("benefits") or [],
            } if offer_variant else {},
        }

        profile["gaps"] = self._identify_gaps(profile)
        return profile

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    def _fetch_brand(self, brand_id: str) -> Dict[str, Any]:
        """Fetch brand basics."""
        try:
            result = self.supabase.table("brands").select(
                "id, name, brand_code, brand_voice_tone, brand_colors, "
                "disallowed_claims, description"
            ).eq("id", brand_id).single().execute()
            return result.data or {}
        except Exception as e:
            logger.error(f"Failed to fetch brand {brand_id}: {e}")
            return {}

    def _fetch_product(self, product_id: str) -> Dict[str, Any]:
        """Fetch product with all blueprint-relevant fields."""
        try:
            result = self.supabase.table("products").select(
                "id, name, target_audience, "
                "guarantee, ingredients, results_timeline, faq_items, "
                "prohibited_claims, required_disclaimers, "
                "review_platforms, media_features, awards_certifications, "
                "key_benefits, key_problems_solved, features"
            ).eq("id", product_id).single().execute()
            return result.data or {}
        except Exception as e:
            logger.error(f"Failed to fetch product {product_id}: {e}")
            return {}

    def _fetch_offer_variant(
        self, product_id: str, offer_variant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch the specified offer variant, or the default for the product."""
        try:
            if offer_variant_id:
                result = self.supabase.table("product_offer_variants").select(
                    "id, name, landing_page_url, pain_points, "
                    "desires_goals, benefits, target_audience, is_default"
                ).eq("id", offer_variant_id).single().execute()
                return result.data or {}

            # Fetch default variant
            result = self.supabase.table("product_offer_variants").select(
                "id, name, landing_page_url, pain_points, "
                "desires_goals, benefits, target_audience, is_default"
            ).eq("product_id", product_id).eq("is_default", True).limit(1).execute()

            if result.data:
                return result.data[0]

            # Fallback: first active variant
            result = self.supabase.table("product_offer_variants").select(
                "id, name, landing_page_url, pain_points, "
                "desires_goals, benefits, target_audience, is_default"
            ).eq("product_id", product_id).eq("is_active", True).limit(1).execute()

            return result.data[0] if result.data else {}
        except Exception as e:
            logger.debug(f"No offer variants found for product {product_id}: {e}")
            return {}

    def _fetch_mechanisms_from_variants(self, product_id: str) -> List[Dict[str, Any]]:
        """Fetch mechanism data from offer variants (mechanism fields live on product_offer_variants)."""
        try:
            result = self.supabase.table("product_offer_variants").select(
                "mechanism_name, mechanism_problem, mechanism_solution"
            ).eq("product_id", product_id).eq("is_active", True).execute()
            # Deduplicate by mechanism_name
            seen = set()
            mechanisms = []
            for row in (result.data or []):
                name = row.get("mechanism_name", "")
                if name and name not in seen:
                    seen.add(name)
                    mechanisms.append(row)
            return mechanisms
        except Exception as e:
            logger.debug(f"No mechanisms found for product {product_id}: {e}")
            return []

    def _fetch_personas(self, product_id: str) -> List[Dict[str, Any]]:
        """Fetch 4D personas for the product."""
        try:
            result = self.supabase.table("personas_4d").select(
                "id, name, snapshot, demographics, transformation_map, "
                "desires, pain_points, outcomes_jtbd, buying_objections, "
                "current_self_image, desired_self_image, "
                "activation_events, failed_solutions, core_values"
            ).eq("product_id", product_id).execute()
            return result.data or []
        except Exception as e:
            logger.debug(f"No personas found for product {product_id}: {e}")
            return []

    def _fetch_pricing(self, product_id: str) -> List[Dict[str, Any]]:
        """Fetch product variant pricing."""
        try:
            result = self.supabase.table("product_variants").select(
                "name, price, compare_at_price, variant_type, is_default"
            ).eq("product_id", product_id).eq("is_active", True).order(
                "display_order"
            ).execute()
            return result.data or []
        except Exception as e:
            logger.debug(f"No pricing found for product {product_id}: {e}")
            return []

    def _fetch_review_analysis(self, product_id: str) -> Dict[str, Any]:
        """Fetch Amazon review analysis for customer voice."""
        try:
            result = self.supabase.table("amazon_review_analysis").select(
                "pain_points, desires, language_patterns, objections, "
                "purchase_triggers, top_positive_quotes, top_negative_quotes, "
                "transformation_quotes"
            ).eq("product_id", product_id).order(
                "analyzed_at", desc=True
            ).limit(1).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.debug(f"No review analysis for product {product_id}: {e}")
            return {}

    def _fetch_competitors(self, brand_id: str) -> List[Dict[str, Any]]:
        """Fetch competitor summary for differentiation."""
        try:
            result = self.supabase.table("competitors").select(
                "id, name, website_url, notes"
            ).eq("brand_id", brand_id).limit(10).execute()
            return [
                {
                    "name": c.get("name", ""),
                    "website": c.get("website_url", ""),
                    "notes": c.get("notes", ""),
                }
                for c in (result.data or [])
            ]
        except Exception as e:
            logger.debug(f"No competitors found for brand {brand_id}: {e}")
            return []

    # ------------------------------------------------------------------
    # Data assembly helpers
    # ------------------------------------------------------------------

    def _build_mechanism_section(
        self,
        mechanisms: List[Dict[str, Any]],
        offer_variant: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build mechanism section from offer variant mechanism fields."""
        if mechanisms:
            primary = mechanisms[0]
            return {
                "name": primary.get("mechanism_name", ""),
                "root_cause": primary.get("mechanism_problem", ""),
                "solution": primary.get("mechanism_solution", ""),
                "all_mechanisms": [
                    {
                        "name": m.get("mechanism_name", ""),
                        "root_cause": m.get("mechanism_problem", ""),
                        "solution": m.get("mechanism_solution", ""),
                    }
                    for m in mechanisms
                ],
            }
        return {}

    def _build_pain_points_section(
        self,
        offer_variant: Dict[str, Any],
        personas: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge pain points from offer variant and personas."""
        pain_points = list(offer_variant.get("pain_points") or []) if offer_variant else []
        desires = list(offer_variant.get("desires_goals") or []) if offer_variant else []
        benefits = list(offer_variant.get("benefits") or []) if offer_variant else []

        # Merge persona pain points
        persona_pains = []
        persona_desires = []
        for p in personas:
            pp = p.get("pain_points") or {}
            if isinstance(pp, dict):
                for domain_pains in pp.values():
                    if isinstance(domain_pains, list):
                        persona_pains.extend(domain_pains)
            des = p.get("desires") or {}
            if isinstance(des, dict):
                for domain_des in des.values():
                    if isinstance(domain_des, list):
                        persona_desires.extend(domain_des)

        return {
            "pain_points": pain_points,
            "desires_goals": desires,
            "benefits": benefits,
            "persona_pain_points": persona_pains[:10],
            "persona_desires": persona_desires[:10],
        }

    def _summarize_persona(self, persona: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize a persona for the brand profile (avoid sending everything)."""
        return {
            "name": persona.get("name", ""),
            "snapshot": persona.get("snapshot", ""),
            "demographics": persona.get("demographics") or {},
            "core_values": persona.get("core_values") or [],
            "current_self_image": persona.get("current_self_image", ""),
            "desired_self_image": persona.get("desired_self_image", ""),
            "buying_objections": persona.get("buying_objections") or {},
            "activation_events": persona.get("activation_events") or [],
        }

    # ------------------------------------------------------------------
    # Lookup helpers (for UI dropdowns)
    # ------------------------------------------------------------------

    def get_products_for_brand(self, brand_id: str) -> List[Dict[str, Any]]:
        """Get products for a brand (for UI dropdowns)."""
        try:
            result = self.supabase.table("products").select(
                "id, name"
            ).eq("brand_id", brand_id).order("name").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch products for brand {brand_id}: {e}")
            return []

    def get_personas_for_product(self, product_id: str) -> List[Dict[str, Any]]:
        """Get personas for a product (for UI dropdowns).

        Returns:
            List of dicts with id, name, snapshot for each persona.
        """
        personas = self._fetch_personas(product_id)
        return [{"id": p["id"], "name": p["name"], "snapshot": p.get("snapshot", "")} for p in personas]

    def get_offer_variants(self, product_id: str) -> List[Dict[str, Any]]:
        """Get active offer variants for a product (for UI dropdowns)."""
        try:
            result = self.supabase.table("product_offer_variants").select(
                "id, name, is_default, is_active"
            ).eq("product_id", product_id).eq("is_active", True).order(
                "display_order"
            ).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch offer variants for product {product_id}: {e}")
            return []

    # ------------------------------------------------------------------
    # Gap detection
    # ------------------------------------------------------------------

    def _identify_gaps(self, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check profile sections for missing data, return structured gap list.

        Returns:
            List of dicts with: field, section, severity (critical|moderate|low),
            instruction (human-readable guidance)
        """
        gaps = []

        def _check(section: str, field: str, value, severity: str, instruction: str):
            is_empty = (
                value is None
                or value == ""
                or value == []
                or value == {}
                or (isinstance(value, list) and len(value) == 0)
                or (isinstance(value, dict) and len(value) == 0)
            )
            if is_empty:
                gaps.append({
                    "field": field,
                    "section": section,
                    "severity": severity,
                    "instruction": instruction,
                })

        bb = profile.get("brand_basics", {})
        _check("brand_basics", "voice_tone", bb.get("voice_tone"),
               "moderate", "CONTENT NEEDED: Define brand voice/tone in Brand Manager → Brand Settings.")

        prod = profile.get("product", {})
        _check("product", "name", prod.get("name"),
               "critical", "CONTENT NEEDED: Set product name in Brand Manager → Products.")

        mech = profile.get("mechanism", {})
        _check("mechanism", "name", mech.get("name"),
               "critical", "CONTENT NEEDED: Define a unique mechanism in Brand Manager → Offer Variants.")
        _check("mechanism", "root_cause", mech.get("root_cause"),
               "moderate", "CONTENT NEEDED: Define the root cause (mechanism problem) in Brand Manager → Offer Variants.")

        guar = profile.get("guarantee", {})
        _check("guarantee", "text", guar.get("text"),
               "moderate", "CONTENT NEEDED: Add guarantee text in Brand Manager → Product → Blueprint Fields.")

        _check("ingredients", "ingredients", profile.get("ingredients"),
               "moderate", "CONTENT NEEDED: Add ingredients in Brand Manager → Product → Blueprint Fields.")

        _check("results_timeline", "results_timeline", profile.get("results_timeline"),
               "moderate", "CONTENT NEEDED: Add results timeline in Brand Manager → Product → Blueprint Fields.")

        _check("faq_items", "faq_items", profile.get("faq_items"),
               "low", "CONTENT NEEDED: Add FAQ items in Brand Manager → Product → Blueprint Fields.")

        sp = profile.get("social_proof", {})
        _check("social_proof", "review_platforms", sp.get("review_platforms"),
               "moderate", "CONTENT NEEDED: Add verified review platform ratings in Brand Manager → Product.")
        _check("social_proof", "top_positive_quotes", sp.get("top_positive_quotes"),
               "moderate", "CONTENT NEEDED: Scrape Amazon reviews or add testimonials manually.")

        _check("pricing", "pricing", profile.get("pricing"),
               "moderate", "CONTENT NEEDED: Add product variants with pricing in Brand Manager → Products → Variants.")

        pp = profile.get("pain_points", {})
        _check("pain_points", "pain_points", pp.get("pain_points"),
               "critical", "CONTENT NEEDED: Add pain points to offer variant or build a persona.")

        _check("personas", "personas", profile.get("personas"),
               "moderate", "CONTENT NEEDED: Build a 4D persona in Brand Manager → Personas.")

        return gaps
