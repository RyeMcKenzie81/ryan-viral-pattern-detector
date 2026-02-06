# Phase 4 Step 0-1: Implementation Plan

**Date**: 2026-01-24
**Scope**: Infrastructure + Ad Creator instrumentation

---

## Architecture Understanding

The Ad Creator workflow involves:

```
UI Page → Agent (PydanticAI) → Tools → Services → AI APIs
```

**AI calls happen in two places:**

1. **PydanticAI Agent runs** - The orchestrator and ad_creation_agent make LLM calls
2. **GeminiService** - Direct API calls for:
   - `generate_image()` - Image generation (billed per image)
   - `analyze_image()` - Vision analysis (tokens)
   - `review_image()` - Ad review (tokens)
   - `analyze_text()` - Text analysis (tokens)

---

## Step 0: Infrastructure

### 0.1 Database Migration

Create `token_usage` table to store all AI usage events.

**File**: `migrations/2026-01-24_token_usage.sql`

### 0.2 Cost Configuration

Add token/unit costs to `viraltracker/core/config.py`

| Provider | Model | Input (per 1M) | Output (per 1M) |
|----------|-------|----------------|-----------------|
| Anthropic | claude-opus-4-5 | $15.00 | $75.00 |
| Anthropic | claude-sonnet-4 | $3.00 | $15.00 |
| OpenAI | gpt-4o | $2.50 | $10.00 |
| Google | gemini-2.0-flash | $0.10 | $0.40 |
| Google | gemini-2.5-pro | $1.25 | $5.00 |

| Provider | Unit Type | Cost |
|----------|-----------|------|
| Google | image_generation | $0.02 per image |
| ElevenLabs | characters | $0.00003 per char |
| Google Veo | video_seconds | $0.05 per second |

### 0.3 UsageTracker Service

Create `viraltracker/services/usage_tracker.py` with:

- `track()` - Record a usage event (fire-and-forget, never fails main op)
- `get_usage_summary()` - Aggregate usage for date range
- `get_current_month_usage()` - Quick summary for dashboard

---

## Step 1: Instrument Ad Creator

### 1.1 GeminiService Instrumentation

Add optional `usage_tracker` parameter to GeminiService and track:

| Method | What to Track |
|--------|---------------|
| `generate_image()` | 1 image unit + generation time |
| `analyze_image()` | Token usage from response.usage_metadata |
| `review_image()` | Token usage from response.usage_metadata |
| `analyze_text()` | Token usage from response.usage_metadata |
| `generate_content()` | Token usage from response.usage_metadata |

### 1.2 Tracking Pattern (Safe)

```python
# After successful API call
if self.usage_tracker:
    try:
        self.usage_tracker.track(
            user_id=user_id,
            organization_id=organization_id,
            record=UsageRecord(...)
        )
    except Exception as e:
        logger.warning(f"Usage tracking failed: {e}")
        # Continue - don't fail the main operation
```

### 1.3 Context Passing

The GeminiService needs `user_id` and `organization_id` to track.

Options:
- **A**: Pass as parameters to each method (explicit, more changes)
- **B**: Store on service instance when created (cleaner, fewer changes)

**Choosing Option B** - Set context on service initialization.

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `migrations/2026-01-24_token_usage.sql` | CREATE | Usage tracking table |
| `viraltracker/core/config.py` | MODIFY | Add cost constants |
| `viraltracker/services/usage_tracker.py` | CREATE | UsageTracker service |
| `viraltracker/services/models.py` | MODIFY | Add UsageRecord model |
| `viraltracker/services/gemini_service.py` | MODIFY | Add usage tracking |

---

## Validation Plan

After implementation:

1. **Generate an ad** via the Ad Creator UI
2. **Check database**:
   ```sql
   SELECT * FROM token_usage ORDER BY created_at DESC LIMIT 10;
   ```
3. **Verify records have**:
   - Correct provider/model
   - Token counts (for text operations)
   - Unit counts (for image generation)
   - Calculated costs
   - organization_id populated

4. **Verify no errors** in ad generation workflow
5. **Verify no latency increase** (tracking is async/fire-and-forget)

---

## Rollback Plan

If issues occur:
1. Remove usage_tracker from GeminiService init
2. All tracking calls are wrapped in try/except, so they fail silently
3. Table can remain (no harm in empty table)

---

## Implementation Order

1. Create migration file
2. Add cost config to Config
3. Add UsageRecord to models.py
4. Create UsageTracker service
5. Modify GeminiService to accept and use usage_tracker
6. Test ad generation
7. Verify usage records in database
