# Phase 4: Usage Tracking

## Goal

Track all AI/API usage to enable:
- Billing per organization
- Usage limits and rate limiting
- Cost visibility for users
- Identifying expensive operations

## Prerequisites

- Phase 3 (Organizations) must be complete
- `organization_id` available in session/context

---

## Architecture Alignment

This phase follows the project's 3-layer architecture:

```
Agent Layer → Tools call UsageTracker via ctx.deps.usage_tracker
Service Layer → UsageTracker service with business logic
Interface Layer → Usage Dashboard UI page
```

---

## Pydantic Models

All models use Pydantic `BaseModel` (not `@dataclass`):

```python
# viraltracker/services/models.py (add to existing file)

from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class UsageRecord(BaseModel):
    """Single AI/API usage event for tracking."""
    provider: str                           # 'openai', 'anthropic', 'google', 'elevenlabs'
    model: str                              # 'gpt-4o', 'claude-opus-4-5', 'gemini-3-pro'
    tool_name: Optional[str] = None         # 'ad_creator', 'competitor_research'
    operation: Optional[str] = None         # 'generate_ad', 'analyze_competitor'
    input_tokens: int = 0
    output_tokens: int = 0
    units: Optional[float] = None           # For non-token APIs (seconds, characters)
    unit_type: Optional[str] = None         # 'seconds', 'characters', 'images'
    cost_usd: Optional[Decimal] = None      # Calculated or provided cost
    request_metadata: Optional[dict] = None # Additional context (brand_id, ad_id)
    duration_ms: Optional[int] = None       # API call duration

class UsageSummary(BaseModel):
    """Aggregated usage summary."""
    organization_id: UUID
    period_start: datetime
    period_end: datetime
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal
    by_provider: dict                       # {provider: {tokens, cost}}
    by_tool: dict                           # {tool_name: {tokens, cost}}
```

---

## Database Schema

### `token_usage` Table

```sql
-- migrations/2026-01-XX_usage_tracking.sql

CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Who
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- What
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    tool_name TEXT,
    operation TEXT,

    -- Token usage
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    -- Non-token APIs (video, audio, images)
    units NUMERIC,
    unit_type TEXT,

    -- Cost
    cost_usd NUMERIC(10, 6),

    -- Context
    request_metadata JSONB,

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INT
);

-- Indexes for common queries
CREATE INDEX idx_token_usage_org_created ON token_usage(organization_id, created_at DESC);
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at DESC);
CREATE INDEX idx_token_usage_tool ON token_usage(tool_name, created_at DESC);
CREATE INDEX idx_token_usage_provider ON token_usage(provider, created_at DESC);

-- Helper function for summing usage
CREATE OR REPLACE FUNCTION sum_usage(
    org_id UUID,
    column_name TEXT,
    start_date TIMESTAMPTZ
) RETURNS NUMERIC AS $$
DECLARE
    result NUMERIC;
BEGIN
    EXECUTE format(
        'SELECT COALESCE(SUM(%I), 0) FROM token_usage WHERE organization_id = $1 AND created_at >= $2',
        column_name
    ) INTO result USING org_id, start_date;
    RETURN result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE token_usage IS 'Tracks all AI/API usage for billing and limits';
```

---

## Cost Configuration

Move cost constants to Config class:

```python
# viraltracker/core/config.py (add to Config class)

class Config:
    # ... existing config ...

    # Token costs per 1M tokens (input, output)
    TOKEN_COSTS: dict = {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "claude-opus-4-5": (15.00, 75.00),
        "claude-sonnet-4": (3.00, 15.00),
        "gemini-3-pro": (1.25, 5.00),
        "gemini-3-flash": (0.075, 0.30),
    }

    # Non-token API costs
    UNIT_COSTS: dict = {
        "veo_seconds": 0.05,           # Per second of video
        "elevenlabs_characters": 0.00003,  # Per character
        "dalle_image": 0.04,           # Per image (standard)
        "imagen_image": 0.02,          # Per image
    }
```

---

## UsageTracker Service

```python
# viraltracker/services/usage_tracker.py

from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta
from decimal import Decimal
from supabase import Client
import logging

from viraltracker.core.config import Config
from viraltracker.services.models import UsageRecord, UsageSummary

logger = logging.getLogger(__name__)


class UsageTracker:
    """
    Service for tracking AI/API usage.

    Follows thin-tools pattern: this service handles business logic,
    tools/agents call it via ctx.deps.usage_tracker.
    """

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    def track(
        self,
        user_id: Optional[str],
        organization_id: str,
        record: UsageRecord
    ) -> None:
        """
        Record a usage event.

        Args:
            user_id: User who triggered the usage (optional for system ops)
            organization_id: Organization to bill
            record: Usage details
        """
        cost = record.cost_usd or self._calculate_cost(record)

        try:
            self.client.table("token_usage").insert({
                "user_id": user_id,
                "organization_id": organization_id,
                "provider": record.provider,
                "model": record.model,
                "tool_name": record.tool_name,
                "operation": record.operation,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "units": float(record.units) if record.units else None,
                "unit_type": record.unit_type,
                "cost_usd": float(cost) if cost else None,
                "request_metadata": record.request_metadata,
                "duration_ms": record.duration_ms,
            }).execute()

            logger.debug(
                f"Tracked usage: {record.provider}/{record.model} "
                f"tokens={record.input_tokens}+{record.output_tokens} "
                f"cost=${cost}"
            )
        except Exception as e:
            # Don't fail the main operation if tracking fails
            logger.error(f"Failed to track usage: {e}")

    def _calculate_cost(self, record: UsageRecord) -> Optional[Decimal]:
        """Calculate cost based on usage and configured rates."""
        # Token-based cost
        if record.model in Config.TOKEN_COSTS:
            input_rate, output_rate = Config.TOKEN_COSTS[record.model]
            input_cost = (record.input_tokens / 1_000_000) * input_rate
            output_cost = (record.output_tokens / 1_000_000) * output_rate
            return Decimal(str(round(input_cost + output_cost, 6)))

        # Unit-based cost
        if record.units and record.unit_type:
            unit_key = f"{record.provider}_{record.unit_type}"
            if unit_key in Config.UNIT_COSTS:
                return Decimal(str(round(record.units * Config.UNIT_COSTS[unit_key], 6)))

        return None

    def get_usage_summary(
        self,
        organization_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> UsageSummary:
        """
        Get aggregated usage summary for an organization.

        Args:
            organization_id: Organization ID
            start_date: Period start
            end_date: Period end

        Returns:
            UsageSummary with aggregated data
        """
        result = self.client.table("token_usage").select("*").eq(
            "organization_id", organization_id
        ).gte("created_at", start_date.isoformat()).lte(
            "created_at", end_date.isoformat()
        ).execute()

        records = result.data or []

        # Aggregate
        total_input = sum(r.get("input_tokens", 0) for r in records)
        total_output = sum(r.get("output_tokens", 0) for r in records)
        total_cost = sum(Decimal(str(r.get("cost_usd", 0) or 0)) for r in records)

        # By provider
        by_provider = {}
        for r in records:
            provider = r.get("provider", "unknown")
            if provider not in by_provider:
                by_provider[provider] = {"tokens": 0, "cost": Decimal("0")}
            by_provider[provider]["tokens"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)
            by_provider[provider]["cost"] += Decimal(str(r.get("cost_usd", 0) or 0))

        # By tool
        by_tool = {}
        for r in records:
            tool = r.get("tool_name") or "unknown"
            if tool not in by_tool:
                by_tool[tool] = {"tokens": 0, "cost": Decimal("0")}
            by_tool[tool]["tokens"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)
            by_tool[tool]["cost"] += Decimal(str(r.get("cost_usd", 0) or 0))

        return UsageSummary(
            organization_id=UUID(organization_id),
            period_start=start_date,
            period_end=end_date,
            total_requests=len(records),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_usd=total_cost,
            by_provider=by_provider,
            by_tool=by_tool,
        )

    def get_current_month_usage(self, organization_id: str) -> UsageSummary:
        """Get usage summary for current month."""
        now = datetime.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_usage_summary(organization_id, start_of_month, now)
```

---

## AgentDependencies Integration

Add UsageTracker to AgentDependencies:

```python
# viraltracker/agent/dependencies.py

from dataclasses import dataclass
from typing import Optional
from viraltracker.services.usage_tracker import UsageTracker
# ... other imports

@dataclass
class AgentDependencies:
    # Existing services
    twitter: TwitterService
    gemini: GeminiService
    ad_creation: AdCreationService
    # ... other existing services

    # User/Org context (from Phase 3)
    user_id: Optional[str] = None
    organization_id: Optional[str] = None

    # Usage tracking (Phase 4)
    usage_tracker: Optional[UsageTracker] = None
```

Update dependency factory:

```python
# viraltracker/agent/dependencies.py (or wherever deps are created)

def create_agent_dependencies(
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None
) -> AgentDependencies:
    """Create AgentDependencies with all services."""
    from viraltracker.core.database import get_supabase_client

    client = get_supabase_client()

    return AgentDependencies(
        twitter=TwitterService(client),
        gemini=GeminiService(),
        ad_creation=AdCreationService(client),
        # ... other services
        user_id=user_id,
        organization_id=organization_id,
        usage_tracker=UsageTracker(client),
    )
```

---

## Integration Patterns

### Pattern 1: Track in Agent Tools (Recommended)

```python
# viraltracker/agent/agents/ad_creation_agent.py

@ad_creation_agent.tool(...)
async def generate_ad_copy(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    template_id: str
) -> dict:
    """Generate ad copy for a product."""
    import time
    start_time = time.time()

    # Do the work
    result = await ctx.deps.ad_creation.generate_copy(product_id, template_id)

    # Track usage (if we have token counts from the result)
    if ctx.deps.usage_tracker and ctx.deps.organization_id:
        ctx.deps.usage_tracker.track(
            user_id=ctx.deps.user_id,
            organization_id=ctx.deps.organization_id,
            record=UsageRecord(
                provider="anthropic",
                model="claude-opus-4-5",
                tool_name="ad_creation",
                operation="generate_ad_copy",
                input_tokens=result.get("usage", {}).get("input_tokens", 0),
                output_tokens=result.get("usage", {}).get("output_tokens", 0),
                duration_ms=int((time.time() - start_time) * 1000),
                request_metadata={"product_id": product_id, "template_id": template_id}
            )
        )

    return result
```

### Pattern 2: Track in Service Layer

For services that make direct AI calls:

```python
# viraltracker/services/gemini_service.py

class GeminiService:
    def __init__(self, usage_tracker: Optional[UsageTracker] = None):
        self.usage_tracker = usage_tracker
        # ... other init

    async def analyze_image(
        self,
        image_url: str,
        prompt: str,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> dict:
        """Analyze an image with Gemini."""
        import time
        start_time = time.time()

        # Make API call
        response = await self.client.generate_content(...)

        # Track usage
        if self.usage_tracker and organization_id:
            self.usage_tracker.track(
                user_id=user_id,
                organization_id=organization_id,
                record=UsageRecord(
                    provider="google",
                    model="gemini-3-pro",
                    tool_name="gemini_service",
                    operation="analyze_image",
                    input_tokens=response.usage_metadata.prompt_token_count,
                    output_tokens=response.usage_metadata.candidates_token_count,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            )

        return {"analysis": response.text, "usage": {...}}
```

### Pattern 3: Context Manager for Easy Tracking

```python
# viraltracker/services/usage_tracker.py (add to UsageTracker class)

from contextlib import contextmanager
import time

@contextmanager
def track_operation(
    self,
    user_id: Optional[str],
    organization_id: str,
    provider: str,
    model: str,
    tool_name: str,
    operation: str,
    metadata: dict = None
):
    """
    Context manager for tracking an operation.

    Usage:
        with tracker.track_operation(...) as usage:
            result = await some_api_call()
            usage["input_tokens"] = result.input_tokens
            usage["output_tokens"] = result.output_tokens
    """
    start_time = time.time()
    usage_data = {"input_tokens": 0, "output_tokens": 0, "units": None, "unit_type": None}

    try:
        yield usage_data
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        self.track(
            user_id=user_id,
            organization_id=organization_id,
            record=UsageRecord(
                provider=provider,
                model=model,
                tool_name=tool_name,
                operation=operation,
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                units=usage_data.get("units"),
                unit_type=usage_data.get("unit_type"),
                request_metadata=metadata,
                duration_ms=duration_ms,
            )
        )
```

Usage:
```python
with ctx.deps.usage_tracker.track_operation(
    user_id=ctx.deps.user_id,
    organization_id=ctx.deps.organization_id,
    provider="openai",
    model="gpt-4o",
    tool_name="ad_creator",
    operation="generate_hook"
) as usage:
    response = await openai_client.chat.completions.create(...)
    usage["input_tokens"] = response.usage.prompt_tokens
    usage["output_tokens"] = response.usage.completion_tokens
```

---

## Pydantic AI Agent Run Tracking

Track usage from Pydantic AI agent runs:

```python
# viraltracker/agent/orchestrator.py (or agent runner)

async def run_agent_with_tracking(
    agent: Agent,
    prompt: str,
    deps: AgentDependencies
) -> AgentResult:
    """Run an agent and track its usage."""
    import time
    start_time = time.time()

    result = await agent.run(prompt, deps=deps)

    # Track if we have usage info and org context
    if result.usage() and deps.usage_tracker and deps.organization_id:
        usage = result.usage()
        deps.usage_tracker.track(
            user_id=deps.user_id,
            organization_id=deps.organization_id,
            record=UsageRecord(
                provider=_get_provider_from_model(agent.model),
                model=str(agent.model),
                tool_name="agent_run",
                operation=agent.name or "orchestrator",
                input_tokens=usage.request_tokens or 0,
                output_tokens=usage.response_tokens or 0,
                duration_ms=int((time.time() - start_time) * 1000),
            )
        )

    return result

def _get_provider_from_model(model: str) -> str:
    """Extract provider from model string."""
    if "claude" in model.lower():
        return "anthropic"
    elif "gpt" in model.lower():
        return "openai"
    elif "gemini" in model.lower():
        return "google"
    return "unknown"
```

---

## UI: Usage Dashboard

Create new page: `viraltracker/ui/pages/68_📊_Usage_Dashboard.py`

```python
"""Usage Dashboard - View AI/API usage and costs."""

import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Usage Dashboard", page_icon="📊", layout="wide")

from viraltracker.ui.auth import require_auth
require_auth()

from viraltracker.ui.utils import render_organization_selector, get_current_organization_id
from viraltracker.services.usage_tracker import UsageTracker
from viraltracker.core.database import get_supabase_client

st.title("📊 Usage Dashboard")

# Organization selector
org_id = render_organization_selector()
if not org_id:
    st.warning("Please select an organization")
    st.stop()

# Get usage data
tracker = UsageTracker(get_supabase_client())
summary = tracker.get_current_month_usage(org_id)

# Display metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Cost", f"${summary.total_cost_usd:.2f}")
with col2:
    st.metric("Total Tokens", f"{(summary.total_input_tokens + summary.total_output_tokens):,}")
with col3:
    st.metric("API Calls", f"{summary.total_requests:,}")
with col4:
    st.metric("Input Tokens", f"{summary.total_input_tokens:,}")

st.divider()

# Breakdown tables
col1, col2 = st.columns(2)

with col1:
    st.subheader("By Provider")
    if summary.by_provider:
        for provider, data in sorted(summary.by_provider.items(), key=lambda x: x[1]["cost"], reverse=True):
            st.write(f"**{provider}**: {data['tokens']:,} tokens, ${data['cost']:.2f}")
    else:
        st.info("No usage data yet")

with col2:
    st.subheader("By Tool")
    if summary.by_tool:
        for tool, data in sorted(summary.by_tool.items(), key=lambda x: x[1]["cost"], reverse=True):
            st.write(f"**{tool}**: {data['tokens']:,} tokens, ${data['cost']:.2f}")
    else:
        st.info("No usage data yet")
```

---

## Services to Instrument

| Service | File | What to Track |
|---------|------|---------------|
| GeminiService | `services/gemini_service.py` | All Gemini API calls |
| AdCreationService | `services/ad_creation_service.py` | Ad generation calls |
| Audio Service | `services/audio_service.py` | ElevenLabs TTS |
| Veo Service | `services/veo_service.py` | Video generation |
| Agent Orchestrator | `agent/orchestrator.py` | All agent runs |

---

## Implementation Order

1. **Create migration** - Add `token_usage` table
2. **Add Pydantic models** - `UsageRecord`, `UsageSummary` to `models.py`
3. **Add cost config** - `TOKEN_COSTS`, `UNIT_COSTS` to `Config`
4. **Create UsageTracker** - `services/usage_tracker.py`
5. **Update AgentDependencies** - Add `usage_tracker`
6. **Instrument GeminiService** - Add tracking to Gemini calls
7. **Instrument agent runs** - Track Pydantic AI usage
8. **Create Usage Dashboard** - UI page for viewing usage
9. **Instrument remaining services** - Audio, Veo, etc.

---

## Testing

1. Make some AI calls through the UI (ad creator, etc.)
2. Check `token_usage` table has records:
   ```sql
   SELECT * FROM token_usage ORDER BY created_at DESC LIMIT 10;
   ```
3. Verify cost calculations match expected rates
4. Test Usage Dashboard shows accurate data
5. Test with missing org_id (should not crash, just not track)
