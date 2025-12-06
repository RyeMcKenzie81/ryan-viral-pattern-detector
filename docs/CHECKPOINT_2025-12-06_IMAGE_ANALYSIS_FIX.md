# Checkpoint: Image Analysis & Asset Download Fixes

**Date**: 2025-12-06
**Branch**: `feature/brand-research-pipeline`
**Status**: Complete - asset download issue resolved

---

## Completed This Session

### 1. Image Analysis - Switched to Gemini (DONE)
**File**: `viraltracker/services/brand_research_service.py`

- `analyze_image()` now uses Gemini Vision (`gemini-2.0-flash-exp`) instead of Claude Vision
- Supports images up to 20MB (vs Claude's 5MB limit)
- Uses PIL to decode base64 (handles mime types automatically)
- `_save_analysis()` updated with `model_used` parameter
- `analyze_images_batch()` has `delay_between=2.0` parameter

### 2. Copy Analysis Fixes (DONE)
**File**: `viraltracker/services/brand_research_service.py`

- Fixed column name: `ad_creative_body` → `ad_body`
- Added `ad_title` to query for headlines
- Moved delay BEFORE requests (not after) for proper rate limiting
- Increased delay from 1s to 2s
- Added progress logging and better error messages

### 3. Stats Display Improvements (DONE)
**File**: `viraltracker/ui/pages/19_🔬_Brand_Research.py`

- Shows 5 columns: Ads Linked, Videos, Images, Copy Analyzed, Total Analyses
- Shows "X need download" for ads without assets
- Shows "X analyzed, Y pending" for videos/images

### 4. Persona Review UI Expansion (DONE)
**File**: `viraltracker/ui/pages/19_🔬_Brand_Research.py`

Added 6 tabs to display all 4D persona fields:
- Pain & Desires (pain points, desires, transformation, outcomes/JTBD)
- Identity (self-narratives, current/desired self-image, identity artifacts)
- Social (who they want to impress, fear judgment from, influences)
- Worldview (values, forces of good/evil, allergies/turn-offs)
- Barriers (failed solutions, buying objections, familiar promises, risks)
- Activation (activation events, decision process, current workarounds)

### 5. Asset URL Extraction Fix (DONE)
**File**: `viraltracker/services/ad_scraping_service.py`

- `extract_asset_urls()` now extracts from:
  - `snapshot.videos[].video_hd_url`
  - `snapshot.images[].original_image_url`
  - `snapshot.extra_videos[]`
  - `snapshot.extra_images[]`
- Previously only checked `cards[]` array which was empty for many ads

### 6. Download Logging Improvements (DONE)
**Files**: `ad_scraping_service.py`, `brand_research_service.py`

- Increased video timeout from 60s to 120s
- Added detailed logging for debugging:
  - "Starting download for ad X"
  - "Downloading video 1/1 for ad X"
  - "Downloaded video: X bytes"
  - Warnings when URLs exist but download fails

### 7. Asset Download Async Fix (DONE)
**File**: `viraltracker/ui/pages/19_🔬_Brand_Research.py`

**Problem**: Asset downloads worked once after server deploy, then returned "0 videos, 0 images from 0 ads" on subsequent clicks.

**Root Cause**: The Supabase client uses a singleton pattern (`_supabase_client` in `core/database.py`). When `asyncio.run()` completes, it closes the event loop. The singleton client retains stale async connections (httpx) bound to the closed loop, causing silent failures on subsequent calls.

**Fix**: Reset the Supabase singleton before each async call in `run_async()`:
```python
def run_async(coro):
    """Run async function in Streamlit context."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()
    return asyncio.run(coro)
```

This ensures a fresh client with valid async connections for each operation.

---

## Commits This Session

```
6de16af fix: Add better logging for asset downloads and increase timeout
3970005 fix: Extract asset URLs from videos/images arrays in snapshot
995df95 fix: Increase copy analysis delay to 2s between requests
9968aa0 feat: Improve stats display with pending counts
b6247bd feat: Expand persona review UI to show all 4D fields
754da6d fix: Improve copy analysis rate limiting and error logging
7d58e1e fix: Use correct column names for copy analysis
6a9f328 fix: Switch image analysis from Claude Vision to Gemini
```

---

## Key Method Signatures

### BrandResearchService

```python
# Image (uses Gemini)
async def analyze_image(asset_id, image_base64, brand_id, facebook_ad_id, mime_type="image/jpeg")
async def analyze_images_batch(asset_ids, brand_id, delay_between=2.0)

# Video (uses Gemini)
async def analyze_video(asset_id, storage_path, brand_id, facebook_ad_id)
async def analyze_videos_batch(asset_ids, brand_id, delay_between=5.0)

# Copy (uses Claude)
async def analyze_copy(ad_id, ad_copy, headline, brand_id)
async def analyze_copy_batch(brand_id, limit=50, delay_between=2.0)

# Synthesis
async def synthesize_to_personas(brand_id, max_personas=3)

# Asset Download
async def download_assets_for_brand(brand_id, limit=50, include_videos=True, include_images=True)

# Private
def _save_analysis(asset_id, brand_id, facebook_ad_id, analysis_type, raw_response, tokens_used=0, model_used="gemini-2.0-flash-exp")
```

### AdScrapingService

```python
def extract_asset_urls(snapshot) -> Dict[str, List[str]]  # Returns {"images": [], "videos": []}
async def download_asset(url, timeout=30.0) -> Optional[bytes]
async def scrape_and_store_assets(facebook_ad_id, snapshot, brand_id, scrape_source) -> Dict[str, List[UUID]]
```

---

## Files Modified This Session

```
viraltracker/services/brand_research_service.py
- analyze_image(): Claude → Gemini
- analyze_images_batch(): Added delay_between
- analyze_copy_batch(): Fixed columns, rate limiting
- _save_analysis(): Added model_used param
- download_assets_for_brand(): Added logging

viraltracker/services/ad_scraping_service.py
- extract_asset_urls(): Handle videos/images arrays
- scrape_and_store_assets(): Added logging, increased timeout

viraltracker/ui/pages/19_🔬_Brand_Research.py
- render_stats_section(): 5 columns with pending counts
- render_persona_review(): 6 tabs for all 4D fields
- run_async(): Reset Supabase singleton to fix stale async connections
```

---

## Next Steps

1. **Test copy analysis** - Run with new rate limiting
2. **Wire up product filtering** - Filter ads by product URL patterns
3. **Test full persona flow** - Analyze → Synthesize → Approve → Save
4. **Download remaining assets** - ~25 ads still need asset downloads

---

## Related Docs

- [Previous Checkpoint](CHECKPOINT_2025-12-05_SPRINT2_TESTING.md)
- [Roadmap](ROADMAP_REMAINING_FEATURES.md)
- [4D Persona Implementation Plan](plans/4D_PERSONA_IMPLEMENTATION_PLAN.md)
- [Architecture Guide](/docs/architecture.md)
- [Claude Code Guide](/docs/claude_code_guide.md)

---

## Critical Requirements for Next Session

1. **Create checkpoint every ~40K tokens** at `/docs/CHECKPOINT_*.md` documenting:
   - What was implemented
   - Method signatures
   - Database changes
   - Bugs found/fixed
   - Next steps

2. **STRICTLY follow pydantic-ai patterns** from `/CLAUDE.md`, `/docs/claude_code_guide.md`, and `/docs/architecture.md`:
   - Tools = thin wrappers calling services
   - Services = all business logic in `viraltracker/services/`
   - No business logic in tools or UI
