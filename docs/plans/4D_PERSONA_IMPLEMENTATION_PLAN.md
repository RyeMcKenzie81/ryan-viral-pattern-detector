# 4D Persona & Competitive Analysis - Implementation Plan

**Date**: 2025-12-04
**Status**: Approved for Implementation
**Architecture**: Pydantic AI + Pydantic Graph

---

## Architecture Decision Summary

Based on the architecture guidelines:

| Feature | Pattern | Rationale |
|---------|---------|-----------|
| **Persona Builder** | Direct Service Calls | User-driven, interactive, form-based |
| **Competitive Analysis Pipeline** | Pydantic-Graph | Autonomous, multi-step, AI-powered |
| **Ad Creation Integration** | Thin Tools | LLM selects persona, services handle logic |

**Key Principle**: "Who decides what happens next—the AI or the user?"

---

## Phase 1: Database Schema

**File**: `sql/2025-12-04_4d_persona_schema.sql`

### Tables to Create

```sql
-- ============================================================================
-- 4D PERSONA TABLES
-- ============================================================================

-- Main 4D persona table (used for both own brand and competitors)
CREATE TABLE personas_4d (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Ownership (one of these will be set)
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE,

    -- Classification
    persona_type TEXT NOT NULL CHECK (persona_type IN ('own_brand', 'product_specific', 'competitor')),
    name TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT false,

    -- ========================================
    -- DIMENSION 1: BASICS
    -- ========================================
    snapshot TEXT,  -- Big picture description
    demographics JSONB DEFAULT '{}',  -- {age_range, gender, location, income, education, occupation, family_status}
    behavior_habits JSONB DEFAULT '{}',  -- {daily_routines, media_consumption, free_time, work_life, health_habits}
    digital_presence JSONB DEFAULT '{}',  -- {platforms, content_consumption, shopping_behavior, device_prefs}
    purchase_drivers JSONB DEFAULT '{}',  -- {triggers, research_method, price_sensitivity, brand_loyalty}
    cultural_context JSONB DEFAULT '{}',  -- {background, regional, generational, subcultures}
    typology_profile JSONB DEFAULT '{}',  -- {mbti, enneagram, disc, other}

    -- ========================================
    -- DIMENSION 2: PSYCHOGRAPHIC MAPPING
    -- ========================================
    transformation_map JSONB DEFAULT '{}',  -- {before: [], after: []}

    -- Core desires with verbiage instances
    desires JSONB DEFAULT '{}',  -- {
    --   "survival_life_extension": [{text: "...", source: "ad/review"}],
    --   "freedom_from_fear": [...],
    --   "superiority_status": [...],
    --   "care_protection": [...],
    --   "social_approval": [...],
    --   "self_actualization": [...],
    --   ... (all 10 categories)
    -- }

    -- ========================================
    -- DIMENSION 3: IDENTITY
    -- ========================================
    self_narratives TEXT[],  -- "Because I am X, therefore I Y"
    current_self_image TEXT,
    past_failures JSONB DEFAULT '{}',  -- {failures: [], blame_attribution: []}
    desired_self_image TEXT,
    identity_artifacts TEXT[],  -- Brands/objects associated with desired image

    -- ========================================
    -- DIMENSION 4: SOCIAL DYNAMICS
    -- ========================================
    social_relations JSONB DEFAULT '{}',  -- {
    --   "admire": [],
    --   "envy": [],
    --   "want_to_impress": [],
    --   "love_loyalty": [],
    --   "dislike_animosity": [],
    --   "compared_to": [],
    --   "influence_decisions": [],
    --   "fear_judged_by": [],
    --   "want_to_belong": [],
    --   "distance_from": []
    -- }

    -- ========================================
    -- DIMENSION 5: WORLDVIEW
    -- ========================================
    worldview TEXT,  -- General worldview/reality interpretation
    world_stories TEXT,  -- Heroes/villains, cause/effect narratives
    core_values TEXT[],
    forces_of_good TEXT[],
    forces_of_evil TEXT[],
    cultural_zeitgeist TEXT,  -- The era/moment they believe they're in
    allergies JSONB DEFAULT '{}',  -- {trigger: reaction} - things that trigger negative reactions

    -- ========================================
    -- DIMENSION 6: DOMAIN SENTIMENT (Product-Specific)
    -- ========================================
    outcomes_jtbd JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    pain_points JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    desired_features TEXT[],
    failed_solutions TEXT[],
    buying_objections JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    familiar_promises TEXT[],  -- Claims they've heard before

    -- ========================================
    -- DIMENSION 7: PURCHASE BEHAVIOR
    -- ========================================
    pain_symptoms TEXT[],  -- Observable signs of pain points
    activation_events TEXT[],  -- What triggers purchase NOW
    purchasing_habits TEXT,
    decision_process TEXT,
    current_workarounds TEXT[],  -- Hacks they use instead of buying

    -- ========================================
    -- DIMENSION 8: 3D OBJECTIONS
    -- ========================================
    emotional_risks TEXT[],
    barriers_to_behavior TEXT[],

    -- ========================================
    -- META
    -- ========================================
    source_type TEXT CHECK (source_type IN ('manual', 'ai_generated', 'competitor_analysis', 'hybrid')),
    source_data JSONB DEFAULT '{}',  -- Raw analysis data that generated this persona
    confidence_score FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT DEFAULT 'system'
);

-- Indexes for personas_4d
CREATE INDEX idx_personas_4d_brand ON personas_4d(brand_id);
CREATE INDEX idx_personas_4d_product ON personas_4d(product_id);
CREATE INDEX idx_personas_4d_competitor ON personas_4d(competitor_id);
CREATE INDEX idx_personas_4d_type ON personas_4d(persona_type);
CREATE INDEX idx_personas_4d_primary ON personas_4d(is_primary) WHERE is_primary = true;

-- Junction table for products with multiple personas
CREATE TABLE product_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    persona_id UUID REFERENCES personas_4d(id) ON DELETE CASCADE NOT NULL,
    is_primary BOOLEAN DEFAULT false,
    weight FLOAT DEFAULT 1.0,  -- For weighted persona targeting
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id, persona_id)
);

CREATE INDEX idx_product_personas_product ON product_personas(product_id);
CREATE INDEX idx_product_personas_persona ON product_personas(persona_id);

-- Ensure only one primary persona per product
CREATE UNIQUE INDEX idx_product_personas_primary
ON product_personas(product_id)
WHERE is_primary = true;

-- ============================================================================
-- COMPETITOR TABLES
-- ============================================================================

CREATE TABLE competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE NOT NULL,  -- Our brand tracking this competitor
    name TEXT NOT NULL,
    facebook_page_id TEXT,
    website_url TEXT,
    ad_library_url TEXT,
    industry TEXT,
    notes TEXT,

    -- Analysis status
    last_scraped_at TIMESTAMPTZ,
    last_analyzed_at TIMESTAMPTZ,
    ads_count INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_competitors_brand ON competitors(brand_id);

-- Competitor ads (separate from facebook_ads to avoid mixing data)
CREATE TABLE competitor_ads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    ad_archive_id TEXT,
    page_name TEXT,
    ad_body TEXT,
    ad_title TEXT,
    link_url TEXT,
    cta_text TEXT,
    started_running DATE,
    is_active BOOLEAN DEFAULT true,
    platforms TEXT[],
    snapshot_data JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competitor_id, ad_archive_id)
);

CREATE INDEX idx_competitor_ads_competitor ON competitor_ads(competitor_id);

-- Competitor ad assets
CREATE TABLE competitor_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_ad_id UUID REFERENCES competitor_ads(id) ON DELETE CASCADE NOT NULL,
    asset_type TEXT CHECK (asset_type IN ('image', 'video')),
    storage_path TEXT,  -- Path in Supabase storage
    original_url TEXT,
    mime_type TEXT,
    file_size INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_competitor_assets_ad ON competitor_ad_assets(competitor_ad_id);

-- Competitor analysis results (individual ad analyses)
CREATE TABLE competitor_ad_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    competitor_ad_id UUID REFERENCES competitor_ads(id) ON DELETE CASCADE,
    asset_id UUID REFERENCES competitor_ad_assets(id) ON DELETE SET NULL,

    analysis_type TEXT CHECK (analysis_type IN ('ad_creative', 'ad_copy', 'landing_page', 'combined')),

    -- Extracted data
    raw_response JSONB DEFAULT '{}',

    -- Structured extractions
    products_mentioned TEXT[],
    benefits_mentioned TEXT[],
    pain_points_addressed TEXT[],
    desires_appealed JSONB DEFAULT '{}',  -- {desire_category: [instances]}
    hooks_extracted JSONB DEFAULT '[]',  -- [{text, type, notes}]
    messaging_patterns TEXT[],
    awareness_level INTEGER CHECK (awareness_level BETWEEN 1 AND 5),

    -- AI metadata
    model_used TEXT,
    tokens_used INTEGER,
    cost_usd FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_competitor_analysis_competitor ON competitor_ad_analysis(competitor_id);
CREATE INDEX idx_competitor_analysis_ad ON competitor_ad_analysis(competitor_ad_id);

-- Competitor landing page analysis
CREATE TABLE competitor_landing_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    url TEXT NOT NULL,

    -- Scraped content (via FireCrawl)
    page_title TEXT,
    meta_description TEXT,
    raw_markdown TEXT,

    -- AI analysis
    products JSONB DEFAULT '[]',  -- [{name, price, description}]
    offers JSONB DEFAULT '[]',  -- [{type, details, urgency}]
    social_proof JSONB DEFAULT '[]',  -- [{type, content, source}]
    guarantees TEXT[],
    usps TEXT[],
    objection_handling JSONB DEFAULT '[]',  -- [{objection, response}]

    -- Meta
    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    model_used TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_competitor_lp_competitor ON competitor_landing_pages(competitor_id);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE personas_4d IS '4D persona profiles for own brand products and competitors';
COMMENT ON TABLE product_personas IS 'Junction table linking products to multiple personas';
COMMENT ON TABLE competitors IS 'Competitors being tracked for competitive analysis';
COMMENT ON TABLE competitor_ads IS 'Ads scraped from competitor Ad Library pages';
COMMENT ON TABLE competitor_ad_assets IS 'Images/videos from competitor ads';
COMMENT ON TABLE competitor_ad_analysis IS 'AI analysis of individual competitor ads';
COMMENT ON TABLE competitor_landing_pages IS 'Scraped and analyzed competitor landing pages';
```

---

## Phase 2: Pydantic Models

**File**: `viraltracker/services/models.py` (add to existing)

```python
# ============================================================================
# 4D PERSONA MODELS
# ============================================================================

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime
from enum import Enum


class PersonaType(str, Enum):
    OWN_BRAND = "own_brand"
    PRODUCT_SPECIFIC = "product_specific"
    COMPETITOR = "competitor"


class SourceType(str, Enum):
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    HYBRID = "hybrid"


class DesireCategory(str, Enum):
    SURVIVAL_LIFE_EXTENSION = "survival_life_extension"
    FOOD_BEVERAGES = "food_beverages"
    FREEDOM_FROM_FEAR = "freedom_from_fear"
    SEXUAL_COMPANIONSHIP = "sexual_companionship"
    COMFORTABLE_LIVING = "comfortable_living"
    SUPERIORITY_STATUS = "superiority_status"
    CARE_PROTECTION = "care_protection"
    SOCIAL_APPROVAL = "social_approval"
    JUSTICE_FAIRNESS = "justice_fairness"
    SELF_ACTUALIZATION = "self_actualization"


class DesireInstance(BaseModel):
    """A specific instance of a desire with captured verbiage."""
    text: str
    source: str = "manual"  # "ad", "review", "manual", "competitor_ad"
    source_id: Optional[str] = None


class Demographics(BaseModel):
    """Demographic profile."""
    age_range: Optional[str] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    income_level: Optional[str] = None
    education: Optional[str] = None
    occupation: Optional[str] = None
    family_status: Optional[str] = None


class TransformationMap(BaseModel):
    """Before/after transformation."""
    before: List[str] = Field(default_factory=list)
    after: List[str] = Field(default_factory=list)


class SocialRelations(BaseModel):
    """Social dynamics mapping."""
    admire: List[str] = Field(default_factory=list)
    envy: List[str] = Field(default_factory=list)
    want_to_impress: List[str] = Field(default_factory=list)
    love_loyalty: List[str] = Field(default_factory=list)
    dislike_animosity: List[str] = Field(default_factory=list)
    compared_to: List[str] = Field(default_factory=list)
    influence_decisions: List[str] = Field(default_factory=list)
    fear_judged_by: List[str] = Field(default_factory=list)
    want_to_belong: List[str] = Field(default_factory=list)
    distance_from: List[str] = Field(default_factory=list)


class DomainSentiment(BaseModel):
    """Product-specific outcomes, pain points, objections."""
    emotional: List[str] = Field(default_factory=list)
    social: List[str] = Field(default_factory=list)
    functional: List[str] = Field(default_factory=list)


class Persona4D(BaseModel):
    """Complete 4D Persona model."""
    id: Optional[UUID] = None
    name: str
    persona_type: PersonaType
    is_primary: bool = False

    # Ownership
    brand_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    competitor_id: Optional[UUID] = None

    # Dimension 1: Basics
    snapshot: Optional[str] = None
    demographics: Demographics = Field(default_factory=Demographics)
    behavior_habits: Dict[str, Any] = Field(default_factory=dict)
    digital_presence: Dict[str, Any] = Field(default_factory=dict)
    purchase_drivers: Dict[str, Any] = Field(default_factory=dict)
    cultural_context: Dict[str, Any] = Field(default_factory=dict)
    typology_profile: Dict[str, Any] = Field(default_factory=dict)

    # Dimension 2: Psychographic
    transformation_map: TransformationMap = Field(default_factory=TransformationMap)
    desires: Dict[str, List[DesireInstance]] = Field(default_factory=dict)

    # Dimension 3: Identity
    self_narratives: List[str] = Field(default_factory=list)
    current_self_image: Optional[str] = None
    past_failures: Dict[str, Any] = Field(default_factory=dict)
    desired_self_image: Optional[str] = None
    identity_artifacts: List[str] = Field(default_factory=list)

    # Dimension 4: Social
    social_relations: SocialRelations = Field(default_factory=SocialRelations)

    # Dimension 5: Worldview
    worldview: Optional[str] = None
    world_stories: Optional[str] = None
    core_values: List[str] = Field(default_factory=list)
    forces_of_good: List[str] = Field(default_factory=list)
    forces_of_evil: List[str] = Field(default_factory=list)
    cultural_zeitgeist: Optional[str] = None
    allergies: Dict[str, str] = Field(default_factory=dict)

    # Dimension 6: Domain Sentiment
    outcomes_jtbd: DomainSentiment = Field(default_factory=DomainSentiment)
    pain_points: DomainSentiment = Field(default_factory=DomainSentiment)
    desired_features: List[str] = Field(default_factory=list)
    failed_solutions: List[str] = Field(default_factory=list)
    buying_objections: DomainSentiment = Field(default_factory=DomainSentiment)
    familiar_promises: List[str] = Field(default_factory=list)

    # Dimension 7: Purchase Behavior
    pain_symptoms: List[str] = Field(default_factory=list)
    activation_events: List[str] = Field(default_factory=list)
    purchasing_habits: Optional[str] = None
    decision_process: Optional[str] = None
    current_workarounds: List[str] = Field(default_factory=list)

    # Dimension 8: 3D Objections
    emotional_risks: List[str] = Field(default_factory=list)
    barriers_to_behavior: List[str] = Field(default_factory=list)

    # Meta
    source_type: SourceType = SourceType.MANUAL
    source_data: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: Optional[float] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PersonaSummary(BaseModel):
    """Lightweight persona for lists and selections."""
    id: UUID
    name: str
    persona_type: PersonaType
    is_primary: bool
    snapshot: Optional[str] = None
    source_type: SourceType


class CompetitorSummary(BaseModel):
    """Competitor summary for lists."""
    id: UUID
    name: str
    website_url: Optional[str]
    ads_count: int = 0
    last_analyzed_at: Optional[datetime] = None
```

---

## Phase 3: PersonaService (Direct Service Calls)

**File**: `viraltracker/services/persona_service.py`

**Pattern**: Direct service calls (user-driven)

```python
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
from .models import Persona4D, PersonaSummary, PersonaType, SourceType

logger = logging.getLogger(__name__)


# AI Prompt for generating 4D persona from product data
PERSONA_GENERATION_PROMPT = """You are an expert at creating detailed customer personas for copywriting.

Given the following product/brand information, generate a comprehensive 4D persona for their target customer.

PRODUCT/BRAND INFO:
{product_info}

EXISTING TARGET AUDIENCE (if any):
{target_audience}

Generate a detailed 4D persona with ALL of the following sections. Be specific and use language the customer would actually use.

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
    "care_protection": ["Specific desire related to protecting loved ones..."],
    "social_approval": ["Wanting to be seen as a good pet parent..."],
    "freedom_from_fear": ["Relief from worry about pet health..."]
  }},

  "self_narratives": [
    "Because I am a responsible pet owner, I research everything before buying",
    "I'm the kind of person who..."
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
    "trigger": "reaction - things that make them immediately distrust a brand"
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
  "current_workarounds": ["What they're doing instead of buying the ideal solution"]
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
        """Update a persona."""
        updates["updated_at"] = datetime.utcnow().isoformat()

        result = self.supabase.table("personas_4d").update(updates).eq(
            "id", str(persona_id)
        ).execute()

        if result.data:
            logger.info(f"Updated persona: {persona_id}")
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

    def get_personas_for_product(self, product_id: UUID) -> List[PersonaSummary]:
        """Get all personas linked to a product."""
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

        return [PersonaSummary(**p) for p in result.data]

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

    def get_primary_persona_for_product(self, product_id: UUID) -> Optional[Persona4D]:
        """Get the primary persona for a product."""
        result = self.supabase.table("product_personas").select(
            "persona_id"
        ).eq("product_id", str(product_id)).eq("is_primary", True).execute()

        if result.data:
            return self.get_persona(UUID(result.data[0]["persona_id"]))
        return None

    # =========================================================================
    # AI-Assisted Generation
    # =========================================================================

    async def generate_persona_from_product(
        self,
        product_id: UUID,
        brand_id: Optional[UUID] = None
    ) -> Persona4D:
        """
        Generate a 4D persona using AI from product data.

        Returns the generated persona (not saved - user reviews first).
        """
        # Get product data
        product_result = self.supabase.table("products").select("*").eq(
            "id", str(product_id)
        ).execute()

        if not product_result.data:
            raise ValueError(f"Product not found: {product_id}")

        product = product_result.data[0]

        # Build product info for prompt
        product_info = {
            "name": product.get("name"),
            "description": product.get("description"),
            "benefits": product.get("benefits", []),
            "key_ingredients": product.get("key_ingredients", []),
            "category": product.get("category"),
            "price_range": product.get("price_range")
        }

        target_audience = product.get("target_audience", "Not specified")

        # Call Claude for generation
        anthropic = Anthropic()
        prompt = PERSONA_GENERATION_PROMPT.format(
            product_info=json.dumps(product_info, indent=2),
            target_audience=target_audience
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
            clean_response = clean_response.split("```")[1]
            if clean_response.startswith("json"):
                clean_response = clean_response[4:]
        clean_response = clean_response.strip()

        persona_data = json.loads(clean_response)

        # Build Persona4D model
        persona = Persona4D(
            name=persona_data.get("name", f"{product.get('name')} Target Customer"),
            persona_type=PersonaType.PRODUCT_SPECIFIC,
            brand_id=brand_id,
            product_id=product_id,
            source_type=SourceType.AI_GENERATED,
            source_data={"raw_response": response_text, "product_id": str(product_id)},
            **{k: v for k, v in persona_data.items() if k != "name"}
        )

        logger.info(f"Generated persona for product {product_id}: {persona.name}")
        return persona

    # =========================================================================
    # Export for Ad Creation
    # =========================================================================

    def export_for_copy_brief(self, persona_id: UUID) -> Dict[str, Any]:
        """Export persona in format optimized for ad copy generation."""
        persona = self.get_persona(persona_id)
        if not persona:
            raise ValueError(f"Persona not found: {persona_id}")

        # Flatten desires into list of strings with category context
        desires_flat = []
        for category, instances in persona.desires.items():
            for instance in instances:
                if isinstance(instance, dict):
                    desires_flat.append(f"[{category}] {instance.get('text', '')}")
                else:
                    desires_flat.append(f"[{category}] {instance}")

        return {
            "persona_name": persona.name,
            "snapshot": persona.snapshot,
            "target_demo": persona.demographics.dict() if persona.demographics else {},

            # For hooks
            "primary_desires": desires_flat[:5],
            "top_pain_points": [
                *persona.pain_points.emotional[:2],
                *persona.pain_points.functional[:2]
            ],

            # For copy
            "their_language": persona.self_narratives,
            "transformation": persona.transformation_map.dict() if persona.transformation_map else {},

            # For objection handling
            "objections": [
                *persona.buying_objections.emotional,
                *persona.buying_objections.functional
            ],
            "failed_solutions": persona.failed_solutions,

            # For urgency
            "activation_events": persona.activation_events,

            # Avoid these
            "allergies": persona.allergies
        }

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _persona_to_db(self, persona: Persona4D) -> Dict[str, Any]:
        """Convert Persona4D to database format."""
        data = persona.dict(exclude_none=True, exclude={"id", "created_at", "updated_at"})

        # Convert UUIDs to strings
        for key in ["brand_id", "product_id", "competitor_id"]:
            if key in data and data[key]:
                data[key] = str(data[key])

        # Convert enums to values
        if "persona_type" in data:
            data["persona_type"] = data["persona_type"].value if hasattr(data["persona_type"], "value") else data["persona_type"]
        if "source_type" in data:
            data["source_type"] = data["source_type"].value if hasattr(data["source_type"], "value") else data["source_type"]

        return data

    def _db_to_persona(self, data: Dict[str, Any]) -> Persona4D:
        """Convert database row to Persona4D."""
        # Convert string UUIDs to UUID objects
        for key in ["id", "brand_id", "product_id", "competitor_id"]:
            if key in data and data[key]:
                data[key] = UUID(data[key])

        return Persona4D(**data)
```

---

## Phase 4: CompetitiveAnalysisService + Pipeline (Pydantic-Graph)

**Files**:
- `viraltracker/pipelines/states.py` (add CompetitorAnalysisState)
- `viraltracker/pipelines/competitive_analysis.py` (new)
- `viraltracker/services/competitive_analysis_service.py` (new)

**Pattern**: Pydantic-Graph (autonomous pipeline) + Service (reusable logic)

### State Class

```python
# Add to viraltracker/pipelines/states.py

@dataclass
class CompetitorAnalysisState:
    """
    State for competitor analysis pipeline.

    Pipeline: AddCompetitor → ScrapeAds → DownloadAssets → AnalyzeAds →
              AnalyzeLandingPages → SynthesizePersona → GenerateReport

    Attributes:
        competitor_id: UUID of competitor being analyzed
        brand_id: Our brand tracking this competitor
        ad_library_url: Facebook Ad Library URL for competitor
        website_url: Competitor's main website
        max_ads: Maximum ads to scrape
        analyze_landing_pages: Whether to scrape and analyze LPs

        ad_ids: Scraped competitor_ads UUIDs
        asset_ids: Downloaded asset UUIDs
        ad_analyses: Results from ad analysis
        lp_analyses: Results from landing page analysis

        synthesized_persona: Generated 4D persona
        competitive_report: Final report

        current_step: Progress tracking
        error: Error message if failed
    """

    # Input
    competitor_id: Optional[UUID] = None
    brand_id: UUID = None
    competitor_name: str = ""
    ad_library_url: str = ""
    website_url: str = ""
    max_ads: int = 30
    analyze_landing_pages: bool = True

    # Scrape results
    ad_ids: List[UUID] = field(default_factory=list)
    asset_ids: List[UUID] = field(default_factory=list)
    landing_page_urls: List[str] = field(default_factory=list)

    # Analysis results
    ad_analyses: List[Dict] = field(default_factory=list)
    lp_analyses: List[Dict] = field(default_factory=list)

    # Synthesis
    synthesized_persona_id: Optional[UUID] = None
    competitive_report: Optional[Dict] = None

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None
```

### Pipeline (Pydantic-Graph)

```python
# viraltracker/pipelines/competitive_analysis.py

"""
Competitive Analysis Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeAds → DownloadAssets → AnalyzeAds → AnalyzeLandingPages →
          SynthesizePersona → GenerateReport

This pipeline autonomously:
1. Scrapes competitor ads from Facebook Ad Library
2. Downloads images/videos
3. Analyzes each ad with Claude Vision
4. Scrapes and analyzes landing pages with FireCrawl
5. Synthesizes findings into a 4D persona
6. Generates competitive intelligence report

Uses PYDANTIC-GRAPH because:
- Autonomous, multi-step workflow
- AI makes decisions at each step
- Complex branching logic
- Multiple AI-powered steps in sequence
"""

import logging
from dataclasses import dataclass
from typing import Union
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import CompetitorAnalysisState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeCompetitorAdsNode(BaseNode[CompetitorAnalysisState]):
    """Step 1: Scrape ads from competitor's Ad Library."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> "DownloadCompetitorAssetsNode":
        logger.info(f"Step 1: Scraping competitor ads from {ctx.state.ad_library_url[:50]}...")
        ctx.state.current_step = "scraping_ads"

        try:
            # Use service to scrape
            ads = await ctx.deps.competitive_analysis.scrape_competitor_ads(
                competitor_id=ctx.state.competitor_id,
                ad_library_url=ctx.state.ad_library_url,
                max_ads=ctx.state.max_ads
            )

            if not ads:
                ctx.state.error = "No ads found"
                return End({"status": "no_ads", "message": "No ads found at URL"})

            ctx.state.ad_ids = [ad["id"] for ad in ads]

            # Extract unique landing page URLs for later analysis
            urls = set()
            for ad in ads:
                if ad.get("link_url"):
                    urls.add(ad["link_url"])
            ctx.state.landing_page_urls = list(urls)[:5]  # Limit to 5 LPs

            logger.info(f"Scraped {len(ctx.state.ad_ids)} ads, found {len(ctx.state.landing_page_urls)} unique LPs")
            return DownloadCompetitorAssetsNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Scrape failed: {e}")
            return End({"status": "error", "error": str(e), "step": "scrape"})


@dataclass
class DownloadCompetitorAssetsNode(BaseNode[CompetitorAnalysisState]):
    """Step 2: Download images/videos from scraped ads."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> "AnalyzeCompetitorAdsNode":
        logger.info(f"Step 2: Downloading assets from {len(ctx.state.ad_ids)} ads")
        ctx.state.current_step = "downloading_assets"

        try:
            asset_ids = await ctx.deps.competitive_analysis.download_competitor_assets(
                ad_ids=ctx.state.ad_ids
            )

            ctx.state.asset_ids = asset_ids
            logger.info(f"Downloaded {len(asset_ids)} assets")
            return AnalyzeCompetitorAdsNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Download failed: {e}")
            return End({"status": "error", "error": str(e), "step": "download"})


@dataclass
class AnalyzeCompetitorAdsNode(BaseNode[CompetitorAnalysisState]):
    """Step 3: Analyze ads with Claude Vision."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> Union["AnalyzeLandingPagesNode", "SynthesizePersonaNode"]:
        logger.info(f"Step 3: Analyzing {len(ctx.state.asset_ids)} ad assets")
        ctx.state.current_step = "analyzing_ads"

        try:
            analyses = await ctx.deps.competitive_analysis.analyze_competitor_ads(
                asset_ids=ctx.state.asset_ids,
                competitor_id=ctx.state.competitor_id
            )

            ctx.state.ad_analyses = analyses
            logger.info(f"Analyzed {len(analyses)} ads")

            # Branch: analyze LPs or skip to synthesis
            if ctx.state.analyze_landing_pages and ctx.state.landing_page_urls:
                return AnalyzeLandingPagesNode()
            else:
                return SynthesizePersonaNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "analyze_ads"})


@dataclass
class AnalyzeLandingPagesNode(BaseNode[CompetitorAnalysisState]):
    """Step 4: Scrape and analyze landing pages with FireCrawl."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> "SynthesizePersonaNode":
        logger.info(f"Step 4: Analyzing {len(ctx.state.landing_page_urls)} landing pages")
        ctx.state.current_step = "analyzing_landing_pages"

        try:
            analyses = await ctx.deps.competitive_analysis.analyze_landing_pages(
                urls=ctx.state.landing_page_urls,
                competitor_id=ctx.state.competitor_id
            )

            ctx.state.lp_analyses = analyses
            logger.info(f"Analyzed {len(analyses)} landing pages")
            return SynthesizePersonaNode()

        except Exception as e:
            # LP analysis is optional, continue on error
            logger.warning(f"LP analysis failed (continuing): {e}")
            return SynthesizePersonaNode()


@dataclass
class SynthesizePersonaNode(BaseNode[CompetitorAnalysisState]):
    """Step 5: Synthesize findings into 4D persona."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> "GenerateReportNode":
        logger.info("Step 5: Synthesizing competitor persona")
        ctx.state.current_step = "synthesizing_persona"

        try:
            persona_id = await ctx.deps.competitive_analysis.synthesize_competitor_persona(
                competitor_id=ctx.state.competitor_id,
                ad_analyses=ctx.state.ad_analyses,
                lp_analyses=ctx.state.lp_analyses
            )

            ctx.state.synthesized_persona_id = persona_id
            logger.info(f"Synthesized persona: {persona_id}")
            return GenerateReportNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Synthesis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "synthesize"})


@dataclass
class GenerateReportNode(BaseNode[CompetitorAnalysisState]):
    """Step 6: Generate competitive intelligence report."""

    async def run(
        self,
        ctx: GraphRunContext[CompetitorAnalysisState, AgentDependencies]
    ) -> End:
        logger.info("Step 6: Generating competitive report")
        ctx.state.current_step = "generating_report"

        try:
            report = await ctx.deps.competitive_analysis.generate_competitive_report(
                competitor_id=ctx.state.competitor_id,
                ad_analyses=ctx.state.ad_analyses,
                lp_analyses=ctx.state.lp_analyses,
                persona_id=ctx.state.synthesized_persona_id
            )

            ctx.state.competitive_report = report
            ctx.state.current_step = "complete"

            logger.info("Competitive analysis complete")
            return End({
                "status": "complete",
                "competitor_id": str(ctx.state.competitor_id),
                "ads_analyzed": len(ctx.state.ad_analyses),
                "persona_id": str(ctx.state.synthesized_persona_id) if ctx.state.synthesized_persona_id else None,
                "report": report
            })

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Report generation failed: {e}")
            return End({"status": "error", "error": str(e), "step": "report"})


# Build the graph
competitive_analysis_graph = Graph(
    nodes=[
        ScrapeCompetitorAdsNode,
        DownloadCompetitorAssetsNode,
        AnalyzeCompetitorAdsNode,
        AnalyzeLandingPagesNode,
        SynthesizePersonaNode,
        GenerateReportNode
    ],
    state_type=CompetitorAnalysisState,
    deps_type=AgentDependencies
)


async def run_competitive_analysis(
    brand_id: UUID,
    competitor_name: str,
    ad_library_url: str,
    website_url: str = "",
    max_ads: int = 30,
    analyze_landing_pages: bool = True,
    deps: AgentDependencies = None
) -> Dict:
    """
    Run the competitive analysis pipeline.

    Args:
        brand_id: Our brand tracking this competitor
        competitor_name: Name of the competitor
        ad_library_url: Facebook Ad Library URL
        website_url: Competitor's website (optional)
        max_ads: Maximum ads to scrape
        analyze_landing_pages: Whether to analyze LPs
        deps: AgentDependencies with services

    Returns:
        Pipeline result with competitive report
    """
    if deps is None:
        from ..agent.dependencies import create_dependencies
        deps = create_dependencies()

    # Create competitor record first
    competitor_id = await deps.competitive_analysis.create_competitor(
        brand_id=brand_id,
        name=competitor_name,
        ad_library_url=ad_library_url,
        website_url=website_url
    )

    # Build initial state
    state = CompetitorAnalysisState(
        competitor_id=competitor_id,
        brand_id=brand_id,
        competitor_name=competitor_name,
        ad_library_url=ad_library_url,
        website_url=website_url,
        max_ads=max_ads,
        analyze_landing_pages=analyze_landing_pages
    )

    # Run the graph
    result = await competitive_analysis_graph.run(
        ScrapeCompetitorAdsNode(),
        state=state,
        deps=deps
    )

    return result.output
```

---

## Phase 5: UI Components

### 5a. Persona Builder UI

**File**: `viraltracker/ui/pages/17_👤_Personas.py`

**Pattern**: Direct service calls (user-driven forms)

```python
"""
4D Persona Builder UI

Create and manage customer personas:
- View personas for a product/brand
- Create new personas manually
- Generate personas with AI
- Edit persona details
- Link personas to products
"""

import streamlit as st
from typing import Optional, List, Dict
from uuid import UUID

# Page config
st.set_page_config(
    page_title="Persona Builder",
    page_icon="👤",
    layout="wide"
)

from viraltracker.ui.auth import require_auth
require_auth()

# ... [Full implementation with forms, tabs, etc.]
```

### 5b. Competitor Management UI

**File**: `viraltracker/ui/pages/18_🔍_Competitors.py`

**Pattern**: UI triggers pipeline, then displays results

```python
"""
Competitor Analysis UI

Track and analyze competitors:
- Add competitors
- Trigger analysis pipeline
- View competitive reports
- Compare own personas vs competitor personas
"""

import streamlit as st
import asyncio
from typing import Optional
from uuid import UUID

# Page config
st.set_page_config(
    page_title="Competitor Analysis",
    page_icon="🔍",
    layout="wide"
)

from viraltracker.ui.auth import require_auth
require_auth()

# ... [Full implementation]
```

---

## Phase 6: Ad Creation Integration

### Add to AgentDependencies

**File**: `viraltracker/agent/dependencies.py` (modify)

```python
# Add to AgentDependencies class
persona: PersonaService = field(default_factory=lambda: PersonaService())
competitive_analysis: CompetitiveAnalysisService = field(default_factory=lambda: CompetitiveAnalysisService())
```

### Thin Tool for Persona Selection

**File**: `viraltracker/agent/agents/ad_creation_agent.py` (add tool)

```python
@ad_creation_agent.tool(
    metadata=ToolMetadata(
        category='Generation',
        platform='Facebook',
        rate_limit='20/minute',
        use_cases=[
            'Select persona for ad generation',
            'Get persona details for copy'
        ],
        examples=[
            'Use the Budget Mom persona for this ad',
            'What personas are available for this product?'
        ]
    )
)
async def get_persona_for_copy(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    persona_id: Optional[str] = None
) -> Dict:
    """
    Get persona data formatted for ad copy generation.

    If persona_id is provided, uses that specific persona.
    Otherwise returns the primary persona for the product.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of the product
        persona_id: Optional specific persona UUID

    Returns:
        Persona data formatted for copy generation including:
        - Primary desires to appeal to
        - Pain points to address
        - Language/verbiage to use
        - Objections to handle
    """
    from uuid import UUID

    if persona_id:
        copy_brief = ctx.deps.persona.export_for_copy_brief(UUID(persona_id))
    else:
        persona = ctx.deps.persona.get_primary_persona_for_product(UUID(product_id))
        if not persona:
            return {"error": "No persona found for product"}
        copy_brief = ctx.deps.persona.export_for_copy_brief(persona.id)

    return copy_brief
```

---

## Implementation Order

1. **Database Schema** → Run migration
2. **Pydantic Models** → Add to models.py
3. **PersonaService** → Direct service calls
4. **Persona Builder UI** → Test with manual personas
5. **AgentDependencies update** → Wire up services
6. **Ad Creation Integration** → Test persona in copy
7. **CompetitiveAnalysisService** → Service methods
8. **Competitive Analysis Pipeline** → Pydantic-graph
9. **Competitor UI** → Trigger pipeline, view results

---

## Testing Checklist

### Phase 1-3 (Personas)
- [ ] Create persona via service
- [ ] Link persona to product
- [ ] Generate persona from product with AI
- [ ] Export persona for copy brief

### Phase 4 (Competitor Analysis)
- [ ] Add competitor
- [ ] Scrape competitor ads
- [ ] Analyze ads with Claude
- [ ] Scrape landing pages with FireCrawl
- [ ] Synthesize competitor persona
- [ ] Generate competitive report

### Phase 5-6 (Integration)
- [ ] Persona Builder UI works
- [ ] Competitor UI triggers pipeline
- [ ] Ad creation uses persona data
- [ ] Persona language appears in generated copy

---

## Files to Create/Modify

| File | Action | Pattern |
|------|--------|---------|
| `sql/2025-12-04_4d_persona_schema.sql` | Create | SQL migration |
| `viraltracker/services/models.py` | Modify | Add Pydantic models |
| `viraltracker/services/persona_service.py` | Create | Direct service calls |
| `viraltracker/services/competitive_analysis_service.py` | Create | Service methods |
| `viraltracker/pipelines/states.py` | Modify | Add CompetitorAnalysisState |
| `viraltracker/pipelines/competitive_analysis.py` | Create | Pydantic-graph pipeline |
| `viraltracker/agent/dependencies.py` | Modify | Add new services |
| `viraltracker/agent/agents/ad_creation_agent.py` | Modify | Add persona tool |
| `viraltracker/ui/pages/17_👤_Personas.py` | Create | Streamlit UI |
| `viraltracker/ui/pages/18_🔍_Competitors.py` | Create | Streamlit UI |
