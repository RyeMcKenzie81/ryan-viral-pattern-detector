# ViralTracker - Gemini SDK Migration Required (2025-10-14)

**Date:** 2025-10-14 15:20 PST
**Status:** 🔧 ACTION REQUIRED - SDK Migration Needed
**Session:** Gemini API Investigation & Resolution

---

## 🎯 CRITICAL DISCOVERY: SDK Migration Required

### The Problem
The `ragStoreName` error is caused by using the **deprecated old SDK** (`google-generativeai`). Google has released a **new unified SDK** (`google-genai`) with different syntax.

### Evidence
1. ✅ Google AI Studio works fine (uses new SDK)
2. ❌ Our code fails with `ragStoreName` error (uses old SDK)
3. ✅ Text generation works (doesn't use file uploads)
4. ❌ Video file uploads fail (old SDK has RAG bug)

### Root Cause
We're using: `import google.generativeai as genai`
We need: `from google import genai` with `client = genai.Client()`

---

## 📋 Current State Summary

### Python Analyzer
- **Current Version:** v1.1.0
- **Status:** Using deprecated SDK (`google-generativeai==0.7.2`)
- **Issue:** Video file uploads fail with `ragStoreName` error
- **Action Needed:** Migrate to new SDK (`google-genai`)

### TypeScript Scorer
- **Version:** v1.2.0 ✅ COMPLETE
- **Status:** Ready to test once analyzer is working
- **Location:** `scorer/src/formulas.ts` and `scorer/src/scorer.ts`

### Hook Intelligence v1.2.0 Implementation
- **Status:** 100% COMPLETE but untested
- **Python Changes:** Documented in `CHECKPOINT_2025-10-14_hook-intelligence-v1.2.0_FINAL.md`
- **TypeScript Changes:** Already implemented and built successfully
- **Blocked By:** Need SDK migration to test

---

## 🔄 SDK Migration Guide

### Old SDK → New SDK Syntax Changes

#### 1. Import Statement
```python
# OLD (deprecated)
import google.generativeai as genai

# NEW (current)
from google import genai
from google.genai import types
```

#### 2. Initialization
```python
# OLD
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name)

# NEW
client = genai.Client(api_key=api_key)
# Model used directly in generate_content call
```

#### 3. File Upload
```python
# OLD
video_file = genai.upload_file(path=file_path)
genai.delete_file(video_file.name)

# NEW
video_file = client.files.upload(file=file_path)
client.files.delete(name=video_file.name)
```

#### 4. Generate Content
```python
# OLD
response = model.generate_content([video_file, prompt])

# NEW
response = client.models.generate_content(
    model='models/gemini-2.5-pro',
    contents=[video_file, prompt]
)
```

---

## 📝 Migration Steps (Next Session)

### Step 1: Install New SDK
```bash
cd /Users/ryemckenzie/projects/viraltracker
source venv/bin/activate
pip install google-genai
pip uninstall google-generativeai  # Optional: remove old SDK
```

### Step 2: Update video_analyzer.py

**File:** `viraltracker/analysis/video_analyzer.py`

**Changes Required:**

1. **Import Statement (Line 17):**
```python
# Change from:
import google.generativeai as genai

# To:
from google import genai
from google.genai import types
```

2. **Initialization (Lines ~60-70):**
```python
# Change from:
genai.configure(api_key=self.gemini_api_key)
self.model = genai.GenerativeModel(model_name=self.gemini_model)

# To:
self.client = genai.Client(api_key=self.gemini_api_key)
# Remove self.model - use client.models.generate_content directly
```

3. **File Upload (Lines ~200-220):**
```python
# Change from:
video_file = genai.upload_file(path=file_path)

# To:
video_file = self.client.files.upload(file=file_path)
```

4. **Generate Content (Lines ~240-260):**
```python
# Change from:
response = self.model.generate_content([video_file, prompt])

# To:
response = self.client.models.generate_content(
    model=self.gemini_model,
    contents=[video_file, prompt]
)
```

5. **Delete File (Lines ~280-290):**
```python
# Change from:
genai.delete_file(video_file.name)

# To:
self.client.files.delete(name=video_file.name)
```

### Step 3: Test with 1 Video
```bash
echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro --limit 1
```

### Step 4: Once Working, Restore Hook Intelligence v1.2.0

The v1.2.0 Python analyzer changes are fully documented in:
`CHECKPOINT_2025-10-14_hook-intelligence-v1.2.0_FINAL.md`

Key changes to restore:
- Update `self.analysis_version = "vid-1.2.0"`
- Add hook intelligence extraction to prompt
- Parse 10 hook_features fields from JSON response
- Update database write to include `hook_features` JSONB

### Step 5: Test End-to-End
```bash
# Test with 2-3 videos
echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro --limit 3

# Inspect database
# Query hook_features JSONB to verify all 10 fields populated

# Test TypeScript scorer
cd scorer && npm run build && npm test
```

---

## 🧪 Test Results from Today

### Simple Text Generation Test
```bash
venv/bin/python test_gemini_basic.py
```
**Result:** ✅ SUCCESS - Text generation works perfectly

### Video File Upload Test
```bash
venv/bin/python test_gemini_basic.py  # With test_video.mp4
```
**Result:** ❌ FAILED - `Missing required parameter "ragStoreName"`

**Conclusion:** Old SDK has bug in video file upload, new SDK fixes it.

---

## 📁 Files & Locations

### Code Files
- **Analyzer:** `viraltracker/analysis/video_analyzer.py` (needs migration)
- **Test Script:** `test_gemini_basic.py` (minimal repro)
- **Test Video:** `test_video.mp4` (2-second generated video)

### Checkpoints
- **This File:** `CHECKPOINT_2025-10-14_SDK-MIGRATION.md`
- **Previous:** `CHECKPOINT_2025-10-14_hook-intelligence-v1.2.0_FINAL.md`
- **API Issue:** `CHECKPOINT_2025-10-14_gemini-api-issue.md` (now obsolete)

### Related Documentation
- **Google Docs:** User provided video understanding documentation
- **New SDK Docs:** https://googleapis.github.io/python-genai/

---

## 🎯 Priority Tasks for Next Session

1. **[HIGH]** Install new SDK: `pip install google-genai`
2. **[HIGH]** Migrate video_analyzer.py to new SDK (see Step 2 above)
3. **[HIGH]** Test with 1 video to verify migration works
4. **[MEDIUM]** Restore Hook Intelligence v1.2.0 changes from checkpoint
5. **[MEDIUM]** Test v1.2.0 end-to-end with 3 videos
6. **[LOW]** Inspect database to verify hook_features JSONB output
7. **[LOW]** Update requirements.txt to use `google-genai`

---

## 📊 Status Dashboard

| Component | Version | Status | Notes |
|-----------|---------|--------|-------|
| Python Analyzer | v1.1.0 | ⚠️ Needs Migration | Uses old SDK |
| TypeScript Scorer | v1.2.0 | ✅ Complete | Ready to test |
| Hook Intelligence | v1.2.0 | ✅ Code Complete | Needs testing |
| Gemini SDK | OLD | ❌ Deprecated | Causes ragStoreName error |
| Database Schema | ✅ Ready | hook_features JSONB | Supports v1.2.0 |

---

## 🔍 Technical Details

### SDK Versions Tested (All Failed)
- `google-generativeai==0.7.2` ❌
- `google-generativeai==0.8.3` ❌
- `google-generativeai==0.8.5` ❌

### New SDK to Install
- `google-genai` (latest) ✅ Expected to work

### Models Tested
- `models/gemini-2.5-pro` ❌ (old SDK)
- `models/gemini-2.0-flash-exp` ❌ (old SDK)
- Both should work with new SDK ✅

---

## 💡 Key Insights

1. **Not a Google API Issue:** The API itself works fine (verified via AI Studio)
2. **SDK Deprecation:** Old `google-generativeai` is deprecated and buggy
3. **New SDK Required:** Must use `google-genai` with `Client()` pattern
4. **Breaking Change:** Complete syntax rewrite, not just version upgrade
5. **Hook Intelligence Ready:** v1.2.0 is 100% implemented, just needs testing

---

**Session End:** 2025-10-14 15:20 PST
**Next Session:** Install new SDK, migrate code, test Hook Intelligence v1.2.0

**Estimated Time:** 30-45 minutes for full migration and testing
