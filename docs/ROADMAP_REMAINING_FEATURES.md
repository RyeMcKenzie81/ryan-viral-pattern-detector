# ViralTracker - Remaining Features Roadmap

**Date**: 2025-12-08
**Branch**: `feature/brand-research-pipeline`
**Status**: Sprint 3 Complete, Sprint 3.5 In Progress

---

## Completed Features

### Sprint 1: URL Mapping (Complete)
- Product URL service for mapping landing pages to products
- URL review queue for unmatched ads
- Bulk matching operations
- UI page: `18_🔗_URL_Mapping.py`

### Sprint 2: Brand Research Pipeline (Complete)
- Video analysis with Gemini (transcripts, hooks, persona signals)
- Image analysis with Gemini Vision
- Ad copy analysis for messaging patterns
- Asset download from ad snapshots
- Persona synthesis with multi-segment detection
- UI page: `19_🔬_Brand_Research.py`
- 4D Persona builder: `17_👤_Personas.py`

### Sprint 3: Landing Page Scraping (Complete)
- WebScrapingService using FireCrawl API
- Landing page scraping from product URLs
- Landing page analysis for persona signals
- Product filtering across all operations
- Full 4D persona fields (10 social relations, purchase behavior)

---

## Remaining Features

### Sprint 3.5: Amazon Review Scraping (High Priority) ← CURRENT

**Purpose**: Enrich 4D personas with authentic customer language from Amazon reviews.

**Why This Matters**:
- Ads show what marketers *think* resonates
- Reviews show what customers *actually* feel and say
- Real emotional language for hooks and copy
- Unbiased pain points and desires
- Authentic objections and purchase triggers

**Tasks**:
1. Create `AmazonReviewService`
   - Scrape reviews from Amazon product pages
   - Extract: rating, title, body, verified purchase, helpful votes
   - Handle pagination and rate limiting
   - Store in `amazon_reviews` table

2. Review Analysis with Claude
   - Extract pain points, desires, language patterns
   - Categorize by sentiment and topic
   - Identify common objections and triggers
   - Pull exact quotes for ad copy

3. UI Integration
   - Add Amazon URL input to Brand Research or URL Mapping
   - "Scrape Reviews" button
   - Display review insights
   - Include in persona synthesis

4. Integrate into Persona Synthesis
   - Feed review analysis into persona generation
   - Weight authentic customer language highly
   - Extract verbatim quotes for copy briefs

**Database Changes**:
```sql
CREATE TABLE amazon_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),
    product_id UUID REFERENCES products(id),
    amazon_url TEXT NOT NULL,
    amazon_asin TEXT,

    -- Review data
    rating INTEGER,
    title TEXT,
    body TEXT,
    author TEXT,
    review_date DATE,
    verified_purchase BOOLEAN,
    helpful_votes INTEGER,

    -- AI analysis
    sentiment TEXT,
    pain_points TEXT[],
    desires TEXT[],
    key_phrases TEXT[],
    analysis_raw JSONB,

    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Challenges**: (to be discussed)
- Amazon anti-scraping measures
- Rate limiting
- Review authenticity filtering
- ASIN extraction from URLs

---

### Sprint 4: Competitive Analysis Pipeline (Medium Priority)

**Purpose**: Enrich brand research with landing page data from ads.

**Tasks**:
1. Add `scrape_landing_page()` method to BrandResearchService
   - Use FireCrawl or Jina to scrape `link_url` from ads
   - Extract: product info, pricing, offers, testimonials, USPs
   - Store in new `brand_landing_pages` table

2. Add landing page analysis
   - Analyze scraped content with Claude
   - Extract copy patterns, objection handling, social proof
   - Feed into persona synthesis

3. UI Integration
   - Add "Scrape Landing Pages" button to Brand Research page
   - Display scraped page summaries
   - Include LP insights in persona synthesis

**Database Changes**:
```sql
CREATE TABLE brand_landing_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    url TEXT NOT NULL,

    -- Scraped content
    page_title TEXT,
    meta_description TEXT,
    raw_markdown TEXT,

    -- AI analysis
    products JSONB DEFAULT '[]',
    offers JSONB DEFAULT '[]',
    testimonials JSONB DEFAULT '[]',
    usps TEXT[],
    objection_handling JSONB DEFAULT '[]',
    copy_patterns JSONB DEFAULT '{}',

    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### Sprint 4: Competitive Analysis Pipeline (Medium Priority)

**Purpose**: Analyze competitor ads to build competitor personas and competitive intelligence.

**Reference**: `docs/plans/4D_PERSONA_IMPLEMENTATION_PLAN.md` Phase 4

**Tasks**:
1. Create `CompetitiveAnalysisService`
   - `create_competitor()` - Add competitor to track
   - `scrape_competitor_ads()` - Scrape from Ad Library
   - `download_competitor_assets()` - Download images/videos
   - `analyze_competitor_ads()` - Run Claude Vision analysis
   - `analyze_landing_pages()` - Scrape competitor LPs
   - `synthesize_competitor_persona()` - Build 4D persona
   - `generate_competitive_report()` - Full report

2. Create Pydantic-Graph Pipeline
   - `viraltracker/pipelines/competitive_analysis.py`
   - Autonomous multi-step workflow
   - ScrapeAds → DownloadAssets → AnalyzeAds → AnalyzeLPs → SynthesizePersona → Report

3. UI Page
   - `20_🔍_Competitors.py` (or renumber as needed)
   - Add competitor form
   - Trigger analysis pipeline
   - View competitive reports
   - Compare own vs competitor personas

**Database Changes**:
```sql
-- See docs/plans/4D_PERSONA_IMPLEMENTATION_PLAN.md for full schema:
-- competitors, competitor_ads, competitor_ad_assets,
-- competitor_ad_analysis, competitor_landing_pages
```

---

### Sprint 5: Ad Creation Integration (Medium Priority)

**Purpose**: Use personas in ad generation workflow.

**Tasks**:
1. Add persona tool to ad_creation_agent
   ```python
   @ad_creation_agent.tool(...)
   async def get_persona_for_copy(ctx, product_id, persona_id=None):
       """Get persona data formatted for ad copy generation."""
       return ctx.deps.persona.export_for_copy_brief(persona_id)
   ```

2. Wire persona selection into ad creation workflow
   - Select persona in Ad Creator UI
   - Pass persona to copy generation
   - Use persona language in hooks and body copy

3. Test persona-aware ad generation
   - Verify persona pain points appear in copy
   - Verify persona language/verbiage is used
   - Verify transformation messaging is present

---

### Sprint 6: Enhancements (Low Priority)

**Tasks**:
1. Batch analysis progress bars
   - Show progress during video/image analysis
   - Estimate time remaining

2. Cost tracking
   - Track API costs per analysis
   - Show cost per brand/product
   - Budget alerts

3. Analysis quality scoring
   - Score analyses by completeness
   - Flag low-quality analyses for review

4. Persona comparison tools
   - Compare own vs competitor personas
   - Identify gaps and opportunities
   - Visualize persona differences

---

## File Reference

### Services
| File | Status | Purpose |
|------|--------|---------|
| `brand_research_service.py` | ✅ Done | Video/image/copy/LP analysis, synthesis |
| `persona_service.py` | ✅ Done | 4D persona CRUD |
| `product_url_service.py` | ✅ Done | URL-product mapping |
| `web_scraping_service.py` | ✅ Done | Generic FireCrawl scraping |
| `amazon_review_service.py` | 🔄 Sprint 3.5 | Amazon review scraping |
| `competitive_analysis_service.py` | ❌ Not started | Competitor analysis |

### UI Pages
| File | Status | Purpose |
|------|--------|---------|
| `17_👤_Personas.py` | ✅ Done | Persona builder |
| `18_🔗_URL_Mapping.py` | ✅ Done | URL review queue |
| `19_🔬_Brand_Research.py` | ✅ Done | Brand analysis & synthesis |
| `20_🔍_Competitors.py` | ❌ Not started | Competitor management |

### Pipelines
| File | Status | Purpose |
|------|--------|---------|
| `competitive_analysis.py` | ❌ Not started | Pydantic-graph pipeline |

---

## Dependencies & APIs

| Service | Used For | Status |
|---------|----------|--------|
| Gemini API | Video & image analysis | ✅ Working |
| Anthropic Claude | Copy analysis, synthesis | ✅ Working |
| FireCrawl | Landing page scraping | ✅ Working |
| Supabase Storage | Asset storage | ✅ Working |
| Amazon Scraper | Review scraping | 🔄 Sprint 3.5 |

---

## Related Documentation

- [4D Persona Implementation Plan](plans/4D_PERSONA_IMPLEMENTATION_PLAN.md) - Full schema and pipeline design
- [Sprint 1 Checkpoint](CHECKPOINT_2025-12-04_SPRINT1_URL_MAPPING_COMPLETE.md)
- [Sprint 2 Analysis Checkpoint](CHECKPOINT_2025-12-05_SPRINT2_BRAND_RESEARCH_ANALYSIS.md)
- [Sprint 2 Complete Checkpoint](CHECKPOINT_2025-12-05_SPRINT2_COMPLETE.md)
