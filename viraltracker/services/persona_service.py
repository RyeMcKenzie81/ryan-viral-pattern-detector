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
from anthropic import Anthropic

from ..core.database import get_supabase_client
from .models import (
    Persona4D, PersonaSummary, PersonaType, SourceType,
    Demographics, TransformationMap, SocialRelations, DomainSentiment,
    DesireInstance, CopyBrief, ProductPersonaLink
)

logger = logging.getLogger(__name__)


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
    "before": ["Current frustration 1", "Current limitation 2", "..."],
    "after": ["Desired outcome 1", "Desired state 2", "..."]
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
    "Because I am a responsible pet owner, I research everything before buying",
    "I'm the kind of person who only wants the best for my family"
  ],
  "current_self_image": "How they see themselves now",
  "desired_self_image": "How they want to be seen/who they want to become",
  "identity_artifacts": ["Brands/products associated with their desired identity"],

  "social_relations": {{
    "want_to_impress": ["Their vet", "Other pet owners at the dog park"],
    "fear_judged_by": ["Other pet parents who might think they're not caring enough"],
    "influence_decisions": ["Pet influencers", "Facebook pet groups"]
  }},

  "worldview": "Their general interpretation of reality",
  "core_values": ["Value 1", "Value 2"],
  "allergies": {{
    "fake urgency": "They immediately distrust 'LIMITED TIME' messaging",
    "too good to be true": "Skeptical of miracle claims"
  }},

  "pain_points": {{
    "emotional": ["Worry about pet's health", "Guilt when can't afford premium"],
    "social": ["Embarrassment at vet visits", "Judgment from other owners"],
    "functional": ["Hard to find products that actually work"]
  }},

  "outcomes_jtbd": {{
    "emotional": ["Feel confident they're doing the right thing"],
    "social": ["Be seen as a great pet parent"],
    "functional": ["Healthy, happy pet with good dental health"]
  }},

  "failed_solutions": ["What they've tried before that didn't work"],
  "buying_objections": {{
    "emotional": ["What if it doesn't work and I wasted money?"],
    "social": ["What if people think I'm being duped?"],
    "functional": ["Will my pet actually like it?"]
  }},
  "familiar_promises": ["Claims they've heard before and are skeptical of"],

  "activation_events": ["What triggers them to buy NOW - e.g., vet visit, bad breath noticed"],
  "decision_process": "How they typically make purchase decisions",
  "current_workarounds": ["What they're doing instead of buying the ideal solution"],

  "emotional_risks": ["Fear of wasting money", "Fear of looking foolish"],
  "barriers_to_behavior": ["Price concerns", "Uncertainty about effectiveness"]
}}

Return ONLY valid JSON, no other text."""


class PersonaService:
    """Service for 4D persona management."""

    def __init__(self, supabase: Optional[Client] = None):
        self.supabase = supabase or get_supabase_client()
        logger.info("PersonaService initialized")

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
        """Get all personas extracted from a competitor."""
        result = self.supabase.table("personas_4d").select(
            "id, name, persona_type, is_primary, snapshot, source_type"
        ).eq("competitor_id", str(competitor_id)).execute()

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
        brand_id: Optional[UUID] = None
    ) -> Persona4D:
        """
        Generate a 4D persona using AI from product data and existing ad analyses.

        Uses:
        - Product table data (benefits, target audience, etc.)
        - Existing ad image analyses (hooks, benefits, pain points)
        - Brand research synthesis (if available)

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

        # Build product info for prompt
        product_info = {
            "name": product.get("name"),
            "description": product.get("description"),
            "benefits": product.get("benefits", []),
            "key_ingredients": product.get("key_ingredients", []),
            "category": product.get("category"),
            "price_range": product.get("price_range"),
            "unique_selling_points": product.get("unique_selling_points", []),
            "brand_voice_notes": product.get("brand_voice_notes")
        }

        target_audience = product.get("target_audience", "Not specified")

        # Gather ad insights from existing analyses
        ad_insights = await self._gather_ad_insights(resolved_brand_id, product_id)

        # Call Claude for generation
        anthropic = Anthropic()
        prompt = PERSONA_GENERATION_PROMPT.format(
            product_info=json.dumps(product_info, indent=2),
            target_audience=target_audience,
            ad_insights=json.dumps(ad_insights, indent=2) if ad_insights else "No ad analyses available yet."
        )

        message = anthropic.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text

        # Parse response
        clean_response = response_text.strip()
        if clean_response.startswith("```"):
            lines = clean_response.split("\n")
            # Remove first and last lines if they're ```
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_response = "\n".join(lines)
        clean_response = clean_response.strip()

        persona_data = json.loads(clean_response)

        # Build Persona4D model from AI response
        persona = self._build_persona_from_ai_response(
            persona_data,
            product_id=product_id,
            brand_id=brand_id or UUID(product.get("brand_id")) if product.get("brand_id") else None,
            raw_response=response_text
        )

        logger.info(f"Generated persona for product {product_id}: {persona.name}")
        return persona

    def _build_persona_from_ai_response(
        self,
        data: Dict[str, Any],
        product_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
        competitor_id: Optional[UUID] = None,
        raw_response: str = ""
    ) -> Persona4D:
        """Build a Persona4D from AI-generated JSON data."""

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
