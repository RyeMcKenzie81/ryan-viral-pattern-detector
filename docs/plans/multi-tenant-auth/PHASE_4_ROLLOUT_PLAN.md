# Phase 4: Usage Tracking - Incremental Rollout Plan

**Approach**: Start with Ad Creator, validate it works, then expand to other services one at a time.

---

## Rollout Order

| Step | Service/Page | Provider | Status |
|------|--------------|----------|--------|
| 0 | Infrastructure (table + UsageTracker) | - | Pending |
| 1 | Ad Creator | Anthropic | Pending |
| **--- Brands ---** | | | |
| 2 | Brand Manager | Mixed | Pending |
| 3 | Personas | Anthropic/OpenAI | Pending |
| 4 | URL Mapping | Gemini | Pending |
| 5 | Brand Research | Mixed | Pending |
| 6 | Client Onboarding | Mixed | Pending |
| **--- Competitors ---** | | | |
| 7 | Competitors | Mixed | Pending |
| 8 | Competitor Research | Mixed | Pending |
| 9 | Competitive Analysis | Anthropic | Pending |
| 10 | Reddit Research | OpenAI | Pending |
| **--- Other ---** | | | |
| 11 | Veo Avatars | Google (Veo) | Pending |
| 12 | Knowledge Base | OpenAI (embeddings) | Pending |
| **--- System ---** | | | |
| 13 | Scheduled Tasks | Mixed | Pending |
| 14 | Agent Catalog | - | Pending |
| 15 | Remaining services | Mixed | Pending |

---

## Step 0: Infrastructure (One-Time Setup)

### Database Migration
```sql
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    provider TEXT NOT NULL,           -- 'anthropic', 'openai', 'google'
    model TEXT NOT NULL,              -- 'claude-opus-4-5', 'gpt-4o'
    tool_name TEXT,                   -- 'ad_creator', 'competitor_research'
    operation TEXT,                   -- 'generate_hook', 'analyze_ad'
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    units NUMERIC,                    -- For non-token APIs (video seconds, characters)
    unit_type TEXT,                   -- 'seconds', 'characters'
    cost_usd NUMERIC(10, 6),
    request_metadata JSONB,
    duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_token_usage_org_created ON token_usage(organization_id, created_at DESC);
CREATE INDEX idx_token_usage_tool ON token_usage(tool_name, created_at DESC);
```

### UsageTracker Service
- Create `viraltracker/services/usage_tracker.py`
- Methods: `track()`, `get_usage_summary()`, `get_current_month_usage()`
- Safe tracking with try/except (never fails the main operation)

### Cost Config
- Add token costs to `viraltracker/core/config.py`

---

## Step 1: Ad Creator

### Target Files
- `viraltracker/services/ad_creation_service.py`
- Methods that call Claude API

### What to Track
| Method | Provider | Model |
|--------|----------|-------|
| `generate_hook()` | Anthropic | claude-opus-4-5 |
| `generate_ad_copy()` | Anthropic | claude-opus-4-5 |
| `recreate_template()` | Anthropic | claude-opus-4-5 |

### Implementation Pattern
```python
async def generate_hook(self, ...):
    start_time = time.time()

    # Existing code - call Claude
    response = await self.client.messages.create(...)

    # NEW: Track usage (safe - won't break if fails)
    if self.usage_tracker:
        try:
            self.usage_tracker.track(
                user_id=user_id,
                organization_id=organization_id,
                record=UsageRecord(
                    provider="anthropic",
                    model="claude-opus-4-5",
                    tool_name="ad_creator",
                    operation="generate_hook",
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            )
        except Exception as e:
            logger.warning(f"Usage tracking failed: {e}")

    return result  # Always return result
```

### Validation
1. Generate some ads
2. Check `token_usage` table has records
3. Verify costs calculated correctly
4. Confirm no errors or slowdowns in ad generation

---

## Step 2-N: Additional Services

**Common services to add (pick based on usage):**

| Service | Provider | Notes |
|---------|----------|-------|
| GeminiService | Google | Image analysis, video analysis |
| Competitor Research | Mixed | Multiple AI calls |
| Brand Research | Mixed | Multiple AI calls |
| Veo Service | Google | Track video seconds, not tokens |
| Audio Service | ElevenLabs | Track characters, not tokens |

---

## Cost Reference

### Token Costs (per 1M tokens)

| Model | Input | Output |
|-------|-------|--------|
| claude-opus-4-5 | $15.00 | $75.00 |
| claude-sonnet-4 | $3.00 | $15.00 |
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gemini-3-pro | $1.25 | $5.00 |

### Unit Costs

| Service | Unit | Cost |
|---------|------|------|
| Veo | per second | $0.05 |
| ElevenLabs | per character | $0.00003 |
| DALL-E | per image | $0.04 |

---

## Success Criteria

- [ ] token_usage table populated with Ad Creator calls
- [ ] Costs calculated correctly (spot check a few)
- [ ] No errors in ad generation workflow
- [ ] No noticeable latency increase

---

## Commands for Implementation

```bash
# Read this plan
cat docs/plans/multi-tenant-auth/PHASE_4_ROLLOUT_PLAN.md

# Check usage after testing
# SQL: SELECT * FROM token_usage ORDER BY created_at DESC LIMIT 10;
```
