"""
PersonaService - 4D Persona CRUD and AI generation.

This service handles:
- Creating, updating, deleting 4D personas
- AI-assisted persona generation from product data
- Linking personas to products
- Exporting personas to copy brief format

Uses DIRECT SERVICE CALLS (not pydantic-graph) because:
- User-driven workflow (forms, button clicks)
- Interactive with user review/editing
- Short, synchronous operations
"""

import logging
import json
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.config import Config
from pydantic_ai import Agent
import asyncio


from ..core.database import get_supabase_client
from .agent_tracking import run_agent_with_tracking
from .usage_tracker import UsageTracker
from .models import (
    Persona4D, PersonaSummary, PersonaType, SourceType,
    Demographics, TransformationMap, SocialRelations, DomainSentiment,
    DesireInstance, CopyBrief, ProductPersonaLink
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for Structured AI Output
# ============================================================================

class DesireItemResponse(BaseModel):
    """A single desire item from AI."""
    text: str
    source: str = "ai_generated"


class DesiresResponse(BaseModel):
    """Desires section from AI response."""
    care_protection: List[DesireItemResponse] = Field(default_factory=list)
    social_approval: List[DesireItemResponse] = Field(default_factory=list)
    freedom_from_fear: List[DesireItemResponse] = Field(default_factory=list)


class DemographicsResponse(BaseModel):
    """Demographics from AI response."""
    age_range: str = ""
    gender: str = ""
    location: str = ""
    income_level: str = ""
    education: str = ""
    occupation: str = ""
    family_status: str = ""


class TransformationMapResponse(BaseModel):
    """Before/after transformation from AI response."""
    before: List[str] = Field(default_factory=list)
    after: List[str] = Field(default_factory=list)


class SocialRelationsResponse(BaseModel):
    """Social relations from AI response."""
    want_to_impress: List[str] = Field(default_factory=list)
    fear_judged_by: List[str] = Field(default_factory=list)
    influence_decisions: List[str] = Field(default_factory=list)


class DomainPainPointsResponse(BaseModel):
    """Pain points by domain from AI response."""
    emotional: List[str] = Field(default_factory=list)
    social: List[str] = Field(default_factory=list)
    functional: List[str] = Field(default_factory=list)


class DomainOutcomesResponse(BaseModel):
    """Outcomes/JTBD by domain from AI response."""
    emotional: List[str] = Field(default_factory=list)
    social: List[str] = Field(default_factory=list)
    functional: List[str] = Field(default_factory=list)


class DomainObjectionsResponse(BaseModel):
    """Buying objections by domain from AI response."""
    emotional: List[str] = Field(default_factory=list)
    social: List[str] = Field(default_factory=list)
    functional: List[str] = Field(default_factory=list)


class PersonaAIResponse(BaseModel):
    """
    Structured output model for AI persona generation.
    Using Pydantic model as result_type eliminates JSON parsing errors.
    """
    name: str = Field(description="Descriptive persona name")
    snapshot: str = Field(description="2-3 sentence big picture description")

    demographics: DemographicsResponse = Field(default_factory=DemographicsResponse)
    transformation_map: TransformationMapResponse = Field(default_factory=TransformationMapResponse)
    desires: DesiresResponse = Field(default_factory=DesiresResponse)

    self_narratives: List[str] = Field(default_factory=list)
    current_self_image: str = ""
    desired_self_image: str = ""
    identity_artifacts: List[str] = Field(default_factory=list)

    social_relations: SocialRelationsResponse = Field(default_factory=SocialRelationsResponse)

    worldview: str = ""
    core_values: List[str] = Field(default_factory=list)
    allergies: Dict[str, str] = Field(default_factory=dict)

    pain_points: DomainPainPointsResponse = Field(default_factory=DomainPainPointsResponse)
    outcomes_jtbd: DomainOutcomesResponse = Field(default_factory=DomainOutcomesResponse)

    failed_solutions: List[str] = Field(default_factory=list)
    buying_objections: DomainObjectionsResponse = Field(default_factory=DomainObjectionsResponse)
    familiar_promises: List[str] = Field(default_factory=list)

    activation_events: List[str] = Field(default_factory=list)
    decision_process: str = ""
    current_workarounds: List[str] = Field(default_factory=list)

    emotional_risks: List[str] = Field(default_factory=list)
    barriers_to_behavior: List[str] = Field(default_factory=list)


def repair_json(json_str: str) -> str:
    """
    Attempt to repair common JSON syntax errors from LLM output.

    Handles:
    - Trailing commas before ] or }
    - Missing commas between elements
    - Unescaped quotes in strings
    """
    import re

    # Remove trailing commas before ] or }
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    # Try to fix missing commas between string values
    # Pattern: "value" "next_key" -> "value", "next_key"
    json_str = re.sub(r'"\s*\n\s*"', '",\n"', json_str)

    # Pattern: } { or ] { -> }, { or ], {
    json_str = re.sub(r'}\s*{', '}, {', json_str)
    json_str = re.sub(r']\s*{', '], {', json_str)

    # Pattern: } [ -> }, [
    json_str = re.sub(r'}\s*\[', '}, [', json_str)

    # Pattern: ] [ -> ], [
    json_str = re.sub(r']\s*\[', '], [', json_str)

    # Pattern: "value" [ or "value" { -> "value": [ or "value": {
    # This catches cases where : was forgotten
    json_str = re.sub(r'"\s+(\[{)', r'": \1', json_str)

    return json_str


def parse_llm_json(response_text: str) -> dict:
    """
    Parse JSON from LLM response with repair attempts.

    Args:
        response_text: Raw LLM response that should contain JSON

    Returns:
        Parsed JSON as dict

    Raises:
        ValueError: If JSON cannot be parsed after repair attempts
    """
    # Clean markdown code blocks
    clean_response = response_text.strip()
    if clean_response.startswith("```"):
        lines = clean_response.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_response = "\n".join(lines)
    clean_response = clean_response.strip()

    # First attempt: parse as-is
    try:
        return json.loads(clean_response)
    except json.JSONDecodeError as first_error:
        logger.warning(f"Initial JSON parse failed: {first_error}")

    # Second attempt: repair and parse
    try:
        repaired = repair_json(clean_response)
        return json.loads(repaired)
    except json.JSONDecodeError as second_error:
        logger.warning(f"Repaired JSON parse also failed: {second_error}")

    # Third attempt: try to extract JSON object from response
    # Sometimes LLMs add text before/after the JSON
    try:
        # Find the first { and last }
        start_idx = clean_response.find('{')
        end_idx = clean_response.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_subset = clean_response[start_idx:end_idx + 1]
            repaired_subset = repair_json(json_subset)
            return json.loads(repaired_subset)
    except json.JSONDecodeError:
        pass

    # All attempts failed
    raise ValueError(f"Could not parse JSON after repair attempts. Original error: {first_error}")


# AI Prompt for generating 4D persona from product data
PERSONA_GENERATION_PROMPT = """You are an expert at creating detailed customer personas for copywriting.

Given the following product/brand information and ad insights, generate a comprehensive 4D persona for their target customer.

PRODUCT/BRAND INFO:
{product_info}

EXISTING TARGET AUDIENCE (if any):
{target_audience}

AD INSIGHTS (extracted from analyzed ads - use these to inform the persona):
{ad_insights}

Generate a detailed 4D persona with ALL of the following sections. Be specific and use language the customer would actually use.
Use the hooks, benefits, and pain points from the ad insights to inform the persona's desires, pain points, and language.

Return JSON with this structure:
{{
  "name": "Descriptive persona name (e.g., 'Worried First-Time Dog Mom')",
  "snapshot": "2-3 sentence big picture description",

  "demographics": {{
    "age_range": "e.g., 28-45",
    "gender": "male/female/any",
    "location": "e.g., Suburban USA",
    "income_level": "e.g., Middle to upper-middle class",
    "education": "e.g., College educated",
    "occupation": "e.g., Professional, works from home",
    "family_status": "e.g., Married with young children"
  }},

  "transformation_map": {{
    "before": ["Current frustration 1", "Current limitation 2"],
    "after": ["Desired outcome 1", "Desired state 2"]
  }},

  "desires": {{
    "care_protection": [
      {{"text": "I want to give my dog the absolute best", "source": "ai_generated"}}
    ],
    "social_approval": [
      {{"text": "I want the vet to say I'm doing a great job", "source": "ai_generated"}}
    ],
    "freedom_from_fear": [
      {{"text": "I don't want to worry about my pet's health", "source": "ai_generated"}}
    ]
  }},

  "self_narratives": [
    "Because I am a responsible pet owner, I research everything before buying"
  ],
  "current_self_image": "How they see themselves now",
  "desired_self_image": "How they want to be seen/who they want to become",
  "identity_artifacts": ["Brands/products associated with their desired identity"],

  "social_relations": {{
    "want_to_impress": ["Their vet", "Other pet owners"],
    "fear_judged_by": ["Other pet parents"],
    "influence_decisions": ["Pet influencers", "Facebook groups"]
  }},

  "worldview": "Their general interpretation of reality",
  "core_values": ["Value 1", "Value 2"],
  "allergies": {{
    "fake urgency": "They immediately distrust 'LIMITED TIME' messaging",
    "too good to be true": "Skeptical of miracle claims"
  }},

  "pain_points": {{
    "emotional": ["Worry about health", "Guilt"],
    "social": ["Embarrassment", "Judgment"],
    "functional": ["Hard to find products that work"]
  }},

  "outcomes_jtbd": {{
    "emotional": ["Feel confident"],
    "social": ["Be seen as great parent"],
    "functional": ["Healthy pet"]
  }},

  "failed_solutions": ["What they've tried before that didn't work"],
  "buying_objections": {{
    "emotional": ["What if it doesn't work?"],
    "social": ["What if people think I'm being duped?"],
    "functional": ["Will my pet like it?"]
  }},
  "familiar_promises": ["Claims they've heard before and are skeptical of"],

  "activation_events": ["What triggers them to buy NOW"],
  "decision_process": "How they typically make purchase decisions",
  "current_workarounds": ["What they're doing instead"],

  "emotional_risks": ["Fear of wasting money"],
  "barriers_to_behavior": ["Price concerns"]
}}

IMPORTANT: Return ONLY valid JSON, no markdown code blocks, no other text."""


class PersonaService:
    """Service for 4D persona management."""

    def __init__(self, supabase: Optional[Client] = None):
        self.supabase = supabase or get_supabase_client()
        # Usage tracking context
        self._tracker: Optional[UsageTracker] = None
        self._user_id: Optional[str] = None
        self._org_id: Optional[str] = None
        logger.info("PersonaService initialized")

    def set_tracking_context(
        self,
        tracker: UsageTracker,
        user_id: Optional[str],
        org_id: str
    ) -> None:
        """
        Set the tracking context for usage billing.

        Args:
            tracker: UsageTracker instance
            user_id: User ID for billing
            org_id: Organization ID for billing
        """
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def create_persona(self, persona: Persona4D) -> UUID:
        """Create a new 4D persona."""
        data = self._persona_to_db(persona)
        result = self.supabase.table("personas_4d").insert(data).execute()

        if result.data:
            persona_id = UUID(result.data[0]["id"])
            logger.info(f"Created persona: {persona.name} ({persona_id})")
            return persona_id

        raise Exception("Failed to create persona")

    def get_persona(self, persona_id: UUID) -> Optional[Persona4D]:
        """Get a persona by ID."""
        result = self.supabase.table("personas_4d").select("*").eq(
            "id", str(persona_id)
        ).execute()

        if result.data:
            return self._db_to_persona(result.data[0])
        return None

    def update_persona(self, persona_id: UUID, updates: Dict[str, Any]) -> bool:
        """Update a persona with partial data."""
        updates["updated_at"] = datetime.utcnow().isoformat()

        result = self.supabase.table("personas_4d").update(updates).eq(
            "id", str(persona_id)
        ).execute()

        if result.data:
            logger.info(f"Updated persona: {persona_id}")
            return True
        return False

    def update_persona_full(self, persona: Persona4D) -> bool:
        """Update a persona with full Persona4D object."""
        if not persona.id:
            raise ValueError("Persona must have an ID to update")

        data = self._persona_to_db(persona)
        data["updated_at"] = datetime.utcnow().isoformat()

        result = self.supabase.table("personas_4d").update(data).eq(
            "id", str(persona.id)
        ).execute()

        if result.data:
            logger.info(f"Updated persona: {persona.id}")
            return True
        return False

    def delete_persona(self, persona_id: UUID) -> bool:
        """Delete a persona."""
        result = self.supabase.table("personas_4d").delete().eq(
            "id", str(persona_id)
        ).execute()

        if result.data:
            logger.info(f"Deleted persona: {persona_id}")
            return True
        return False

    # =========================================================================
    # Query Operations
    # =========================================================================

    def get_personas_for_product(self, product_id: UUID) -> List[PersonaSummary]:
        """Get all personas linked to a product via junction table."""
        result = self.supabase.table("product_personas").select(
            "*, personas_4d(*)"
        ).eq("product_id", str(product_id)).execute()

        personas = []
        for row in result.data:
            p = row.get("personas_4d", {})
            if p:
                personas.append(PersonaSummary(
                    id=UUID(p["id"]),
                    name=p["name"],
                    persona_type=PersonaType(p["persona_type"]),
                    is_primary=row.get("is_primary", False),
                    snapshot=p.get("snapshot"),
                    source_type=SourceType(p.get("source_type", "manual"))
                ))

        return personas

    def get_personas_for_brand(self, brand_id: UUID) -> List[PersonaSummary]:
        """Get all personas for a brand."""
        result = self.supabase.table("personas_4d").select(
            "id, name, persona_type, is_primary, snapshot, source_type"
        ).eq("brand_id", str(brand_id)).execute()

        return [
            PersonaSummary(
                id=UUID(p["id"]),
                name=p["name"],
                persona_type=PersonaType(p["persona_type"]),
                is_primary=p.get("is_primary", False),
                snapshot=p.get("snapshot"),
                source_type=SourceType(p.get("source_type", "manual"))
            )
            for p in result.data
        ]

    def get_personas_for_competitor(self, competitor_id: UUID) -> List[PersonaSummary]:
        """Get all personas extracted from a competitor (competitor-level only, not product-level)."""
        result = self.supabase.table("personas_4d").select(
            "id, name, persona_type, is_primary, snapshot, source_type"
        ).eq("competitor_id", str(competitor_id)).is_("competitor_product_id", "null").execute()

        return [
            PersonaSummary(
                id=UUID(p["id"]),
                name=p["name"],
                persona_type=PersonaType.COMPETITOR,
                is_primary=p.get("is_primary", False),
                snapshot=p.get("snapshot"),
                source_type=SourceType(p.get("source_type", "competitor_analysis"))
            )
            for p in result.data
        ]

    def get_personas_for_competitor_product(self, competitor_product_id: UUID) -> List[PersonaSummary]:
        """Get all personas for a specific competitor product."""
        result = self.supabase.table("personas_4d").select(
            "id, name, persona_type, is_primary, snapshot, source_type"
        ).eq("competitor_product_id", str(competitor_product_id)).execute()

        return [
            PersonaSummary(
                id=UUID(p["id"]),
                name=p["name"],
                persona_type=PersonaType.COMPETITOR,
                is_primary=p.get("is_primary", False),
                snapshot=p.get("snapshot"),
                source_type=SourceType(p.get("source_type", "competitor_analysis"))
            )
            for p in result.data
        ]

    # =========================================================================
    # Product-Persona Linking
    # =========================================================================

    def link_persona_to_product(
        self,
        persona_id: UUID,
        product_id: UUID,
        is_primary: bool = False,
        weight: float = 1.0
    ) -> bool:
        """Link a persona to a product."""
        # If setting as primary, unset other primaries first
        if is_primary:
            self.supabase.table("product_personas").update({
                "is_primary": False
            }).eq("product_id", str(product_id)).execute()

        # Insert or update link
        result = self.supabase.table("product_personas").upsert({
            "product_id": str(product_id),
            "persona_id": str(persona_id),
            "is_primary": is_primary,
            "weight": weight
        }, on_conflict="product_id,persona_id").execute()

        if result.data:
            logger.info(f"Linked persona {persona_id} to product {product_id}")
            return True
        return False

    def unlink_persona_from_product(self, persona_id: UUID, product_id: UUID) -> bool:
        """Remove persona-product link."""
        result = self.supabase.table("product_personas").delete().match({
            "product_id": str(product_id),
            "persona_id": str(persona_id)
        }).execute()

        return len(result.data) > 0

    def set_primary_persona(self, product_id: UUID, persona_id: UUID) -> bool:
        """Set a persona as primary for a product."""
        # First unset all primaries for this product
        self.supabase.table("product_personas").update({
            "is_primary": False
        }).eq("product_id", str(product_id)).execute()

        # Then set the specified persona as primary
        result = self.supabase.table("product_personas").update({
            "is_primary": True
        }).match({
            "product_id": str(product_id),
            "persona_id": str(persona_id)
        }).execute()

        return len(result.data) > 0

    def get_primary_persona_for_product(self, product_id: UUID) -> Optional[Persona4D]:
        """Get the primary persona for a product."""
        result = self.supabase.table("product_personas").select(
            "persona_id"
        ).eq("product_id", str(product_id)).eq("is_primary", True).execute()

        if result.data:
            return self.get_persona(UUID(result.data[0]["persona_id"]))
        return None

    def get_product_persona_links(self, product_id: UUID) -> List[ProductPersonaLink]:
        """Get all persona links for a product with weights."""
        result = self.supabase.table("product_personas").select(
            "id, product_id, persona_id, is_primary, weight, notes"
        ).eq("product_id", str(product_id)).execute()

        return [
            ProductPersonaLink(
                id=UUID(row["id"]),
                product_id=UUID(row["product_id"]),
                persona_id=UUID(row["persona_id"]),
                is_primary=row.get("is_primary", False),
                weight=row.get("weight", 1.0),
                notes=row.get("notes")
            )
            for row in result.data
        ]

    # =========================================================================
    # AI-Assisted Generation
    # =========================================================================

    async def _gather_ad_insights(
        self,
        brand_id: Optional[UUID],
        product_id: UUID
    ) -> Dict[str, Any]:
        """
        Gather insights from existing ad analyses for persona generation.

        Pulls from:
        - product_images.image_analysis (analyzed product images)
        - facebook_ads with brand analysis
        - brand_research_synthesis (if available)
        """
        insights = {
            "hooks_found": [],
            "benefits_mentioned": [],
            "pain_points_addressed": [],
            "persona_signals": [],
            "brand_voice": [],
            "source_count": 0
        }

        try:
            # 1. Get analyzed product images
            images_result = self.supabase.table("product_images").select(
                "image_analysis"
            ).eq("product_id", str(product_id)).not_.is_("image_analysis", "null").execute()

            for img in images_result.data:
                analysis = img.get("image_analysis", {})
                if isinstance(analysis, str):
                    try:
                        analysis = json.loads(analysis)
                    except json.JSONDecodeError:
                        continue

                # Extract hooks
                hooks = analysis.get("hooks", [])
                for hook in hooks:
                    if isinstance(hook, dict):
                        insights["hooks_found"].append({
                            "text": hook.get("text", ""),
                            "type": hook.get("hook_type", ""),
                            "source": "product_image"
                        })

                # Extract benefits
                benefits = analysis.get("benefits_mentioned", [])
                insights["benefits_mentioned"].extend(benefits)

                # Extract pain points
                pain_points = analysis.get("pain_points_addressed", [])
                insights["pain_points_addressed"].extend(pain_points)

                # Extract persona signals
                persona = analysis.get("persona_signals", {})
                if persona:
                    insights["persona_signals"].append(persona)

                # Extract brand voice
                voice = analysis.get("brand_voice", {})
                if voice:
                    insights["brand_voice"].append(voice)

                insights["source_count"] += 1

            # 2. Get brand research synthesis if available
            if brand_id:
                synthesis_result = self.supabase.table("brand_research_synthesis").select(
                    "top_benefits, common_pain_points, recommended_hooks, target_persona"
                ).eq("brand_id", str(brand_id)).order("created_at", desc=True).limit(1).execute()

                if synthesis_result.data:
                    synthesis = synthesis_result.data[0]

                    # Add synthesized benefits
                    top_benefits = synthesis.get("top_benefits", [])
                    insights["benefits_mentioned"].extend(top_benefits)

                    # Add synthesized pain points
                    pain_points = synthesis.get("common_pain_points", [])
                    insights["pain_points_addressed"].extend(pain_points)

                    # Add recommended hooks
                    rec_hooks = synthesis.get("recommended_hooks", [])
                    for hook in rec_hooks:
                        if isinstance(hook, dict):
                            insights["hooks_found"].append({
                                "text": hook.get("hook_template", hook.get("example", "")),
                                "type": hook.get("hook_type", ""),
                                "source": "brand_synthesis"
                            })

                    # Add target persona insights
                    target_persona = synthesis.get("target_persona", {})
                    if target_persona:
                        insights["persona_signals"].append(target_persona)

                    insights["source_count"] += 1

            # Deduplicate lists
            insights["benefits_mentioned"] = list(set(insights["benefits_mentioned"]))
            insights["pain_points_addressed"] = list(set(insights["pain_points_addressed"]))

            logger.info(f"Gathered ad insights: {insights['source_count']} sources, "
                       f"{len(insights['hooks_found'])} hooks, "
                       f"{len(insights['benefits_mentioned'])} benefits")

            return insights if insights["source_count"] > 0 else {}

        except Exception as e:
            logger.warning(f"Failed to gather ad insights: {e}")
            return {}

    async def generate_persona_from_product(
        self,
        product_id: UUID,
        brand_id: Optional[UUID] = None,
        offer_variant_id: Optional[UUID] = None
    ) -> Persona4D:
        """
        Generate a 4D persona using AI from product data and existing ad analyses.

        Uses:
        - Product table data (benefits, target audience, etc.)
        - Offer variant data if specified (pain_points, desires_goals, benefits, target_audience)
        - Existing ad image analyses (hooks, benefits, pain points)
        - Brand research synthesis (if available)

        Args:
            product_id: UUID of the product
            brand_id: Optional brand UUID (resolved from product if not provided)
            offer_variant_id: Optional offer variant UUID - if provided, uses variant's
                              pain_points, desires, and target_audience for persona generation

        Returns the generated persona (not saved - user reviews first).
        """
        # Get product data
        product_result = self.supabase.table("products").select("*").eq(
            "id", str(product_id)
        ).execute()

        if not product_result.data:
            raise ValueError(f"Product not found: {product_id}")

        product = product_result.data[0]
        resolved_brand_id = brand_id or (UUID(product.get("brand_id")) if product.get("brand_id") else None)

        # Get offer variant data if specified
        offer_variant = None
        if offer_variant_id:
            variant_result = self.supabase.table("product_offer_variants").select("*").eq(
                "id", str(offer_variant_id)
            ).execute()
            if variant_result.data:
                offer_variant = variant_result.data[0]
                logger.info(f"Using offer variant for persona generation: {offer_variant.get('name')}")

        # Build product info for prompt - prefer offer variant data if available
        product_info = {
            "name": product.get("name"),
            "description": product.get("description"),
            "benefits": offer_variant.get("benefits") if offer_variant and offer_variant.get("benefits") else product.get("benefits", []),
            "key_ingredients": product.get("key_ingredients", []),
            "category": product.get("category"),
            "price_range": product.get("price_range"),
            "unique_selling_points": product.get("unique_selling_points", []),
            "brand_voice_notes": product.get("brand_voice_notes")
        }

        # Add offer variant specific data if available
        if offer_variant:
            product_info["offer_variant_name"] = offer_variant.get("name")
            product_info["pain_points"] = offer_variant.get("pain_points", [])
            product_info["desires_goals"] = offer_variant.get("desires_goals", [])
            product_info["landing_page_url"] = offer_variant.get("landing_page_url")

        # Prefer offer variant target audience, then product target audience
        target_audience = (
            offer_variant.get("target_audience") if offer_variant and offer_variant.get("target_audience")
            else product.get("target_audience", "Not specified")
        )

        # Gather ad insights from existing analyses
        ad_insights = await self._gather_ad_insights(resolved_brand_id, product_id)

        # Pydantic AI Agent
        agent = Agent(
            model=Config.get_model("persona"),
            system_prompt="You are an expert persona creator. Return ONLY valid JSON."
        )

        prompt = PERSONA_GENERATION_PROMPT.format(
            product_info=json.dumps(product_info, indent=2),
            target_audience=target_audience,
            ad_insights=json.dumps(ad_insights, indent=2) if ad_insights else "No ad analyses available yet."
        )

        result = await run_agent_with_tracking(
            agent,
            prompt,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="persona_service",
            operation="generate_persona_from_product"
        )

        # Parse response with robust JSON repair
        persona_data = parse_llm_json(result.output)

        # Build Persona4D model from AI response
        persona = self._build_persona_from_ai_response(
            persona_data,
            product_id=product_id,
            brand_id=brand_id or UUID(product.get("brand_id")) if product.get("brand_id") else None,
            raw_response=result.output
        )

        logger.info(f"Generated persona for product {product_id}: {persona.name}")
        return persona

    async def synthesize_competitor_persona(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Persona4D:
        """
        Synthesize a 4D persona from competitor analysis data.

        Gathers insights from:
        - competitor_amazon_review_analysis
        - competitor_landing_pages
        - competitor_ads

        Args:
            competitor_id: UUID of the competitor
            brand_id: UUID of the brand tracking this competitor
            competitor_product_id: Optional - filter to product-level analysis

        Returns:
            Generated Persona4D (not saved - user reviews first)
        """
        # Get competitor info
        competitor_result = self.supabase.table("competitors").select(
            "name, website_url, industry"
        ).eq("id", str(competitor_id)).execute()

        if not competitor_result.data:
            raise ValueError(f"Competitor not found: {competitor_id}")

        competitor = competitor_result.data[0]

        # Get competitor product info if specified
        product_info = None
        if competitor_product_id:
            product_result = self.supabase.table("competitor_products").select(
                "name, description"
            ).eq("id", str(competitor_product_id)).execute()
            if product_result.data:
                product_info = product_result.data[0]

        # Gather Amazon review analyses
        # Table has specific columns: pain_points, desires, language_patterns, etc.
        amazon_query = self.supabase.table("competitor_amazon_review_analysis").select(
            "pain_points, desires, language_patterns, objections, transformation, "
            "transformation_quotes, top_positive_quotes, top_negative_quotes, purchase_triggers"
        ).eq("competitor_id", str(competitor_id))

        if competitor_product_id:
            amazon_query = amazon_query.eq("competitor_product_id", str(competitor_product_id))
        else:
            amazon_query = amazon_query.is_("competitor_product_id", "null")

        amazon_result = amazon_query.execute()
        amazon_analyses = amazon_result.data or []

        # Gather landing page analyses
        landing_query = self.supabase.table("competitor_landing_pages").select(
            "url, analysis_data"
        ).eq("competitor_id", str(competitor_id))

        if competitor_product_id:
            landing_query = landing_query.eq("competitor_product_id", str(competitor_product_id))
        else:
            landing_query = landing_query.is_("competitor_product_id", "null")

        landing_result = landing_query.limit(10).execute()
        landing_pages = landing_result.data or []

        # Gather ad analyses (from snapshot_data)
        ads_query = self.supabase.table("competitor_ads").select(
            "ad_creative_body, snapshot_data"
        ).eq("competitor_id", str(competitor_id))

        if competitor_product_id:
            ads_query = ads_query.eq("competitor_product_id", str(competitor_product_id))

        ads_result = ads_query.limit(20).execute()
        ads = ads_result.data or []

        # Gather AI analyses from competitor_ad_analysis (video, image, copy)
        ad_analysis_result = self.supabase.table("competitor_ad_analysis").select(
            "analysis_type, raw_response"
        ).eq("competitor_id", str(competitor_id)).limit(30).execute()
        ad_analyses = ad_analysis_result.data or []

        # Build synthesis input
        synthesis_input = {
            "competitor_name": competitor.get("name"),
            "competitor_website": competitor.get("website_url"),
            "industry": competitor.get("industry"),
            "product_name": product_info.get("name") if product_info else None,
            "product_description": product_info.get("description") if product_info else None,
            "amazon_review_insights": [
                {
                    "pain_points": a.get("pain_points", {}),
                    "desires": a.get("desires", {}),
                    "language_patterns": a.get("language_patterns", {}),
                    "objections": a.get("objections", {}),
                    "transformation": a.get("transformation", {}),
                    "top_quotes": (a.get("top_positive_quotes") or [])[:3] + (a.get("top_negative_quotes") or [])[:3],
                    "purchase_triggers": a.get("purchase_triggers", [])
                }
                for a in amazon_analyses
            ],
            "landing_page_insights": [
                {
                    "url": lp.get("url"),
                    "analysis": lp.get("analysis_data", {})
                }
                for lp in landing_pages if lp.get("analysis_data")
            ],
            "ad_copy_samples": [
                ad.get("ad_creative_body")
                for ad in ads if ad.get("ad_creative_body")
            ][:10],  # Limit to 10 samples
            "ad_ai_analyses": {
                "video_analyses": [
                    a.get("raw_response", {})
                    for a in ad_analyses if a.get("analysis_type") == "video_vision"
                ][:5],
                "image_analyses": [
                    a.get("raw_response", {})
                    for a in ad_analyses if a.get("analysis_type") == "image_vision"
                ][:10],
                "copy_analyses": [
                    a.get("raw_response", {})
                    for a in ad_analyses if a.get("analysis_type") == "copy_analysis"
                ][:10]
            }
        }

        # Check if we have enough data
        ad_ai = synthesis_input["ad_ai_analyses"]
        total_sources = (
            len(synthesis_input["amazon_review_insights"]) +
            len(synthesis_input["landing_page_insights"]) +
            len(synthesis_input["ad_copy_samples"]) +
            len(ad_ai["video_analyses"]) +
            len(ad_ai["image_analyses"]) +
            len(ad_ai["copy_analyses"])
        )

        if total_sources == 0:
            raise ValueError(
                f"No analysis data found for competitor. "
                f"Please scrape and analyze Amazon reviews, landing pages, or ads first."
            )

        # Build prompt for competitor persona synthesis
        level = "product" if competitor_product_id else "competitor"
        prompt = f"""You are an expert at reverse-engineering customer personas from competitor marketing.

Given the following competitor analysis data, synthesize a comprehensive 4D persona representing who this competitor is targeting.

COMPETITOR INFO:
- Name: {competitor.get('name')}
- Website: {competitor.get('website_url', 'N/A')}
- Industry: {competitor.get('industry', 'N/A')}
{f"- Product: {product_info.get('name')}" if product_info else ""}
{f"- Product Description: {product_info.get('description')}" if product_info else ""}

AMAZON REVIEW INSIGHTS (what customers say):
{json.dumps(synthesis_input['amazon_review_insights'], indent=2) if synthesis_input['amazon_review_insights'] else 'No Amazon review data available'}

LANDING PAGE INSIGHTS:
{json.dumps(synthesis_input['landing_page_insights'], indent=2) if synthesis_input['landing_page_insights'] else 'No landing page data available'}

AD COPY SAMPLES (how competitor speaks to customers):
{json.dumps(synthesis_input['ad_copy_samples'], indent=2) if synthesis_input['ad_copy_samples'] else 'No ad copy available'}

AD AI ANALYSES (extracted insights from videos, images, copy):
{json.dumps(synthesis_input.get('ad_ai_analyses', {}), indent=2) if synthesis_input.get('ad_ai_analyses') else 'No AI analyses available'}

Based on this data, generate a detailed 4D persona for the competitor's target customer.
This is a {level}-level persona synthesis.

Return JSON with this structure:
{{
  "name": "Descriptive persona name that reflects competitor's target",
  "snapshot": "2-3 sentence description of who competitor targets",

  "demographics": {{
    "age_range": "e.g., 28-45",
    "gender": "male/female/any",
    "location": "e.g., Suburban USA",
    "income_level": "e.g., Middle to upper-middle class",
    "education": "e.g., College educated",
    "occupation": "e.g., Professional",
    "family_status": "e.g., Married with children"
  }},

  "transformation_map": {{
    "before": ["Pain points competitor addresses"],
    "after": ["Outcomes competitor promises"]
  }},

  "desires": {{
    "primary_desire": [
      {{"text": "What competitor's customers want most", "source": "competitor_analysis"}}
    ],
    "emotional_desire": [
      {{"text": "Emotional outcome they seek", "source": "competitor_analysis"}}
    ]
  }},

  "self_narratives": ["How competitor's customers see themselves"],
  "current_self_image": "Their current identity",
  "desired_self_image": "Who they want to become",
  "identity_artifacts": ["Brands/products associated with desired identity"],

  "social_relations": {{
    "want_to_impress": ["Who they want to impress"],
    "fear_judged_by": ["Who they fear judgment from"],
    "influence_decisions": ["Who influences their decisions"]
  }},

  "worldview": "Their general interpretation of reality",
  "core_values": ["Value 1", "Value 2"],
  "allergies": {{
    "messaging_turnoff_1": "What turns them off in marketing"
  }},

  "pain_points": {{
    "emotional": ["Emotional pain points"],
    "social": ["Social pain points"],
    "functional": ["Functional pain points"]
  }},

  "outcomes_jtbd": {{
    "emotional": ["Emotional outcomes sought"],
    "social": ["Social outcomes sought"],
    "functional": ["Functional outcomes sought"]
  }},

  "failed_solutions": ["Solutions competitor customers have tried before"],
  "buying_objections": {{
    "emotional": ["Emotional objections to buying"],
    "social": ["Social objections"],
    "functional": ["Functional objections"]
  }},

  "activation_events": ["What triggers them to buy NOW"],
  "decision_process": "How they make purchase decisions",

  "confidence_score": 0.85,
  "data_quality_notes": "Brief note on data strengths/gaps"
}}

IMPORTANT: confidence_score must be a float between 0.0 and 1.0 indicating your confidence in this persona based on the quality and quantity of the input data. Higher scores (0.8+) for rich data, lower (0.4-0.6) for sparse data.

Return ONLY valid JSON, no other text."""

        # Call Claude for synthesis
        # Pydantic AI Agent (Creative)
        agent = Agent(
            model=Config.get_model("persona"),
            system_prompt="You are an expert persona synthesizer. Return ONLY valid JSON."
        )

        result = await run_agent_with_tracking(
            agent,
            prompt,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="persona_service",
            operation="synthesize_competitor_persona"
        )

        response_text = result.output

        # Parse response with robust JSON repair
        persona_data = parse_llm_json(response_text)

        # Build Persona4D from response
        persona = self._build_persona_from_ai_response(
            persona_data,
            competitor_id=competitor_id,
            competitor_product_id=competitor_product_id,
            brand_id=brand_id,
            raw_response=response_text
        )

        level_desc = f"product {competitor_product_id}" if competitor_product_id else f"competitor {competitor_id}"
        logger.info(f"Synthesized competitor persona for {level_desc}: {persona.name}")
        return persona

    def _build_persona_from_structured_response(
        self,
        ai_response: PersonaAIResponse,
        product_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None
    ) -> Persona4D:
        """Build a Persona4D from structured AI response (no JSON parsing needed)."""

        # Convert demographics
        demographics = Demographics(
            age_range=ai_response.demographics.age_range,
            gender=ai_response.demographics.gender,
            location=ai_response.demographics.location,
            income_level=ai_response.demographics.income_level,
            education=ai_response.demographics.education,
            occupation=ai_response.demographics.occupation,
            family_status=ai_response.demographics.family_status
        )

        # Convert transformation map
        transformation_map = TransformationMap(
            before=ai_response.transformation_map.before,
            after=ai_response.transformation_map.after
        )

        # Convert desires - structured response already has proper types
        desires = {}
        if ai_response.desires.care_protection:
            desires["care_protection"] = [
                DesireInstance(text=d.text, source=d.source)
                for d in ai_response.desires.care_protection
            ]
        if ai_response.desires.social_approval:
            desires["social_approval"] = [
                DesireInstance(text=d.text, source=d.source)
                for d in ai_response.desires.social_approval
            ]
        if ai_response.desires.freedom_from_fear:
            desires["freedom_from_fear"] = [
                DesireInstance(text=d.text, source=d.source)
                for d in ai_response.desires.freedom_from_fear
            ]

        # Convert social relations
        social_relations = SocialRelations(
            want_to_impress=ai_response.social_relations.want_to_impress,
            fear_judged_by=ai_response.social_relations.fear_judged_by,
            influence_decisions=ai_response.social_relations.influence_decisions
        )

        # Convert domain sentiments
        pain_points = DomainSentiment(
            emotional=ai_response.pain_points.emotional,
            social=ai_response.pain_points.social,
            functional=ai_response.pain_points.functional
        )
        outcomes_jtbd = DomainSentiment(
            emotional=ai_response.outcomes_jtbd.emotional,
            social=ai_response.outcomes_jtbd.social,
            functional=ai_response.outcomes_jtbd.functional
        )
        buying_objections = DomainSentiment(
            emotional=ai_response.buying_objections.emotional,
            social=ai_response.buying_objections.social,
            functional=ai_response.buying_objections.functional
        )

        return Persona4D(
            name=ai_response.name,
            persona_type=PersonaType.PRODUCT_SPECIFIC if product_id else PersonaType.OWN_BRAND,
            brand_id=brand_id,
            product_id=product_id,

            # Basics
            snapshot=ai_response.snapshot,
            demographics=demographics,

            # Psychographic
            transformation_map=transformation_map,
            desires=desires,

            # Identity
            self_narratives=ai_response.self_narratives,
            current_self_image=ai_response.current_self_image,
            desired_self_image=ai_response.desired_self_image,
            identity_artifacts=ai_response.identity_artifacts,

            # Social
            social_relations=social_relations,

            # Worldview
            worldview=ai_response.worldview,
            core_values=ai_response.core_values,
            allergies=ai_response.allergies,

            # Domain Sentiment
            outcomes_jtbd=outcomes_jtbd,
            pain_points=pain_points,
            failed_solutions=ai_response.failed_solutions,
            buying_objections=buying_objections,
            familiar_promises=ai_response.familiar_promises,

            # Purchase Behavior
            activation_events=ai_response.activation_events,
            decision_process=ai_response.decision_process,
            current_workarounds=ai_response.current_workarounds,

            # 3D Objections
            emotional_risks=ai_response.emotional_risks,
            barriers_to_behavior=ai_response.barriers_to_behavior,

            # Meta
            source_type=SourceType.AI_GENERATED
        )

    def _build_persona_from_ai_response(
        self,
        data: Dict[str, Any],
        product_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
        competitor_id: Optional[UUID] = None,
        competitor_product_id: Optional[UUID] = None,
        raw_response: str = ""
    ) -> Persona4D:
        """Build a Persona4D from AI-generated JSON data (used for competitor personas)."""

        # Parse demographics
        demographics = Demographics(**(data.get("demographics", {})))

        # Parse transformation map
        transformation_map = TransformationMap(
            before=data.get("transformation_map", {}).get("before", []),
            after=data.get("transformation_map", {}).get("after", [])
        )

        # Parse desires - convert to DesireInstance objects
        desires = {}
        for category, instances in data.get("desires", {}).items():
            if isinstance(instances, list):
                desires[category] = [
                    DesireInstance(
                        text=inst.get("text", str(inst)) if isinstance(inst, dict) else str(inst),
                        source=inst.get("source", "ai_generated") if isinstance(inst, dict) else "ai_generated"
                    )
                    for inst in instances
                ]

        # Parse social relations
        social_data = data.get("social_relations", {})
        social_relations = SocialRelations(
            admire=social_data.get("admire", []),
            envy=social_data.get("envy", []),
            want_to_impress=social_data.get("want_to_impress", []),
            love_loyalty=social_data.get("love_loyalty", []),
            dislike_animosity=social_data.get("dislike_animosity", []),
            compared_to=social_data.get("compared_to", []),
            influence_decisions=social_data.get("influence_decisions", []),
            fear_judged_by=social_data.get("fear_judged_by", []),
            want_to_belong=social_data.get("want_to_belong", []),
            distance_from=social_data.get("distance_from", [])
        )

        # Parse domain sentiments
        def parse_domain_sentiment(d: Dict) -> DomainSentiment:
            return DomainSentiment(
                emotional=d.get("emotional", []),
                social=d.get("social", []),
                functional=d.get("functional", [])
            )

        pain_points = parse_domain_sentiment(data.get("pain_points", {}))
        outcomes_jtbd = parse_domain_sentiment(data.get("outcomes_jtbd", {}))
        buying_objections = parse_domain_sentiment(data.get("buying_objections", {}))

        # Determine persona type
        if competitor_id:
            persona_type = PersonaType.COMPETITOR
        elif product_id:
            persona_type = PersonaType.PRODUCT_SPECIFIC
        else:
            persona_type = PersonaType.OWN_BRAND

        return Persona4D(
            name=data.get("name", "Generated Persona"),
            persona_type=persona_type,
            brand_id=brand_id,
            product_id=product_id,
            competitor_id=competitor_id,
            competitor_product_id=competitor_product_id,

            # Basics
            snapshot=data.get("snapshot"),
            demographics=demographics,
            behavior_habits=data.get("behavior_habits", {}),
            digital_presence=data.get("digital_presence", {}),
            purchase_drivers=data.get("purchase_drivers", {}),
            cultural_context=data.get("cultural_context", {}),
            typology_profile=data.get("typology_profile", {}),

            # Psychographic
            transformation_map=transformation_map,
            desires=desires,

            # Identity
            self_narratives=data.get("self_narratives", []),
            current_self_image=data.get("current_self_image"),
            past_failures=data.get("past_failures", {}),
            desired_self_image=data.get("desired_self_image"),
            identity_artifacts=data.get("identity_artifacts", []),

            # Social
            social_relations=social_relations,

            # Worldview
            worldview=data.get("worldview"),
            world_stories=data.get("world_stories"),
            core_values=data.get("core_values", []),
            forces_of_good=data.get("forces_of_good", []),
            forces_of_evil=data.get("forces_of_evil", []),
            cultural_zeitgeist=data.get("cultural_zeitgeist"),
            allergies=data.get("allergies", {}),

            # Domain Sentiment
            outcomes_jtbd=outcomes_jtbd,
            pain_points=pain_points,
            desired_features=data.get("desired_features", []),
            failed_solutions=data.get("failed_solutions", []),
            buying_objections=buying_objections,
            familiar_promises=data.get("familiar_promises", []),

            # Purchase Behavior
            pain_symptoms=data.get("pain_symptoms", []),
            activation_events=data.get("activation_events", []),
            purchasing_habits=data.get("purchasing_habits"),
            decision_process=data.get("decision_process"),
            current_workarounds=data.get("current_workarounds", []),

            # 3D Objections
            emotional_risks=data.get("emotional_risks", []),
            barriers_to_behavior=data.get("barriers_to_behavior", []),

            # Meta
            source_type=SourceType.AI_GENERATED,
            source_data={"raw_response": raw_response},
            confidence_score=data.get("confidence_score")
        )

    # =========================================================================
    # Export for Ad Creation
    # =========================================================================

    def export_for_copy_brief(self, persona_id: UUID) -> CopyBrief:
        """Export persona in format optimized for ad copy generation."""
        persona = self.get_persona(persona_id)
        if not persona:
            raise ValueError(f"Persona not found: {persona_id}")

        # Flatten desires into list of strings with category context
        desires_flat = []
        for category, instances in persona.desires.items():
            for instance in instances:
                if isinstance(instance, DesireInstance):
                    desires_flat.append(f"[{category}] {instance.text}")
                elif isinstance(instance, dict):
                    desires_flat.append(f"[{category}] {instance.get('text', '')}")
                else:
                    desires_flat.append(f"[{category}] {instance}")

        # Combine pain points
        top_pain_points = [
            *persona.pain_points.emotional[:2],
            *persona.pain_points.functional[:2]
        ]

        # Combine objections
        objections = [
            *persona.buying_objections.emotional,
            *persona.buying_objections.functional
        ]

        return CopyBrief(
            persona_name=persona.name,
            snapshot=persona.snapshot,
            target_demo=persona.demographics.model_dump() if persona.demographics else {},

            # For hooks
            primary_desires=desires_flat[:5],
            top_pain_points=top_pain_points,

            # For copy
            their_language=persona.self_narratives,
            transformation=persona.transformation_map.model_dump() if persona.transformation_map else {},

            # For objection handling
            objections=objections,
            failed_solutions=persona.failed_solutions,

            # For urgency
            activation_events=persona.activation_events,

            # Avoid these
            allergies=persona.allergies
        )

    def export_for_copy_brief_dict(self, persona_id: UUID) -> Dict[str, Any]:
        """Export persona as dict for ad copy generation (for tools)."""
        brief = self.export_for_copy_brief(persona_id)
        return brief.model_dump()

    def export_for_ad_generation(self, persona_id: UUID) -> Dict[str, Any]:
        """
        Export persona in simplified format for ad image generation prompts.

        Returns key persona traits useful for generating relevant ad imagery.
        This is lighter than export_for_copy_brief - meant for image generation,
        not copy writing.

        Args:
            persona_id: UUID of the persona

        Returns:
            Dict with name, snapshot, demographics, key traits

        Raises:
            ValueError: If persona not found
        """
        persona = self.get_persona(persona_id)
        if not persona:
            raise ValueError(f"Persona not found: {persona_id}")

        return {
            "id": str(persona_id),
            "name": persona.name,
            "snapshot": persona.snapshot or "",
            "demographics": persona.demographics.model_dump() if persona.demographics else {},
            "current_self_image": persona.current_self_image or "",
            "desired_self_image": persona.desired_self_image or "",
            "worldview": persona.worldview or "",
            "activation_events": persona.activation_events or [],
            "pain_symptoms": persona.pain_symptoms or [],
        }

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _persona_to_db(self, persona: Persona4D) -> Dict[str, Any]:
        """Convert Persona4D to database format."""
        data = {}

        # Simple fields
        data["name"] = persona.name
        data["persona_type"] = persona.persona_type.value if hasattr(persona.persona_type, "value") else persona.persona_type
        data["is_primary"] = persona.is_primary

        # UUID fields
        if persona.brand_id:
            data["brand_id"] = str(persona.brand_id)
        if persona.product_id:
            data["product_id"] = str(persona.product_id)
        if persona.competitor_id:
            data["competitor_id"] = str(persona.competitor_id)
        if persona.competitor_product_id:
            data["competitor_product_id"] = str(persona.competitor_product_id)

        # Text fields
        data["snapshot"] = persona.snapshot
        data["current_self_image"] = persona.current_self_image
        data["desired_self_image"] = persona.desired_self_image
        data["worldview"] = persona.worldview
        data["world_stories"] = persona.world_stories
        data["cultural_zeitgeist"] = persona.cultural_zeitgeist
        data["purchasing_habits"] = persona.purchasing_habits
        data["decision_process"] = persona.decision_process

        # Array fields
        data["self_narratives"] = persona.self_narratives
        data["identity_artifacts"] = persona.identity_artifacts
        data["core_values"] = persona.core_values
        data["forces_of_good"] = persona.forces_of_good
        data["forces_of_evil"] = persona.forces_of_evil
        data["desired_features"] = persona.desired_features
        data["failed_solutions"] = persona.failed_solutions
        data["familiar_promises"] = persona.familiar_promises
        data["pain_symptoms"] = persona.pain_symptoms
        data["activation_events"] = persona.activation_events
        data["current_workarounds"] = persona.current_workarounds
        data["emotional_risks"] = persona.emotional_risks
        data["barriers_to_behavior"] = persona.barriers_to_behavior

        # JSONB fields - convert Pydantic models to dicts
        data["demographics"] = persona.demographics.model_dump() if persona.demographics else {}
        data["transformation_map"] = persona.transformation_map.model_dump() if persona.transformation_map else {}
        data["social_relations"] = persona.social_relations.model_dump() if persona.social_relations else {}
        data["pain_points"] = persona.pain_points.model_dump() if persona.pain_points else {}
        data["outcomes_jtbd"] = persona.outcomes_jtbd.model_dump() if persona.outcomes_jtbd else {}
        data["buying_objections"] = persona.buying_objections.model_dump() if persona.buying_objections else {}

        data["behavior_habits"] = persona.behavior_habits
        data["digital_presence"] = persona.digital_presence
        data["purchase_drivers"] = persona.purchase_drivers
        data["cultural_context"] = persona.cultural_context
        data["typology_profile"] = persona.typology_profile
        data["past_failures"] = persona.past_failures
        data["allergies"] = persona.allergies
        data["source_data"] = persona.source_data

        # Desires - convert DesireInstance objects to dicts
        desires_dict = {}
        for category, instances in persona.desires.items():
            desires_dict[category] = [
                inst.model_dump() if isinstance(inst, DesireInstance) else inst
                for inst in instances
            ]
        data["desires"] = desires_dict

        # Meta
        data["source_type"] = persona.source_type.value if hasattr(persona.source_type, "value") else persona.source_type
        data["confidence_score"] = persona.confidence_score

        return data

    def _db_to_persona(self, data: Dict[str, Any]) -> Persona4D:
        """Convert database row to Persona4D."""

        # Parse demographics
        demographics = Demographics(**(data.get("demographics") or {}))

        # Parse transformation map
        tm_data = data.get("transformation_map") or {}
        transformation_map = TransformationMap(
            before=tm_data.get("before", []),
            after=tm_data.get("after", [])
        )

        # Parse social relations
        sr_data = data.get("social_relations") or {}
        social_relations = SocialRelations(
            admire=sr_data.get("admire", []),
            envy=sr_data.get("envy", []),
            want_to_impress=sr_data.get("want_to_impress", []),
            love_loyalty=sr_data.get("love_loyalty", []),
            dislike_animosity=sr_data.get("dislike_animosity", []),
            compared_to=sr_data.get("compared_to", []),
            influence_decisions=sr_data.get("influence_decisions", []),
            fear_judged_by=sr_data.get("fear_judged_by", []),
            want_to_belong=sr_data.get("want_to_belong", []),
            distance_from=sr_data.get("distance_from", [])
        )

        # Parse domain sentiments
        def parse_domain_sentiment(d: Dict) -> DomainSentiment:
            d = d or {}
            return DomainSentiment(
                emotional=d.get("emotional", []),
                social=d.get("social", []),
                functional=d.get("functional", [])
            )

        pain_points = parse_domain_sentiment(data.get("pain_points"))
        outcomes_jtbd = parse_domain_sentiment(data.get("outcomes_jtbd"))
        buying_objections = parse_domain_sentiment(data.get("buying_objections"))

        # Parse desires
        desires = {}
        for category, instances in (data.get("desires") or {}).items():
            if isinstance(instances, list):
                desires[category] = [
                    DesireInstance(
                        text=inst.get("text", "") if isinstance(inst, dict) else str(inst),
                        source=inst.get("source", "manual") if isinstance(inst, dict) else "manual",
                        source_id=inst.get("source_id") if isinstance(inst, dict) else None
                    )
                    for inst in instances
                ]

        return Persona4D(
            id=UUID(data["id"]) if data.get("id") else None,
            name=data.get("name", ""),
            persona_type=PersonaType(data.get("persona_type", "own_brand")),
            is_primary=data.get("is_primary", False),

            brand_id=UUID(data["brand_id"]) if data.get("brand_id") else None,
            product_id=UUID(data["product_id"]) if data.get("product_id") else None,
            competitor_id=UUID(data["competitor_id"]) if data.get("competitor_id") else None,
            competitor_product_id=UUID(data["competitor_product_id"]) if data.get("competitor_product_id") else None,

            # Basics
            snapshot=data.get("snapshot"),
            demographics=demographics,
            behavior_habits=data.get("behavior_habits") or {},
            digital_presence=data.get("digital_presence") or {},
            purchase_drivers=data.get("purchase_drivers") or {},
            cultural_context=data.get("cultural_context") or {},
            typology_profile=data.get("typology_profile") or {},

            # Psychographic
            transformation_map=transformation_map,
            desires=desires,

            # Identity
            self_narratives=data.get("self_narratives") or [],
            current_self_image=data.get("current_self_image"),
            past_failures=data.get("past_failures") or {},
            desired_self_image=data.get("desired_self_image"),
            identity_artifacts=data.get("identity_artifacts") or [],

            # Social
            social_relations=social_relations,

            # Worldview
            worldview=data.get("worldview"),
            world_stories=data.get("world_stories"),
            core_values=data.get("core_values") or [],
            forces_of_good=data.get("forces_of_good") or [],
            forces_of_evil=data.get("forces_of_evil") or [],
            cultural_zeitgeist=data.get("cultural_zeitgeist"),
            allergies=data.get("allergies") or {},

            # Domain Sentiment
            outcomes_jtbd=outcomes_jtbd,
            pain_points=pain_points,
            desired_features=data.get("desired_features") or [],
            failed_solutions=data.get("failed_solutions") or [],
            buying_objections=buying_objections,
            familiar_promises=data.get("familiar_promises") or [],

            # Purchase Behavior
            pain_symptoms=data.get("pain_symptoms") or [],
            activation_events=data.get("activation_events") or [],
            purchasing_habits=data.get("purchasing_habits"),
            decision_process=data.get("decision_process"),
            current_workarounds=data.get("current_workarounds") or [],

            # 3D Objections
            emotional_risks=data.get("emotional_risks") or [],
            barriers_to_behavior=data.get("barriers_to_behavior") or [],

            # Meta
            source_type=SourceType(data.get("source_type", "manual")),
            source_data=data.get("source_data") or {},
            confidence_score=data.get("confidence_score"),

            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )
