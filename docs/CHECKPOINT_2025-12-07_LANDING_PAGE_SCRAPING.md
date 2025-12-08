# Checkpoint: Landing Page Scraping with FireCrawl (Sprint 3)

**Date**: 2025-12-07
**Branch**: `feature/brand-research-pipeline`
**Status**: Complete - ready for testing

---

## Session Summary

Implemented Sprint 3: Landing Page Scraping. Created a generic `WebScrapingService` using FireCrawl and integrated it into the Brand Research pipeline.

---

## New Files Created

### 1. WebScrapingService (`viraltracker/services/web_scraping_service.py`)

Generic, reusable web scraping service using FireCrawl API.

**Key Methods:**
```python
class WebScrapingService:
    def scrape_url(url, formats=["markdown"], only_main_content=True, wait_for=0, timeout=30000) -> ScrapeResult
    async def scrape_url_async(...) -> ScrapeResult
    def batch_scrape(urls, ...) -> List[ScrapeResult]
    async def batch_scrape_async(urls, ...) -> List[ScrapeResult]
    def extract_structured(url, schema=None, prompt=None) -> ExtractResult
    async def extract_structured_async(...) -> ExtractResult
    def batch_extract(urls, ...) -> List[ExtractResult]
```

**Pre-built Schemas:**
- `LANDING_PAGE_SCHEMA` - For landing pages (pricing, testimonials, benefits, etc.)
- `PRODUCT_PAGE_SCHEMA` - For product pages
- `COMPETITOR_PAGE_SCHEMA` - For competitor analysis

**Reusable For:**
- Landing page scraping (current use)
- Competitor website analysis (Sprint 4)
- Product page enrichment
- Any tool needing web content

### 2. Database Migration (`migrations/2025-12-07_brand_landing_pages.sql`)

```sql
CREATE TABLE brand_landing_pages (
    id UUID PRIMARY KEY,
    brand_id UUID REFERENCES brands(id),
    url TEXT NOT NULL,
    source_ad_id UUID REFERENCES facebook_ads(id),

    -- Scraped content
    page_title TEXT,
    meta_description TEXT,
    raw_markdown TEXT,

    -- AI-extracted structured data
    extracted_data JSONB,
    product_name TEXT,
    pricing JSONB,
    benefits TEXT[],
    features TEXT[],
    testimonials JSONB,
    social_proof TEXT[],
    call_to_action TEXT,
    objection_handling JSONB,
    guarantee TEXT,
    urgency_elements TEXT[],

    -- AI analysis
    analysis_raw JSONB,
    copy_patterns JSONB,
    persona_signals JSONB,

    -- Status tracking
    scrape_status TEXT CHECK (scrape_status IN ('pending', 'scraped', 'analyzed', 'failed')),
    scrape_error TEXT,
    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    model_used TEXT
);
```

---

## BrandResearchService Additions

### New Methods

```python
# Scrape landing pages from ad link_urls
async def scrape_landing_pages_for_brand(
    brand_id: UUID,
    limit: int = 20,
    delay_between: float = 2.0
) -> Dict[str, Any]:
    """Returns: {"urls_found", "pages_scraped", "pages_failed"}"""

# Analyze scraped pages for persona signals
async def analyze_landing_pages_for_brand(
    brand_id: UUID,
    limit: int = 20,
    delay_between: float = 2.0
) -> List[Dict]:
    """Returns list of analysis results"""

# Helper methods
def get_landing_pages_for_brand(brand_id: UUID) -> List[Dict]
def get_landing_page_stats(brand_id: UUID) -> Dict[str, int]
def _clean_url(url: str) -> str  # Removes tracking params
def _save_landing_page(...) -> Optional[UUID]
def _save_landing_page_error(...)
def _update_landing_page_analysis(...)
```

### Landing Page Analysis Prompt

Extracts:
- Copy patterns (headline style, tone, key phrases, CTAs)
- Persona signals (demographics, psychographics, values)
- Pain points addressed (emotional, functional, social)
- Desires appealed to (transformation, outcomes, emotional benefits)
- Objection handling techniques
- Social proof analysis
- Urgency/scarcity tactics

---

## UI Changes (`19_🔬_Brand_Research.py`)

### New Sync Wrappers
```python
def scrape_landing_pages_sync(brand_id: str, limit: int = 20) -> Dict
def analyze_landing_pages_sync(brand_id: str, limit: int = 20) -> List[Dict]
def get_landing_page_stats(brand_id: str) -> Dict[str, int]
```

### Stats Section
- Added 6th column for "Landing Pages" count
- Shows scraped/analyzed counts

### New Section: "3. Landing Pages"
- **Scrape Landing Pages** button - Extracts content from ad link_urls
- **Analyze Landing Pages** button - Runs Claude analysis for persona signals
- Progress indicators and status feedback

### Section Renumbering
1. Download Assets
2. Analyze Assets (Videos, Images, Copy)
3. Landing Pages (NEW)
4. Synthesize Personas

---

## Dependencies

Added to `requirements.txt`:
```
# Web Scraping Dependencies
firecrawl-py>=1.0.0
```

Requires `FIRECRAWL_API_KEY` environment variable.

---

## Commits This Session

```
ba4b67a feat: Add landing page scraping with FireCrawl (Sprint 3)
11a2f79 docs: Update checkpoint status to tested and working
6f5941b chore: Remove old debug scripts
cb7339f docs: Add checkpoint for video/image async fix
88074aa fix: Combine fetch+analyze in one async context for video/image analysis
```

---

## Architecture Notes

Following pydantic-ai best practices:
- **Service Layer** (`web_scraping_service.py`, `brand_research_service.py`): All business logic
- **UI Layer** (`19_🔬_Brand_Research.py`): Thin sync wrappers, no business logic
- **Generic Service**: `WebScrapingService` is reusable across features

---

## Testing Checklist

Before deploying:
1. [ ] Run database migration on Supabase
2. [ ] Add `FIRECRAWL_API_KEY` to Railway environment
3. [ ] Test scraping a few landing pages
4. [ ] Test analyzing scraped pages
5. [ ] Verify stats display correctly
6. [ ] Test full pipeline: Download → Analyze → Landing Pages → Synthesize

---

## Next Steps

1. **Test landing page scraping** - Verify FireCrawl integration works
2. **Integrate LP analysis into synthesis** - Include LP persona signals in persona generation
3. **Sprint 4: Competitive Analysis** - Use WebScrapingService for competitor sites
4. **Sprint 5: Ad Creation Integration** - Wire personas into ad generation

---

## Start Next Session With

```
Continue from checkpoint at /docs/CHECKPOINT_2025-12-07_LANDING_PAGE_SCRAPING.md

Sprint 3 (Landing Page Scraping) is complete. Need to:
1. Run migration on Supabase
2. Add FIRECRAWL_API_KEY to Railway
3. Test scraping and analysis

The WebScrapingService is generic and ready for reuse in Sprint 4
(Competitive Analysis).
```

---

## Related Docs

- [Previous Checkpoint](CHECKPOINT_2025-12-07_VIDEO_IMAGE_ASYNC_FIX.md)
- [Roadmap](ROADMAP_REMAINING_FEATURES.md)
- [Architecture Guide](/docs/architecture.md)
