# Checkpoint: Fix Ad Regeneration UUID Serialization Error

**Date**: 2026-02-06
**Branch**: `main`
**Commits**: `a9cc789`, `d3eb5d8`

## Problem

Clicking "Rerun" on a rejected/flagged ad in the Ad History page caused an error:

```
Regeneration failed: Object of type UUID is not JSON serializable
```

The error would flash briefly on screen and immediately disappear, making it hard to diagnose.

## Root Cause Analysis

Two issues were identified:

### Issue 1: UUID objects leaking into Supabase JSONB insert

In `regenerate_ad()` (`ad_creation_service.py:1928`), the product data was converted using:

```python
product_dict = product.model_dump()
```

Pydantic v2's `model_dump()` (default mode) preserves Python types — so `Product.brand_id: UUID` and `Product.id: UUID` remained as `uuid.UUID` objects in the dict. This product dict was then passed to `generate_prompt()`, which incorporated product fields into the `json_prompt` dict. When the `json_prompt` was inserted into the `prompt_spec` JSONB column via Supabase (line 2070), the JSON serializer raised `TypeError: Object of type UUID is not JSON serializable`.

### Issue 2: Error message hidden by immediate `st.rerun()`

In `22_📊_Ad_History.py`, the Rerun button handler called `st.rerun()` unconditionally after both success and failure:

```python
except Exception as e:
    st.error(f"Regeneration failed: {e}")
st.session_state.rerun_generating = False
st.rerun()  # This hid the error immediately
```

## Fix

### Fix 1: `model_dump(mode='json')` (ad_creation_service.py:1928)

Changed to:

```python
product_dict = product.model_dump(mode='json')
```

Pydantic's `mode='json'` serializes all types to JSON-compatible formats: UUIDs → strings, datetimes → ISO strings, etc. This prevents UUID objects from leaking into the prompt spec or any downstream data structures.

### Fix 2: Defensive `UUID(str(brand_id))` (ad_creation_service.py:1934)

Changed `UUID(brand_id)` to `UUID(str(brand_id))` as belt-and-suspenders safety — handles both UUID objects and strings.

### Fix 3: Error visibility in Ad History (22_📊_Ad_History.py)

Restructured the Rerun button handler:
- **On success**: saves result to `st.session_state.rerun_result`, then calls `st.rerun()`. After page reload, the result is displayed at the top of the page via a new session state check.
- **On failure**: calls `st.error()` without `st.rerun()`, so the error message persists and the user can read it.

## Files Modified

| File | Change |
|------|--------|
| `viraltracker/services/ad_creation_service.py` | `model_dump(mode='json')` + `UUID(str(brand_id))` |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | Error visibility fix + success message via session state |

## Lesson Learned

When using Pydantic models that contain UUID fields, always use `model_dump(mode='json')` when the result will be:
- Inserted into a JSONB database column
- Passed to any JSON serialization context
- Used as part of a dict that may be serialized later

The default `model_dump()` preserves Python-native types, which is useful for internal Python code but breaks JSON serialization boundaries.

## Verification

Tested in production — clicking "Rerun" on a rejected ad now:
1. Successfully regenerates the image
2. Saves to database without serialization errors
3. Shows success message after page reload
4. On failure, shows a persistent error message the user can read
