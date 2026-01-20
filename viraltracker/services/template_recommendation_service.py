"""
TemplateRecommendationService - AI-powered template recommendations.

Provides template recommendations for products based on:
- Industry/niche matching
- Awareness level alignment
- Target audience fit
- Format suitability

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from supabase import Client

from ..core.database import get_supabase_client
from .models import (
    GenerateRecommendationsRequest,
    GenerateRecommendationsResult,
    RecommendationMethodology,
    ScoreBreakdown,
    TemplateRecommendationCandidate,
)

logger = logging.getLogger(__name__)


# =============================================================================
# AI Matching Prompt
# =============================================================================

AI_MATCH_PROMPT = """Analyze how well this template matches the product for Facebook ad creation.

PRODUCT INFO:
- Name: {product_name}
- Description: {product_description}
- Target Audience: {target_audience}
- Key Benefits: {benefits}
- Pain Points Addressed: {pain_points}

TEMPLATE INFO:
- Name: {template_name}
- Category: {template_category}
- Industry Niche: {template_niche}
- Target Sex: {template_target_sex}
- Awareness Level: {template_awareness} ({awareness_name})
- Description: {template_description}

Score this template's fit for the product on these dimensions (0.0-1.0 each):

1. NICHE_MATCH: How well does the template's industry/niche match the product category?
2. AWARENESS_MATCH: Is the template's awareness level appropriate for this product's marketing?
3. AUDIENCE_MATCH: Does the template's target audience align with the product's audience?
4. FORMAT_FIT: Is this template format (testimonial, before/after, etc.) suitable for showcasing this product?

Return ONLY valid JSON with this structure:
{{
  "niche_match": <0.0-1.0>,
  "awareness_match": <0.0-1.0>,
  "audience_match": <0.0-1.0>,
  "format_fit": <0.0-1.0>,
  "overall_score": <0.0-1.0>,
  "reasoning": "<1-2 sentence explanation>"
}}"""


class TemplateRecommendationService:
    """Service for template recommendations."""

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize TemplateRecommendationService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("TemplateRecommendationService initialized")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def get_recommendations(
        self,
        product_id: UUID,
        unused_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get saved recommendations for a product.

        Args:
            product_id: Product UUID
            unused_only: If True, only return recommendations not yet used
            limit: Max results

        Returns:
            List of recommendation records with template data
        """
        query = self.supabase.table("product_template_recommendations").select(
            "*, scraped_templates(id, name, category, storage_path, industry_niche, "
            "awareness_level, target_sex, description)"
        ).eq("product_id", str(product_id)).order("score", desc=True).limit(limit)

        if unused_only:
            query = query.eq("used", False)

        result = query.execute()
        return result.data or []

    def save_recommendations(
        self,
        product_id: UUID,
        template_ids: List[UUID],
        methodology: RecommendationMethodology,
        scores: Dict[str, Dict[str, Any]],
        offer_variant_id: Optional[UUID] = None,
        recommended_by: str = "system",
    ) -> int:
        """
        Save selected recommendations.

        Args:
            product_id: Product UUID
            template_ids: List of template UUIDs to recommend
            methodology: How recommendations were generated
            scores: Dict mapping template_id str to {score, breakdown, reasoning}
            offer_variant_id: Optional offer variant context
            recommended_by: Who created recommendations

        Returns:
            Number of recommendations saved
        """
        saved = 0
        for tid in template_ids:
            score_data = scores.get(str(tid), {})
            try:
                # Upsert: update if exists, insert if not
                data = {
                    "product_id": str(product_id),
                    "template_id": str(tid),
                    "offer_variant_id": str(offer_variant_id) if offer_variant_id else None,
                    "methodology": methodology.value,
                    "score": score_data.get("score", 0.5),
                    "score_breakdown": score_data.get("breakdown", {}),
                    "reasoning": score_data.get("reasoning", ""),
                    "recommended_at": datetime.utcnow().isoformat(),
                    "recommended_by": recommended_by,
                }

                self.supabase.table("product_template_recommendations").upsert(
                    data, on_conflict="product_id,template_id"
                ).execute()
                saved += 1

            except Exception as e:
                logger.error(f"Failed to save recommendation {tid}: {e}")

        logger.info(f"Saved {saved} recommendations for product {product_id}")
        return saved

    def remove_recommendation(self, recommendation_id: UUID) -> bool:
        """
        Remove a single recommendation.

        Args:
            recommendation_id: UUID of the recommendation record

        Returns:
            True if removed successfully
        """
        self.supabase.table("product_template_recommendations").delete().eq(
            "id", str(recommendation_id)
        ).execute()
        logger.info(f"Removed recommendation: {recommendation_id}")
        return True

    def remove_all_recommendations(self, product_id: UUID) -> int:
        """
        Remove all recommendations for a product.

        Args:
            product_id: Product UUID

        Returns:
            Number of recommendations removed
        """
        result = self.supabase.table("product_template_recommendations").delete().eq(
            "product_id", str(product_id)
        ).execute()
        count = len(result.data) if result.data else 0
        logger.info(f"Removed {count} recommendations for product {product_id}")
        return count

    def mark_as_used(self, product_id: UUID, template_id: UUID) -> bool:
        """
        Mark a recommendation as used (called after ad creation).

        Args:
            product_id: Product UUID
            template_id: Template UUID

        Returns:
            True if updated, False if not found
        """
        result = self.supabase.table("product_template_recommendations").select(
            "id, times_used"
        ).eq("product_id", str(product_id)).eq("template_id", str(template_id)).execute()

        if not result.data:
            return False

        rec = result.data[0]
        self.supabase.table("product_template_recommendations").update({
            "used": True,
            "times_used": (rec.get("times_used") or 0) + 1,
            "last_used_at": datetime.utcnow().isoformat(),
        }).eq("id", rec["id"]).execute()

        logger.info(f"Marked recommendation used: product={product_id}, template={template_id}")
        return True

    # =========================================================================
    # Recommendation Generation
    # =========================================================================

    async def generate_recommendations(
        self,
        request: GenerateRecommendationsRequest,
    ) -> GenerateRecommendationsResult:
        """
        Generate template recommendations using AI matching.

        Args:
            request: Generation request with product_id and methodology

        Returns:
            GenerateRecommendationsResult with candidate templates
        """
        start_time = time.time()

        # Get product data
        product = self._get_product_with_context(request.product_id, request.offer_variant_id)
        if not product:
            raise ValueError(f"Product not found: {request.product_id}")

        # Get all active templates
        templates = self._get_active_templates(limit=100)

        if not templates:
            logger.warning("No active templates found in library")
            return GenerateRecommendationsResult(
                product_id=request.product_id,
                product_name=product.get("name", "Unknown"),
                methodology=request.methodology,
                candidates=[],
                total_templates_analyzed=0,
                generation_time_ms=0,
            )

        # Score templates
        if request.methodology == RecommendationMethodology.AI_MATCH:
            candidates = await self._score_templates_ai(product, templates, request.limit)
        elif request.methodology == RecommendationMethodology.DIVERSITY:
            candidates = self._score_templates_diversity(product, templates, request.limit)
        else:
            raise ValueError(f"Unsupported methodology: {request.methodology}")

        elapsed_ms = int((time.time() - start_time) * 1000)

        return GenerateRecommendationsResult(
            product_id=request.product_id,
            product_name=product.get("name", "Unknown"),
            methodology=request.methodology,
            candidates=candidates,
            total_templates_analyzed=len(templates),
            generation_time_ms=elapsed_ms,
        )

    def _get_product_with_context(
        self,
        product_id: UUID,
        offer_variant_id: Optional[UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get product with optional offer variant context merged."""
        result = self.supabase.table("products").select("*").eq(
            "id", str(product_id)
        ).execute()

        if not result.data:
            return None

        product = result.data[0]

        # Merge offer variant data if specified
        if offer_variant_id:
            ov_result = self.supabase.table("product_offer_variants").select("*").eq(
                "id", str(offer_variant_id)
            ).execute()
            if ov_result.data:
                ov = ov_result.data[0]
                product["pain_points"] = ov.get("pain_points", [])
                product["desires_goals"] = ov.get("desires_goals", [])
                product["benefits"] = ov.get("benefits", []) or product.get("benefits", [])
                if ov.get("target_audience"):
                    product["target_audience"] = ov["target_audience"]

        return product

    def _get_active_templates(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get active templates from library."""
        result = self.supabase.table("scraped_templates").select(
            "id, name, category, storage_path, description, industry_niche, "
            "awareness_level, awareness_level_name, target_sex, times_used"
        ).eq("is_active", True).order("times_used", desc=True).limit(limit).execute()

        return result.data or []

    async def _score_templates_ai(
        self,
        product: Dict[str, Any],
        templates: List[Dict[str, Any]],
        limit: int,
    ) -> List[TemplateRecommendationCandidate]:
        """Score templates using AI analysis."""
        from .gemini_service import GeminiService

        gemini = GeminiService()
        candidates = []

        awareness_names = {
            1: "Unaware",
            2: "Problem Aware",
            3: "Solution Aware",
            4: "Product Aware",
            5: "Most Aware",
        }

        # Get product benefits and pain points
        benefits = product.get("benefits", [])
        if isinstance(benefits, str):
            benefits = [benefits]
        pain_points = product.get("pain_points", []) or product.get("key_problems_solved", [])
        if isinstance(pain_points, str):
            pain_points = [pain_points]

        for template in templates:
            try:
                prompt = AI_MATCH_PROMPT.format(
                    product_name=product.get("name", ""),
                    product_description=product.get("description", "")[:300],
                    target_audience=product.get("target_audience", "General"),
                    benefits=", ".join(benefits[:5]) if benefits else "Not specified",
                    pain_points=", ".join(pain_points[:5]) if pain_points else "Not specified",
                    template_name=template.get("name", ""),
                    template_category=template.get("category", "other"),
                    template_niche=template.get("industry_niche", "other"),
                    template_target_sex=template.get("target_sex", "unisex"),
                    template_awareness=template.get("awareness_level", 3),
                    awareness_name=awareness_names.get(template.get("awareness_level", 3), "Unknown"),
                    template_description=(template.get("description") or "")[:200],
                )

                # Use analyze_text with empty text since prompt is self-contained
                response = await gemini.analyze_text("", prompt)

                # Parse JSON response
                clean = response.strip()
                if clean.startswith("```"):
                    parts = clean.split("```")
                    if len(parts) >= 2:
                        clean = parts[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                clean = clean.strip()

                scores = json.loads(clean)

                candidate = TemplateRecommendationCandidate(
                    template_id=UUID(template["id"]),
                    template_name=template.get("name", "Unnamed"),
                    template_category=template.get("category", "other"),
                    storage_path=template.get("storage_path", ""),
                    score=float(scores.get("overall_score", 0.5)),
                    score_breakdown=ScoreBreakdown(
                        niche_match=float(scores.get("niche_match", 0.5)),
                        awareness_match=float(scores.get("awareness_match", 0.5)),
                        audience_match=float(scores.get("audience_match", 0.5)),
                        format_fit=float(scores.get("format_fit", 0.5)),
                    ),
                    reasoning=scores.get("reasoning", ""),
                    industry_niche=template.get("industry_niche"),
                    awareness_level=template.get("awareness_level"),
                    target_sex=template.get("target_sex"),
                )
                candidates.append(candidate)

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AI response for template {template.get('id')}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Failed to score template {template.get('id')}: {e}")
                continue

        # Sort by score and limit
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:limit]

    def _score_templates_diversity(
        self,
        product: Dict[str, Any],
        templates: List[Dict[str, Any]],
        limit: int,
    ) -> List[TemplateRecommendationCandidate]:
        """Score templates for diversity across categories."""
        # Group by category, pick top from each
        by_category: Dict[str, List] = {}
        for t in templates:
            cat = t.get("category", "other")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(t)

        candidates = []
        per_category = max(1, limit // len(by_category)) if by_category else limit

        for category, cat_templates in by_category.items():
            for t in cat_templates[:per_category]:
                candidates.append(TemplateRecommendationCandidate(
                    template_id=UUID(t["id"]),
                    template_name=t.get("name", "Unnamed"),
                    template_category=category,
                    storage_path=t.get("storage_path", ""),
                    score=0.7,  # Neutral score for diversity picks
                    score_breakdown=ScoreBreakdown(format_fit=1.0),
                    reasoning=f"Selected for format diversity ({category})",
                    industry_niche=t.get("industry_niche"),
                    awareness_level=t.get("awareness_level"),
                    target_sex=t.get("target_sex"),
                ))

        return candidates[:limit]

    # =========================================================================
    # Query Helpers (for Ad Creator/Scheduler integration)
    # =========================================================================

    def get_recommended_template_ids(
        self,
        product_id: UUID,
        unused_only: bool = False,
    ) -> List[UUID]:
        """
        Get list of recommended template IDs for filtering.

        Args:
            product_id: Product UUID
            unused_only: If True, only return unused recommendations

        Returns:
            List of template UUIDs
        """
        recs = self.get_recommendations(product_id, unused_only=unused_only)
        return [UUID(r["template_id"]) for r in recs]

    def is_template_recommended(self, product_id: UUID, template_id: UUID) -> bool:
        """
        Check if a template is recommended for a product.

        Args:
            product_id: Product UUID
            template_id: Template UUID

        Returns:
            True if template is recommended for this product
        """
        result = self.supabase.table("product_template_recommendations").select(
            "id"
        ).eq("product_id", str(product_id)).eq("template_id", str(template_id)).execute()
        return bool(result.data)

    def get_recommendation_count(self, product_id: UUID) -> Dict[str, int]:
        """
        Get recommendation counts for a product.

        Args:
            product_id: Product UUID

        Returns:
            Dict with total, used, and unused counts
        """
        result = self.supabase.table("product_template_recommendations").select(
            "used"
        ).eq("product_id", str(product_id)).execute()

        total = len(result.data) if result.data else 0
        used = sum(1 for r in (result.data or []) if r.get("used"))
        unused = total - used

        return {"total": total, "used": used, "unused": unused}
