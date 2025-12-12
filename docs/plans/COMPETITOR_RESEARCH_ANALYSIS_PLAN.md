# Competitor Research Analysis Plan

## Overview

Add full asset download and AI analysis workflow to Competitor Research page, mirroring the Brand Research page functionality.

## Current State Analysis

### Brand Research Workflow (Page 19)
```
1. Download Assets → scraped_ad_assets table
   - BrandResearchService.download_assets_for_brand()
   - Uses AdScrapingService to download from snapshot URLs
   - Stores in Supabase storage bucket: "scraped-assets"

2. Analyze Videos → brand_ad_analysis (type='video_vision')
   - BrandResearchService.analyze_videos_for_brand()
   - Uses Gemini Video Model
   - Extracts: transcript, hooks, persona signals, pain points, benefits

3. Analyze Images → brand_ad_analysis (type='image_vision')
   - BrandResearchService.analyze_images_for_brand()
   - Uses Gemini Vision
   - Extracts: hooks, benefits, persona signals, visual style

4. Analyze Copy → brand_ad_analysis (type='copy_analysis')
   - BrandResearchService.analyze_copy_batch()
   - Uses Claude
   - Extracts: hooks, pain points, benefits, messaging patterns

5. Scrape Landing Pages → landing_pages table
   - BrandResearchService.scrape_landing_pages_for_brand()
   - Uses FireCrawl API

6. Analyze Landing Pages
   - BrandResearchService.analyze_landing_pages_for_brand()
   - Uses Claude for analysis

7. Synthesize Personas
   - BrandResearchService.synthesize_to_personas()
   - Aggregates all analyses into 4D personas
```

### Database Tables (Brand Side)
| Table | Purpose |
|-------|---------|
| `facebook_ads` | Main ad data from FB Ad Library |
| `brand_facebook_ads` | Junction: brand ↔ facebook_ads |
| `scraped_ad_assets` | Downloaded images/videos |
| `brand_ad_analysis` | AI analysis results |
| `brand_research_summary` | Consolidated insights |

### Database Tables (Competitor Side) - ALREADY EXIST!
| Table | Purpose | Status |
|-------|---------|--------|
| `competitor_ads` | Scraped competitor ad data | ✅ Has data |
| `competitor_ad_assets` | Downloaded images/videos | ✅ Empty, needs populating |
| `competitor_ad_analysis` | AI analysis results | ✅ Empty, needs populating |
| `competitor_landing_pages` | Landing page scrapes | ✅ Partially implemented |

### Current Competitor Research Page (Page 23)
- ✅ Ad scraping (working)
- ✅ URL assignment to products (working)
- ⚠️ Landing pages (basic one-by-one, no batch)
- ❌ Asset download
- ❌ Video analysis
- ❌ Image analysis
- ❌ Copy analysis
- ✅ Persona synthesis (calls PersonaService)

---

## Implementation Plan

### Phase 1: Create CompetitorResearchService

New service at: `viraltracker/services/competitor_research_service.py`

#### Methods to Implement:

```python
class CompetitorResearchService:
    """Service for competitor ad research and analysis."""

    # 1. Asset Download
    async def download_assets_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 50,
        include_videos: bool = True,
        include_images: bool = True
    ) -> Dict[str, int]:
        """Download assets from competitor_ads.snapshot_data to competitor_ad_assets."""

    # 2. Video Analysis
    async def analyze_videos_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 10
    ) -> List[Dict]:
        """Analyze video assets with Gemini, store in competitor_ad_analysis."""

    # 3. Image Analysis
    async def analyze_images_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 20
    ) -> List[Dict]:
        """Analyze image assets with Gemini Vision, store in competitor_ad_analysis."""

    # 4. Copy Analysis
    async def analyze_copy_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 50
    ) -> List[Dict]:
        """Analyze ad copy with Claude, store in competitor_ad_analysis."""

    # 5. Stats
    def get_asset_stats(self, competitor_id: UUID) -> Dict:
        """Get counts: total ads, videos, images, analyzed counts."""

    def get_analysis_stats(self, competitor_id: UUID) -> Dict:
        """Get counts by analysis type."""
```

#### Key Differences from BrandResearchService:

| Aspect | Brand | Competitor |
|--------|-------|------------|
| Ad source table | `facebook_ads` via `brand_facebook_ads` | `competitor_ads` directly |
| Asset storage | `scraped_ad_assets.facebook_ad_id` | `competitor_ad_assets.competitor_ad_id` |
| Analysis storage | `brand_ad_analysis` | `competitor_ad_analysis` |
| Snapshot field | `facebook_ads.snapshot` | `competitor_ads.snapshot_data` |

### Phase 2: Update Competitor Research UI (Page 23)

Add new sections to the Ads tab (or create new tabs):

#### New Stats Section
```
| Ads Scraped | Videos | Images | Copy Analyzed | Landing Pages |
| 371         | 0      | 0      | 0             | 0/0           |
|             | download needed | download needed |   | to scrape/analyze |
```

#### New Download Section
```
### 1. Download Assets
Download video and image assets from scraped ads to storage.

[Slider: Max ads to process (10-100)]
[Button: Download Assets]
```

#### New Analysis Section
```
### 2. Analyze Assets
Run AI analysis on videos, images, and ad copy.

| Video Analysis        | Image Analysis       | Copy Analysis          |
| Transcripts, hooks... | Visual style, hooks  | Headlines, messaging   |
| [Input: 1-20]         | [Input: 1-50]        | [Input: 1-100]         |
| [Analyze Videos]      | [Analyze Images]     | [Analyze Copy]         |
```

#### Updated Landing Pages Section
Add batch operations like Brand Research has:
- Scrape Landing Pages (batch)
- Analyze Landing Pages (batch)

### Phase 3: Migration (if needed)

Check if `competitor_ad_analysis.analysis_type` supports our types:
```sql
-- Current constraint
CHECK (analysis_type IN ('ad_creative', 'ad_copy', 'landing_page', 'combined'))

-- May need to add:
ALTER TABLE competitor_ad_analysis
DROP CONSTRAINT IF EXISTS competitor_ad_analysis_analysis_type_check;

ALTER TABLE competitor_ad_analysis
ADD CONSTRAINT competitor_ad_analysis_analysis_type_check
CHECK (analysis_type IN (
    'ad_creative', 'ad_copy', 'landing_page', 'combined',
    'video_vision', 'image_vision', 'copy_analysis'
));
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPETITOR RESEARCH FLOW                      │
└─────────────────────────────────────────────────────────────────┘

1. SCRAPE ADS (already working)
   ┌──────────────┐     ┌──────────────────┐
   │ FB Ad Library│────▶│ competitor_ads    │
   │ (via Apify)  │     │ (snapshot_data)   │
   └──────────────┘     └──────────────────┘
                               │
2. DOWNLOAD ASSETS (to implement)
                               ▼
   ┌──────────────────────────────────────────┐
   │ Extract URLs from snapshot_data          │
   │ Download from FB CDN                     │
   │ Store in Supabase Storage               │
   └──────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────────┐
   │ competitor_ad_   │
   │ assets           │
   │ (storage_path)   │
   └──────────────────┘
                               │
3. ANALYZE ASSETS (to implement)
                               ▼
   ┌──────────────────────────────────────────┐
   │ Videos → Gemini Video Model              │
   │ Images → Gemini Vision                   │
   │ Copy → Claude                            │
   └──────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────────┐
   │ competitor_ad_   │
   │ analysis         │
   │ (raw_response)   │
   └──────────────────┘
                               │
4. ANALYZE LANDING PAGES (partially working)
   ┌──────────────────┐     ┌──────────────────┐
   │ competitor_      │────▶│ FireCrawl        │
   │ landing_pages    │     │ + Claude         │
   └──────────────────┘     └──────────────────┘
                               │
5. SYNTHESIZE PERSONA (already working)
                               ▼
   ┌──────────────────────────────────────────┐
   │ Aggregate all analyses                   │
   │ PersonaService.synthesize_competitor_    │
   │ persona()                                │
   └──────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────────┐
   │ personas_4d      │
   │ (type=competitor)│
   └──────────────────┘
```

---

## Files to Create/Modify

### New Files
1. `viraltracker/services/competitor_research_service.py` - Main service

### Modified Files
1. `viraltracker/ui/pages/23_🔍_Competitor_Research.py` - Add UI sections
2. `migrations/YYYY-MM-DD_competitor_analysis_types.sql` - If constraint update needed

### Reused Code
- Can reuse AI prompts from `BrandResearchService` (IMAGE_ANALYSIS_PROMPT, VIDEO_ANALYSIS_PROMPT, COPY_ANALYSIS_PROMPT)
- Can reuse `AdScrapingService.extract_asset_urls()` for extracting URLs
- Can reuse `AdScrapingService.download_asset()` for downloading

---

## Estimated Effort

| Task | Complexity | Lines of Code |
|------|------------|---------------|
| CompetitorResearchService | Medium | ~600 |
| UI Updates (Page 23) | Medium | ~300 |
| Migration (if needed) | Simple | ~10 |
| Testing | Medium | - |

**Total: ~900 lines of new/modified code**

---

## Questions Before Implementation

1. **Storage bucket**: Use same "scraped-assets" bucket or create "competitor-assets"?
   - Recommend: Same bucket, different path prefix (`competitors/{competitor_id}/`)

2. **Analysis type constraint**: Add new types or reuse existing?
   - Recommend: Add video_vision, image_vision, copy_analysis for consistency

3. **Rate limiting**: Same delays as brand analysis?
   - Recommend: Yes (2s for images, 5s for videos)

4. **Persona synthesis**: Current implementation uses `PersonaService.synthesize_competitor_persona()` which already aggregates from `competitor_ad_analysis` and `competitor_landing_pages`. May need to verify it reads the new analysis types.
