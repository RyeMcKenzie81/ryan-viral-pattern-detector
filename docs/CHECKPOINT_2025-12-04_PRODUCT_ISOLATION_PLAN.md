# Checkpoint: Product Isolation & Competitive Analysis Plan

**Date**: 2025-12-04
**Branch**: `feature/brand-research-pipeline`
**Status**: Planning - Consolidated Roadmap

---

## Executive Summary

This document consolidates the remaining work for the Brand Research Pipeline, adding **product-level isolation** to ensure 4D personas and ad analyses are properly segmented by product (not just brand).

### Core Problem
When a brand has multiple products (e.g., Wonder Paws has Plaque Defense, Omega Max, Collange), Facebook ad scraping captures ALL ads at the brand level. Without product isolation:
- 4D personas mix insights from different product audiences
- Ad creative analysis doesn't distinguish which product an ad promotes
- Competitive analysis can't track competitor product lines

### Solution: Multi-Pass URL-Based Product Identification

1. **First Pass**: Extract landing page URLs from ads
2. **Second Pass**: Match URLs to known products or flag for review
3. **Third Pass**: Run product-specific AI analysis
4. **Result**: Hierarchical personas (brand-level AND product-level)

### Persona Hierarchy
```
Brand (Wonder Paws)
├── Brand-Level 4D Persona (aggregated insights from ALL products)
│
├── Product: Plaque Defense
│   └── Product-Level 4D Persona (isolated to dental powder ads)
│
├── Product: Omega Max 3X
│   └── Product-Level 4D Persona (isolated to fish oil ads)
│
└── Product: Collange
    └── Product-Level 4D Persona (isolated to collagen ads)
```

**Use Cases:**
- **Brand-level persona**: Overall brand messaging, brand voice, cross-product campaigns
- **Product-level persona**: Product-specific copy, targeted ads, competitive positioning

---

## What's Already Built (Complete)

### Brand Research Pipeline (Phases 0-3) ✅
- Ad scraping via Apify → `facebook_ads` table
- Asset download → `scraped_ad_assets` table, Supabase storage
- Image analysis with Claude Vision → `brand_ad_analysis` table
- Synthesis → `brand_research_synthesis` table
- Template queue with approval UI
- Ad Creator integration with scraped templates

### 4D Persona System ✅
- `personas_4d` table with full 4D framework schema
- `PersonaService` for CRUD and AI generation
- Persona Builder UI
- Basic integration with Ad Creation

### Video Analysis Infrastructure ✅
- `VideoAnalyzer` class (`viraltracker/analysis/video_analyzer.py`)
- Gemini video upload and analysis
- Hook extraction, storyboard, viral factors
- Product-aware adaptation prompts
- Saves to `video_analysis` table

---

## What Needs to Be Built

### Phase 4: Product URL Mapping & Identification

#### 4.1 Database Schema
```sql
-- Product landing page URLs
CREATE TABLE product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    url_pattern TEXT NOT NULL,  -- Can be exact URL or pattern (e.g., "mywonderpaws.com/products/plaque*")
    is_primary BOOLEAN DEFAULT false,
    match_type TEXT DEFAULT 'exact' CHECK (match_type IN ('exact', 'prefix', 'contains', 'regex')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id, url_pattern)
);

CREATE INDEX idx_product_urls_product ON product_urls(product_id);
CREATE INDEX idx_product_urls_pattern ON product_urls(url_pattern);

-- Track which product each ad promotes
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_match_confidence FLOAT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_match_method TEXT;  -- 'url', 'ai', 'manual'

CREATE INDEX idx_facebook_ads_product ON facebook_ads(product_id);

-- Queue for unmatched URLs needing review
CREATE TABLE url_review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),
    url TEXT NOT NULL,
    occurrence_count INT DEFAULT 1,
    sample_ad_ids UUID[],  -- Sample ads using this URL
    suggested_product_id UUID REFERENCES products(id),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'assigned', 'new_product', 'ignored')),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, url)
);
```

#### 4.2 ProductURLService
```python
# viraltracker/services/product_url_service.py

class ProductURLService:
    """Service for URL-to-product mapping."""

    def add_product_url(self, product_id: UUID, url: str, match_type: str = 'exact') -> Dict
    def match_url_to_product(self, url: str, brand_id: UUID) -> Optional[Tuple[UUID, float]]
    def get_unmatched_urls(self, brand_id: UUID) -> List[Dict]
    def assign_url_to_product(self, url: str, product_id: UUID) -> None
    def bulk_match_ads(self, brand_id: UUID) -> Dict[str, int]  # Returns match stats
```

#### 4.3 URL Review UI
New Streamlit page: `XX_🔗_URL_Mapping.py`
- Show unmatched URLs grouped by brand
- Preview sample ads for each URL
- Options: Assign to existing product / Create new product / Ignore
- Bulk operations for similar URLs

---

### Phase 5: Facebook Ad Video Analysis

#### 5.1 Adapt VideoAnalyzer for Facebook Ads
The existing `VideoAnalyzer` is built for scraped social videos. Adapt for Facebook ads:

```python
# viraltracker/services/ad_video_analysis_service.py

class AdVideoAnalysisService:
    """Analyze Facebook ad videos using Gemini."""

    def __init__(self):
        self.video_analyzer = VideoAnalyzer(...)  # Reuse core logic

    async def analyze_ad_video(
        self,
        asset_id: UUID,
        brand_id: UUID,
        product_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze a Facebook ad video.

        Extracts:
        - Full transcript
        - Hook (first 3 seconds)
        - Product identification (if not provided)
        - Benefits/USPs mentioned
        - Pain points addressed
        - CTA and offer
        - Visual style analysis
        """

    async def analyze_batch(self, asset_ids: List[UUID], brand_id: UUID) -> List[Dict]

    def get_analysis_prompt(self, product_context: Optional[Dict]) -> str:
        """Custom prompt for ad analysis (different from viral video analysis)."""
```

#### 5.2 Ad-Specific Analysis Prompt
```
Analyze this Facebook ad video. Extract:

1. PRODUCT IDENTIFICATION
   - What product is being advertised?
   - Product category (supplement, beauty, pet, etc.)
   - Key identifying features

2. MESSAGING ANALYSIS
   - Main hook/opening (transcript + visual)
   - Benefits promised (list)
   - Pain points addressed (list)
   - USPs/differentiators
   - Social proof elements
   - CTA and offer

3. TARGET AUDIENCE SIGNALS
   - Demographics implied
   - Psychographics/values
   - Desires appealed to
   - Objections addressed

4. CREATIVE STYLE
   - Format (UGC, testimonial, demo, etc.)
   - Tone (professional, casual, urgent, etc.)
   - Visual style notes
   - Audio/music style

Return as JSON with these sections.
```

---

### Phase 6: Competitive Analysis Pipeline

#### 6.1 Database Schema
```sql
-- Competitors
CREATE TABLE competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),  -- Our brand tracking this competitor
    name TEXT NOT NULL,
    website_url TEXT,
    facebook_page_id TEXT,
    ad_library_url TEXT,
    industry TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Competitor products (their product lines)
CREATE TABLE competitor_products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    website_url TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Competitor product URLs (same pattern as own products)
CREATE TABLE competitor_product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE CASCADE,
    url_pattern TEXT NOT NULL,
    match_type TEXT DEFAULT 'exact',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competitor_product_id, url_pattern)
);

-- Link scraped ads to competitors
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS competitor_id UUID REFERENCES competitors(id);
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id);
```

#### 6.2 CompetitiveAnalysisService
```python
# viraltracker/services/competitive_analysis_service.py

class CompetitiveAnalysisService:
    """Analyze competitor ads and extract positioning."""

    async def add_competitor(
        self, brand_id: UUID, name: str, ad_library_url: str, website_url: Optional[str] = None
    ) -> Dict

    async def scrape_competitor_ads(
        self, competitor_id: UUID, max_ads: int = 50
    ) -> List[Dict]

    async def identify_competitor_products(
        self, competitor_id: UUID
    ) -> List[Dict]:
        """First pass: extract URLs and cluster into product groups."""

    async def analyze_competitor_ad(
        self, ad_id: UUID, competitor_product_id: Optional[UUID] = None
    ) -> Dict

    async def extract_competitor_persona(
        self, competitor_id: UUID, competitor_product_id: Optional[UUID] = None
    ) -> Dict:
        """Generate 4D persona from competitor's ads."""

    async def generate_competitive_report(
        self, brand_id: UUID, competitor_id: UUID
    ) -> Dict:
        """
        Full competitive report:
        - Their products vs ours
        - Messaging comparison
        - Persona comparison
        - Hook/angle analysis
        - Differentiation opportunities
        """
```

#### 6.3 Competitor Management UI
New Streamlit page: `XX_🎯_Competitors.py`
- Add/edit competitors
- Trigger ad scraping
- View competitor products (auto-discovered)
- Run analysis
- View competitive reports

---

### Phase 7: Integration & Synthesis

#### 7.1 Update PersonaService for Hierarchical Personas
```python
# Modify persona_service.py to support both levels

async def generate_persona(
    self,
    brand_id: UUID,
    product_id: Optional[UUID] = None,  # None = brand-level
    name: str = "Generated Persona"
) -> Dict:
    """
    Generate 4D persona at brand or product level.

    Args:
        brand_id: Brand to generate persona for
        product_id: If provided, generate product-specific persona.
                   If None, generate brand-level persona (all products).
        name: Persona name
    """
    if product_id:
        # Product-level: Filter insights to specific product
        insights = await self._gather_product_insights(brand_id, product_id)
    else:
        # Brand-level: Aggregate insights from ALL products
        insights = await self._gather_brand_insights(brand_id)

    return await self._generate_with_ai(insights, name)

async def _gather_product_insights(self, brand_id: UUID, product_id: UUID) -> Dict:
    """Gather insights FILTERED BY PRODUCT."""

    # Get product-specific image analyses
    images = self.supabase.table("product_images")
        .select("*")
        .eq("product_id", str(product_id))
        .execute()

    # Get Facebook ad analyses for THIS PRODUCT ONLY
    ad_analyses = self.supabase.table("brand_ad_analysis")
        .select("*, facebook_ads!inner(product_id)")
        .eq("facebook_ads.product_id", str(product_id))
        .execute()

    return {"images": images.data, "ad_analyses": ad_analyses.data}

async def _gather_brand_insights(self, brand_id: UUID) -> Dict:
    """Gather insights from ALL products (brand-level)."""

    # Get all product images for brand
    images = self.supabase.table("product_images")
        .select("*, products!inner(brand_id)")
        .eq("products.brand_id", str(brand_id))
        .execute()

    # Get all Facebook ad analyses for brand
    ad_analyses = self.supabase.table("brand_ad_analysis")
        .select("*, facebook_ads!inner(brand_id)")
        .eq("facebook_ads.brand_id", str(brand_id))
        .execute()

    return {"images": images.data, "ad_analyses": ad_analyses.data}
```

#### 7.1.1 Database Schema for Hierarchical Personas
```sql
-- Update personas_4d to support both levels
ALTER TABLE personas_4d ADD COLUMN IF NOT EXISTS persona_level TEXT
    DEFAULT 'product' CHECK (persona_level IN ('brand', 'product'));

-- brand_id is required, product_id is optional (null = brand-level)
-- Existing constraint: product_id can be null for brand-level personas

CREATE INDEX idx_personas_4d_level ON personas_4d(brand_id, persona_level);
```

#### 7.2 Update Ad Creation Flow
```python
# When generating ads, use product-specific persona

1. Select Product → Load product's primary persona
2. Persona data includes product-specific:
   - Desires and language
   - Pain points
   - Objections
   - Competitor differentiation
3. Generate copy using product-isolated insights
```

---

## Implementation Order

### Sprint 1: Product URL Mapping (Foundation)
1. Create `product_urls` table migration
2. Implement `ProductURLService`
3. Build URL Review UI
4. Add initial URLs for existing products (Wonder Paws)
5. Run first pass matching on existing ads

### Sprint 2: Video Analysis Integration
1. Create `AdVideoAnalysisService` (reusing VideoAnalyzer)
2. Add ad-specific analysis prompt
3. Integrate with brand onboarding pipeline
4. Test with Wonder Paws video ads

### Sprint 3: Competitive Analysis
1. Create competitor tables migration
2. Implement `CompetitiveAnalysisService`
3. Build Competitor Management UI
4. Test with one competitor

### Sprint 4: Persona Isolation & Integration
1. Update `PersonaService._gather_ad_insights()` for product filtering
2. Update ad creation to use product-specific personas
3. Add competitive insights to persona generation
4. End-to-end test: product-isolated persona → ad generation

---

## Data Flow Diagram

```
                                    SCRAPING
                                       │
                                       ▼
                              ┌─────────────────┐
                              │  facebook_ads   │
                              │  (raw scraped)  │
                              └────────┬────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
            ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
            │  PASS 1       │  │  PASS 1       │  │  PASS 1       │
            │  Extract URLs │  │  Download     │  │  Extract copy │
            └───────┬───────┘  │  Assets       │  └───────────────┘
                    │          └───────┬───────┘
                    ▼                  │
            ┌───────────────┐          │
            │  PASS 2       │          │
            │  Match URLs   │          │
            │  to Products  │          │
            └───────┬───────┘          │
                    │                  │
           ┌────────┴────────┐         │
           │                 │         │
           ▼                 ▼         │
    ┌─────────────┐   ┌─────────────┐  │
    │  Matched    │   │  Unmatched  │  │
    │  (tagged)   │   │  (review)   │  │
    └──────┬──────┘   └──────┬──────┘  │
           │                 │         │
           │    ┌────────────┘         │
           │    ▼                      │
           │  URL Review UI            │
           │    │                      │
           │    └──► Assign/Create     │
           │                           │
           └───────────┬───────────────┘
                       │
                       ▼
               ┌───────────────┐
               │  PASS 3       │
               │  AI Analysis  │
               │  (per product)│
               └───────┬───────┘
                       │
           ┌───────────┴───────────┐
           │                       │
           ▼                       ▼
    ┌─────────────┐         ┌─────────────┐
    │  Images     │         │  Videos     │
    │  (Claude)   │         │  (Gemini)   │
    └──────┬──────┘         └──────┬──────┘
           │                       │
           └───────────┬───────────┘
                       │
                       ▼
               ┌───────────────┐
               │  SYNTHESIS    │
               │  (per product)│
               └───────┬───────┘
                       │
                       ▼
               ┌───────────────┐
               │  4D PERSONA   │
               │  (product-    │
               │   isolated)   │
               └───────────────┘
```

---

## Existing Code to Reuse

| Component | Location | Reuse Strategy |
|-----------|----------|----------------|
| Video analysis | `viraltracker/analysis/video_analyzer.py` | Wrap in new service, adapt prompt |
| Gemini client | `viraltracker/services/gemini_service.py` | Use directly |
| Facebook scraping | `viraltracker/services/facebook_service.py` | Already working |
| Asset download | `viraltracker/services/ad_scraping_service.py` | Already working |
| Image analysis | `viraltracker/services/brand_research_service.py` | Add product filtering |
| Persona generation | `viraltracker/services/persona_service.py` | Update for product isolation |

---

## Testing Strategy

### Unit Tests
- URL pattern matching (exact, prefix, contains, regex)
- Product identification from URL
- Video analysis parsing

### Integration Tests
- Full scrape → URL extract → match → analyze flow
- Competitor scrape → product discovery → persona extraction
- Product-isolated persona generation

### E2E Tests
- Wonder Paws: Scrape → identify 3 products → generate product-specific personas
- Competitor: Add → scrape → discover products → generate competitive report

---

## Success Criteria

### Product Isolation
- [ ] Can add multiple URLs per product
- [ ] Ads auto-tagged with product_id via URL matching
- [ ] Unmatched URLs queued for review
- [ ] URL Review UI functional
- [ ] 4D personas generated per-product (not brand-level)

### Video Analysis
- [ ] Facebook ad videos analyzed with Gemini
- [ ] Transcripts extracted
- [ ] Product identification from video content
- [ ] Results stored in database

### Competitive Analysis
- [ ] Can add competitors and scrape their ads
- [ ] Competitor products auto-discovered from URLs
- [ ] Competitor personas generated
- [ ] Competitive reports show differentiation opportunities

### Integration
- [ ] Ad creation uses product-specific persona
- [ ] Persona includes competitive differentiation
- [ ] Full flow: scrape → analyze → persona → ad generation

---

## Architecture Compliance (CRITICAL)

All implementations MUST follow the pydantic-ai patterns defined in:
- `/CLAUDE.md` - Development guidelines
- `/docs/CLAUDE_CODE_GUIDE.md` - Tool development patterns
- `/docs/ARCHITECTURE.md` - System design

### Three-Layer Architecture
```
Agent Layer (PydanticAI) → Tools = thin orchestration, LLM decides when to call
Service Layer           → Business logic, deterministic preprocessing, reusable
Interface Layer         → CLI, API, Streamlit UI (all call services)
```

### Thin Tools Pattern
```python
# ✅ CORRECT: Tool calls service
@agent.tool(metadata=ToolMetadata(...))
async def match_ad_to_product(ctx: RunContext[AgentDependencies], ad_id: str):
    """Match a Facebook ad to a product based on landing page URL."""
    return ctx.deps.product_url.match_ad(UUID(ad_id))

# ❌ WRONG: Business logic in tool
@agent.tool(...)
async def match_ad_to_product(ctx: RunContext[AgentDependencies], ad_id: str):
    url = extract_url_from_snapshot(ad)  # Should be in service!
    return find_matching_product(url)     # Should be in service!
```

### Service Registration
All new services MUST be added to `AgentDependencies`:
```python
# viraltracker/agent/dependencies.py
@dataclass
class AgentDependencies:
    # ... existing services ...
    product_url: ProductURLService
    ad_video_analysis: AdVideoAnalysisService
    competitive_analysis: CompetitiveAnalysisService
```

### UI Pattern (Direct Service Calls)
Streamlit UI pages call services directly (user-driven flow):
```python
# viraltracker/ui/pages/XX_URL_Mapping.py
def render_url_review():
    service = get_product_url_service()
    unmatched = service.get_unmatched_urls(brand_id)
    # Render UI, handle user actions via service calls
```

### When to Use pydantic-graph
- **Use pydantic-graph**: Autonomous AI-driven pipelines (brand onboarding, batch analysis)
- **Use direct service calls**: User-driven flows (URL review, template approval, manual triggers)

---

## Related Documents

- `/docs/archive/CHECKPOINT_BRAND_RESEARCH_PIPELINE.md` - Original pipeline plan
- `/docs/archive/CHECKPOINT_4D_PERSONA_COMPETITIVE_ANALYSIS.md` - 4D persona schema
- `/docs/reference/4d_persona_framework.md` - 4D framework reference
- `/viraltracker/analysis/video_analyzer.py` - Existing video analysis code
- `/CLAUDE.md` - Development guidelines (required reading)
- `/docs/CLAUDE_CODE_GUIDE.md` - Tool development patterns
- `/docs/ARCHITECTURE.md` - System architecture

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-04 | 1.0.0 | Initial consolidated plan |
