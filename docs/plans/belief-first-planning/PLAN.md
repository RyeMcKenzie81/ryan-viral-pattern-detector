# Belief-First Advertising Planning System

**Feature Branch**: `feature/belief-first-planning`
**Created**: 2025-12-15
**Status**: Phase 4 - BUILD (in progress)

---

## Phase 1: INTAKE ✅

### 1.1 Overview

A Belief-First Advertising Planning Tool that sits upstream of the ad creation engine. The planning tool **thinks** (decides what to test, enforces sequencing), while the ad creator **executes** (generates only what the plan specifies).

**Core Principle**: We are not building ads. We are building a system that discovers, explains, and scales belief.

### 1.2 Requirements Gathered

| Requirement | Decision |
|-------------|----------|
| **Interface** | Streamlit UI (consistent with existing ViralTracker pages) |
| **Templates** | Pre-built templates - user selects from existing ad templates |
| **DB Strategy** | Link to existing tables (`brands`, `products`, `personas_4d`), add minimal new tables |
| **UX Flow** | Wizard-style steps with on-demand AI assistance at each step |
| **AI Assistance** | On-demand "Suggest ideas" button - user can request help at any step |
| **AI Model** | Claude Opus 4.5 for creative suggestions |
| **Seed Data** | Wonder Paws already exists with product, 50+ hooks, personas |
| **Phase Enforcement** | Warnings only - warn if skipping phases but allow it |

### 1.3 MVP Scope

**In Scope:**
- PHASE_1 (Product × Persona × JTBD × Angle Discovery) planning
- PHASE_2 (Angle Confirmation) planning
- Wizard-style Streamlit UI with step-gated navigation
- On-demand AI assistance (Claude Opus 4.5) for suggestions
- Supabase storage for all entities
- Compiled JSON payload for ad creator consumption
- RLS for user data isolation

**Out of Scope (MVP - schema only):**
- PHASE_3-6 planning UI
- Sub-layer creation/management UI (schema created for future)
- Meta API ingestion
- Automated promotion/kill logic
- Video generation

### 1.4 Belief Hierarchy → Existing Data Model Mapping

**Key Insight**: Most data already exists. The wizard **selects** existing entities and **creates** angles.

```
Market Context (constraints) - Global, not stored per-plan
└─ Brand
│  └─ TABLE: brands (EXISTS)
│
└─ Product / Offer
   │  └─ TABLE: products (EXISTS - rich: benefits, USPs, target_audience, current_offer)
   │  └─ TABLE: belief_offers (NEW - proper offer versioning, linked to products)
   │
   └─ Persona
      │  └─ TABLE: personas_4d (EXISTS - comprehensive 4D framework)
      │  └─ TABLE: product_personas (EXISTS - links products to personas)
      │
      ├─ Awareness Level
      │  └─ FIELD: Can add to personas_4d or belief_personas (state, not identity)
      │
      ├─ Persona Sub-Layers (6 types - see Section 1.5)
      │  └─ TABLE: belief_sublayers (NEW - schema for PHASE_3)
      │
      └─ Jobs To Be Done (JTBD)
           │  └─ JSONB: personas_4d.domain_sentiment.outcomes_jtbd (EXISTS - embedded)
           │  └─ TABLE: belief_jtbd_framed (NEW - for explicit plan linking)
           │
           └─ Angle (belief / explanation)
                │  └─ TABLE: belief_angles (NEW - **main new entity**)
                │
                └─ [Future: Mechanism, Problem, Benefits, Features, Proof]
                     └─ Expression
                          └─ TABLE: hooks (EXISTS - 50+ for Wonder Paws)
                          └─ TABLE: ad_brief_templates (EXISTS)
```

**Existing Services to Reuse:**
| Service | Methods | Use In Planning |
|---------|---------|-----------------|
| `AdCreationService` | `get_product()`, `search_products_by_name()`, `get_hooks()`, `get_ad_brief_template()`, `get_personas_for_product()` | Product/template selection |
| `PersonaService` | Full 4D persona CRUD + AI generation | Persona selection/creation |

**New Tables Needed (Minimal):**
```
belief_offers          → Proper offer versioning (products.current_offer is just a string)
belief_sublayers       → 6 sub-layer types (schema for PHASE_3)
belief_jtbd_framed     → Persona-framed JTBDs for plan linking
belief_angles          → Angle beliefs (MAIN NEW ENTITY)
belief_plans           → Plan configuration + compiled payload
belief_plan_angles     → Many-to-many: plan ↔ angles
belief_plan_templates  → Many-to-many: plan ↔ templates
belief_plan_runs       → Phase run tracking (future)
```

### 1.5 Persona Sub-Layer Taxonomy (Canonical)

**6 Valid Sub-Layer Types (ONLY THESE):**

| # | Type | What It Modifies | Example Values | Rules |
|---|------|------------------|----------------|-------|
| 1 | **Geography / Locale** | Familiarity, trust | Country, State, Climate, Urban/Rural | Does not change belief |
| 2 | **Asset-Specific** | Self-selection | Breed, Size class, Body type, Hair texture | Immediate relevance |
| 3 | **Environment / Physical Context** | Problem realism | Stairs, Hardwood floors, Slippery surfaces | Makes symptoms tangible |
| 4 | **Lifestyle / Usage Context** | Product fit | Active vs low activity, Busy routine, Traveler | Behavioral, not psychological |
| 5 | **Purchase Constraints** | Buying comfort | Simple routine, Subscription-friendly, Budget | Light use only |
| 6 | **Values / Identity Signals** | Trust | Anti-pharma, Natural-only, Research-driven | **Restricted**: small curated list, never stack |

**NOT Sub-Layers (belong elsewhere):**
| ❌ Removed | Why | Belongs Under |
|-----------|-----|---------------|
| Problem Severity | Changes urgency and claims | JTBD → Progress/Severity State |
| Symptoms | Recognition triggers | Problem → Pain → Symptoms layer |
| Awareness Level | State, not modifier | Alongside Persona (already correct) |
| Mechanism Hints | Implies causality | Angle/Mechanism layer |
| Offer Elements | Affects conversion, not belief | Offer layer |

### 1.6 Phase Definitions

| Phase | Name | Goal | What Can Change | MVP Status |
|-------|------|------|-----------------|------------|
| 1 | Discovery | Identify belief systems Meta can find buyers for | Product, Persona, JTBD, 5-7 Angles | **Full UI** |
| 2 | Confirmation | Ensure angle survives repetition | Nothing (volume test) | **Full UI** |
| 3 | Sub-Layer Activation | Improve relevance without fragmenting belief | Sub-layers only (belief locked) | Schema only |
| 4 | Mechanism & Problem | Discover why angle works best | Mechanism, Problem | Schema only |
| 5 | Benefit & Messaging | Find scalable emotional payload | Benefits, Messaging density | Schema only |
| 6 | Format Expansion | Translate to video and scale | Formats, spend | Schema only |

### 1.7 User Flow (Wizard Steps)

**Step 1: Select Brand**
- Dropdown of user's brands (from existing `brands` table)
- Display brand constraints/rules

**Step 2: Select Product**
- Select from existing `products` linked to brand
- Display product benefits, USPs, target audience
- Shows existing hooks count

**Step 3: Define/Select Offer (Optional)**
- Select existing offer OR create new
- Fields: name, description, urgency drivers
- AI assist: "Suggest offers for this product"

**Step 4: Select/Create Persona**
- Select from existing `personas_4d` linked to product
- OR create new using `PersonaService` AI generation
- Display persona snapshot, transformation map

**Step 5: Define/Select JTBD**
- Show JTBDs from persona's `domain_sentiment.outcomes_jtbd`
- OR create new persona-framed JTBD
- Progress statement: "When I..., I want to..., so I can..."
- AI assist: "Suggest JTBDs for this persona + product"

**Step 6: Define Angles (5-7)**
- Create angles for this JTBD
- Fields: name, belief statement, explanation
- AI assist: "Suggest angles for this JTBD" (Claude Opus 4.5)

**Step 7: Select Templates**
- Pick from existing `ad_brief_templates`
- Template strategy: fixed or random
- Ads per angle setting

**Step 8: Review & Compile**
- Summary of all selections
- Phase validation (warnings if skipping)
- Compile button → generates deterministic payload
- Stored in Supabase for ad creator

### 1.8 Plan Output Schema

```json
{
  "plan_id": "uuid",
  "brand_id": "uuid",
  "product_id": "uuid",
  "offer_id": "uuid | null",
  "persona_id": "uuid",
  "jtbd_framed_id": "uuid",
  "phase_id": 1,
  "angles": [
    {"angle_id": "uuid", "name": "string", "belief_statement": "string"}
  ],
  "templates": [
    {"template_id": "uuid", "name": "string"}
  ],
  "template_strategy": "fixed | random",
  "ads_per_angle": 3,
  "locked_fields": ["brand_id", "product_id", "persona_id", "jtbd_id"],
  "allowed_variations": ["angle_id", "template_id"],
  "compiled_at": "timestamp",
  "status": "draft | ready | running | completed"
}
```

### 1.9 API Contract for Ad Creator

**Service Methods (primary):**
```python
planning_service.list_plans(brand_id=brand_id, status="ready")
planning_service.get_plan(plan_id=plan_id)
planning_service.get_compiled_plan(plan_id=plan_id)
planning_service.get_next_phase_recommendation(plan_id=plan_id)  # stub for MVP
```

**Optional REST Endpoints:**
- `GET /api/plans?brand_id=X&status=ready`
- `GET /api/plans/{plan_id}`
- `GET /api/plans/{plan_id}/compiled`

---

## Phase 2: ARCHITECTURE DECISION ✅

### 2.1 Pattern Decision: Direct Service Calls (NOT pydantic-graph)

| Criteria | pydantic-graph | Python workflow | **Decision** |
|----------|----------------|-----------------|--------------|
| Who decides next step? | AI | User (wizard steps) | **User** |
| Autonomous execution? | Yes | No (interactive) | **No** |
| Pause/resume needed? | Yes | No (single session) | **No** |
| Branching complexity? | Complex | Linear (wizard) | **Linear** |

**Decision**: Python workflow with direct service calls

**Reasoning**:
- Planning wizard is user-driven and linear
- Each step is a form submission, not AI-decided
- AI assistance is on-demand (button click) rather than autonomous
- Same pattern as existing `PersonaService` (which explicitly states "Uses DIRECT SERVICE CALLS (not pydantic-graph)")

### 2.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Streamlit UI (Wizard)                                           │
│ viraltracker/ui/pages/XX_📋_Ad_Planning.py                      │
│                                                                 │
│ Step 1 → Step 2 → Step 3 → ... → Step 8 (Review & Compile)     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ calls
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ PlanningService                                                 │
│ viraltracker/services/planning_service.py                       │
│                                                                 │
│ Methods:                                                        │
│ - CRUD: offers, jtbd_framed, angles, plans                     │
│ - compile_plan() → deterministic JSON payload                   │
│ - validate_phase() → warnings if skipping                       │
│ - suggest_*() → AI suggestions (Claude Opus 4.5)               │
└──────────┬──────────────────────────┬───────────────────────────┘
           │                          │
           │ reuses                   │ calls
           ▼                          ▼
┌─────────────────────┐    ┌─────────────────────────────────────┐
│ Existing Services   │    │ Anthropic API (Claude Opus 4.5)     │
│                     │    │ For on-demand AI suggestions        │
│ - AdCreationService │    └─────────────────────────────────────┘
│ - PersonaService    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Supabase (Postgres + RLS)                                       │
│                                                                 │
│ EXISTING: brands, products, personas_4d, product_personas,      │
│           hooks, ad_brief_templates                             │
│                                                                 │
│ NEW: belief_offers, belief_sublayers, belief_jtbd_framed,      │
│      belief_angles, belief_plans, belief_plan_angles,           │
│      belief_plan_templates, belief_plan_runs                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Service Integration

```python
# PlanningService will be added to AgentDependencies
# viraltracker/agent/dependencies.py

class AgentDependencies(BaseModel):
    # ... existing services ...
    planning: PlanningService  # NEW
```

---

## Phase 3: INVENTORY & GAP ANALYSIS ✅

### 3.1 Existing Components to Reuse

| Component | Location | What We Use |
|-----------|----------|-------------|
| `brands` table | Existing DB | FK for all planning entities |
| `products` table | Existing DB | Select product (has benefits, USPs, current_offer) |
| `personas_4d` table | Existing DB | Select persona (has JTBDs in domain_sentiment) |
| `product_personas` table | Existing DB | Product-persona links |
| `hooks` table | Existing DB | Expression layer (50+ for Wonder Paws) |
| `ad_brief_templates` table | Existing DB | Template selection |
| `AdCreationService` | `services/ad_creation_service.py:41-59` | `get_product()` |
| `AdCreationService` | `services/ad_creation_service.py:150-184` | `get_personas_for_product()` |
| `PersonaService` | `services/persona_service.py` | Full 4D persona CRUD + AI generation |
| Supabase client | `core/database.py` | `get_supabase_client()` pattern |
| Anthropic client | Multiple services | Pattern: `anthropic.Anthropic(api_key=...)` |

### 3.1.1 Anthropic API Patterns Found

**Model to use**: `claude-opus-4-5-20251101` (matches ScriptService, ComicService, AdCreationService)

**Two initialization patterns in codebase:**
1. **Lazy init in `__init__`** (ScriptService, ComicService) - stores `self.client`
2. **Per-call instantiation** (PersonaService) - creates client each call

**Recommendation**: Use lazy init pattern (store `self.client` in PlanningService)

```python
# Pattern from ScriptService (lines 210-215)
def __init__(self, anthropic_api_key: Optional[str] = None, model: Optional[str] = None):
    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set - suggestions will fail")
        self.client = None
    else:
        self.client = anthropic.Anthropic(api_key=api_key)
    self.model = model or "claude-opus-4-5-20251101"
```

### 3.1.2 Streamlit UI Patterns Found

**From Ad Creator (01_🎨_Ad_Creator.py) and Personas (17_👤_Personas.py):**

1. **Session state** for wizard steps: `st.session_state.selected_product`, `st.session_state.selected_persona_id`
2. **Helper functions** fetch data (instantiate service inside function to avoid stale connections)
3. **Authentication**: `from viraltracker.ui.auth import require_auth; require_auth()`
4. **Page config**: `st.set_page_config(page_title="...", page_icon="...", layout="wide")`
5. **Service instantiation inside functions** (not at module level)

```python
# Pattern from Personas page (lines 50-53)
def get_persona_service():
    """Get PersonaService instance."""
    from viraltracker.services.persona_service import PersonaService
    return PersonaService()
```

### 3.2 New Components Needed

| Component | Type | Location | Purpose |
|-----------|------|----------|---------|
| `PlanningService` | Service | `services/planning_service.py` | All planning business logic |
| Planning models | Pydantic | `services/models.py` or inline | Offer, Angle, Plan, etc. |
| `Ad_Planning.py` | UI Page | `ui/pages/XX_📋_Ad_Planning.py` | Wizard interface |
| Migration SQL | Database | `sql/2025-12-15_belief_planning.sql` | Create new tables |

### 3.3 Database Schema (Final)

```sql
-- ============================================
-- BELIEF-FIRST PLANNING TABLES
-- Migration: 2025-12-15
-- ============================================

-- belief_offers (proper offer versioning, linked to existing products)
CREATE TABLE IF NOT EXISTS belief_offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id),
    name TEXT NOT NULL,
    description TEXT,
    urgency_drivers JSONB, -- ["limited time", "bonus gift", etc.]
    active BOOLEAN DEFAULT true,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_offers IS 'Versioned offers for products (vs products.current_offer string)';

-- belief_sublayers (6 types - schema for PHASE_3)
CREATE TABLE IF NOT EXISTS belief_sublayers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id UUID NOT NULL REFERENCES personas_4d(id),
    sublayer_type TEXT NOT NULL CHECK (sublayer_type IN (
        'geography_locale',
        'asset_specific',
        'environment_context',
        'lifestyle_usage',
        'purchase_constraints',
        'values_identity'
    )),
    name TEXT NOT NULL,
    values JSONB NOT NULL, -- ["Vancouver", "BC", "Canada"] or ["Labrador", "Golden Retriever"]
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_sublayers IS 'Persona relevance modifiers (6 canonical types only)';
COMMENT ON COLUMN belief_sublayers.sublayer_type IS 'One of: geography_locale, asset_specific, environment_context, lifestyle_usage, purchase_constraints, values_identity';

-- belief_jtbd_framed (persona-framed JTBDs for explicit plan linking)
CREATE TABLE IF NOT EXISTS belief_jtbd_framed (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id UUID NOT NULL REFERENCES personas_4d(id),
    product_id UUID NOT NULL REFERENCES products(id),
    name TEXT NOT NULL,
    description TEXT,
    progress_statement TEXT, -- "When I..., I want to..., so I can..."
    source TEXT DEFAULT 'manual', -- 'manual', 'extracted_from_persona', 'ai_generated'
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_jtbd_framed IS 'Persona-framed JTBDs (advertising-relevant, for plan linking)';

-- belief_angles (MAIN NEW ENTITY)
CREATE TABLE IF NOT EXISTS belief_angles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jtbd_framed_id UUID NOT NULL REFERENCES belief_jtbd_framed(id),
    name TEXT NOT NULL,
    belief_statement TEXT NOT NULL, -- The core belief/explanation
    explanation TEXT, -- Why this angle works
    status TEXT DEFAULT 'untested', -- 'untested', 'testing', 'winner', 'loser'
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_angles IS 'Angle beliefs that explain why the JTBD exists and why this solution works';

-- belief_plans (plan configuration + compiled payload)
CREATE TABLE IF NOT EXISTS belief_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID NOT NULL REFERENCES products(id),
    offer_id UUID REFERENCES belief_offers(id),
    persona_id UUID NOT NULL REFERENCES personas_4d(id),
    jtbd_framed_id UUID NOT NULL REFERENCES belief_jtbd_framed(id),
    phase_id INTEGER NOT NULL DEFAULT 1 CHECK (phase_id BETWEEN 1 AND 6),
    template_strategy TEXT DEFAULT 'fixed' CHECK (template_strategy IN ('fixed', 'random')),
    ads_per_angle INTEGER DEFAULT 3,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'running', 'completed')),
    compiled_payload JSONB, -- Generator-ready deterministic payload
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    compiled_at TIMESTAMPTZ
);

COMMENT ON TABLE belief_plans IS 'Ad testing plans with compiled payload for ad creator';

-- belief_plan_angles (many-to-many: plan ↔ angles)
CREATE TABLE IF NOT EXISTS belief_plan_angles (
    plan_id UUID NOT NULL REFERENCES belief_plans(id) ON DELETE CASCADE,
    angle_id UUID NOT NULL REFERENCES belief_angles(id),
    display_order INTEGER DEFAULT 0,
    PRIMARY KEY (plan_id, angle_id)
);

-- belief_plan_templates (many-to-many: plan ↔ templates)
CREATE TABLE IF NOT EXISTS belief_plan_templates (
    plan_id UUID NOT NULL REFERENCES belief_plans(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES ad_brief_templates(id),
    display_order INTEGER DEFAULT 0,
    PRIMARY KEY (plan_id, template_id)
);

-- belief_plan_runs (phase run tracking - for future PHASE_3+)
CREATE TABLE IF NOT EXISTS belief_plan_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES belief_plans(id),
    phase_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    results JSONB, -- Performance data, winner angles, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_plan_runs IS 'Track phase execution history for a plan';

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_belief_offers_product ON belief_offers(product_id);
CREATE INDEX IF NOT EXISTS idx_belief_sublayers_persona ON belief_sublayers(persona_id);
CREATE INDEX IF NOT EXISTS idx_belief_jtbd_framed_persona ON belief_jtbd_framed(persona_id);
CREATE INDEX IF NOT EXISTS idx_belief_angles_jtbd ON belief_angles(jtbd_framed_id);
CREATE INDEX IF NOT EXISTS idx_belief_plans_brand ON belief_plans(brand_id);
CREATE INDEX IF NOT EXISTS idx_belief_plans_status ON belief_plans(status);
```

---

## Phase 4: BUILD

*To be completed after Phase 3 approval*

### Build Order

1. **Database migration** - Create all new tables
2. **Pydantic models** - Add to `services/models.py`
3. **PlanningService** - CRUD + compilation + AI suggestions
4. **Update AgentDependencies** - Add `planning` service
5. **Streamlit wizard UI** - 8-step wizard
6. **Integration testing**

### 4.1 PlanningService Methods (Draft)

```python
class PlanningService:
    # CRUD - Offers
    def create_offer(self, product_id, name, description, urgency_drivers) -> BeliefOffer
    def get_offers_for_product(self, product_id) -> List[BeliefOffer]

    # CRUD - JTBD Framed
    def create_jtbd_framed(self, persona_id, product_id, name, progress_statement) -> BeliefJTBDFramed
    def get_jtbd_for_persona_product(self, persona_id, product_id) -> List[BeliefJTBDFramed]
    def extract_jtbd_from_persona(self, persona_id) -> List[BeliefJTBDFramed]  # From domain_sentiment

    # CRUD - Angles
    def create_angle(self, jtbd_framed_id, name, belief_statement, explanation) -> BeliefAngle
    def get_angles_for_jtbd(self, jtbd_framed_id) -> List[BeliefAngle]

    # CRUD - Plans
    def create_plan(self, ...) -> BeliefPlan
    def get_plan(self, plan_id) -> BeliefPlan
    def list_plans(self, brand_id, status) -> List[BeliefPlan]

    # Compilation
    def compile_plan(self, plan_id) -> Dict  # Returns compiled_payload
    def validate_phase(self, plan_id) -> List[str]  # Returns warnings

    # AI Suggestions (Claude Opus 4.5)
    async def suggest_offers(self, product_id) -> List[Dict]
    async def suggest_jtbd(self, persona_id, product_id) -> List[Dict]
    async def suggest_angles(self, jtbd_framed_id) -> List[Dict]
```

---

## Phase 5: INTEGRATION & TEST

*To be completed after Phase 4 approval*

---

## Phase 6: MERGE & CLEANUP

*To be completed after Phase 5 approval*

---

## Future Roadmap (PHASE_3-6)

### PHASE_3: Sub-Layer Activation
- Full UI for creating/managing sub-layers
- Sub-layer selection in plans
- Rules enforcement (Values/Identity restricted, never stack)

### PHASE_4: Mechanism & Problem Expansion
- Add `belief_mechanisms` table
- Add `belief_problems` table (problem → pain → symptoms)
- UI for mechanism/problem definition

### PHASE_5: Benefit & Messaging Density
- Add benefits layer
- Messaging density variations

### PHASE_6: Format Expansion & Scale
- Video format support
- Spend scaling recommendations
- Meta API integration for performance data
