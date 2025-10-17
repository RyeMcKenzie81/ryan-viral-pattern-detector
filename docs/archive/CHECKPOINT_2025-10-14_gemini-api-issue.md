# ViralTracker - Gemini API Issue (2025-10-14)

**Date:** 2025-10-14 15:02 PST
**Status:** BLOCKED - Google Gemini API Issue
**Session:** Attempted Hook Intelligence v1.2.0 Testing

## Critical Issue: Google Gemini API "ragStoreName" Error

### Error Details
```
[2025-10-14 15:01:47] ERROR: Error processing video: Missing required parameter "ragStoreName"
```

### What We Discovered

1. **NOT Our Code**: The error `ragStoreName` does NOT appear anywhere in our codebase
2. **API-Level Issue**: Error occurs during `genai.upload_file()` or `model.generate_content()` calls
3. **Affects ALL Versions**: Both v1.1.0 (working yesterday) and v1.2.0 (new code) fail with same error
4. **SDK Independent**: Tested multiple SDK versions - all fail:
   - `google-generativeai==0.7.2` ❌
   - `google-generativeai==0.8.3` ❌
   - `google-generativeai==0.8.5` ❌
5. **Timeline**:
   - ✅ Working: 2025-10-13 (v1.1.0 successfully analyzed 34 videos)
   - ❌ Broken: 2025-10-14 (both v1.1.0 and v1.2.0 fail)

### Root Cause Analysis

**Conclusion:** This is a **Google Gemini API server-side breaking change or outage** that started on 2025-10-14.

The error mentions "ragStoreName" which suggests:
- Google added RAG (Retrieval-Augmented Generation) features
- New required parameter introduced server-side
- Breaking change not documented in SDK

### Current State

**Hook Intelligence v1.2.0 Implementation:** ✅ 100% COMPLETE
- ✅ Python analyzer updated (vid-1.2.0)
- ✅ TypeScript scorer updated (v1.2.0)
- ✅ All 10 hook intelligence fields implemented
- ✅ 14 hook types with probabilities
- ✅ Modality attribution (audio/visual/overlay)
- ✅ Windowed metrics (0-1s, 0-2s, 0-3s, 0-5s)
- ✅ Hook catalysts & risk flags
- ✅ Adaptive scoring (70% pace + 30% content)
- ✅ TypeScript builds successfully

**Blocked:** Cannot test with live videos due to Gemini API issue

### Files Backed Up

```bash
# v1.2.0 implementation backed up to:
viraltracker/analysis/video_analyzer.py.v1.2.0.backup

# Currently running v1.1.0 (restored from git)
# Both versions fail with same error
```

### SDK Version Pinned

Currently using: `google-generativeai==0.7.2` (downgraded for testing)

### Recommended Actions

**Immediate (Next Session):**
1. ✅ Restore v1.2.0 code: `cp viraltracker/analysis/video_analyzer.py.v1.2.0.backup viraltracker/analysis/video_analyzer.py`
2. ⏳ Wait 24-48 hours for Google to fix API issue
3. 📧 Consider reporting to Google AI forum
4. ✅ Test TypeScript scorer with existing v1.1.0 data from database

**Alternative Workarounds:**
1. Use older Gemini models (if available)
2. Switch to different video analysis API temporarily
3. Test scorer logic with mock data

**Once API Fixed:**
1. Test v1.2.0 with 1-3 videos
2. Inspect `hook_features` JSONB output
3. Verify TypeScript scorer processes new data
4. Run full analysis on project videos

### Context for Next Session

**What Works:**
- ✅ TypeScript scorer v1.2.0 (builds successfully)
- ✅ Python analyzer v1.2.0 (code complete)
- ✅ All Hook Intelligence logic implemented
- ✅ Database schema supports `hook_features` JSONB

**What's Blocked:**
- ❌ Live video analysis (Gemini API issue)
- ❌ Testing hook_features extraction
- ❌ End-to-end v1.2.0 validation

**Quick Restore Commands:**
```bash
cd /Users/ryemckenzie/projects/viraltracker

# Restore v1.2.0
cp viraltracker/analysis/video_analyzer.py.v1.2.0.backup viraltracker/analysis/video_analyzer.py

# Re-upgrade SDK when API fixed
source venv/bin/activate
pip install google-generativeai==0.8.3

# Test with 1 video
echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro --limit 1
```

### Related Files

- **Checkpoint (This):** `CHECKPOINT_2025-10-14_gemini-api-issue.md`
- **Previous:** `CHECKPOINT_2025-10-14_hook-intelligence-v1.2.0_FINAL.md`
- **Backup:** `viraltracker/analysis/video_analyzer.py.v1.2.0.backup`

---

**Session End:** 2025-10-14 15:02 PST
**Next Session:** Restore v1.2.0, wait for API fix, then test
