# Checkpoint: Brand Research Pipeline & Template System

**Date**: 2025-12-03 (Updated: 2025-12-04)
**Status**: Phase 3 Complete - Integration
**Version**: 3.0.0
**Branch**: `feature/brand-research-pipeline`

---

## Session Progress (2025-12-04)

### Completed
- **Phase 0**: pydantic-graph verified, `scraped-assets` bucket created, `pipelines/` directory created
- **Phase 1**: Database migration run (8 tables), AdScrapingService implemented, added to AgentDependencies

### Database Fixes Applied
The `facebook_ads` table already existed with different schema. Applied these fixes:
```sql
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS brand_id UUID;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS project_id UUID;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_id TEXT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS page_name TEXT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS scrape_source TEXT;
ALTER TABLE facebook_ads ALTER COLUMN platform_id DROP NOT NULL;
```

### Bug Fixes
- Fixed `FacebookService` to handle `impressions` as dict (was failing Pydantic validation)
- Fixed `FacebookService` to handle `reach_estimate` similarly

### Files Created/Modified
```
NEW:
  viraltracker/services/ad_scraping_service.py
  viraltracker/pipelines/__init__.py
  sql/migration_brand_research_pipeline.sql
  product_setup/ONBOARDING_CHECKLIST.md
  product_setup/templates/brand_data_template.py
  test_ad_scraping_service.py
  test_e2e_ad_scraping.py

MODIFIED:
  viraltracker/agent/dependencies.py
  viraltracker/services/facebook_service.py
  docs/README.md
  product_setup/README.md
```

### E2E Test Results (PASSED)
Testing with URL: `https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&is_targeted_country=false&media_type=all&search_type=page&view_all_page_id=470900729771745`
- ✓ Apify scraping: 10 ads from "Wuffes" page (ID: 470900729771745)
- ✓ Page ID/Name captured in database
- ✓ Saving to DB: 10 records in facebook_ads
- ✓ Asset download: 16 videos (145.7 MB) stored in scraped-assets bucket
- ✓ Asset records: 16 records in scraped_ad_assets table

### Phase 2A: Brand Research Analysis ✅ COMPLETE
Implemented:
- `viraltracker/services/brand_research_service.py` - Claude Vision analysis
- `viraltracker/pipelines/states.py` - BrandOnboardingState, TemplateIngestionState
- `viraltracker/pipelines/brand_onboarding.py` - Full pipeline with 5 nodes
- Added BrandResearchService to AgentDependencies
- `test_brand_research_pipeline.py` - Test script

Pipeline nodes:
1. ScrapeAdsNode - Scrape ads via Apify
2. DownloadAssetsNode - Download to Supabase storage
3. AnalyzeImagesNode - Claude Vision analysis
4. AnalyzeVideosNode - (Gemini, pending implementation)
5. SynthesizeNode - Combine insights into brand summary

### Extracted Fields Enhancement ✅ COMPLETE
Added 10 new queryable columns to `facebook_ads` table:
- `link_url` - Landing page URL (for competitor/funnel research)
- `cta_text`, `cta_type` - CTA analysis ("Shop now", "Learn more")
- `ad_title`, `ad_body` - Ad copy text
- `caption` - Link preview (often shows offers like "wuffes.com/Save50%")
- `link_description` - Link description text
- `page_like_count` - Page authority metric
- `page_profile_uri` - Facebook page URL
- `display_format` - Ad type (VIDEO, DCO, IMAGE, etc.)

Files:
- `sql/migration_facebook_ads_extract_fields.sql` - Migration script
- Updated `AdScrapingService.save_facebook_ad()` - Extracts fields on save
- Backfilled 804 existing ads via Python script

### Phase 2B: Template Queue ✅ COMPLETE
Implemented:
- `viraltracker/services/template_queue_service.py` - Queue management service
- `viraltracker/pipelines/template_ingestion.py` - 3-node pipeline
- `viraltracker/ui/pages/16_📋_Template_Queue.py` - Streamlit approval UI
- Added TemplateQueueService to AgentDependencies

Pipeline flow:
1. ScrapeAdsNode - Scrape ads via Apify
2. DownloadAssetsNode - Download to Supabase storage
3. QueueForReviewNode - Add to template_queue table (pauses here)
4. Human reviews in Streamlit UI - approve/reject/archive

Streamlit UI features:
- Queue statistics dashboard (pending/approved/rejected/archived)
- Three tabs: Pending Review, Template Library, Ingest New
- Preview images with approve/reject/archive actions
- Category selection and naming on approval
- Template ingestion trigger form

Tested flows:
- ✓ Add asset to queue
- ✓ Approve template (creates scraped_templates record)
- ✓ Reject template with reason
- ✓ Archive template
- ✓ Queue stats update correctly
- ✓ Templates appear in library after approval

### Phase 3: Integration ✅ COMPLETE
Implemented:
- Updated Ad Creator UI with "Scraped Template Library" option
- Added category filtering for scraped templates
- Template preview and selection in grid view
- Template usage tracking (times_used, last_used_at)
- Links ad_runs to source_template_id
- Updated onboarding checklist with Phase 0 instructions

Files modified:
- `viraltracker/ui/pages/01_🎨_Ad_Creator.py` - Added scraped template selection
- `product_setup/ONBOARDING_CHECKLIST.md` - Added Phase 0 brand research instructions

Ad Creator features:
- Three reference ad sources: Upload New, Uploaded Templates, Scraped Template Library
- Category filter for scraped templates (testimonial, quote_card, etc.)
- Shows template usage stats (Used Nx)
- Records template usage after ad generation

---

## Executive Summary

This document outlines the architecture for a **Brand Ad Research Pipeline** that enables:

1. **Brand Onboarding** - Scrape a brand's Facebook ads, analyze them with AI, and extract benefits, USPs, hooks, personas, and brand voice to populate product setup
2. **Competitive Intelligence** - Research competitor ads without creating brand records
3. **Template Library** - Scrape ads, queue for human review, approve as reusable templates for ad generation

### Key Architecture Decision: Pydantic Graph

**New pipelines will use Pydantic Graph** for deterministic, state-driven workflows. This provides:
- Explicit DAG structure with state passed between nodes
- Built-in persistence for resumable workflows (critical for approval gates)
- Error recovery from last successful step
- Auto-generated Mermaid diagrams for documentation

**Existing workflows remain unchanged** - we'll consider refactoring after proving the pattern.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pydantic Graph Pattern](#pydantic-graph-pattern)
3. [Database Schema](#database-schema)
4. [Service Layer](#service-layer)
5. [Pipelines](#pipelines)
6. [Agent Tools](#agent-tools)
7. [UI Components](#ui-components)
8. [Implementation Phases](#implementation-phases)
9. [Testing Strategy](#testing-strategy)
10. [Cost Estimates](#cost-estimates)
11. [Future Expansion](#future-expansion)

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BRAND RESEARCH PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Ad Library URL                                                              │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    PYDANTIC GRAPH PIPELINES                          │    │
│  │                                                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │  BRAND ONBOARDING PIPELINE (brand_onboarding_graph)         │   │    │
│  │  │                                                              │   │    │
│  │  │  ScrapeAdsNode ──► DownloadAssetsNode ──► AnalyzeImagesNode │   │    │
│  │  │                                                  │          │   │    │
│  │  │                                                  ▼          │   │    │
│  │  │                    End ◄── SynthesizeNode ◄── AnalyzeVideos │   │    │
│  │  │                     │                                        │   │    │
│  │  │                     ▼                                        │   │    │
│  │  │              BrandResearchSummary                            │   │    │
│  │  │              (benefits, USPs, hooks, personas)               │   │    │
│  │  └─────────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │  TEMPLATE INGESTION PIPELINE (template_ingestion_graph)     │   │    │
│  │  │                                                              │   │    │
│  │  │  ScrapeAdsNode ──► DownloadAssetsNode ──► QueueForReviewNode│   │    │
│  │  │                                                  │          │   │    │
│  │  │                                                  ▼          │   │    │
│  │  │                                          [PAUSE - Human]    │   │    │
│  │  │                                          [Reviews in UI]    │   │    │
│  │  │                                                  │          │   │    │
│  │  │                                                  ▼          │   │    │
│  │  │                                          ApproveTemplateNode│   │    │
│  │  │                                                  │          │   │    │
│  │  │                                                  ▼          │   │    │
│  │  │                                          ad_templates table │   │    │
│  │  └─────────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         SERVICE LAYER                                │    │
│  │                                                                      │    │
│  │  AdScrapingService    BrandResearchService    TemplateQueueService  │    │
│  │  ├─ extract_urls()    ├─ analyze_image()      ├─ add_to_queue()     │    │
│  │  ├─ download()        ├─ analyze_video()      ├─ approve()          │    │
│  │  └─ store()           └─ synthesize()         └─ get_templates()    │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         DATABASE LAYER                               │    │
│  │                                                                      │    │
│  │  scraped_ad_assets   brand_ad_analysis   template_queue             │    │
│  │  scraped_ad_copy     brand_research_     ad_templates               │    │
│  │                      summary                                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Pydantic Graph for Pipelines** - Deterministic workflows use Graph for state management
2. **Thin Tools Pattern** - Agent tools call services; business logic in service layer
3. **Shared Foundation** - Scraping/storage nodes reused across pipelines
4. **Resumable Workflows** - Template approval can pause and resume
5. **Existing Code Unchanged** - Current agents/services remain as-is

---

## Pydantic Graph Pattern

### Why Graph for These Pipelines

| Workflow | Graph Benefit |
|----------|---------------|
| **Brand Onboarding** | State passed cleanly through 5+ steps, error recovery |
| **Template Ingestion** | **Approval gate** requires pause/resume capability |

### Graph vs Current Approach

| Aspect | Async Functions | Pydantic Graph |
|--------|-----------------|----------------|
| State between steps | Function parameters | Shared `ctx.state` |
| Approval gates | Manual DB polling | Built-in interruption |
| Error recovery | Re-run from start | Resume from last step |
| Visualization | Manual docs | Auto Mermaid diagrams |

### Core Concepts

```python
from dataclasses import dataclass, field
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

# 1. STATE - Shared data across all nodes
@dataclass
class PipelineState:
    input_url: str
    results: list = field(default_factory=list)
    current_step: str = "pending"
    error: Optional[str] = None

# 2. NODES - Execution units
@dataclass
class StepOneNode(BaseNode[PipelineState]):
    async def run(self, ctx: GraphRunContext) -> "StepTwoNode":
        # Access state: ctx.state.input_url
        # Access services: ctx.deps.some_service
        ctx.state.current_step = "step_one_complete"
        return StepTwoNode()  # Edge to next node

@dataclass
class StepTwoNode(BaseNode[PipelineState]):
    async def run(self, ctx: GraphRunContext) -> End[dict]:
        ctx.state.current_step = "complete"
        return End({"result": ctx.state.results})

# 3. GRAPH - Composed from nodes
pipeline_graph = Graph(
    nodes=(StepOneNode, StepTwoNode),
    name="my_pipeline"
)

# 4. EXECUTION
result = await pipeline_graph.run(
    StepOneNode(),
    state=PipelineState(input_url="https://..."),
    deps=AgentDependencies.create()
)
```

---

## Database Schema

### New Tables

```sql
-- ============================================================================
-- Migration: 2025-12-03_brand_research_foundation.sql
-- ============================================================================

-- ============================================================================
-- LAYER 1: SHARED FOUNDATION (Scraping & Storage)
-- ============================================================================

-- Raw scraped ad assets (images/videos)
CREATE TABLE scraped_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID REFERENCES facebook_ads(id) ON DELETE CASCADE,
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,

    -- Asset info
    asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'video')),
    storage_path TEXT NOT NULL,
    original_url TEXT,

    -- Metadata
    file_size_bytes INT,
    mime_type TEXT,
    duration_sec FLOAT,              -- Videos only
    dimensions JSONB,                -- {width, height}

    -- Source tracking
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    scrape_source TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scraped_assets_fb_ad ON scraped_ad_assets(facebook_ad_id);
CREATE INDEX idx_scraped_assets_brand ON scraped_ad_assets(brand_id);
CREATE INDEX idx_scraped_assets_type ON scraped_ad_assets(asset_type);

-- Extracted ad copy
CREATE TABLE scraped_ad_copy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID REFERENCES facebook_ads(id) ON DELETE CASCADE,

    headline TEXT,
    body_text TEXT,
    cta_text TEXT,
    link_description TEXT,
    text_overlays JSONB,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scraped_copy_fb_ad ON scraped_ad_copy(facebook_ad_id);

-- ============================================================================
-- WORKFLOW A: BRAND RESEARCH (Analysis & Onboarding)
-- ============================================================================

-- Individual asset analysis results
CREATE TABLE brand_ad_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    asset_id UUID REFERENCES scraped_ad_assets(id) ON DELETE CASCADE,
    facebook_ad_id UUID REFERENCES facebook_ads(id),

    analysis_type TEXT NOT NULL CHECK (analysis_type IN (
        'image_vision', 'video_storyboard', 'copy_analysis', 'synthesis'
    )),

    -- Raw AI response (preserved for re-processing)
    raw_response JSONB NOT NULL,

    -- Extracted insights
    extracted_hooks JSONB,
    extracted_benefits TEXT[],
    extracted_usps TEXT[],
    pain_points TEXT[],
    persona_signals JSONB,
    brand_voice_notes TEXT,
    visual_analysis JSONB,

    -- Model tracking
    model_used TEXT,
    model_version TEXT,
    tokens_used INT,
    cost_usd DECIMAL(10,4),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_brand_analysis_brand ON brand_ad_analysis(brand_id);
CREATE INDEX idx_brand_analysis_asset ON brand_ad_analysis(asset_id);
CREATE INDEX idx_brand_analysis_type ON brand_ad_analysis(analysis_type);

-- Consolidated brand research summary
CREATE TABLE brand_research_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,

    top_benefits TEXT[],
    top_usps TEXT[],
    common_pain_points TEXT[],
    recommended_hooks JSONB,
    persona_profile JSONB,
    brand_voice_summary TEXT,
    visual_style_guide JSONB,

    total_ads_analyzed INT,
    images_analyzed INT,
    videos_analyzed INT,
    copy_analyzed INT,
    date_range JSONB,

    generated_at TIMESTAMPTZ DEFAULT NOW(),
    model_used TEXT,

    UNIQUE(brand_id)
);

CREATE INDEX idx_research_summary_brand ON brand_research_summary(brand_id);

-- ============================================================================
-- WORKFLOW C: TEMPLATE QUEUE (Approval & Creative Library)
-- ============================================================================

-- Queue of scraped ads pending review
CREATE TABLE template_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID REFERENCES scraped_ad_assets(id) ON DELETE CASCADE,
    facebook_ad_id UUID REFERENCES facebook_ads(id),

    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'archived'
    )),

    -- AI pre-analysis
    ai_analysis JSONB,
    ai_quality_score DECIMAL(3,1),
    ai_suggested_category TEXT,

    -- Review info
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,

    template_category TEXT,
    template_name TEXT,
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_template_queue_status ON template_queue(status);
CREATE INDEX idx_template_queue_asset ON template_queue(asset_id);

-- Approved templates
CREATE TABLE ad_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_asset_id UUID REFERENCES scraped_ad_assets(id),
    source_facebook_ad_id UUID REFERENCES facebook_ads(id),
    source_queue_id UUID REFERENCES template_queue(id),

    name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL CHECK (category IN (
        'testimonial', 'quote_card', 'before_after', 'product_showcase',
        'ugc_style', 'meme', 'carousel_frame', 'story_format', 'other'
    )),

    storage_path TEXT NOT NULL,
    thumbnail_path TEXT,

    layout_analysis JSONB,
    color_palette JSONB,
    format_type TEXT,
    canvas_size TEXT,

    recommended_for TEXT[],
    aspect_ratio TEXT,

    times_used INT DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    avg_approval_rate DECIMAL(3,2),

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ad_templates_category ON ad_templates(category);
CREATE INDEX idx_ad_templates_active ON ad_templates(is_active);
CREATE INDEX idx_ad_templates_times_used ON ad_templates(times_used DESC);

-- ============================================================================
-- AD CREATOR INTEGRATION: Template Usage Tracking
-- ============================================================================

ALTER TABLE ad_runs
ADD COLUMN IF NOT EXISTS source_template_id UUID REFERENCES ad_templates(id);

CREATE INDEX IF NOT EXISTS idx_ad_runs_template ON ad_runs(source_template_id);

-- ============================================================================
-- PIPELINE STATE PERSISTENCE (for Graph resumption)
-- ============================================================================

CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name TEXT NOT NULL,

    -- State snapshot (JSON serialized)
    state_snapshot JSONB NOT NULL,
    current_node TEXT NOT NULL,
    status TEXT DEFAULT 'running' CHECK (status IN (
        'running', 'paused', 'complete', 'failed'
    )),

    -- Tracking
    started_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,

    -- Links
    brand_id UUID REFERENCES brands(id),
    initiated_by TEXT
);

CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX idx_pipeline_runs_name ON pipeline_runs(pipeline_name);
```

---

## Service Layer

### File Structure

```
viraltracker/services/
├── ad_scraping_service.py      # NEW - Asset download & storage
├── brand_research_service.py   # NEW - AI analysis & synthesis
├── template_queue_service.py   # NEW - Queue & approval management
├── facebook_service.py         # EXISTING - FB API calls
├── gemini_service.py           # EXISTING - AI operations
└── ad_creation_service.py      # EXISTING - Ad generation
```

### AdScrapingService

**File**: `viraltracker/services/ad_scraping_service.py`

```python
"""
AdScrapingService - Download and store Facebook ad assets.

This service handles:
- Extracting image/video URLs from FB ad snapshots
- Downloading assets from Facebook CDN
- Uploading to Supabase Storage
- Creating scraped_ad_assets records
"""

import logging
from typing import List, Dict, Optional
from uuid import UUID

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class AdScrapingService:
    """Service for scraping and storing Facebook ad assets."""

    STORAGE_BUCKET = "scraped-assets"

    def __init__(self):
        self.supabase: Client = get_supabase_client()
        logger.info("AdScrapingService initialized")

    def extract_asset_urls(self, snapshot: Dict) -> Dict[str, List[str]]:
        """
        Extract image and video URLs from FB ad snapshot.

        Args:
            snapshot: The snapshot JSONB from facebook_ads table

        Returns:
            {"images": [url1, url2], "videos": [url1]}
        """
        images = []
        videos = []

        # Handle snapshot as string or dict
        if isinstance(snapshot, str):
            import json
            snapshot = json.loads(snapshot)

        # Extract from cards array
        cards = snapshot.get('cards', [])
        for card in cards:
            if card.get('video_hd_url'):
                videos.append(card['video_hd_url'])
            elif card.get('video_sd_url'):
                videos.append(card['video_sd_url'])
            if card.get('resized_image_url'):
                images.append(card['resized_image_url'])
            elif card.get('original_image_url'):
                images.append(card['original_image_url'])

        # Extract from top-level
        if snapshot.get('video_hd_url'):
            videos.append(snapshot['video_hd_url'])
        elif snapshot.get('video_sd_url'):
            videos.append(snapshot['video_sd_url'])

        # Extract from images array
        for img in snapshot.get('images', []):
            if img.get('resized_image_url'):
                images.append(img['resized_image_url'])
            elif img.get('original_image_url'):
                images.append(img['original_image_url'])

        # Deduplicate
        return {
            "images": list(set(images)),
            "videos": list(set(videos))
        }

    async def download_asset(self, url: str, timeout: int = 60) -> bytes:
        """
        Download asset from Facebook CDN.

        Args:
            url: Asset URL
            timeout: Request timeout in seconds

        Returns:
            Binary asset data
        """
        import httpx
        import asyncio

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content

    async def upload_to_storage(
        self,
        data: bytes,
        path: str,
        content_type: str = "image/jpeg"
    ) -> str:
        """
        Upload asset to Supabase Storage.

        Args:
            data: Binary asset data
            path: Storage path (e.g., "brand-id/asset-id.jpg")
            content_type: MIME type

        Returns:
            Full storage path
        """
        import asyncio

        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                path,
                data,
                {"content-type": content_type}
            )
        )
        return f"{self.STORAGE_BUCKET}/{path}"

    async def download_and_store_assets(
        self,
        ad_ids: List[UUID],
        brand_id: Optional[UUID] = None
    ) -> List[Dict]:
        """
        Download all assets for given ads and store in Supabase.

        Args:
            ad_ids: List of facebook_ads UUIDs
            brand_id: Optional brand UUID to link assets to

        Returns:
            List of created scraped_ad_assets records
        """
        created_assets = []

        for ad_id in ad_ids:
            # Get ad snapshot
            result = self.supabase.table("facebook_ads").select(
                "id, snapshot"
            ).eq("id", str(ad_id)).execute()

            if not result.data:
                logger.warning(f"Ad not found: {ad_id}")
                continue

            ad = result.data[0]
            snapshot = ad.get('snapshot', {})

            # Extract URLs
            urls = self.extract_asset_urls(snapshot)

            # Download and store images
            for i, url in enumerate(urls['images']):
                try:
                    data = await self.download_asset(url)

                    # Generate storage path
                    import uuid
                    asset_id = uuid.uuid4()
                    path = f"{ad_id}/{asset_id}.jpg"

                    storage_path = await self.upload_to_storage(data, path)

                    # Create record
                    record = {
                        "id": str(asset_id),
                        "facebook_ad_id": str(ad_id),
                        "brand_id": str(brand_id) if brand_id else None,
                        "asset_type": "image",
                        "storage_path": storage_path,
                        "original_url": url,
                        "file_size_bytes": len(data),
                        "mime_type": "image/jpeg"
                    }

                    self.supabase.table("scraped_ad_assets").insert(record).execute()
                    created_assets.append(record)
                    logger.info(f"Stored image: {storage_path}")

                except Exception as e:
                    logger.error(f"Failed to download image {url}: {e}")

            # Download and store videos (Phase 2)
            # TODO: Add video support

        logger.info(f"Stored {len(created_assets)} assets from {len(ad_ids)} ads")
        return created_assets

    async def get_asset_as_base64(self, storage_path: str) -> str:
        """Download asset and return as base64 string."""
        import base64
        import asyncio

        # Parse bucket and path
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        data = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        return base64.b64encode(data).decode('utf-8')
```

### BrandResearchService

**File**: `viraltracker/services/brand_research_service.py`

```python
"""
BrandResearchService - AI analysis and synthesis for brand research.

This service handles:
- Image analysis with Claude Vision
- Video analysis with Gemini
- Synthesis of insights into brand research summary
"""

import logging
from typing import List, Dict, Optional
from uuid import UUID

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class BrandResearchService:
    """Service for brand ad research and analysis."""

    def __init__(self):
        self.supabase: Client = get_supabase_client()
        logger.info("BrandResearchService initialized")

    async def analyze_image(
        self,
        asset_id: UUID,
        image_base64: str,
        brand_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze image with Claude Vision.

        Extracts:
        - Layout/format type
        - Text overlays
        - Color palette
        - Visual style
        - Hook patterns
        """
        # TODO: Implement Claude Vision analysis
        pass

    async def analyze_images_batch(
        self,
        asset_ids: List[UUID],
        brand_id: Optional[UUID] = None
    ) -> List[Dict]:
        """Analyze multiple images, store results."""
        # TODO: Implement batch analysis
        pass

    async def analyze_video(
        self,
        asset_id: UUID,
        video_path: str,
        brand_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze video with Gemini.

        Extracts:
        - Full transcript
        - Hook (first 3 seconds)
        - Storyboard with timestamps
        - Text overlays
        """
        # TODO: Implement Gemini video analysis
        pass

    async def synthesize_insights(
        self,
        brand_id: UUID,
        image_analyses: List[Dict],
        video_analyses: List[Dict],
        copy_data: List[Dict]
    ) -> Dict:
        """
        Synthesize all analyses into brand research summary.

        Produces:
        - Top benefits (ranked)
        - Top USPs
        - Common pain points
        - Recommended hooks
        - Persona profile
        - Brand voice summary
        """
        # TODO: Implement synthesis
        pass

    def export_to_product_data(self, summary: Dict) -> Dict:
        """Format summary for product setup."""
        return {
            "benefits": summary.get("top_benefits", []),
            "unique_selling_points": summary.get("top_usps", []),
            "target_audience": self._format_persona(summary.get("persona_profile", {})),
            "brand_voice_notes": summary.get("brand_voice_summary", ""),
            "hooks": summary.get("recommended_hooks", [])
        }

    def _format_persona(self, persona: Dict) -> str:
        """Format persona profile as text."""
        if not persona:
            return ""

        lines = ["DEMOGRAPHICS:"]
        for key, value in persona.get("demographics", {}).items():
            lines.append(f"- {key}: {value}")

        lines.append("\nPSYCHOGRAPHICS:")
        for trait in persona.get("psychographics", []):
            lines.append(f"- {trait}")

        return "\n".join(lines)
```

### TemplateQueueService

**File**: `viraltracker/services/template_queue_service.py`

```python
"""
TemplateQueueService - Template approval queue management.

This service handles:
- Adding assets to review queue
- AI pre-analysis for reviewers
- Approval/rejection workflow
- Template library management
"""

import logging
from typing import List, Dict, Optional
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class TemplateQueueService:
    """Service for template queue management."""

    def __init__(self):
        self.supabase: Client = get_supabase_client()
        logger.info("TemplateQueueService initialized")

    async def add_to_queue(
        self,
        asset_ids: List[UUID],
        run_ai_analysis: bool = True
    ) -> int:
        """
        Add assets to template review queue.

        Args:
            asset_ids: List of scraped_ad_assets UUIDs
            run_ai_analysis: Whether to run AI pre-analysis

        Returns:
            Number of items added to queue
        """
        count = 0
        for asset_id in asset_ids:
            # Get asset info
            asset = self.supabase.table("scraped_ad_assets").select(
                "id, facebook_ad_id, storage_path"
            ).eq("id", str(asset_id)).execute()

            if not asset.data:
                continue

            asset_data = asset.data[0]

            # Create queue item
            queue_item = {
                "asset_id": str(asset_id),
                "facebook_ad_id": asset_data.get("facebook_ad_id"),
                "status": "pending"
            }

            # Run AI pre-analysis if requested
            if run_ai_analysis:
                ai_analysis = await self._run_pre_analysis(asset_data["storage_path"])
                queue_item["ai_analysis"] = ai_analysis
                queue_item["ai_quality_score"] = ai_analysis.get("quality_score")
                queue_item["ai_suggested_category"] = ai_analysis.get("suggested_category")

            self.supabase.table("template_queue").insert(queue_item).execute()
            count += 1

        logger.info(f"Added {count} items to template queue")
        return count

    async def _run_pre_analysis(self, storage_path: str) -> Dict:
        """Run quick AI analysis for reviewer assistance."""
        # TODO: Implement Gemini Flash pre-analysis
        return {
            "layout_type": "unknown",
            "suggested_category": "other",
            "quality_score": 5.0,
            "style_notes": ""
        }

    def get_pending_queue(
        self,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """Get pending items for review."""
        result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, asset_type)"
        ).eq("status", "pending").order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        return result.data

    def get_queue_stats(self) -> Dict:
        """Get queue statistics."""
        result = self.supabase.table("template_queue").select(
            "status"
        ).execute()

        stats = {"pending": 0, "approved": 0, "rejected": 0, "archived": 0}
        for item in result.data:
            status = item.get("status", "pending")
            stats[status] = stats.get(status, 0) + 1

        return stats

    def approve_template(
        self,
        queue_id: UUID,
        category: str,
        name: str,
        description: Optional[str] = None,
        reviewed_by: str = "system"
    ) -> Dict:
        """
        Approve queue item and create template.

        Returns:
            Created template record
        """
        # Get queue item
        queue_result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, facebook_ad_id)"
        ).eq("id", str(queue_id)).execute()

        if not queue_result.data:
            raise ValueError(f"Queue item not found: {queue_id}")

        queue_item = queue_result.data[0]
        asset = queue_item.get("scraped_ad_assets", {})

        # Update queue status
        self.supabase.table("template_queue").update({
            "status": "approved",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.now().isoformat(),
            "template_category": category,
            "template_name": name
        }).eq("id", str(queue_id)).execute()

        # Create template
        template = {
            "source_asset_id": queue_item["asset_id"],
            "source_facebook_ad_id": queue_item.get("facebook_ad_id"),
            "source_queue_id": str(queue_id),
            "name": name,
            "description": description,
            "category": category,
            "storage_path": asset.get("storage_path", ""),
            "layout_analysis": queue_item.get("ai_analysis", {})
        }

        result = self.supabase.table("ad_templates").insert(template).execute()
        logger.info(f"Created template: {name} ({category})")
        return result.data[0]

    def reject_template(
        self,
        queue_id: UUID,
        reason: str,
        reviewed_by: str = "system"
    ) -> None:
        """Reject queue item with reason."""
        self.supabase.table("template_queue").update({
            "status": "rejected",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.now().isoformat(),
            "rejection_reason": reason
        }).eq("id", str(queue_id)).execute()
        logger.info(f"Rejected template queue item: {queue_id}")

    def get_templates(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50
    ) -> List[Dict]:
        """Get approved templates."""
        query = self.supabase.table("ad_templates").select("*")

        if active_only:
            query = query.eq("is_active", True)
        if category:
            query = query.eq("category", category)

        query = query.order("times_used", desc=True).limit(limit)
        result = query.execute()
        return result.data

    def record_template_usage(self, template_id: UUID, ad_run_id: UUID) -> None:
        """Record that a template was used."""
        self.supabase.table("ad_templates").update({
            "times_used": self.supabase.sql("times_used + 1"),
            "last_used_at": datetime.now().isoformat()
        }).eq("id", str(template_id)).execute()

        # Link to ad_run
        self.supabase.table("ad_runs").update({
            "source_template_id": str(template_id)
        }).eq("id", str(ad_run_id)).execute()
```

---

## Pipelines

### File Structure

```
viraltracker/pipelines/
├── __init__.py
├── states.py                   # Shared state dataclasses
├── brand_onboarding.py         # Brand onboarding graph
└── template_ingestion.py       # Template ingestion graph
```

### Pipeline States

**File**: `viraltracker/pipelines/states.py`

```python
"""
Pipeline state dataclasses for Pydantic Graph workflows.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from uuid import UUID


@dataclass
class BrandOnboardingState:
    """State for brand onboarding pipeline."""

    # Input
    ad_library_url: str
    brand_id: Optional[UUID] = None
    max_ads: int = 50
    analyze_videos: bool = True

    # Populated by ScrapeAdsNode
    ad_ids: List[UUID] = field(default_factory=list)

    # Populated by DownloadAssetsNode
    image_asset_ids: List[UUID] = field(default_factory=list)
    video_asset_ids: List[UUID] = field(default_factory=list)

    # Populated by AnalyzeImagesNode
    image_analyses: List[Dict] = field(default_factory=list)

    # Populated by AnalyzeVideosNode
    video_analyses: List[Dict] = field(default_factory=list)

    # Populated by SynthesizeNode
    summary: Optional[Dict] = None
    product_data: Optional[Dict] = None

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None

    # Metrics
    total_ads_scraped: int = 0
    total_images: int = 0
    total_videos: int = 0


@dataclass
class TemplateIngestionState:
    """State for template ingestion pipeline."""

    # Input
    ad_library_url: str
    max_ads: int = 50
    images_only: bool = True
    run_ai_analysis: bool = True

    # Populated by ScrapeAdsNode
    ad_ids: List[UUID] = field(default_factory=list)

    # Populated by DownloadAssetsNode
    asset_ids: List[UUID] = field(default_factory=list)

    # Populated by QueueForReviewNode
    queue_ids: List[UUID] = field(default_factory=list)

    # Tracking
    current_step: str = "pending"
    awaiting_approval: bool = False
    error: Optional[str] = None
```

### Brand Onboarding Pipeline

**File**: `viraltracker/pipelines/brand_onboarding.py`

```python
"""
Brand Onboarding Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeAds → DownloadAssets → AnalyzeImages → AnalyzeVideos → Synthesize
"""

import logging
from dataclasses import dataclass
from typing import Union
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import BrandOnboardingState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeAdsNode(BaseNode[BrandOnboardingState]):
    """Step 1: Scrape ads from Ad Library URL."""

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "DownloadAssetsNode":
        logger.info(f"Step 1: Scraping ads from {ctx.state.ad_library_url}")

        try:
            ads = await ctx.deps.facebook.search_ads(
                search_url=ctx.state.ad_library_url,
                count=ctx.state.max_ads,
                save_to_db=True
            )

            ctx.state.ad_ids = [ad.id for ad in ads]
            ctx.state.total_ads_scraped = len(ads)
            ctx.state.current_step = "scraped"

            logger.info(f"Scraped {len(ads)} ads")
            return DownloadAssetsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Scrape failed: {e}")
            return End({"status": "error", "error": str(e), "step": "scrape"})


@dataclass
class DownloadAssetsNode(BaseNode[BrandOnboardingState]):
    """Step 2: Download images and videos from scraped ads."""

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "AnalyzeImagesNode":
        logger.info(f"Step 2: Downloading assets from {len(ctx.state.ad_ids)} ads")

        try:
            assets = await ctx.deps.ad_scraping.download_and_store_assets(
                ad_ids=ctx.state.ad_ids,
                brand_id=ctx.state.brand_id
            )

            # Separate images and videos
            ctx.state.image_asset_ids = [
                a["id"] for a in assets if a["asset_type"] == "image"
            ]
            ctx.state.video_asset_ids = [
                a["id"] for a in assets if a["asset_type"] == "video"
            ]

            ctx.state.total_images = len(ctx.state.image_asset_ids)
            ctx.state.total_videos = len(ctx.state.video_asset_ids)
            ctx.state.current_step = "downloaded"

            logger.info(f"Downloaded {ctx.state.total_images} images, {ctx.state.total_videos} videos")
            return AnalyzeImagesNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Download failed: {e}")
            return End({"status": "error", "error": str(e), "step": "download"})


@dataclass
class AnalyzeImagesNode(BaseNode[BrandOnboardingState]):
    """Step 3: Analyze images with Claude Vision."""

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> Union["AnalyzeVideosNode", "SynthesizeNode"]:
        logger.info(f"Step 3: Analyzing {len(ctx.state.image_asset_ids)} images")

        try:
            if ctx.state.image_asset_ids:
                analyses = await ctx.deps.brand_research.analyze_images_batch(
                    asset_ids=ctx.state.image_asset_ids,
                    brand_id=ctx.state.brand_id
                )
                ctx.state.image_analyses = analyses

            ctx.state.current_step = "images_analyzed"
            logger.info(f"Analyzed {len(ctx.state.image_analyses)} images")

            # Skip video analysis if not requested or no videos
            if ctx.state.analyze_videos and ctx.state.video_asset_ids:
                return AnalyzeVideosNode()
            else:
                return SynthesizeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Image analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "analyze_images"})


@dataclass
class AnalyzeVideosNode(BaseNode[BrandOnboardingState]):
    """Step 4: Analyze videos with Gemini."""

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "SynthesizeNode":
        logger.info(f"Step 4: Analyzing {len(ctx.state.video_asset_ids)} videos")

        try:
            if ctx.state.video_asset_ids:
                analyses = await ctx.deps.brand_research.analyze_videos_batch(
                    asset_ids=ctx.state.video_asset_ids,
                    brand_id=ctx.state.brand_id
                )
                ctx.state.video_analyses = analyses

            ctx.state.current_step = "videos_analyzed"
            logger.info(f"Analyzed {len(ctx.state.video_analyses)} videos")
            return SynthesizeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Video analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "analyze_videos"})


@dataclass
class SynthesizeNode(BaseNode[BrandOnboardingState]):
    """Step 5: Synthesize all insights into brand research summary."""

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> End[dict]:
        logger.info("Step 5: Synthesizing brand insights")

        try:
            summary = await ctx.deps.brand_research.synthesize_insights(
                brand_id=ctx.state.brand_id,
                image_analyses=ctx.state.image_analyses,
                video_analyses=ctx.state.video_analyses,
                copy_data=[]  # TODO: Add copy extraction
            )

            ctx.state.summary = summary
            ctx.state.product_data = ctx.deps.brand_research.export_to_product_data(summary)
            ctx.state.current_step = "complete"

            logger.info("Brand research complete")
            return End({
                "status": "success",
                "summary": summary,
                "product_data": ctx.state.product_data,
                "metrics": {
                    "ads_scraped": ctx.state.total_ads_scraped,
                    "images_analyzed": ctx.state.total_images,
                    "videos_analyzed": ctx.state.total_videos
                }
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Synthesis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "synthesize"})


# Build the graph
brand_onboarding_graph = Graph(
    nodes=(
        ScrapeAdsNode,
        DownloadAssetsNode,
        AnalyzeImagesNode,
        AnalyzeVideosNode,
        SynthesizeNode
    ),
    name="brand_onboarding"
)


# Convenience function
async def run_brand_onboarding(
    ad_library_url: str,
    brand_id: UUID = None,
    max_ads: int = 50,
    analyze_videos: bool = True
) -> dict:
    """
    Run the brand onboarding pipeline.

    Args:
        ad_library_url: Facebook Ad Library search URL
        brand_id: Optional brand UUID to link research to
        max_ads: Maximum ads to scrape
        analyze_videos: Whether to analyze video ads

    Returns:
        Pipeline result with summary and product data
    """
    from ..agent.dependencies import AgentDependencies

    result = await brand_onboarding_graph.run(
        ScrapeAdsNode(),
        state=BrandOnboardingState(
            ad_library_url=ad_library_url,
            brand_id=brand_id,
            max_ads=max_ads,
            analyze_videos=analyze_videos
        ),
        deps=AgentDependencies.create()
    )

    return result.output
```

### Template Ingestion Pipeline

**File**: `viraltracker/pipelines/template_ingestion.py`

```python
"""
Template Ingestion Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeAds → DownloadAssets → QueueForReview → [PAUSE] → Approve
"""

import logging
from dataclasses import dataclass

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import TemplateIngestionState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeAdsNode(BaseNode[TemplateIngestionState]):
    """Step 1: Scrape ads from Ad Library URL."""

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> "DownloadAssetsNode":
        logger.info(f"Step 1: Scraping ads from {ctx.state.ad_library_url}")

        try:
            ads = await ctx.deps.facebook.search_ads(
                search_url=ctx.state.ad_library_url,
                count=ctx.state.max_ads,
                save_to_db=True
            )

            ctx.state.ad_ids = [ad.id for ad in ads]
            ctx.state.current_step = "scraped"

            logger.info(f"Scraped {len(ads)} ads")
            return DownloadAssetsNode()

        except Exception as e:
            ctx.state.error = str(e)
            return End({"status": "error", "error": str(e)})


@dataclass
class DownloadAssetsNode(BaseNode[TemplateIngestionState]):
    """Step 2: Download assets (images only by default)."""

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> "QueueForReviewNode":
        logger.info(f"Step 2: Downloading assets")

        try:
            assets = await ctx.deps.ad_scraping.download_and_store_assets(
                ad_ids=ctx.state.ad_ids,
                brand_id=None  # No brand link for templates
            )

            # Filter to images if requested
            if ctx.state.images_only:
                assets = [a for a in assets if a["asset_type"] == "image"]

            ctx.state.asset_ids = [a["id"] for a in assets]
            ctx.state.current_step = "downloaded"

            logger.info(f"Downloaded {len(assets)} assets")
            return QueueForReviewNode()

        except Exception as e:
            ctx.state.error = str(e)
            return End({"status": "error", "error": str(e)})


@dataclass
class QueueForReviewNode(BaseNode[TemplateIngestionState]):
    """Step 3: Add to template queue and PAUSE for human review."""

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> End[dict]:
        logger.info(f"Step 3: Queueing {len(ctx.state.asset_ids)} assets for review")

        try:
            count = await ctx.deps.template_queue.add_to_queue(
                asset_ids=ctx.state.asset_ids,
                run_ai_analysis=ctx.state.run_ai_analysis
            )

            ctx.state.current_step = "queued"
            ctx.state.awaiting_approval = True

            logger.info(f"Queued {count} items for review")

            # Pipeline pauses here - human reviews in Streamlit UI
            return End({
                "status": "awaiting_approval",
                "queued_count": count,
                "message": "Items added to template queue. Review in Template Queue UI."
            })

        except Exception as e:
            ctx.state.error = str(e)
            return End({"status": "error", "error": str(e)})


# Build the graph
template_ingestion_graph = Graph(
    nodes=(
        ScrapeAdsNode,
        DownloadAssetsNode,
        QueueForReviewNode
    ),
    name="template_ingestion"
)


# Convenience function
async def run_template_ingestion(
    ad_library_url: str,
    max_ads: int = 50,
    images_only: bool = True
) -> dict:
    """
    Run the template ingestion pipeline.

    Args:
        ad_library_url: Facebook Ad Library search URL
        max_ads: Maximum ads to scrape
        images_only: Only queue images (not videos)

    Returns:
        Pipeline result with queue status
    """
    from ..agent.dependencies import AgentDependencies

    result = await template_ingestion_graph.run(
        ScrapeAdsNode(),
        state=TemplateIngestionState(
            ad_library_url=ad_library_url,
            max_ads=max_ads,
            images_only=images_only
        ),
        deps=AgentDependencies.create()
    )

    return result.output
```

---

## Agent Tools

Agent tools remain thin wrappers that can call pipelines or services directly.

**File**: `viraltracker/agent/agents/facebook_agent.py` (additions)

```python
@facebook_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '5/minute'
    }
)
async def download_ad_assets(
    ctx: RunContext[AgentDependencies],
    ad_ids: List[str],
    brand_id: Optional[str] = None
) -> Dict:
    """
    Download images and videos from Facebook ads.

    Args:
        ctx: Run context with AgentDependencies
        ad_ids: List of facebook_ads UUIDs
        brand_id: Optional brand UUID to link assets to

    Returns:
        Download results with asset counts and IDs
    """
    from uuid import UUID

    assets = await ctx.deps.ad_scraping.download_and_store_assets(
        ad_ids=[UUID(id) for id in ad_ids],
        brand_id=UUID(brand_id) if brand_id else None
    )

    return {
        "images_downloaded": len([a for a in assets if a["asset_type"] == "image"]),
        "videos_downloaded": len([a for a in assets if a["asset_type"] == "video"]),
        "asset_ids": [a["id"] for a in assets]
    }
```

---

## UI Components

### Template Approval Queue

**File**: `viraltracker/ui/pages/12_📋_Template_Queue.py`

See previous checkpoint for full implementation.

---

## Implementation Phases

### Phase 0: Setup ✅ COMPLETE
**Effort**: 0.5 session

- [x] Create feature branch `feature/brand-research-pipeline`
- [x] Verify `pydantic-graph` installed: v1.18.0
- [x] Create Supabase bucket `scraped-assets`
- [x] Create `viraltracker/pipelines/` directory

### Phase 1: Foundation (Scraping & Storage) ✅ COMPLETE
**Effort**: 1.5 sessions

**Step 1.1: Database Migration**
- [x] Create `sql/migration_brand_research_pipeline.sql`
- [x] Run migration in Supabase (with fixes for existing schema)
- [x] Verify tables exist

**Step 1.2: AdScrapingService**
- [x] Create `viraltracker/services/ad_scraping_service.py`
- [x] Implement `extract_asset_urls()`
- [x] Implement `download_asset()`
- [x] Implement `upload_to_storage()`
- [x] Implement `scrape_and_store_assets()`

**Step 1.3: Add to AgentDependencies**
- [x] Import AdScrapingService
- [x] Add to AgentDependencies class
- [x] Add to factory method

**Step 1.4: Basic Pipeline Structure**
- [x] Create `viraltracker/pipelines/__init__.py`
- [ ] Create `viraltracker/pipelines/states.py` (Phase 2A)
- [ ] Create pipeline nodes (Phase 2A)

**Step 1.5: Test Script**
- [x] Create `test_ad_scraping_service.py`
- [x] Create `test_e2e_ad_scraping.py`
- [x] Test extraction from FB ad
- [x] Test download and storage (16 videos, 145.7 MB)

### Phase 2A: Analysis (Brand Research) ✅ COMPLETE
**Effort**: 2 sessions

**Step 2A.1: BrandResearchService**
- [x] Create `viraltracker/services/brand_research_service.py`
- [x] Implement Claude Vision analysis prompt
- [x] Implement `analyze_image()`
- [x] Implement `analyze_images_batch()`
- [x] Add to AgentDependencies

**Step 2A.2: Analysis Nodes**
- [x] Create `AnalyzeImagesNode`
- [x] Create `SynthesizeNode`
- [x] Complete `brand_onboarding_graph`

**Step 2A.3: End-to-End Test**
- [x] Test imports and dependency injection
- [ ] Test full pipeline with real Ad Library URL (pending user approval - costs API tokens)
- [ ] Verify brand_research_summary created
- [ ] Verify export_to_product_data works

**Step 2A.4: Video Analysis (Optional)**
- [x] Video download already works in AdScrapingService
- [ ] Implement Gemini video analysis
- [x] Create `AnalyzeVideosNode` (placeholder, skips for now)

### Phase 2B: Template Queue ✅ COMPLETE
**Effort**: 1.5 sessions

**Step 2B.1: TemplateQueueService**
- [x] Create `viraltracker/services/template_queue_service.py`
- [x] Implement `add_to_queue()`
- [x] Implement `get_pending_queue()`
- [x] Implement `approve_template()`
- [x] Implement `reject_template()`
- [x] Implement `archive_template()`
- [x] Implement `get_templates()`
- [x] Implement `get_queue_stats()`
- [x] Implement `record_template_usage()`
- [x] Implement `get_asset_preview_url()`

**Step 2B.2: Template Pipeline**
- [x] Create `viraltracker/pipelines/template_ingestion.py`
- [x] Create `ScrapeAdsNode`
- [x] Create `DownloadAssetsNode`
- [x] Create `QueueForReviewNode`
- [x] Create `template_ingestion_graph`
- [x] Create `run_template_ingestion()` convenience function

**Step 2B.3: Streamlit UI**
- [x] Create Template Queue page (`16_📋_Template_Queue.py`)
- [x] Implement queue stats dashboard
- [x] Implement pending review tab with preview
- [x] Implement approval interface (approve/reject/archive)
- [x] Implement template library tab
- [x] Implement ingestion trigger form
- [x] Test full approve/reject/archive flows

### Phase 3: Integration ✅ COMPLETE
**Effort**: 1 session

- [x] Add template selection to Ad Creator (Scraped Template Library option)
- [x] Add category filtering for scraped templates
- [x] Implement template usage tracking (times_used, last_used_at, source_template_id)
- [x] Update onboarding checklist with Phase 0 brand research instructions
- [x] Update checkpoint documentation

**Total Estimated Effort**: 6.5 sessions ✅ COMPLETE

---

## Testing Strategy

### Unit Tests

```python
# tests/test_ad_scraping_service.py

import pytest
from viraltracker.services.ad_scraping_service import AdScrapingService

def test_extract_asset_urls_from_snapshot():
    """Test URL extraction from FB ad snapshot."""
    service = AdScrapingService()

    snapshot = {
        "cards": [
            {"resized_image_url": "https://example.com/img1.jpg"},
            {"video_hd_url": "https://example.com/vid1.mp4"}
        ]
    }

    urls = service.extract_asset_urls(snapshot)

    assert len(urls["images"]) == 1
    assert len(urls["videos"]) == 1
    assert "img1.jpg" in urls["images"][0]


@pytest.mark.asyncio
async def test_download_asset():
    """Test downloading from URL."""
    service = AdScrapingService()

    # Use a known test image
    data = await service.download_asset("https://via.placeholder.com/150")

    assert len(data) > 0
    assert data[:4] == b'\x89PNG' or data[:2] == b'\xff\xd8'  # PNG or JPEG
```

### Integration Tests

```python
# tests/test_brand_onboarding_pipeline.py

import pytest
from viraltracker.pipelines.brand_onboarding import (
    brand_onboarding_graph,
    ScrapeAdsNode,
    BrandOnboardingState
)
from viraltracker.agent.dependencies import AgentDependencies

@pytest.mark.asyncio
async def test_scrape_and_download():
    """Test first two nodes of pipeline."""
    deps = AgentDependencies.create()

    # Use a known test Ad Library URL
    state = BrandOnboardingState(
        ad_library_url="https://www.facebook.com/ads/library/?...",
        max_ads=3
    )

    result = await brand_onboarding_graph.run(
        ScrapeAdsNode(),
        state=state,
        deps=deps
    )

    assert result.state.current_step in ["complete", "downloaded"]
    assert len(result.state.ad_ids) > 0
```

### Manual Test Script

```python
# scripts/test_brand_onboarding.py

import asyncio
from viraltracker.pipelines.brand_onboarding import run_brand_onboarding

async def main():
    # Test with a real Ad Library URL
    result = await run_brand_onboarding(
        ad_library_url="https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=supplements",
        max_ads=5,
        analyze_videos=False  # Skip video for initial test
    )

    print(f"Status: {result['status']}")
    if result['status'] == 'success':
        print(f"Ads scraped: {result['metrics']['ads_scraped']}")
        print(f"Images analyzed: {result['metrics']['images_analyzed']}")
        print(f"Benefits found: {result['product_data'].get('benefits', [])}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Cost Estimates

(Same as v1.0.0 - no changes)

---

## Future Expansion

### Refactoring Existing Workflows to Graph

Once the pattern is proven, consider migrating:

1. **Ad Creator Workflow** - Complex multi-step generation
2. **Comment Generation** - Scrape → score → generate → export
3. **Video Analysis Pipeline** - Download → analyze → report

### FB Ads API Agent

(Same as v1.0.0)

---

## Related Documents

- [Architecture](../architecture.md) - System design overview
- [Claude Code Guide](../claude_code_guide.md) - Development patterns
- [Onboarding Checklist](../../product_setup/ONBOARDING_CHECKLIST.md) - Manual onboarding process
- [Facebook Ads Ingestion](../workflows/facebook_ads_ingestion.md) - Existing FB scraping docs

---

## Future Features Backlog

### High Priority (for brand/competitor research)

**1. Landing Page Scraping**
- Extract `link_url` to dedicated column in `facebook_ads`
- Scrape landing pages for: product info, pricing, testimonials, copy patterns
- Use for competitor analysis and offer tracking
- SQL to add column:
```sql
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS link_url TEXT;
-- Backfill from snapshot JSON:
UPDATE facebook_ads
SET link_url = snapshot->>'link_url'
WHERE link_url IS NULL AND snapshot->>'link_url' IS NOT NULL;
```

**2. Facebook Page Comment Scraping**
- Scrape comments from brand's Facebook page posts
- Extract: objections, questions, social proof, pain points
- Use `apify/facebook-comments-scraper` or similar
- Analyze with Claude for objection categorization

**3. CTA Analysis**
- Track `cta_text` patterns across competitors
- Analyze which CTAs correlate with high engagement
- Already captured in snapshot, just needs extraction

### Medium Priority

**4. Offer/Pricing Tracking**
- Monitor landing pages over time for promo changes
- Track discount patterns, urgency tactics
- Build competitive intelligence dashboard

**5. Cross-Platform Comment Analysis**
- Scrape YouTube/TikTok comments on brand content
- Compare objections across platforms
- Unified objection taxonomy

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-03 | 1.0.0 | Initial checkpoint - planning complete |
| 2025-12-03 | 2.0.0 | Added Pydantic Graph architecture, detailed implementation plan |
| 2025-12-04 | 2.2.0 | Phase 2A complete - BrandResearchService, pipeline nodes |
| 2025-12-04 | 2.2.1 | Added future features backlog (comments, landing pages) |
| 2025-12-04 | 2.3.0 | Extracted 10 fields from snapshot to columns, backfilled 804 ads |
| 2025-12-04 | 2.4.0 | Phase 2B complete - TemplateQueueService, template_ingestion pipeline, Streamlit UI |
| 2025-12-04 | 3.0.0 | Phase 3 complete - Ad Creator integration, template usage tracking, onboarding docs |
