# Checkpoint 03: Phase 4 Step 0-1 Complete

**Date**: 2026-01-25
**Status**: Ready for Testing

---

## Summary

Implemented usage tracking infrastructure and instrumented GeminiService for the Ad Creator workflow. This is an incremental rollout - after validating Ad Creator works correctly, we'll expand to other services.

---

## What Was Implemented

### Step 0: Infrastructure

| Component | File | Status |
|-----------|------|--------|
| Migration | `migrations/2026-01-24_token_usage.sql` | Created |
| Cost Config | `viraltracker/core/config.py` | Modified |
| UsageTracker Service | `viraltracker/services/usage_tracker.py` | Created |

### Step 1: Ad Creator Instrumentation

| Component | File | Status |
|-----------|------|--------|
| GeminiService | `viraltracker/services/gemini_service.py` | Modified |

**Tracked Methods:**
- `generate_image()` - Tracks 1 image unit + generation time
- `analyze_image()` - Tracks token usage from response
- `review_image()` - Delegates to analyze_image (inherits tracking)
- `analyze_text()` - Tracks token usage from response
- `analyze_hook()` - Tracks token usage from response

### Architecture

```
Ad Creator UI (21_🎨_Ad_Creator.py)
    ↓
    AgentDependencies.create(user_id, organization_id)
    ↓
    GeminiService.set_tracking_context(usage_tracker, user_id, org_id)
    ↓
Agent (PydanticAI)
    ↓
GeminiService.generate_image()  ──┐
GeminiService.analyze_image()   ──┼── _track_usage() ──→ UsageTracker.track()
GeminiService.review_image()    ──┤                           ↓
GeminiService.analyze_text()    ──┘                   token_usage table
```

### Integration Points Updated

- `AgentDependencies.create()` now accepts optional `user_id` and `organization_id`
- When provided, it automatically creates UsageTracker and sets tracking context on GeminiService
- Ad Creator UI passes these from session state (`get_current_user_id()`, `get_current_organization_id()`)

---

## Testing Instructions

### 1. Run the Migration

```sql
-- Run this in Supabase SQL Editor
-- File: migrations/2026-01-24_token_usage.sql

-- Copy and paste the entire contents of that file
```

### 2. Verify Table Created

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'token_usage';
```

Expected columns: id, user_id, organization_id, provider, model, tool_name, operation, input_tokens, output_tokens, total_tokens, units, unit_type, cost_usd, request_metadata, duration_ms, created_at

### 3. Deploy Updated Code

```bash
cd /Users/ryemckenzie/projects/viraltracker
git add -A
git commit -m "feat: Add usage tracking for GeminiService (Phase 4 Step 0-1)"
git push
```

### 4. Test Ad Generation

1. Open the Ad Creator UI in your browser
2. Select a brand and product
3. Generate an ad (this triggers `generate_image()`)
4. View the generated ad (this may trigger `analyze_image()`)

### 5. Verify Usage Records

After generating an ad, run this query:

```sql
SELECT
    created_at,
    provider,
    model,
    tool_name,
    operation,
    input_tokens,
    output_tokens,
    units,
    unit_type,
    cost_usd,
    duration_ms
FROM token_usage
ORDER BY created_at DESC
LIMIT 10;
```

**Expected Results:**
- `operation = 'generate_image'` with `units = 1`, `unit_type = 'image_generation'`
- `operation = 'analyze_image'` with token counts populated
- `provider = 'google'`
- `tool_name = 'gemini_service'`
- `cost_usd` should be calculated (e.g., $0.02 for image generation)

### 6. Verify No Errors

- Ad generation should work exactly as before
- No errors in UI or console
- No latency increase (tracking is fire-and-forget)

---

## Troubleshooting

### No records appearing?

1. **Check organization_id is set**: Usage tracking requires organization_id. If the GeminiService instance doesn't have tracking context set, records won't be created.

2. **Check for errors in logs**: Look for "Usage tracking failed" warnings - these are non-fatal but indicate issues.

3. **Tracking context not set**: The calling code needs to call `gemini_service.set_tracking_context(usage_tracker, user_id, organization_id)` before using the service.

### Records appearing but cost is NULL?

The model name might not match the cost config. Check `viraltracker/core/config.py` TOKEN_COSTS and UNIT_COSTS dictionaries.

---

## Next Steps (After Validation)

Once Ad Creator testing is successful, expand to:

1. **VEO Avatars** - Video generation tracking
2. **Content Pipeline** - Script generation, comic assets
3. **Competitor Research** - Analysis operations
4. **Twitter Service** - Post analysis
5. **Knowledge Base** - RAG query tracking
6. **System Tasks** - Background job tracking

---

## Files Changed

```
migrations/2026-01-24_token_usage.sql        (NEW)
viraltracker/core/config.py                  (MODIFIED - cost config)
viraltracker/services/usage_tracker.py       (NEW)
viraltracker/services/gemini_service.py      (MODIFIED - tracking methods)
viraltracker/agent/dependencies.py           (MODIFIED - tracking context)
viraltracker/ui/pages/21_🎨_Ad_Creator.py    (MODIFIED - pass user/org context)
docs/plans/multi-tenant-auth/PHASE_4_STEP_0_1_IMPLEMENTATION.md (NEW)
docs/plans/multi-tenant-auth/PHASE_4_ROLLOUT_PLAN.md (NEW)
```

---

## Rollback Plan

If issues occur:

1. **Quick fix**: Remove `set_tracking_context()` calls from wherever GeminiService is instantiated
2. **All tracking calls are wrapped in try/except** - they fail silently and won't break ad generation
3. **Table can remain** - empty table causes no harm
