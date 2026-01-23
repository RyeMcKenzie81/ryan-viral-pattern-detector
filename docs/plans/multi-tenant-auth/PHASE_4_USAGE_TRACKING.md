# Phase 4: Usage Tracking

## Goal

Track all AI/API usage to enable:
- Billing per organization
- Usage limits and rate limiting
- Cost visibility for users
- Identifying expensive operations

---

## Database Schema

### `token_usage` Table

Tracks every AI API call:

```sql
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Who
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- What
    provider TEXT NOT NULL,       -- 'openai', 'anthropic', 'google', 'elevenlabs'
    model TEXT NOT NULL,          -- 'gpt-4o', 'claude-opus-4-5', 'gemini-3-pro', etc.
    tool_name TEXT,               -- 'ad_creator', 'competitor_research', 'veo_avatars'
    operation TEXT,               -- 'generate_ad', 'analyze_competitor', 'generate_video'

    -- Usage metrics
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    -- For non-token APIs (video, audio, images)
    units NUMERIC,                -- seconds of video, characters of audio, etc.
    unit_type TEXT,               -- 'seconds', 'characters', 'images'

    -- Cost
    cost_usd NUMERIC(10, 6),      -- Calculated cost in USD

    -- Context
    request_metadata JSONB,       -- Additional context (brand_id, ad_id, etc.)

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INT               -- How long the API call took
);

-- Indexes for common queries
CREATE INDEX idx_token_usage_org_created ON token_usage(organization_id, created_at DESC);
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at DESC);
CREATE INDEX idx_token_usage_tool ON token_usage(tool_name, created_at DESC);
CREATE INDEX idx_token_usage_provider ON token_usage(provider, created_at DESC);
```

### `usage_summary` View

Aggregated view for dashboards:

```sql
CREATE VIEW usage_summary AS
SELECT
    organization_id,
    DATE_TRUNC('day', created_at) AS date,
    provider,
    model,
    tool_name,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(total_tokens) AS total_tokens,
    SUM(cost_usd) AS total_cost_usd
FROM token_usage
GROUP BY organization_id, DATE_TRUNC('day', created_at), provider, model, tool_name;
```

---

## Cost Calculation

### Token-Based Models

| Provider | Model | Input (per 1M) | Output (per 1M) |
|----------|-------|----------------|-----------------|
| OpenAI | gpt-4o | $2.50 | $10.00 |
| OpenAI | gpt-4o-mini | $0.15 | $0.60 |
| Anthropic | claude-opus-4-5 | $15.00 | $75.00 |
| Anthropic | claude-sonnet-4 | $3.00 | $15.00 |
| Google | gemini-3-pro | $1.25 | $5.00 |
| Google | gemini-3-flash | $0.075 | $0.30 |

### Non-Token APIs

| Provider | Service | Unit | Cost |
|----------|---------|------|------|
| Google | Veo (video) | per second | ~$0.05 |
| ElevenLabs | TTS | per character | $0.00003 |
| OpenAI | DALL-E 3 | per image | $0.04-0.12 |
| Google | Imagen | per image | ~$0.02 |

---

## Implementation

### 1. UsageTracker Service

```python
# viraltracker/services/usage_tracker.py

from dataclasses import dataclass
from typing import Optional
from uuid import UUID
from decimal import Decimal

@dataclass
class UsageRecord:
    provider: str
    model: str
    tool_name: str
    operation: str
    input_tokens: int = 0
    output_tokens: int = 0
    units: Optional[float] = None
    unit_type: Optional[str] = None
    cost_usd: Optional[Decimal] = None
    request_metadata: Optional[dict] = None
    duration_ms: Optional[int] = None

class UsageTracker:
    """Track AI/API usage for billing and limits."""

    # Cost per 1M tokens (input, output)
    TOKEN_COSTS = {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "claude-opus-4-5": (15.00, 75.00),
        "claude-sonnet-4": (3.00, 15.00),
        "gemini-3-pro": (1.25, 5.00),
        "gemini-3-flash": (0.075, 0.30),
    }

    def __init__(self, supabase_client):
        self.client = supabase_client

    def track(
        self,
        user_id: Optional[UUID],
        organization_id: UUID,
        record: UsageRecord
    ) -> None:
        """Record a usage event."""
        cost = record.cost_usd or self._calculate_cost(record)

        self.client.table("token_usage").insert({
            "user_id": str(user_id) if user_id else None,
            "organization_id": str(organization_id),
            "provider": record.provider,
            "model": record.model,
            "tool_name": record.tool_name,
            "operation": record.operation,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "units": record.units,
            "unit_type": record.unit_type,
            "cost_usd": float(cost) if cost else None,
            "request_metadata": record.request_metadata,
            "duration_ms": record.duration_ms,
        }).execute()

    def _calculate_cost(self, record: UsageRecord) -> Optional[Decimal]:
        """Calculate cost based on usage."""
        if record.model in self.TOKEN_COSTS:
            input_rate, output_rate = self.TOKEN_COSTS[record.model]
            input_cost = (record.input_tokens / 1_000_000) * input_rate
            output_cost = (record.output_tokens / 1_000_000) * output_rate
            return Decimal(str(input_cost + output_cost))
        return None

    def get_org_usage(
        self,
        organization_id: UUID,
        start_date: datetime,
        end_date: datetime
    ) -> dict:
        """Get usage summary for an organization."""
        result = self.client.table("token_usage").select(
            "provider, model, tool_name, "
            "sum(input_tokens), sum(output_tokens), sum(cost_usd), count(*)"
        ).eq(
            "organization_id", str(organization_id)
        ).gte(
            "created_at", start_date.isoformat()
        ).lte(
            "created_at", end_date.isoformat()
        ).execute()

        return result.data
```

### 2. Integration Points

Where to add tracking:

| Service | File | What to Track |
|---------|------|---------------|
| Gemini | `services/gemini_service.py` | All Gemini calls |
| Ad Creation Agent | `agent/agents/ad_creation_agent.py` | Agent tool calls |
| Pydantic AI | `agent/orchestrator.py` | All agent runs |
| ElevenLabs | `services/audio_service.py` | TTS generation |
| Veo | `services/veo_service.py` | Video generation |

### 3. Pydantic AI Integration

Pydantic AI provides hooks for tracking. Add to agent runs:

```python
from pydantic_ai import Agent
from pydantic_ai.usage import Usage

async def run_agent_with_tracking(
    agent: Agent,
    prompt: str,
    user_id: UUID,
    org_id: UUID,
    tool_name: str
):
    result = await agent.run(prompt)

    # Extract usage from result
    if result.usage:
        tracker.track(
            user_id=user_id,
            organization_id=org_id,
            record=UsageRecord(
                provider="anthropic",  # or detect from model
                model=agent.model,
                tool_name=tool_name,
                operation="agent_run",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )
        )

    return result
```

### 4. Context Manager for Easy Tracking

```python
from contextlib import contextmanager
import time

@contextmanager
def track_usage(
    tracker: UsageTracker,
    user_id: UUID,
    org_id: UUID,
    provider: str,
    model: str,
    tool_name: str,
    operation: str,
    metadata: dict = None
):
    """Context manager for tracking API calls."""
    start_time = time.time()
    usage_data = {"input_tokens": 0, "output_tokens": 0}

    try:
        yield usage_data  # Caller fills in token counts
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        tracker.track(
            user_id=user_id,
            organization_id=org_id,
            record=UsageRecord(
                provider=provider,
                model=model,
                tool_name=tool_name,
                operation=operation,
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                request_metadata=metadata,
                duration_ms=duration_ms,
            )
        )

# Usage example:
with track_usage(tracker, user_id, org_id, "google", "gemini-3-pro", "ad_creator", "generate_hook") as usage:
    response = gemini_client.generate(prompt)
    usage["input_tokens"] = response.usage.input_tokens
    usage["output_tokens"] = response.usage.output_tokens
```

---

## UI: Usage Dashboard

New page: `68_📊_Usage_Dashboard.py`

**Features**:
- Current month usage summary
- Cost breakdown by tool/model
- Daily usage chart
- Top users by usage (for admins)
- Export to CSV

**Mockup**:
```
📊 Usage Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This Month                      Daily Trend
┌─────────────────────────┐    ┌─────────────────────┐
│ Total Cost: $47.23      │    │ ▁▂▄▃▅▆▄▅▇█▆▅       │
│ Total Tokens: 2.4M      │    │ Jan 1 ──────► Jan 23│
│ API Calls: 1,247        │    └─────────────────────┘
└─────────────────────────┘

By Tool                         By Model
┌─────────────────────────┐    ┌─────────────────────┐
│ Ad Creator      $23.45  │    │ claude-opus   $31.20│
│ Competitor Res  $12.30  │    │ gemini-3-pro  $10.45│
│ Veo Avatars     $8.20   │    │ gpt-4o        $5.58 │
│ Other           $3.28   │    └─────────────────────┘
└─────────────────────────┘
```

---

## Migration

```sql
-- migrations/2026-01-XX_usage_tracking.sql

-- Usage tracking table
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID NOT NULL,  -- Will reference organizations after Phase 3
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    tool_name TEXT,
    operation TEXT,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    units NUMERIC,
    unit_type TEXT,
    cost_usd NUMERIC(10, 6),
    request_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INT
);

CREATE INDEX idx_token_usage_org_created ON token_usage(organization_id, created_at DESC);
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at DESC);
CREATE INDEX idx_token_usage_tool ON token_usage(tool_name, created_at DESC);

COMMENT ON TABLE token_usage IS 'Tracks all AI/API usage for billing and limits';
```

---

## Implementation Order

1. **Create migration** - Add `token_usage` table
2. **Create UsageTracker service** - Core tracking logic
3. **Add to AgentDependencies** - Make tracker available to agents
4. **Instrument Gemini service** - Track Gemini calls
5. **Instrument Pydantic AI** - Track agent runs
6. **Create Usage Dashboard UI** - View usage
7. **Add to other services** - ElevenLabs, Veo, etc.

---

## Dependencies

- Phase 3 (Organizations) should be done first so we have `organization_id`
- Or: Use a placeholder org ID for now, update later

---

## Testing

1. Make some AI calls through the UI
2. Check `token_usage` table has records
3. Verify cost calculations are correct
4. Test Usage Dashboard shows accurate data
