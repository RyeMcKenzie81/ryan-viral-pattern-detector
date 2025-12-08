# Checkpoint: Async/Event Loop Fixes for Brand Research

**Date**: 2025-12-07
**Branch**: `feature/brand-research-pipeline`
**Status**: In progress - testing async fixes

---

## Session Summary

This session focused on fixing persistent async/event loop issues in the Brand Research UI that caused operations to fail on repeated runs.

---

## Bugs Fixed This Session

### 1. Copy Analysis Prompt Format Bug (DONE)
**File**: `viraltracker/services/brand_research_service.py`

**Problem**: Copy analysis failed with error `'\\n    \"hook\"'`

**Root Cause**: The `COPY_ANALYSIS_PROMPT` used `str.format()` with `{ad_copy}` placeholder, but the JSON template in the prompt had unescaped braces like `{"hook": {...}}`. Python interpreted these as format placeholders.

**Fix**: Escape all JSON braces by doubling them (`{{` and `}}`):
```python
COPY_ANALYSIS_PROMPT = """...
{{
    "hook": {{
        "text": "...",
        ...
    }}
}}
..."""
```

### 2. Copy Analysis Stats Display (DONE)
**File**: `viraltracker/ui/pages/19_🔬_Brand_Research.py`

**Problem**: After analyzing copy, stats showed "10 Copy Analyzed" but didn't show how many pending.

**Fix**: Updated stats display to always show pending count:
```python
if ad_count > 0:
    pending = ad_count - analysis_stats["copy_analysis"]
    if pending > 0:
        st.caption(f"{pending} pending")
```

### 3. Video/Image Analysis Repeated Run Failure (IN PROGRESS)
**File**: `viraltracker/ui/pages/19_🔬_Brand_Research.py`

**Problem**: Video analysis worked on first run, then returned "0 videos analyzed" on subsequent runs. Copy analysis worked fine on repeated runs.

**Key Insight**: The difference was in the code pattern:

**Copy analysis (worked):**
```python
def analyze_copy_sync(...):
    service = BrandResearchService()
    return run_async(service.analyze_copy_batch(...))  # ALL logic inside async
```

**Video analysis (failed):**
```python
def analyze_videos_sync(...):
    service = BrandResearchService()
    video_assets = service.get_video_assets_for_brand(...)  # SYNC call BEFORE run_async
    return run_async(service.analyze_videos_batch(...))
```

The sync DB call before `run_async()` used a stale connection after the first run's event loop closed.

**Fix**:
1. Use `nest_asyncio` to allow nested event loops
2. Create service INSIDE the async function so all DB operations happen in same event loop context:

```python
def run_async(coro):
    import nest_asyncio
    nest_asyncio.apply()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def analyze_videos_sync(brand_id: str, limit: int = 10):
    async def _analyze():
        service = BrandResearchService()  # Created inside async context
        video_assets = service.get_video_assets_for_brand(...)  # Now inside async
        if not video_assets:
            return []
        asset_ids = [UUID(v['id']) for v in video_assets]
        return await service.analyze_videos_batch(asset_ids, UUID(brand_id))

    return run_async(_analyze())
```

---

## Pattern for Streamlit + Async

**The correct pattern for async operations in Streamlit:**

```python
def sync_wrapper(...):
    """Sync wrapper for Streamlit button handlers."""

    async def _async_operation():
        # Create service INSIDE async context
        service = SomeService()

        # ALL database operations inside async context
        data = service.get_data(...)

        # Async operations
        return await service.async_method(...)

    return run_async(_async_operation())
```

**Key rules:**
1. Never make sync DB calls before `run_async()`
2. Create services inside the async function
3. Use `nest_asyncio` for Streamlit compatibility
4. Keep the event loop alive instead of creating/destroying with `asyncio.run()`

---

## Commits This Session

```
4bf22ea fix: Escape braces in COPY_ANALYSIS_PROMPT for str.format()
b1a3b5d fix: Show pending count for copy analysis in stats
24a089b fix: Reset Supabase client in all sync wrappers before DB operations
2132957 fix: Pass fresh Supabase client to service after reset
dae851d fix: Use nest_asyncio and create service inside async context
```

---

## Files Modified

```
viraltracker/services/brand_research_service.py
- COPY_ANALYSIS_PROMPT: Escaped JSON braces for str.format()

viraltracker/ui/pages/19_🔬_Brand_Research.py
- run_async(): Now uses nest_asyncio and reuses event loop
- All sync wrappers: Create service inside async function
- render_stats_section(): Shows pending count for copy analysis

requirements.txt
- Added nest-asyncio>=1.5.0
```

---

## Next Steps

1. **Test video analysis** - Verify repeated runs now work
2. **Test image analysis** - Same pattern fix applied
3. **Test download assets** - Same pattern fix applied
4. **Test persona synthesis** - Same pattern fix applied
5. **Run full pipeline** - Download → Videos → Images → Copy → Synthesize

---

## Start Next Session With

```
Continue from checkpoint at /docs/CHECKPOINT_2025-12-07_ASYNC_FIXES.md

Testing async fixes for Brand Research UI. Key fix: Create service inside
async function so all DB operations happen in same event loop context.
Use nest_asyncio for Streamlit compatibility.

Test: Run video analysis twice in a row - should work both times now.
```

---

## Related Docs

- [Previous Checkpoint](CHECKPOINT_2025-12-06_IMAGE_ANALYSIS_FIX.md)
- [Architecture Guide](/docs/architecture.md)
