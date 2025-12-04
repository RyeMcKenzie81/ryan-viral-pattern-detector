# Checkpoint: 4D Persona & Competitive Analysis Pipeline

**Date**: 2025-12-04
**Status**: Planning
**Feature**: Expand persona model + build competitive analysis pipeline

## Overview

Two interconnected features:
1. **4D Persona Framework** - Expanded persona data model for richer copy insights
2. **Competitive Analysis Pipeline** - Analyze competitor ads to extract their positioning

Both use the same 4D framework - one for own brand, one for competitors.

---

## 4D Persona Framework (from worksheet)

### 1. Persona Basics
- **Snapshot**: Big picture description
- **Demographics**: Age, gender, location, income, education
- **Behavior & Habits**: Daily life, routines, media consumption
- **Digital Presence**: Platforms, content consumption, online behavior
- **Product & Purchase Drivers**: What triggers purchases
- **Cultural Context**: Cultural background, values, norms
- **Typology Profile**: Personality type indicators

### 2. Psychographic Mapping

#### Transformation Map
| BEFORE (Current State) | AFTER (Desired State) |
|------------------------|----------------------|
| Pain points | Desired outcomes |
| Frustrations | Relief |
| Current identity | Aspirational identity |

#### Core Desires (10 Categories)
1. Survival, Enjoyment of Life, Life Extension
2. Enjoyment of Food and Beverages
3. Freedom from Fear, Pain, Worry, Regret, Past Failures, Shame and Guilt
4. Sexual Companionship
5. Comfortable Living Conditions
6. Superiority, Admiration, Winning, Status
7. Care and Protection of Loved Ones
8. Social Approval / Being Seen
9. Justice / Righting Unfairness
10. Self-Actualization

### 3. Identity
- **Self-narratives**: "Because I am X, therefore I Y"
- **Current self-image**: How they describe themselves
- **Past failures**: And who they blame
- **Desired self-image**: Wildest dreams, how they want to be seen
- **Identity artifacts**: Objects/brands associated with desired image

### 4. Social Dynamics / Relations
- People They Admire
- People They Envy
- People They Want to Impress
- People They Love / Feel Loyalty Toward
- People They Dislike or Feel Animosity Toward
- People They Feel Compared To
- People Who Influence Their Decisions
- People They Fear Being Judged By
- People They Want to Belong To
- People They Want to Distance From

### 5. Worldview
- Reality interpretation / worldview
- Stories about the world (heroes/villains, cause/effect)
- Core convictions, beliefs, values
- Forces of good vs forces of evil
- Cultural Zeitgeist they believe they're in
- Allergies (things that trigger negative reactions)

### 6. Domain Sentiment (Product-Specific)
- **Outcome/JTBD/Transformation** (emotional, social, functional)
- **Pain Points** (emotional, social, functional)
- **Desired features**
- **Failed solutions** they've tried
- **Buying objections** (emotional, social, functional)
- **Familiar promises** they've heard before

### 7. Purchase Behavior
- Symptoms of pain points
- Purchase activation events / deadlines
- Purchasing habits
- Decision making process
- Hacks and workarounds they currently use

### 8. 3D Objections
- Emotional Risks
- Barrier-to-Behavior

---

## Implementation Plan

### Phase 1: Database Schema

#### New Table: `personas_4d`
```sql
CREATE TABLE personas_4d (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),
    product_id UUID REFERENCES products(id),  -- Can link to specific product
    competitor_id UUID REFERENCES competitors(id),  -- NULL for own brand
    persona_type TEXT NOT NULL,  -- 'own_brand', 'product_specific', 'competitor'
    name TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT false,  -- Primary persona for this product/brand

    -- Basics
    snapshot TEXT,
    demographics JSONB,
    behavior_habits JSONB,
    digital_presence JSONB,
    purchase_drivers JSONB,
    cultural_context JSONB,
    typology_profile JSONB,

    -- Psychographic
    transformation_map JSONB,  -- {before: [], after: []}
    desires JSONB,  -- {category: [instances with verbiage]}

    -- Identity
    self_narratives TEXT[],
    current_self_image TEXT,
    past_failures JSONB,
    desired_self_image TEXT,
    identity_artifacts TEXT[],

    -- Social Dynamics
    social_relations JSONB,  -- {admire: [], envy: [], impress: [], ...}

    -- Worldview
    worldview TEXT,
    world_stories TEXT,
    core_values TEXT[],
    forces_of_good TEXT[],
    forces_of_evil TEXT[],
    cultural_zeitgeist TEXT,
    allergies JSONB,  -- {trigger: reaction}

    -- Domain Sentiment
    outcomes_jtbd JSONB,  -- {emotional: [], social: [], functional: []}
    pain_points JSONB,
    desired_features TEXT[],
    failed_solutions TEXT[],
    buying_objections JSONB,
    familiar_promises TEXT[],

    -- Purchase Behavior
    pain_symptoms TEXT[],
    activation_events TEXT[],
    purchasing_habits TEXT,
    decision_process TEXT,
    current_workarounds TEXT[],

    -- 3D Objections
    emotional_risks TEXT[],
    barriers_to_behavior TEXT[],

    -- Meta
    source_type TEXT,  -- 'manual', 'ai_generated', 'competitor_analysis'
    source_data JSONB,  -- Raw analysis data
    confidence_score FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Junction table for products with multiple personas
CREATE TABLE product_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    persona_id UUID REFERENCES personas_4d(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT false,
    weight FLOAT DEFAULT 1.0,  -- For weighted persona targeting
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id, persona_id)
);

CREATE INDEX idx_product_personas_product ON product_personas(product_id);
CREATE INDEX idx_product_personas_persona ON product_personas(persona_id);

CREATE TABLE competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),  -- Our brand tracking this competitor
    name TEXT NOT NULL,
    facebook_page_id TEXT,
    website_url TEXT,
    ad_library_url TEXT,
    industry TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE competitor_ads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id),
    ad_archive_id TEXT UNIQUE,
    page_name TEXT,
    ad_body TEXT,
    ad_title TEXT,
    link_url TEXT,
    cta_text TEXT,
    started_running DATE,
    is_active BOOLEAN,
    platforms TEXT[],
    snapshot_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE competitor_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_ad_id UUID REFERENCES competitor_ads(id),
    asset_type TEXT,  -- 'image', 'video'
    storage_path TEXT,
    original_url TEXT,
    mime_type TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE competitor_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id),
    analysis_type TEXT,  -- 'ad_creative', 'landing_page', 'persona_extraction'
    source_ad_id UUID REFERENCES competitor_ads(id),
    raw_response JSONB,
    extracted_data JSONB,
    model_used TEXT,
    tokens_used INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Phase 2: Competitive Analysis Service

**File**: `viraltracker/services/competitive_analysis_service.py`

```python
class CompetitiveAnalysisService:
    """Analyze competitor ads and extract positioning."""

    async def add_competitor(self, brand_id, name, ad_library_url, website_url=None)
    async def scrape_competitor_ads(self, competitor_id, max_ads=50, images_only=True)
    async def analyze_competitor_ad(self, ad_id) -> Dict  # Extract messaging, hooks, benefits
    async def analyze_landing_page(self, url) -> Dict  # Scrape and analyze LP
    async def extract_competitor_persona(self, competitor_id) -> Dict  # 4D persona from ads
    async def generate_competitive_report(self, competitor_id) -> Dict  # Full report
```

### Phase 3: 4D Persona Analysis Prompts

#### Competitor Ad Analysis Prompt
Analyzes ad creative + copy to extract:
- Products/offers mentioned
- Benefits promised
- Pain points addressed
- Desires appealed to
- Target persona signals
- Messaging patterns
- Hooks and angles

#### Landing Page Analysis Prompt
Scrapes and analyzes landing page to extract:
- Product details
- Pricing/offers
- Social proof
- Objection handling
- USPs
- Guarantees

#### Persona Synthesis Prompt
Combines all analyses to build 4D persona:
- Infers target customer from messaging
- Maps desires to specific verbiage
- Identifies identity appeals
- Extracts social dynamics
- Determines worldview/values
- Catalogs domain sentiment

### Phase 4: UI Components

#### Competitor Management Page
- Add competitors (name, Ad Library URL, website)
- List competitors with scrape status
- Trigger scrape + analysis
- View competitive reports

#### 4D Persona Builder
- Form-based entry for manual personas
- AI-assisted population from ad analysis
- Side-by-side own brand vs competitor view
- Export to copy brief format

### Phase 5: Integration with Ad Creation

Use 4D persona data in:
- Hook generation (appeal to specific desires)
- Copy writing (use their language/verbiage)
- Angle selection (target specific pain points)
- Objection handling (address their specific barriers)

**Ad Creation Flow Enhancement:**
```
1. Select Product → Show linked personas
2. Select Target Persona (or use primary)
3. Persona data injected into prompts:
   - Desires to appeal to
   - Language/verbiage to use
   - Pain points to address
   - Identity narratives to leverage
   - Objections to preempt
```

### Phase 6: Existing Product Migration

For existing products:
1. AI-generate initial 4D persona from existing `target_audience` + product data
2. User reviews and enriches via Persona Builder UI
3. Link personas to products via `product_personas` junction table
4. Multiple personas per product supported (e.g., "Budget-conscious Mom", "Premium Dad")

---

## Workflow: Competitive Analysis Pipeline

```
1. Add Competitor
   └─> Store competitor details + Ad Library URL

2. Scrape Competitor Ads
   └─> Use existing Facebook Ad Library scraper
   └─> Store ads + download assets

3. Analyze Each Ad
   └─> Vision analysis (creative style, hooks, format)
   └─> Copy analysis (messaging, benefits, pain points)
   └─> Store extracted data

4. Analyze Landing Pages (optional)
   └─> Scrape key landing pages
   └─> Extract product info, offers, social proof

5. Synthesize 4D Persona
   └─> Combine all analyses
   └─> Generate competitor's target persona
   └─> Map to 4D framework

6. Generate Competitive Report
   └─> Products & pricing
   └─> Messaging strategy
   └─> Target persona
   └─> Hooks & angles used
   └─> Recommendations for differentiation
```

---

## Key Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `sql/2025-12-04_4d_persona_schema.sql` | Create | Database schema |
| `viraltracker/services/competitive_analysis_service.py` | Create | Competitor analysis logic |
| `viraltracker/services/persona_service.py` | Create | 4D persona CRUD + AI generation |
| `viraltracker/ui/pages/XX_Competitors.py` | Create | Competitor management UI |
| `viraltracker/ui/pages/XX_Personas.py` | Create | 4D persona builder UI |
| `docs/reference/4d_persona_framework.md` | Create | Reference doc for RAG |

---

## Questions to Resolve

1. **Landing page scraping**: Use Firecrawl, Jina, or build custom?
2. **Analysis model**: Claude for accuracy or Gemini for cost?
3. **Persona storage**: One persona per competitor or multiple segments?
4. **UI priority**: Competitor analysis first or persona builder first?

---

## Success Criteria

### Own Brand Personas
- [ ] Can create multiple 4D personas per product
- [ ] Can set primary persona for a product
- [ ] AI can generate initial persona from existing product data
- [ ] Persona Builder UI for manual enrichment
- [ ] Ad creation uses selected persona for copy generation

### Competitive Analysis
- [ ] Can add a competitor and scrape their Ad Library
- [ ] AI extracts products, benefits, pain points from competitor ads
- [ ] Can generate 4D persona for competitor's target customer
- [ ] Competitive report shows differentiation opportunities

### Integration
- [ ] Personas inform hook generation (specific desires)
- [ ] Personas inform copy writing (their language/verbiage)
- [ ] Personas inform objection handling (their specific barriers)
- [ ] Side-by-side view: own persona vs competitor persona

---

## Related Docs

- `/docs/reference/consumer_awareness_levels.md` - Awareness level framework
- `/viraltracker/services/brand_research_service.py` - Existing analysis code
- `/viraltracker/services/template_queue_service.py` - Scraper integration example
