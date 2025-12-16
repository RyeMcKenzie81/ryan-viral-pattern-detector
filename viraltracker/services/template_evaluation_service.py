"""
TemplateEvaluationService - AI-driven template phase eligibility scoring.

This service evaluates templates for Phase 1-2 belief testing suitability
using a 6-dimension rubric (D1-D6):

D1 - Belief Clarity Support (0-3): Can this template clearly express a single belief?
D2 - Neutrality (0-3): Is it free of sales bias, offers, urgency?
D3 - Reusability (0-3): Can it work across different angles?
D4 - Problem-Aware Entry (0-3): Does it support problem-aware audiences?
D5 - Slot Availability (0-3): Does it have clear text slots?
D6 - Compliance (pass/fail): No before/after, medical claims, guarantees?

Phase 1-2 Eligible: D6 pass AND total >= 12 AND D2 >= 2

Uses Gemini for vision-based evaluation of image templates (cheaper + better vision).
Falls back to Claude for text-only templates.
"""

import os
import json
import logging
import asyncio
import base64
import httpx
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client

from ..core.database import get_supabase_client
from .models import TemplateEvaluation
from .gemini_service import GeminiService

logger = logging.getLogger(__name__)

EVALUATION_PROMPT = """You are an expert at evaluating ad creative templates for belief-first testing.

Your task is to evaluate a template for Phase 1-2 eligibility using the following rubric.
The goal is to identify templates that can clearly express a SINGLE BELIEF without introducing confounding variables.

## Template Information
Name: {template_name}
Category: {template_category}
Description/Instructions: {template_description}
{additional_info}

## Evaluation Rubric (Score 0-3 for D1-D5, pass/fail for D6)

**D1 - Belief Clarity Support (0-3)**
Can this template clearly express a single belief/angle?
- 0: Template structure prevents clear belief expression (too busy, multiple focal points)
- 1: Belief can be expressed but competes with other elements
- 2: Belief can be clearly expressed with good prominence
- 3: Template is designed for single-belief clarity (clean layout, single message focus)

**D2 - Neutrality (0-3)**
Is it free of sales bias, offers, urgency cues?
- 0: Heavy sales/urgency elements baked in (countdown, "LIMITED", price callouts)
- 1: Some sales elements present but not dominant
- 2: Minimal sales bias, mostly informational
- 3: Completely neutral, no sales/urgency cues

**D3 - Reusability (0-3)**
Can it work across different angles without modification?
- 0: Very specific to one angle/product type
- 1: Works for some angles but not others
- 2: Works for most angles with minor adjustments
- 3: Highly versatile, works for any angle

**D4 - Problem-Aware Entry (0-3)**
Does it support problem-aware (not solution-aware) audiences?
- 0: Assumes product/solution awareness
- 1: Can work for problem-aware but not ideal
- 2: Good for problem-aware audiences
- 3: Perfect for introducing problems to unaware audiences

**D5 - Slot Availability (0-3)**
Does it have clear text slots for headline and primary text?
- 0: No clear text areas
- 1: Has text areas but poorly defined
- 2: Clear text slots, good sizing
- 3: Excellent text slots with clear hierarchy

**D6 - Compliance (pass/fail)**
Does the template avoid these disqualifying elements?
- Before/after transformation layouts
- Medical claim formatting (clinical trial style)
- Guarantee/warranty callouts baked in
- Testimonial-heavy layouts (quote cards with star ratings)
- Comparison tables

## Response Format
Return a JSON object with your scores and reasoning:
```json
{{
  "d1_belief_clarity": <0-3>,
  "d2_neutrality": <0-3>,
  "d3_reusability": <0-3>,
  "d4_problem_aware_entry": <0-3>,
  "d5_slot_availability": <0-3>,
  "d6_compliance_pass": <true/false>,
  "evaluation_notes": "<brief reasoning for scores, especially any concerns>"
}}
```

Return ONLY the JSON object, no other text."""


class TemplateEvaluationService:
    """Service for evaluating templates for phase eligibility."""

    def __init__(self):
        """
        Initialize TemplateEvaluationService.

        Uses GeminiService for vision-based evaluation (cheaper + better for images).
        """
        self.supabase: Client = get_supabase_client()

        # Initialize Gemini service for vision-based evaluation
        try:
            self.gemini = GeminiService()
            logger.info("TemplateEvaluationService initialized with Gemini")
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini service: {e}")
            self.gemini = None

    # ============================================
    # SINGLE TEMPLATE EVALUATION
    # ============================================

    def evaluate_template_for_phase(
        self,
        template_id: UUID,
        template_source: str,
        phase_id: int = 1
    ) -> Optional[TemplateEvaluation]:
        """
        Evaluate a single template for phase eligibility.

        Args:
            template_id: Template UUID
            template_source: 'ad_brief_templates' or 'scraped_templates'
            phase_id: Phase to evaluate for (default 1)

        Returns:
            TemplateEvaluation with scores, or None if evaluation failed
        """
        # Fetch template data
        template = self._get_template(template_id, template_source)
        if not template:
            logger.error(f"Template not found: {template_id} in {template_source}")
            return None

        # Run AI evaluation
        scores = self._evaluate_with_ai(template, template_source)
        if not scores:
            logger.error(f"AI evaluation failed for template {template_id}")
            return None

        # Create evaluation record
        evaluation = TemplateEvaluation(
            template_id=template_id,
            template_source=template_source,
            phase_id=phase_id,
            d1_belief_clarity=scores.get("d1_belief_clarity", 0),
            d2_neutrality=scores.get("d2_neutrality", 0),
            d3_reusability=scores.get("d3_reusability", 0),
            d4_problem_aware_entry=scores.get("d4_problem_aware_entry", 0),
            d5_slot_availability=scores.get("d5_slot_availability", 0),
            d6_compliance_pass=scores.get("d6_compliance_pass", False),
            evaluation_notes=scores.get("evaluation_notes", ""),
            evaluated_by="ai",
            evaluated_at=datetime.now()
        )

        # Store evaluation
        self._save_evaluation(evaluation)

        # Update template's cached score
        self._update_template_score(template_id, template_source, evaluation)

        return evaluation

    def _get_template(self, template_id: UUID, template_source: str) -> Optional[Dict[str, Any]]:
        """Fetch template data from appropriate table."""
        try:
            if template_source == "scraped_templates":
                # Get template with joined asset info
                result = self.supabase.table("scraped_templates").select(
                    "id, name, description, category, layout_analysis, awareness_level, industry_niche, "
                    "storage_path, thumbnail_path, source_asset_id"
                ).eq("id", str(template_id)).execute()

                if result.data:
                    template = result.data[0]
                    # Convert storage_path to public URL
                    storage_path = template.get("storage_path")
                    if storage_path:
                        template["image_url"] = self._storage_path_to_url(storage_path)

                    # Get asset_type from linked asset if available
                    source_asset_id = template.get("source_asset_id")
                    if source_asset_id:
                        asset_result = self.supabase.table("scraped_ad_assets").select(
                            "asset_type, original_url"
                        ).eq("id", str(source_asset_id)).execute()
                        if asset_result.data:
                            template["asset_type"] = asset_result.data[0].get("asset_type", "image")
                            # Use original_url as fallback if storage URL fails
                            if not template.get("image_url"):
                                template["image_url"] = asset_result.data[0].get("original_url")
                    else:
                        # Assume image if no linked asset
                        template["asset_type"] = "image"

                    return template
                return None
            else:
                result = self.supabase.table("ad_brief_templates").select(
                    "id, name, instructions"
                ).eq("id", str(template_id)).execute()

                return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch template {template_id}: {e}")
            return None

    def _storage_path_to_url(self, storage_path: str) -> Optional[str]:
        """Convert a Supabase storage path to a public URL."""
        try:
            if not storage_path:
                return None

            # Storage path format: "bucket/path/to/file"
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                logger.warning(f"Invalid storage path format: {storage_path}")
                return None

            bucket, path = parts
            return self.supabase.storage.from_(bucket).get_public_url(path)
        except Exception as e:
            logger.error(f"Failed to convert storage path to URL: {e}")
            return None

    def _evaluate_with_ai(self, template: Dict[str, Any], template_source: str) -> Optional[Dict[str, Any]]:
        """Run AI evaluation on template, using Gemini vision for image templates."""
        if not self.gemini:
            logger.error("Gemini service not initialized")
            return None

        # Build template info for prompt
        template_name = template.get("name", "Unknown")

        if template_source == "scraped_templates":
            template_category = template.get("category", "unknown")
            template_description = template.get("description", "No description available")
            additional_info = ""
            if template.get("layout_analysis"):
                additional_info += f"Layout Analysis: {json.dumps(template['layout_analysis'])}\n"
            if template.get("awareness_level"):
                additional_info += f"Awareness Level: {template['awareness_level']}\n"
            if template.get("industry_niche"):
                additional_info += f"Industry/Niche: {template['industry_niche']}\n"
        else:
            template_category = "manual"
            template_description = template.get("instructions", "No instructions available")
            additional_info = ""

        prompt = EVALUATION_PROMPT.format(
            template_name=template_name,
            template_category=template_category,
            template_description=template_description,
            additional_info=additional_info
        )

        try:
            # Check if we have an image to include (scraped templates)
            image_url = template.get("image_url")
            asset_type = template.get("asset_type", "image")

            if image_url and asset_type == "image":
                # Use Gemini vision: fetch image and analyze
                logger.info(f"Evaluating template with Gemini vision: {template_name}")

                # Fetch image and convert to base64
                image_base64 = self._fetch_image_as_base64(image_url)
                if not image_base64:
                    logger.warning(f"Could not fetch image, falling back to text-only: {image_url}")
                    # Fall back to text analysis
                    content = asyncio.run(self.gemini.analyze_text(
                        "",
                        prompt + "\n\n**Note: Image could not be loaded. Evaluate based on metadata only.**"
                    ))
                else:
                    # Vision-based evaluation
                    vision_prompt = prompt + "\n\n**IMPORTANT: Carefully examine the template image above. Look at:**\n- Layout and visual hierarchy\n- Text slot locations and sizes\n- Any baked-in sales elements, prices, or urgency cues\n- Compliance issues (before/after, medical claims, etc.)"
                    content = asyncio.run(self.gemini.analyze_image(image_base64, vision_prompt))
            else:
                # Text-only evaluation using Gemini
                logger.info(f"Evaluating template with Gemini text: {template_name}")
                content = asyncio.run(self.gemini.analyze_text("", prompt))

            # Clean markdown if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)
        except Exception as e:
            logger.error(f"AI evaluation failed: {e}")
            return None

    def _fetch_image_as_base64(self, url: str) -> Optional[str]:
        """Fetch image from URL and return as base64 string."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()
                return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to fetch image from {url}: {e}")
            return None

    def _save_evaluation(self, evaluation: TemplateEvaluation) -> bool:
        """Save evaluation to database."""
        try:
            data = {
                "template_id": str(evaluation.template_id),
                "template_source": evaluation.template_source,
                "phase_id": evaluation.phase_id,
                "d1_belief_clarity": evaluation.d1_belief_clarity,
                "d2_neutrality": evaluation.d2_neutrality,
                "d3_reusability": evaluation.d3_reusability,
                "d4_problem_aware_entry": evaluation.d4_problem_aware_entry,
                "d5_slot_availability": evaluation.d5_slot_availability,
                "d6_compliance_pass": evaluation.d6_compliance_pass,
                "evaluation_notes": evaluation.evaluation_notes,
                "evaluated_by": evaluation.evaluated_by,
            }

            # Upsert (update if exists for same template/source/phase)
            self.supabase.table("template_evaluations").upsert(
                data,
                on_conflict="template_id,template_source,phase_id"
            ).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to save evaluation: {e}")
            return False

    def _update_template_score(
        self,
        template_id: UUID,
        template_source: str,
        evaluation: TemplateEvaluation
    ) -> bool:
        """Update template's cached evaluation score."""
        try:
            table = template_source
            total_score = evaluation.computed_total_score
            eligible = evaluation.computed_eligible

            phase_tags = {
                "eligible_phases": [1, 2] if eligible else [],
                "total_score": total_score,
                "d1_belief_clarity": evaluation.d1_belief_clarity,
                "d2_neutrality": evaluation.d2_neutrality,
                "d3_reusability": evaluation.d3_reusability,
                "d4_problem_aware_entry": evaluation.d4_problem_aware_entry,
                "d5_slot_availability": evaluation.d5_slot_availability,
                "d6_compliance_pass": evaluation.d6_compliance_pass
            }

            self.supabase.table(table).update({
                "evaluation_score": total_score,
                "evaluation_notes": evaluation.evaluation_notes,
                "phase_tags": phase_tags,
                "evaluated_at": datetime.now().isoformat()
            }).eq("id", str(template_id)).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to update template score: {e}")
            return False

    # ============================================
    # BATCH EVALUATION
    # ============================================

    def batch_evaluate_templates(
        self,
        phase_id: int = 1,
        template_ids: Optional[List[UUID]] = None,
        template_source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate multiple templates for phase eligibility.

        Args:
            phase_id: Phase to evaluate for
            template_ids: Specific templates to evaluate (None = all)
            template_source: Filter by source ('ad_brief_templates' or 'scraped_templates')

        Returns:
            Dict with counts: {evaluated, eligible, failed}
        """
        results = {"evaluated": 0, "eligible": 0, "failed": 0, "evaluations": []}

        # Get templates to evaluate
        templates_to_eval = []

        if template_source in [None, "ad_brief_templates"]:
            query = self.supabase.table("ad_brief_templates").select("id").eq("active", True)
            if template_ids:
                query = query.in_("id", [str(t) for t in template_ids])
            result = query.execute()
            for t in result.data or []:
                templates_to_eval.append({"id": t["id"], "source": "ad_brief_templates"})

        if template_source in [None, "scraped_templates"]:
            query = self.supabase.table("scraped_templates").select("id").eq("is_active", True)
            if template_ids:
                query = query.in_("id", [str(t) for t in template_ids])
            result = query.execute()
            for t in result.data or []:
                templates_to_eval.append({"id": t["id"], "source": "scraped_templates"})

        logger.info(f"Evaluating {len(templates_to_eval)} templates for phase {phase_id}")

        # Evaluate each template
        for template_info in templates_to_eval:
            try:
                evaluation = self.evaluate_template_for_phase(
                    UUID(template_info["id"]),
                    template_info["source"],
                    phase_id
                )
                if evaluation:
                    results["evaluated"] += 1
                    if evaluation.computed_eligible:
                        results["eligible"] += 1
                    results["evaluations"].append({
                        "template_id": template_info["id"],
                        "source": template_info["source"],
                        "total_score": evaluation.computed_total_score,
                        "eligible": evaluation.computed_eligible
                    })
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Failed to evaluate template {template_info['id']}: {e}")
                results["failed"] += 1

        logger.info(f"Batch evaluation complete: {results['evaluated']} evaluated, {results['eligible']} eligible, {results['failed']} failed")
        return results

    # ============================================
    # RETRIEVAL
    # ============================================

    def get_evaluation(
        self,
        template_id: UUID,
        template_source: str,
        phase_id: int = 1
    ) -> Optional[TemplateEvaluation]:
        """
        Get existing evaluation for a template.

        Args:
            template_id: Template UUID
            template_source: 'ad_brief_templates' or 'scraped_templates'
            phase_id: Phase to get evaluation for

        Returns:
            TemplateEvaluation or None if not evaluated
        """
        try:
            result = self.supabase.table("template_evaluations").select("*").eq(
                "template_id", str(template_id)
            ).eq("template_source", template_source).eq("phase_id", phase_id).execute()

            if result.data:
                return TemplateEvaluation(**result.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get evaluation: {e}")
            return None

    def get_phase_eligible_templates(
        self,
        brand_id: Optional[UUID] = None,
        phase_id: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Get templates that are eligible for a specific phase.

        Args:
            brand_id: Optional brand filter
            phase_id: Phase to filter for (default 1)

        Returns:
            List of eligible templates with their evaluation data
        """
        eligible_templates = []

        try:
            # Get manual templates with eligible phase_tags
            query = self.supabase.table("ad_brief_templates").select(
                "id, name, instructions, evaluation_score, phase_tags"
            ).eq("active", True)

            if brand_id:
                # Brand-specific or global templates
                query = query.or_(f"brand_id.eq.{brand_id},brand_id.is.null")

            result = query.execute()

            for t in result.data or []:
                phase_tags = t.get("phase_tags", {}) or {}
                eligible_phases = phase_tags.get("eligible_phases", [])
                if phase_id in eligible_phases:
                    t["source"] = "manual"
                    t["eligible"] = True
                    eligible_templates.append(t)

            # Get scraped templates with eligible phase_tags
            result = self.supabase.table("scraped_templates").select(
                "id, name, description, category, evaluation_score, phase_tags"
            ).eq("is_active", True).execute()

            for t in result.data or []:
                phase_tags = t.get("phase_tags", {}) or {}
                eligible_phases = phase_tags.get("eligible_phases", [])
                if phase_id in eligible_phases:
                    t["source"] = "scraped"
                    t["eligible"] = True
                    eligible_templates.append(t)

        except Exception as e:
            logger.error(f"Failed to get eligible templates: {e}")

        return eligible_templates

    def get_all_templates_with_eligibility(
        self,
        brand_id: Optional[UUID] = None,
        phase_id: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Get all templates with their eligibility status.

        Args:
            brand_id: Optional brand filter
            phase_id: Phase to check eligibility for

        Returns:
            List of all templates with eligibility info
        """
        all_templates = []

        try:
            # Manual templates
            query = self.supabase.table("ad_brief_templates").select(
                "id, name, instructions, evaluation_score, evaluation_notes, phase_tags, evaluated_at"
            ).eq("active", True)

            if brand_id:
                query = query.or_(f"brand_id.eq.{brand_id},brand_id.is.null")

            result = query.execute()

            for t in result.data or []:
                phase_tags = t.get("phase_tags", {}) or {}
                eligible_phases = phase_tags.get("eligible_phases", [])
                t["source"] = "manual"
                t["eligible"] = phase_id in eligible_phases
                t["evaluated"] = t.get("evaluated_at") is not None
                all_templates.append(t)

            # Scraped templates
            result = self.supabase.table("scraped_templates").select(
                "id, name, description, category, evaluation_score, evaluation_notes, phase_tags, evaluated_at"
            ).eq("is_active", True).execute()

            for t in result.data or []:
                phase_tags = t.get("phase_tags", {}) or {}
                eligible_phases = phase_tags.get("eligible_phases", [])
                t["source"] = "scraped"
                t["eligible"] = phase_id in eligible_phases
                t["evaluated"] = t.get("evaluated_at") is not None
                all_templates.append(t)

        except Exception as e:
            logger.error(f"Failed to get all templates: {e}")

        return all_templates
