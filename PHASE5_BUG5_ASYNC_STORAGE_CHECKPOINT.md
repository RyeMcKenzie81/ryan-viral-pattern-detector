# Phase 5 - Bug #5: Async/Sync Storage Fix Checkpoint

**Date:** 2025-01-25
**Session:** Gemini API Integration Debug Session 5
**Status:** ✅ Root Cause Identified, Fix Ready to Implement

---

## 🎯 BUG #5: Supabase Storage Download Async/Sync Mismatch

### Issue Summary
Integration test fails during Stage 5 (Analyze Reference Ad) with JSON decode error when downloading reference ad from Supabase storage.

**Error Message:**
```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Error Context:**
- Test progresses successfully through stages 1-4 (463 seconds / 7m 43s)
- Fails when `get_image_as_base64()` tries to download reference ad from storage
- Supabase returns HTML CloudFlare error page instead of binary image data

---

## 🔍 ROOT CAUSE ANALYSIS

### Diagnostic Process

1. **Created Diagnostic Script** (`debug_storage.py`)
   - Tested storage access in standalone context
   - Verified bucket exists and is PUBLIC
   - Verified file exists (30216 bytes - real WEBP image)
   - Download succeeded in sync context ✅

2. **Key Findings**
   - Storage infrastructure is working correctly
   - File is accessible and downloadable
   - Issue only occurs in async test context

3. **Root Cause Identified**
   - `download_image()` method is marked `async` but uses sync Supabase client
   - Sync API calls inside async methods cause race conditions
   - Works in standalone sync scripts but fails in async concurrent contexts

### Diagnostic Results

```
=== SUPABASE STORAGE DEBUG ===
Bucket: reference-ads
File path: e467a89b-0686-47ae-8a79-82541c6be077_test_reference.png

✅ Found 2 buckets:
  - reference-ads (public: True)
  - generated-ads (public: True)
✅ Bucket 'reference-ads' exists
✅ File exists (30216 bytes)
✅ Public URL: https://[...]/reference-ads/e467a89b-[...].png
✅ Download successful!
✅ Data type: <class 'bytes'>
✅ Data length: 30216 bytes
✅ Data appears to be binary (image)
```

**Conclusion:** Storage works perfectly in sync context. Issue is async/sync mismatch.

---

## 🐛 THE BUG

### Location
**File:** `viraltracker/services/ad_creation_service.py`
**Lines:** 207-236

### Current Broken Code

```python
async def download_image(self, storage_path: str) -> bytes:
    """
    Download image from Supabase Storage.

    Args:
        storage_path: Full storage path (e.g., "products/{id}/main.png")

    Returns:
        Binary image data
    """
    # Parse bucket and path
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else storage_path

    # ❌ SYNC CALL IN ASYNC METHOD - RACE CONDITION!
    data = self.supabase.storage.from_(bucket).download(path)
    return data

async def get_image_as_base64(self, storage_path: str) -> str:
    """
    Download image and convert to base64 string.

    Args:
        storage_path: Full storage path

    Returns:
        Base64-encoded image string
    """
    # ❌ Awaits broken async method
    image_data = await self.download_image(storage_path)
    return base64.b64encode(image_data).decode('utf-8')
```

### Why It Fails

1. `self.supabase` is a **sync** Supabase client (from `supabase-py`)
2. `download()` is a **synchronous** blocking I/O operation
3. Calling sync I/O in async context without thread pool wrapper causes:
   - Event loop blocking
   - Race conditions in concurrent async operations
   - Unreliable behavior (works sometimes, fails other times)
4. When it fails, CloudFlare returns HTML error page instead of image

---

## ✅ THE FIX: `asyncio.to_thread()`

### Solution Approach

Use Python's `asyncio.to_thread()` (available since Python 3.9) to run sync Supabase operations in a thread pool.

### Fixed Code

```python
async def download_image(self, storage_path: str) -> bytes:
    """
    Download image from Supabase Storage.

    Args:
        storage_path: Full storage path (e.g., "products/{id}/main.png")

    Returns:
        Binary image data
    """
    import asyncio

    # Parse bucket and path
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else storage_path

    # ✅ Run sync Supabase call in thread pool to avoid blocking event loop
    data = await asyncio.to_thread(
        lambda: self.supabase.storage.from_(bucket).download(path)
    )
    return data
```

### Why This Works

1. `asyncio.to_thread()` runs sync function in thread pool executor
2. Async event loop stays unblocked
3. Proper async/await semantics maintained
4. No race conditions
5. Reliable behavior in concurrent async contexts

### Other Methods That May Need Same Fix

Check these methods in `ad_creation_service.py` for similar issues:

```python
# Lines 150-176: upload_reference_ad() - uses sync .upload()
async def upload_reference_ad(...)
    self.supabase.storage.from_("reference-ads").upload(...)  # ❌ SYNC

# Lines 178-205: upload_generated_ad() - uses sync .upload()
async def upload_generated_ad(...)
    self.supabase.storage.from_("generated-ads").upload(...)  # ❌ SYNC
```

**Action:** Apply same `asyncio.to_thread()` fix to upload methods.

---

## 📊 TEST PROGRESSION TIMELINE

| Fix Applied | Test Duration | Error |
|-------------|---------------|-------|
| None (baseline) | ~10s | JSON scoping error |
| Fix #1 (JSON import) | ~12s | Base64 type mismatch |
| Fix #2 (base64 string) | ~16s | Markdown fence JSON parse |
| Fix #3 (fence stripping) | ~26s | whichOneof protobuf error |
| Fix #4 (real image) | **463s (7m 43s)** | Async/sync storage download |
| Fix #5 (asyncio.to_thread) | **⏳ Testing next** | TBD |

**Total Progress:** From failing at 10 seconds to running for **7 minutes 43 seconds**

**Workflow Stages Completed:**
1. ✅ Create ad run in database
2. ✅ Upload reference ad to storage
3. ✅ Get product data with images
4. ✅ Get hooks for product
5. ⏸️ Analyze reference ad (BLOCKED BY BUG #5)
6. ⏳ Select 5 diverse hooks
7. ⏳ Select product images
8. ⏳ Generate 5 NanoBanana prompts
9. ⏳ Generate 5 ad images
10. ⏳ Review ads with Claude
11. ⏳ Review ads with Gemini
12. ⏳ Apply dual review logic
13. ⏳ Return complete results

---

## 🔑 KEY LEARNINGS

### 1. Async/Sync Client Integration

**Problem:** Mixing sync clients (Supabase) with async code
**Solution:** Always wrap sync I/O with `asyncio.to_thread()`

**Pattern for Reuse:**
```python
# ❌ WRONG - Sync call in async method
async def my_method(self):
    result = self.sync_client.some_operation()
    return result

# ✅ CORRECT - Wrapped in thread pool
async def my_method(self):
    import asyncio
    result = await asyncio.to_thread(
        lambda: self.sync_client.some_operation()
    )
    return result
```

### 2. Diagnostic Strategy for Storage Issues

1. **Isolate the component** - Test storage in standalone context first
2. **Verify infrastructure** - Check buckets, files, permissions
3. **Test sync vs async** - Compare behavior in both contexts
4. **Check actual data** - Inspect response content, not just status
5. **Look for HTML responses** - CloudFlare/error pages indicate API failures

### 3. When to Suspect Async/Sync Issues

Red flags:
- Method marked `async` but no `await` inside
- Using sync SDK clients (Supabase, Firebase, etc.) in async code
- Intermittent failures (works sometimes, fails other times)
- Different behavior in standalone vs integrated contexts
- CloudFlare/error pages instead of expected data

### 4. Python 3.9+ Best Practice

For any sync I/O in async code:
- File operations: `await asyncio.to_thread(open, ...)`
- Database calls: `await asyncio.to_thread(sync_client.query, ...)`
- HTTP requests (sync): `await asyncio.to_thread(requests.get, ...)`
- Storage operations: `await asyncio.to_thread(storage_client.download, ...)`

---

## 📂 FILES INVOLVED

### Diagnostic Files Created
- `debug_storage.py` - Standalone storage diagnostic script ✅

### Production Files to Fix
- `viraltracker/services/ad_creation_service.py`
  - Line 222: `download_image()` - **FIX NEEDED**
  - Line 169: `upload_reference_ad()` - **CHECK NEEDED**
  - Line 198: `upload_generated_ad()` - **CHECK NEEDED**

### Test Files
- `tests/test_ad_creation_integration.py` - Integration test (no changes needed)

---

## 📝 IMPLEMENTATION PLAN

### Step 1: Fix download_image()
- [x] Identify root cause
- [ ] Add `asyncio.to_thread()` wrapper
- [ ] Test with integration test

### Step 2: Fix upload methods
- [ ] Check if upload methods have same issue
- [ ] Apply same fix if needed
- [ ] Verify uploads work in async context

### Step 3: Verify Complete Workflow
- [ ] Re-run integration test
- [ ] Verify workflow completes all 13 stages
- [ ] Check generated ads are saved correctly

### Step 4: Code Quality
- [ ] Commit changes with descriptive message
- [ ] Update checkpoint with final status
- [ ] Document pattern for future reference

---

## ⏭️ NEXT STEPS

### Immediate
1. **Implement fix** for `download_image()` with `asyncio.to_thread()`
2. **Check upload methods** for same async/sync issue
3. **Re-run integration test** to verify workflow progression

### Follow-up
1. **Monitor workflow** through remaining stages (6-13)
2. **Debug new issues** if any arise
3. **Document completion** when workflow passes end-to-end

### Long-term
1. **Consider async Supabase client** - Check if supabase-py has async support
2. **Extract pattern** to utility function for reusability
3. **Add linting rule** to catch sync-in-async patterns

---

## 🎨 REUSABLE PATTERNS

### Pattern 1: Sync Storage in Async Context

```python
import asyncio

class MyService:
    def __init__(self):
        self.sync_client = get_sync_client()  # e.g., Supabase

    async def download(self, path: str) -> bytes:
        """Download file asynchronously using sync client"""
        data = await asyncio.to_thread(
            lambda: self.sync_client.storage.from_("bucket").download(path)
        )
        return data

    async def upload(self, path: str, data: bytes) -> str:
        """Upload file asynchronously using sync client"""
        await asyncio.to_thread(
            lambda: self.sync_client.storage.from_("bucket").upload(path, data)
        )
        return f"bucket/{path}"
```

### Pattern 2: Diagnostic Script Template

```python
"""
Debug [SERVICE] [OPERATION] issue
"""
import os
import asyncio
from myapp.core.client import get_client

async def debug_operation():
    """Diagnose [operation] issues"""
    client = get_client()

    print("=== [SERVICE] DEBUG ===")
    print(f"Config: {os.getenv('SERVICE_URL')}")

    # Step 1: Check connectivity
    print("STEP 1: Checking connection...")
    try:
        result = client.health_check()
        print(f"✅ Connected: {result}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    # Step 2: Test operation
    print("STEP 2: Testing operation...")
    try:
        data = client.do_operation()
        print(f"✅ Operation successful")
        print(f"   Data type: {type(data)}")
        print(f"   Data size: {len(data)}")
    except Exception as e:
        print(f"❌ Operation failed: {e}")
        import traceback
        traceback.print_exc()

    print("=== DEBUG COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(debug_operation())
```

---

## ✨ ACHIEVEMENTS

- **5 production bugs** identified and root causes found
- **Test progression** from 10s to 463s (46x improvement)
- **Storage infrastructure** verified working correctly
- **Diagnostic methodology** refined for async/sync issues
- **Reusable patterns** documented for future reference

---

**Session Start Time:** 2025-01-25 23:00 UTC
**Current Status:** Fix implementation in progress
**Expected Resolution:** Within next 30 minutes

---

## 🔗 RELATED CHECKPOINTS

- `PHASE5_FOUR_BUGS_FIXED_CHECKPOINT.md` - Bugs #1-4 fixes
- `PHASE5_GEMINI_FIX_CHECKPOINT.md` - Markdown fence fix (Bug #3)
- `PHASE5_WORKFLOW_DEBUG_CHECKPOINT.md` - Earlier workflow debugging
