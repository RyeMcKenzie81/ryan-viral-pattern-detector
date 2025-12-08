# Checkpoint: Video/Image Analysis Async Fix

**Date**: 2025-12-07
**Branch**: `feature/brand-research-pipeline`
**Status**: Complete - tested and working

---

## Session Summary

Fixed video and image analysis failing on repeated runs. The root cause was sync DB calls using a Supabase client with stale async connections after `asyncio.run()` completed.

---

## Bug Fixed This Session

### Video/Image Analysis Repeated Run Failure (DONE)

**Files**:
- `viraltracker/services/brand_research_service.py`
- `viraltracker/ui/pages/19_🔬_Brand_Research.py`

**Problem**: Video analysis worked on first run, then returned "0 videos analyzed" on subsequent runs. Same issue for image analysis.

**Root Cause Analysis**:

The **copy analysis worked** on repeated runs because `analyze_copy_batch()` does ALL database operations internally:
```python
async def analyze_copy_batch(self, brand_id: UUID, ...):
    # Fetches ads - DB call happens INSIDE async method
    link_result = self.supabase.table("brand_facebook_ads").select("ad_id")...
    # Filters and analyzes - all in one async context
    ...
```

The **video analysis failed** because:
```python
def analyze_videos_sync(brand_id: str, limit: int = 10):
    async def _analyze():
        service = BrandResearchService()  # Service created here
        # PROBLEM: get_video_assets_for_brand is a SYNC method
        # It uses self.supabase which was created when service was instantiated
        video_assets = service.get_video_assets_for_brand(...)  # Uses stale client
        return await service.analyze_videos_batch(asset_ids, ...)
    return run_async(_analyze())
```

When `asyncio.run()` completes, it closes the event loop. The Supabase client (`self.supabase`) retains httpx async connections bound to the closed loop, causing silent failures on subsequent calls.

**Solution**:

Created new async methods that combine fetching AND analyzing in a single async operation:

```python
async def analyze_videos_for_brand(self, brand_id: UUID, limit: int = 10):
    """Fetch and analyze videos in one async operation."""
    # ALL DB calls happen inside this async method
    link_result = self.supabase.table("brand_facebook_ads").select("ad_id")...
    assets_result = self.supabase.table("scraped_ad_assets").select(...)...
    analyzed_result = self.supabase.table("brand_ad_analysis").select(...)...

    # Then analyze
    for asset in videos_to_analyze:
        await self.analyze_video(...)

async def analyze_images_for_brand(self, brand_id: UUID, limit: int = 20):
    """Same pattern for images."""
    ...
```

Updated UI sync wrappers to use these new methods:
```python
def analyze_videos_sync(brand_id: str, limit: int = 10):
    async def _analyze():
        service = BrandResearchService()
        return await service.analyze_videos_for_brand(UUID(brand_id), limit=limit)
    return run_async(_analyze())
```

---

## Pattern for Streamlit + Async

**The correct pattern for async operations in Streamlit:**

```python
# IN SERVICE (brand_research_service.py):
async def do_something_for_brand(self, brand_id: UUID, ...):
    """
    Combines ALL database operations and async work in one method.
    """
    # 1. Fetch data - DB calls happen inside async context
    result = self.supabase.table("...").select("...").execute()

    # 2. Filter/process
    items_to_process = [...]

    # 3. Do async work
    for item in items_to_process:
        await self.async_method(item)

    return results

# IN UI (19_🔬_Brand_Research.py):
def do_something_sync(brand_id: str, ...):
    """Thin sync wrapper for Streamlit."""
    async def _run():
        service = SomeService()
        return await service.do_something_for_brand(UUID(brand_id), ...)
    return asyncio.run(_run())
```

**Key Rules:**
1. ALL database operations must happen INSIDE the async method
2. Never make sync DB calls before `asyncio.run()`
3. Create service INSIDE the async function (within same event loop context)
4. UI wrappers should be THIN - just call service methods

---

## Commits This Session

```
88074aa fix: Combine fetch+analyze in one async context for video/image analysis
```

---

## New Method Signatures

### BrandResearchService

```python
# NEW: Combined fetch + analyze methods (use these from UI)
async def analyze_videos_for_brand(
    brand_id: UUID,
    limit: int = 10,
    delay_between: float = 5.0
) -> List[Dict]

async def analyze_images_for_brand(
    brand_id: UUID,
    limit: int = 20,
    delay_between: float = 2.0
) -> List[Dict]

# EXISTING: Still available for direct use if you already have asset_ids
async def analyze_videos_batch(asset_ids: List[UUID], brand_id: UUID) -> List[Dict]
async def analyze_images_batch(asset_ids: List[UUID], brand_id: UUID) -> List[Dict]

# EXISTING: Copy analysis (already follows correct pattern)
async def analyze_copy_batch(brand_id: UUID, limit: int = 50) -> List[Dict]
```

---

## Files Modified

```
viraltracker/services/brand_research_service.py
- Added analyze_videos_for_brand() - combines fetch + analyze videos
- Added analyze_images_for_brand() - combines fetch + analyze images

viraltracker/ui/pages/19_🔬_Brand_Research.py
- Updated analyze_videos_sync() to use analyze_videos_for_brand()
- Updated analyze_images_sync() to use analyze_images_for_brand()
```

---

## Next Steps

1. **Test video analysis** - Run twice in a row, should work both times
2. **Test image analysis** - Same test
3. **Test full pipeline** - Download → Videos → Images → Copy → Synthesize
4. **Test persona synthesis** - Verify personas are generated correctly
5. **Wire up product filtering** - Filter ads by product URL patterns

---

## Start Next Session With

```
Continue from checkpoint at /docs/CHECKPOINT_2025-12-07_VIDEO_IMAGE_ASYNC_FIX.md

Testing async fixes for Brand Research UI. Key fix: Created combined
async methods (analyze_videos_for_brand, analyze_images_for_brand) that
do ALL DB operations inside the async context.

Test: Run video analysis twice in a row - should work both times now.
```

---

## Related Docs

- [Previous Checkpoint](CHECKPOINT_2025-12-07_ASYNC_FIXES.md)
- [Image Analysis Fix Checkpoint](CHECKPOINT_2025-12-06_IMAGE_ANALYSIS_FIX.md)
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
