# Phase 2 Polish - Start Handoff

**Date:** 2025-01-17
**Branch:** `phase-2-polish-and-organization`
**Status:** 🔄 IN PROGRESS - Task 2.3 partially complete

---

## Overview

Phase 2 focuses on polishing the agent MVP with production-quality UX features. This includes:
- Structured result models (replacing string responses)
- Result validators for quality control
- Streaming responses for better UX
- Multi-page Streamlit UI
- Multi-format downloads (JSON/CSV/Markdown)
- Refactoring remaining CLI commands

---

## Current Status

### ✅ What's Already Complete

**Phase 1-1.7 (100% complete):**
- ✅ 16 agent tools across 4 platforms (Twitter, TikTok, YouTube, Facebook)
- ✅ 8 services (Twitter, Gemini, Stats, Scraping, Comment, TikTok, YouTube, Facebook)
- ✅ 4 Pydantic models (Tweet, TikTokVideo, YouTubeVideo, FacebookAd)
- ✅ Streamlit UI with conversation context
- ✅ CLI refactored (2/8 commands done)
- ✅ Integration tests passing

**Phase 2 Models (Already implemented in models.py):**
- ✅ `OutlierResult` model (lines 450-517 in viraltracker/services/models.py)
- ✅ `HookAnalysisResult` model (lines 520-617 in viraltracker/services/models.py)

Both models include:
- Full Pydantic validation
- Summary statistics
- `to_markdown()` export method
- JSON schema examples

### ✅ Task 2.3: Structured Result Models (COMPLETE)

**Status:** ✅ COMPLETE - All tools return structured Pydantic models

**What's Done:**
1. ✅ Changed `find_outliers_tool()` return type from `str` → `OutlierResult`
2. ✅ Updated all code paths (empty, error, invalid method, success) to return `OutlierResult`
3. ✅ Changed `analyze_hooks_tool()` return type from `str` → `HookAnalysisResult`
4. ✅ Updated all code paths to return `HookAnalysisResult` with pattern computation
5. ✅ Added `__str__()` methods to both models that delegate to `.to_markdown()`
6. ✅ Updated agent.py with documentation explaining auto-formatting behavior
7. ✅ Updated Streamlit UI with TODO for Task 2.7 (download buttons)
8. ✅ Tested all structural changes (imports, __str__, to_markdown delegation)
9. ✅ Compiled all modified files successfully

**Files Modified:**
- `viraltracker/agent/tools.py` - Both tools now return structured models
- `viraltracker/services/models.py` - Added __str__() methods
- `viraltracker/agent/agent.py` - Added auto-formatting documentation
- `viraltracker/ui/app.py` - Prepared for structured models

**Date Completed:** 2025-01-17

---

## Phase 2 Roadmap

### ✅ Task 2.1: Result Validators (COMPLETE)

**Status:** ✅ COMPLETE - Output validator prevents empty/bad results

**What Was Done:**
1. ✅ Added `@agent.output_validator` decorator using correct Pydantic AI API
2. ✅ Validates OutlierResult for empty results (no tweets or no outliers)
3. ✅ Validates HookAnalysisResult for failed analyses
4. ✅ Raises `ModelRetry` with helpful suggestions when results are invalid
5. ✅ Improves UX by preventing agent from returning useless results
6. ✅ Compiled and tested successfully

**Implementation Details:**
- Decorator: `@agent.output_validator` (not `result_validator`)
- Location: viraltracker/agent/agent.py lines 70-116
- Imports: Added `ModelRetry` from `pydantic_ai`
- Validation logic:
  - OutlierResult: Checks if outlier_count == 0 but total_tweets > 0
  - OutlierResult: Checks if total_tweets == 0 (no data)
  - HookAnalysisResult: Checks if all analyses failed
- Error messages suggest actionable fixes (lower threshold, increase time range, etc.)

**Files Modified:**
- `viraltracker/agent/agent.py` - Added output validator with quality checks

**Date Completed:** 2025-01-17

**Why This Matters:**
- Prevents bad UX from empty result sets
- Agent can retry with better parameters
- Users get helpful suggestions instead of "no results"
- Follows Pydantic AI best practices

---

### Task 2.3: Structured Result Models (PREVIOUSLY COMPLETE)

**Time Remaining:** ~2-3 hours

**Next Steps:**
1. **Update find_outliers_tool main return** (lines 135-165 in tools.py):
   ```python
   # Instead of building response string, return OutlierResult:
   return OutlierResult(
       total_tweets=len(tweets),
       outlier_count=len(outliers),
       threshold=threshold,
       method=method,
       outliers=outliers[:limit],  # Limit for display
       mean_engagement=summary_stats['mean'],
       median_engagement=summary_stats['median'],
       std_engagement=summary_stats['std']
   )
   ```

2. **Update analyze_hooks_tool** (starts ~line 176):
   - Change return type: `str` → `HookAnalysisResult`
   - Build HookAnalysisResult model at end instead of string
   - Call `result.compute_patterns()` before returning

3. **Update Streamlit UI** (viraltracker/ui/app.py):
   - Check if `result` is `OutlierResult` or `HookAnalysisResult`
   - If structured model, call `result.to_markdown()` for display
   - Store raw model in session state for download buttons

4. **Test Everything**:
   ```bash
   # Test CLI chat still works
   viraltracker chat --project yakety-pack-instagram

   # Try: "Find viral tweets from last 24 hours"
   # Should work with new structured return
   ```

**Files to Update:**
- `viraltracker/agent/tools.py` (finish find_outliers_tool, update analyze_hooks_tool)
- `viraltracker/ui/app.py` (handle structured models)
- `viraltracker/cli/chat.py` (if needed - check how it displays results)

---

### Task 2.1: Result Validators (NEXT)

**Time:** 2 hours
**Priority:** High - prevents bad UX

**Implementation:**
```python
# viraltracker/agent/agent.py

from pydantic_ai import ModelRetry

@agent.result_validator
async def validate_results(
    ctx: RunContext[AgentDependencies],
    result: OutlierResult | HookAnalysisResult
) -> OutlierResult | HookAnalysisResult:
    """Validate results are meaningful before returning to user"""

    if isinstance(result, OutlierResult):
        if result.outlier_count == 0 and result.total_tweets > 0:
            raise ModelRetry(
                f"No outliers found from {result.total_tweets:,} tweets. "
                f"Try lowering threshold (current: {result.threshold}) or "
                f"increasing time range."
            )

    elif isinstance(result, HookAnalysisResult):
        if result.successful_analyses == 0:
            raise ModelRetry(
                "Failed to analyze any tweets. Check API quota or tweet selection."
            )

    return result
```

**Why:** Prevents agent from returning useless results, improves UX

---

### Task 2.7: Multi-Format Downloads (AFTER 2.3)

**Time:** 2 hours
**Priority:** High - user-facing feature

**Implementation:**
```python
# viraltracker/ui/app.py (after agent response)

# After displaying result
if isinstance(result, (OutlierResult, HookAnalysisResult)):
    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            "📥 JSON",
            data=result.model_dump_json(indent=2),
            file_name=f"results_{datetime.now():%Y%m%d_%H%M%S}.json",
            mime="application/json"
        )

    with col2:
        # Convert to CSV (for outliers)
        if isinstance(result, OutlierResult):
            import pandas as pd
            df = pd.DataFrame([
                {
                    "rank": o.rank,
                    "author": o.tweet.author_username,
                    "views": o.tweet.view_count,
                    "likes": o.tweet.like_count,
                    "zscore": o.zscore,
                    "percentile": o.percentile,
                    "text": o.tweet.text,
                    "url": o.tweet.url
                }
                for o in result.outliers
            ])
            st.download_button(
                "📥 CSV",
                data=df.to_csv(index=False),
                file_name=f"outliers_{datetime.now():%Y%m%d_%H%M%S}.csv",
                mime="text/csv"
            )

    with col3:
        st.download_button(
            "📥 Markdown",
            data=result.to_markdown(),
            file_name=f"results_{datetime.now():%Y%m%d_%H%M%S}.md",
            mime="text/markdown"
        )
```

**Why:** Users need exports for reports, presentations, further analysis

---

### ⏸️ Task 2.2: Streaming Support (DEFERRED TO TASK 2.4)

**Status:** ⏸️ DEFERRED - Core functionality working, streaming has Streamlit rendering issues
**Date Deferred:** 2025-01-17
**See:** `docs/HANDOFF_PHASE_2_TASK_2.2.md` for full details

**What Was Done:**
- ✅ Integrated Pydantic AI `agent.run_stream()` API successfully
- ✅ Created database tables (`public.outliers`, `public.hook_analyses`)
- ✅ Fixed database persistence for tool results
- ✅ Implemented clean non-streaming UI with spinner
- ⏸️ Deferred actual streaming display due to Streamlit rendering issues

**Current Implementation:**
- Uses `agent.run()` with `st.spinner("Agent is thinking...")`
- Clean, stable display without repetition
- All core functionality working correctly

**Why Deferred:**
- Streamlit's markdown renderer shows cumulative repetition when updated rapidly
- Multiple approaches attempted (throttling, buffering, async generators)
- Not blocking core functionality - can revisit at end of Phase 2

**Next:** Move to Task 2.4 at end of Phase 2 for second streaming attempt

---

### Task 2.4: Streaming Support - Second Attempt (END OF PHASE 2)

**Time:** 4-5 hours
**Priority:** Low - UX polish only

**Current:** Agent uses `agent.run()` - waits for full response
**Target:** Use `agent.run_stream()` - stream tokens in real-time

**Implementation:**
```python
# viraltracker/ui/app.py (replace agent.run() section)

with st.chat_message('assistant'):
    message_placeholder = st.empty()
    full_response = ""

    async def stream_response():
        nonlocal full_response

        async with agent.run_stream(
            prompt,
            deps=st.session_state.deps
        ) as response:
            # Stream text tokens
            async for chunk in response.stream_text():
                full_response += chunk
                message_placeholder.markdown(full_response + "▌")  # Show cursor

            # Remove cursor
            message_placeholder.markdown(full_response)

            # Get final structured result
            final_data = await response.get_data()
            return final_data

    result = asyncio.run(stream_response())

    # Now result is OutlierResult or HookAnalysisResult
    # Add download buttons as per Task 2.7
```

**Why:** Better UX - users see progress instead of waiting

---

### Task 2.5-2.7: Multi-Page Streamlit UI

**Time:** 8 hours total (3 + 3 + 2)
**Priority:** Low - nice-to-have

**Pages to Create:**

1. **`viraltracker/ui/pages/1_Tools_Catalog.py`** (3 hours)
   - List all 16 agent tools with descriptions
   - Show parameters, types, defaults
   - Copy-paste example queries
   - Tool usage statistics

2. **`viraltracker/ui/pages/2_Database_Browser.py`** (3 hours)
   - Table selector (tweets, hooks, outliers, tiktok_videos, etc.)
   - Filter by project, date range, engagement
   - Preview data in dataframe
   - Download as CSV/JSON

3. **`viraltracker/ui/pages/3_History.py`** (2 hours)
   - Show all chat messages with timestamps
   - Re-run previous queries
   - Export conversation transcripts
   - Clear history button

**Why:** Professional multi-page UI, better organization

---

### Task 2.8: Refactor Remaining CLI Commands

**Time:** 15-20 hours
**Priority:** Medium - can be done incrementally

**Commands to Refactor:**

| Command | Location | Time | Dependencies |
|---------|----------|------|--------------|
| `search` | line 178 | 3-4h | ScrapingService |
| `generate-comments` | line 402 | 4-5h | CommentService |
| `export-comments` | line 812 | 2h | ExportService |
| `analyze-search-term` | line 1104 | 2-3h | StatsService, TwitterService |
| `generate-content` | line 1751 | 3-4h | GeminiService |
| `export-content` | line 2001 | 1-2h | ExportService |

**Pattern:** Follow Task 1.11 approach:
- Extract business logic to service methods
- Call services from CLI with `asyncio.run()`
- Maintain exact same CLI interface
- Add async support
- Test backwards compatibility

**Why:** Clean architecture, easier testing, reusable across interfaces

---

## Testing Strategy

### After Task 2.3

```bash
# 1. Test imports
python -m py_compile viraltracker/agent/tools.py
python -m py_compile viraltracker/ui/app.py

# 2. Test CLI chat
viraltracker chat --project yakety-pack-instagram

# In chat, try:
# - "Find viral tweets from last 24 hours"
# - Should return OutlierResult and display markdown
# - Check for download buttons in UI

# 3. Test structured export
# - Click JSON download button
# - Verify valid JSON with OutlierResult structure
```

### After Task 2.1

```bash
# Test validator catches empty results
# In chat, try:
# - "Find outliers with threshold 10.0"
# - Should get ModelRetry suggesting to lower threshold
```

### After Task 2.2

```bash
# Test streaming
# In Streamlit UI:
# - Ask: "Analyze hooks from viral tweets"
# - Should see text appear token-by-token
# - Cursor should show streaming progress
```

---

## Known Issues

1. **Invalid method error case** (line 96 in tools.py):
   - Still returns string instead of OutlierResult
   - Need to fix: return empty OutlierResult for invalid method

2. **Error handler** (line 167-169 in tools.py):
   - Returns string on exception
   - Should return OutlierResult with error state
   - Or let exception propagate (better for debugging)

3. **Tools Phase 1.5-1.7** (tools_phase15.py, tools_phase16.py, tools_phase17.py):
   - Still return strings
   - Need result models for TikTok, YouTube, Facebook tools
   - Lower priority - Twitter tools are most used

---

## File Locations

### Modified
- `viraltracker/agent/tools.py` - Partial update to OutlierResult

### Need Updates
- `viraltracker/agent/tools.py` - Finish find_outliers_tool, update analyze_hooks_tool
- `viraltracker/agent/agent.py` - Add result validators
- `viraltracker/ui/app.py` - Handle structured models, add downloads, add streaming

### Future
- `viraltracker/ui/pages/1_Tools_Catalog.py` - NEW
- `viraltracker/ui/pages/2_Database_Browser.py` - NEW
- `viraltracker/ui/pages/3_History.py` - NEW
- `viraltracker/cli/twitter.py` - Refactor 6 remaining commands

---

## Success Criteria

Phase 2 complete when:
- ✅ All core agent tools return structured Pydantic models
- ✅ Result validators prevent empty/bad results
- ✅ Streaming responses work in Streamlit
- ✅ Download results in JSON/CSV/Markdown
- ✅ Multi-page UI implemented (Tools, Database, History)
- ✅ All 6 remaining CLI commands refactored
- ✅ All tests passing
- ✅ Documentation updated

---

## Next Session Continuation

```
I'm continuing Phase 2 of the Pydantic AI migration.

Current status:
- ✅ Phase 1-1.7 complete (16 tools, 8 services, 4 models)
- 🔄 Task 2.3 (Structured Result Models) started but incomplete
- 📋 7 Phase 2 tasks remaining

Task 2.3 progress:
- ✅ OutlierResult and HookAnalysisResult models exist in models.py
- ✅ find_outliers_tool return type changed to OutlierResult
- ✅ Empty/error cases return OutlierResult
- ⚠️ Main success path still returns string (needs update ~line 135-165)
- ⚠️ analyze_hooks_tool not updated yet
- ⚠️ Streamlit UI doesn't handle structured models yet

Next steps:
1. Finish find_outliers_tool to return OutlierResult
2. Update analyze_hooks_tool to return HookAnalysisResult
3. Update Streamlit UI to display structured models
4. Add download buttons (Task 2.7)
5. Add result validators (Task 2.1)

Reference docs:
- This handoff: /Users/ryemckenzie/projects/viraltracker/docs/PHASE2_START_HANDOFF.md
- Migration plan: /Users/ryemckenzie/projects/viraltracker/docs/PYDANTIC_AI_MIGRATION_PLAN.md
- Models: /Users/ryemckenzie/projects/viraltracker/viraltracker/services/models.py

Please help me continue Task 2.3.
```

---

**Document Status:** ✅ COMPLETE - Ready for handoff
