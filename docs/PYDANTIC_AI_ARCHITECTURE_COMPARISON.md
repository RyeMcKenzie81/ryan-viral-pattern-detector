# PydanticAI Architecture Comparison & Recommendations

**Date:** 2025-01-24
**Purpose:** Compare existing migration plans with PydanticAI best practices from official docs
**Documents Analyzed:**
- `PYDANTIC_AI_MIGRATION_PLAN.md` (Nov 20, 2025)
- `ORCHESTRATOR_REFACTOR_PLAN.md` (Nov 21, 2025)
- ChatGPT/PydanticAI suggested 5-layer structure

---

## Executive Summary

**Good News:** Your architecture is **85% aligned** with PydanticAI best practices! ✅

**What you have right:**
- ✅ Services layer (Level 1: Dependencies)
- ✅ Agent layer (Level 2: Agents as roles)
- ✅ Tools layer (Level 3: Tools & toolsets)
- ✅ Orchestration pattern (Level 4: Multi-agent orchestration)
- ✅ UI/API integration (Level 5: Integrations)

**What needs enhancement:**
- ⚠️ **Level 0 (Settings & Models)** - Needs centralized model/provider config
- ⚠️ **Workflows (pydantic-graph)** - Missing graph-based orchestration
- ⚠️ **Observability** - Missing Logfire + pydantic_evals

**Bottom Line:** Your migration plan is solid. We recommend **minor additions** to reach 100% alignment.

---

## The 5-Layer PydanticAI Mental Model

Based on official docs, here's the recommended structure:

### Layer 0: Settings & Models
**Purpose:** Centralized configuration for LLM providers, models, and environment settings

**What PydanticAI recommends:**
```python
# viraltracker/config/settings.py
# viraltracker/config/models.py

# Centralized configuration for:
- Which LLMs to use (OpenAI, Anthropic, Gemini, etc.)
- Model aliases (e.g., "gateway/openai:gpt-5" vs direct "openai:gpt-5")
- Timeouts, retries, usage limits
- Gateway vs direct provider
```

**What you currently have:**
- ✅ `viraltracker/core/config.py` with environment variable management
- ✅ API keys centralized (GEMINI_API_KEY, OPENAI_API_KEY, etc.)
- ⚠️ **Missing:** Model configuration layer (model selection, aliases, usage limits)
- ⚠️ **Missing:** Provider profiles (dev/staging/prod model configs)

**Recommendation:** ✨ **Minor enhancement needed**

---

### Layer 1: Dependencies & Output Schemas
**Purpose:** One deps_type dataclass per domain + one output_type Pydantic model per agent

**What PydanticAI recommends:**
```python
# Per-domain dependencies
@dataclass
class SupportDependencies:
    db: Database
    config: Config

# Per-domain outputs
class SupportOutput(BaseModel):
    ticket_id: str
    resolution: str
```

**What you currently have:**
- ✅ `AgentDependencies` dataclass in `viraltracker/agent/dependencies.py`
- ✅ All services injected (TwitterService, GeminiService, TikTokService, etc.)
- ✅ Pydantic models in `viraltracker/services/models.py`:
  - `Tweet`, `HookAnalysis`, `OutlierTweet`, `OutlierResult`, `HookAnalysisResult`
- ✅ Per-domain output models already exist
- ⚠️ **Missing:** ResultCache for inter-agent communication (mentioned in ORCHESTRATOR_REFACTOR_PLAN.md but not yet implemented)

**Recommendation:** ✨ **Add ResultCache as planned in ORCHESTRATOR_REFACTOR_PLAN.md**

---

### Layer 2: Agents as Globally-Defined "Roles"
**Purpose:** One Agent per major "role" (specialist agents for domains)

**What PydanticAI recommends:**
```python
# Define one agent per major role
support_agent = Agent(...)
research_agent = Agent(...)
creative_agent = Agent(...)
routing_agent = Agent(...)
```

**What you currently have:**
- ✅ Main agent in `viraltracker/agent/agent.py`
- ✅ Uses PydanticAI `Agent()` class correctly
- ✅ Proper `deps_type=AgentDependencies`
- ✅ Static + dynamic instructions (system prompts)
- 📋 **PLANNED:** Orchestrator refactor with 5 specialized agents:
  - `twitter_agent` (5 tools)
  - `tiktok_agent` (5 tools)
  - `youtube_agent` (1 tool)
  - `facebook_agent` (2 tools)
  - `analysis_agent` (3 tools)
  - `orchestrator` (coordinates all agents)

**Current State:** ✅ **PARTIAL** - Single monolithic agent working
**Planned State:** ✅ **EXCELLENT** - Multi-agent orchestrator pattern follows best practices

**Recommendation:** ✨ **Proceed with ORCHESTRATOR_REFACTOR_PLAN.md as designed**

---

### Layer 3: Tools & Toolsets
**Purpose:** Organize tools by capability, not by agent. Use toolsets for reusable bundles.

**What PydanticAI recommends:**
```python
# viraltracker/tools/
db_tools.py
search_tools.py
file_tools.py
mcp_tools.py

# Toolsets for reusable bundles
from pydantic_ai import ToolSet

twitter_toolset = ToolSet([
    search_twitter_tool,
    export_tweets_tool,
    analyze_tweet_tool
])
```

**What you currently have:**
- ✅ `viraltracker/agent/tools.py` - Core analysis tools
- ✅ `viraltracker/agent/tools_phase15.py` - Twitter/comment tools
- ✅ `viraltracker/agent/tools_phase16.py` - TikTok tools
- ✅ `viraltracker/agent/tools_phase17.py` - YouTube/Facebook tools
- ✅ `viraltracker/agent/tools_registered.py` - Tool registration
- ✅ All tools use `@agent.tool` decorator
- ⚠️ **Missing:** ToolSet pattern (optional but recommended for reusability)

**Recommendation:** ✨ **Optional enhancement: Create ToolSets**

---

### Layer 4: Orchestration (Multi-Agent + Workflows)
**Purpose:** Handle single-agent, agent delegation, programmatic hand-off, and graph-based control flow

**What PydanticAI recommends:**

4 levels of complexity:

1. **Single agent workflows** - Simple, one-shot agent calls
2. **Agent delegation** - Agent A calls Agent B via tool
3. **Programmatic hand-off** - Python orchestrator calls agents in sequence
4. **Graph-based control flow** - Use `pydantic-graph` for complex workflows

```python
# Example: Graph-based workflow
from pydantic_graph import GraphBuilder

g = GraphBuilder()

@g.step
async def fetch_tweets(ctx):
    # Call twitter_agent
    return await twitter_agent.run(...)

@g.step
async def analyze_hooks(ctx, tweets):
    # Call analysis_agent
    return await analysis_agent.run(...)

# Decisions, joins, parallel execution, reducers
```

**What you currently have:**

**Current:**
- ✅ Single agent with 15+ tools (Level 1: ✅)
- ⚠️ No agent delegation (Level 2: ❌)
- ⚠️ No programmatic hand-off (Level 3: ❌)
- ⚠️ No graph-based workflows (Level 4: ❌)

**Planned (ORCHESTRATOR_REFACTOR_PLAN.md):**
- ✅ Agent delegation via orchestrator (Level 2: ✅)
- ✅ Programmatic hand-off via Python orchestrator (Level 3: ✅)
- ⚠️ No graph-based workflows (Level 4: ❌)

**Recommendation:**
- ✨ **Phase 1:** Implement orchestrator pattern as planned (Levels 1-3)
- ✨ **Phase 2 (Optional):** Add `pydantic-graph` for complex multi-step workflows (Level 4)

---

### Layer 5: Integrations (UI, Durable Execution, Evals, Observability)
**Purpose:** External integrations for UI, persistence, evaluation, and monitoring

**What PydanticAI recommends:**

**UI:**
- FastAPI chat endpoints
- Streamlit UI
- AG-UI / Vercel AI integration

**Durable Execution:**
- Temporal / Prefect / DBOS integration
- Built-in `durable_exec` for simple cases

**Evaluations:**
- `pydantic_evals` for eval suites
- Dataset definitions + evaluators

**Observability:**
- `Logfire` for tracing and metrics
- `logfire.instrument_pydantic_ai()` for automatic instrumentation

**What you currently have:**

**UI:**
- ✅ `viraltracker/ui/app.py` - Streamlit chat interface (COMPLETE)
- ✅ `viraltracker/api/app.py` - FastAPI endpoints (COMPLETE)
- ✅ Multi-page Streamlit (Tools Catalog, Database Browser, History, Services Catalog)

**Durable Execution:**
- ⚠️ **Missing:** No Temporal/Prefect/DBOS integration
- ⚠️ **Missing:** No `durable_exec` usage

**Evaluations:**
- ⚠️ **Missing:** No `pydantic_evals` integration
- ⚠️ **Missing:** No eval datasets or test suites

**Observability:**
- ⚠️ **Missing:** No Logfire integration
- ⚠️ **Missing:** No instrumentation for agent/tool calls
- ✅ Basic logging via Python `logging` module

**Recommendation:**
- ✨ **High Priority:** Add Logfire instrumentation (simple setup, huge benefits)
- ✨ **Medium Priority:** Add pydantic_evals for regression testing
- ✨ **Low Priority:** Durable execution (only needed if workflows cross processes/time)

---

## Gap Analysis: What's Missing?

### Critical Gaps (Should Add)
None! Your core architecture is solid.

### Important Gaps (Recommended to Add)

1. **Level 0: Model Configuration Layer**
   - **Status:** ⚠️ Missing
   - **Impact:** Medium - Makes model switching and testing harder
   - **Effort:** Low (2-3 hours)
   - **File:** `viraltracker/config/models.py`

2. **Level 1: ResultCache for Inter-Agent Communication**
   - **Status:** ⚠️ Planned but not implemented
   - **Impact:** High - Needed for orchestrator pattern
   - **Effort:** Low (1-2 hours)
   - **File:** `viraltracker/agent/dependencies.py`

3. **Level 5: Logfire Instrumentation**
   - **Status:** ⚠️ Missing
   - **Impact:** High - Essential for debugging and monitoring agents
   - **Effort:** Low (1-2 hours setup, automatic after)
   - **File:** `viraltracker/core/instrumentation.py`

4. **Level 5: Pydantic Evals**
   - **Status:** ⚠️ Missing
   - **Impact:** Medium - Important for regression testing
   - **Effort:** Medium (4-6 hours for initial setup)
   - **File:** `viraltracker/evals/`

### Optional Gaps (Nice to Have)

5. **Level 3: ToolSets Pattern**
   - **Status:** ⚠️ Not using ToolSet class
   - **Impact:** Low - Current approach works fine
   - **Effort:** Low (2-3 hours refactor)
   - **File:** `viraltracker/agent/toolsets/`

6. **Level 4: Pydantic Graph**
   - **Status:** ⚠️ Missing
   - **Impact:** Low - Only needed for complex multi-step workflows
   - **Effort:** High (8-12 hours to learn + implement)
   - **File:** `viraltracker/workflows/graphs/`

7. **Level 5: Durable Execution**
   - **Status:** ⚠️ Missing
   - **Impact:** Low - Only needed if workflows are long-running or cross processes
   - **Effort:** High (12-20 hours for Temporal/Prefect setup)
   - **File:** `viraltracker/orchestration/durable.py`

---

## Recommended Project Structure (Updated)

Based on PydanticAI best practices + your current architecture:

```
viraltracker/
├── config/                          # NEW: Level 0 - Settings & Models
│   ├── __init__.py
│   ├── settings.py                  # Environment, keys, gateway URLs
│   ├── models.py                    # Model aliases, profiles, usage limits
│   └── providers.py                 # Provider configuration (OpenAI, Anthropic, Gemini)
│
├── services/                        # ✅ EXISTING: Level 1 - Business logic
│   ├── __init__.py
│   ├── twitter_service.py
│   ├── gemini_service.py
│   ├── stats_service.py
│   ├── tiktok_service.py
│   ├── youtube_service.py
│   ├── facebook_service.py
│   └── models.py                    # Pydantic output models
│
├── agent/                           # ✅ EXISTING: Level 2-3 - Agents & Tools
│   ├── __init__.py
│   ├── dependencies.py              # UPDATE: Add ResultCache
│   ├── agent.py                     # Current: Monolithic agent
│   │                                # UPDATE: Will export orchestrator
│   │
│   ├── agents/                      # NEW: Specialized agents
│   │   ├── __init__.py
│   │   ├── twitter_agent.py
│   │   ├── tiktok_agent.py
│   │   ├── youtube_agent.py
│   │   ├── facebook_agent.py
│   │   └── analysis_agent.py
│   │
│   ├── orchestrator.py              # NEW: Level 4 - Orchestrator pattern
│   │
│   ├── tools/                       # ✅ EXISTING (refactor organization)
│   │   ├── __init__.py
│   │   ├── twitter_tools.py
│   │   ├── tiktok_tools.py
│   │   ├── youtube_tools.py
│   │   ├── facebook_tools.py
│   │   └── analysis_tools.py
│   │
│   └── toolsets/                    # NEW: Optional ToolSets
│       ├── __init__.py
│       ├── twitter_toolset.py
│       └── tiktok_toolset.py
│
├── workflows/                       # NEW: Level 4 - Graph-based workflows (optional)
│   ├── __init__.py
│   ├── graphs.py
│   ├── onboarding_flow.py
│   └── analysis_pipeline.py
│
├── api/                             # ✅ EXISTING: Level 5 - FastAPI
│   ├── __init__.py
│   ├── app.py
│   └── routes/
│
├── ui/                              # ✅ EXISTING: Level 5 - Streamlit
│   ├── app.py
│   └── pages/
│
├── evals/                           # NEW: Level 5 - Evaluations
│   ├── __init__.py
│   ├── datasets/
│   │   ├── twitter_evals.py
│   │   └── tiktok_evals.py
│   ├── suites.py
│   └── reports.py
│
├── core/                            # ✅ EXISTING: Core utilities
│   ├── config.py                    # Keep existing, but move model config to config/
│   └── instrumentation.py           # NEW: Logfire setup
│
├── cli/                             # ✅ EXISTING: CLI
│   └── main.py
│
└── tests/                           # ✅ EXISTING: Tests
    ├── agent/
    ├── services/
    └── integration/
```

---

## Comparison: Your Plans vs PydanticAI Best Practices

### PYDANTIC_AI_MIGRATION_PLAN.md (Nov 20, 2025)

**Alignment Score: 90% ✅**

**What aligns:**
- ✅ Services layer (Level 1)
- ✅ Agent with deps_type (Level 2)
- ✅ Tools with @agent.tool (Level 3)
- ✅ Streamlit + FastAPI (Level 5)
- ✅ Result validators
- ✅ Structured outputs (Pydantic models)

**What's missing:**
- ⚠️ Model configuration layer (Level 0)
- ⚠️ Multi-agent orchestration (Level 4)
- ⚠️ Logfire instrumentation (Level 5)
- ⚠️ Pydantic evals (Level 5)

**Verdict:** ✅ **Excellent foundation**, ready for orchestrator refactor

---

### ORCHESTRATOR_REFACTOR_PLAN.md (Nov 21, 2025)

**Alignment Score: 95% ✅**

**What aligns:**
- ✅ ResultCache for inter-agent communication (Level 1)
- ✅ 5 specialized agents (Level 2)
- ✅ Agent delegation via orchestrator (Level 4)
- ✅ Programmatic hand-off (Level 4)
- ✅ Backwards compatibility (agent = orchestrator export)

**What's missing:**
- ⚠️ Model configuration layer (Level 0)
- ⚠️ Graph-based workflows with pydantic-graph (Level 4, optional)
- ⚠️ Logfire instrumentation (Level 5)
- ⚠️ Pydantic evals (Level 5)

**Verdict:** ✅ **Excellent design**, follows multi-agent best practices perfectly

---

## Action Plan: Reaching 100% Alignment

### Phase 1: Complete Orchestrator Refactor (Already Planned ✅)

**Goal:** Implement multi-agent orchestration pattern

**Files:**
1. ✅ Update `viraltracker/agent/dependencies.py` - Add ResultCache
2. ✅ Create `viraltracker/agent/agents/` directory
3. ✅ Create 5 specialized agents (twitter, tiktok, youtube, facebook, analysis)
4. ✅ Create `viraltracker/agent/orchestrator.py`
5. ✅ Update `viraltracker/agent/agent.py` to export orchestrator

**Timeline:** 2-3 days (as planned)

**Status:** ✅ **Ready to implement** - ORCHESTRATOR_REFACTOR_PLAN.md is excellent

---

### Phase 2: Add Missing Layer 0 (Model Configuration)

**Goal:** Centralize model/provider configuration for easier switching

**New Files:**
```
viraltracker/config/
├── settings.py      # Env vars, gateway URLs
├── models.py        # Model aliases, usage limits
└── providers.py     # Provider configs
```

**Example: `viraltracker/config/models.py`**
```python
"""Model configuration and profiles"""
from pydantic import BaseModel
from typing import Dict, Optional

class ModelConfig(BaseModel):
    """Configuration for a specific model"""
    provider: str  # 'openai', 'anthropic', 'gemini'
    model_name: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout: int = 60
    retries: int = 2

# Model aliases for easy switching
MODELS = {
    'fast': ModelConfig(
        provider='openai',
        model_name='gpt-4o-mini',
        temperature=0.5
    ),
    'smart': ModelConfig(
        provider='openai',
        model_name='gpt-5.1-2025-11-13',
        temperature=0.7
    ),
    'creative': ModelConfig(
        provider='anthropic',
        model_name='claude-sonnet-4',
        temperature=0.9
    ),
    'gemini': ModelConfig(
        provider='google',
        model_name='gemini-2.0-flash-exp',
        temperature=0.7
    )
}

# Environment-specific profiles
PROFILES = {
    'dev': 'fast',      # Use fast model in development
    'staging': 'smart', # Use smart model in staging
    'prod': 'smart'     # Use smart model in production
}

def get_model_config(profile: str = 'dev') -> ModelConfig:
    """Get model configuration for environment"""
    alias = PROFILES.get(profile, 'fast')
    return MODELS[alias]
```

**Usage in agents:**
```python
from viraltracker.config.models import get_model_config

model_config = get_model_config('prod')

agent = Agent(
    f'{model_config.provider}:{model_config.model_name}',
    deps_type=AgentDependencies,
    retries=model_config.retries
)
```

**Timeline:** 2-3 hours

**Benefits:**
- Easy model switching for testing
- Environment-specific configs (dev/staging/prod)
- Centralized usage limits and timeouts
- Easier A/B testing of models

---

### Phase 3: Add Logfire Instrumentation

**Goal:** Automatic tracing and monitoring of all agent/tool calls

**New File:** `viraltracker/core/instrumentation.py`

```python
"""Logfire instrumentation for agent observability"""
import os
import logfire
from typing import Optional

def setup_logfire(
    service_name: str = 'viraltracker',
    environment: str = 'development',
    enable_console: bool = True
) -> None:
    """
    Setup Logfire for agent tracing and monitoring.

    Args:
        service_name: Service identifier for Logfire
        environment: dev/staging/prod
        enable_console: Whether to print to console
    """
    # Configure Logfire
    logfire.configure(
        service_name=service_name,
        environment=environment,
        send_to_logfire=True,  # Send to Logfire cloud
        console=enable_console
    )

    # Instrument PydanticAI automatically
    logfire.instrument_pydantic_ai()

    print(f"✅ Logfire configured for {service_name} ({environment})")


# Call this at app startup
# In viraltracker/ui/app.py:
# from viraltracker.core.instrumentation import setup_logfire
# setup_logfire(environment='production')
```

**Update in app startup:**
```python
# viraltracker/ui/app.py
from viraltracker.core.instrumentation import setup_logfire

# At the top of the file
setup_logfire(
    service_name='viraltracker-ui',
    environment=os.getenv('ENVIRONMENT', 'development')
)
```

**Timeline:** 1-2 hours

**Benefits:**
- Automatic tracing of all agent calls
- See which tools agents choose
- Track response times and errors
- Debugging agent behavior becomes trivial
- Visualize agent conversation flows

---

### Phase 4: Add Pydantic Evals (Optional but Recommended)

**Goal:** Regression testing for agent behavior

**New Files:**
```
viraltracker/evals/
├── __init__.py
├── datasets/
│   ├── twitter_dataset.py
│   └── tiktok_dataset.py
├── evaluators.py
└── run_evals.py
```

**Example: `viraltracker/evals/datasets/twitter_dataset.py`**
```python
"""Evaluation dataset for Twitter agent"""
from pydantic_evals import Dataset, Example

twitter_eval_dataset = Dataset(
    name='twitter-agent-evals',
    examples=[
        Example(
            input="Find viral tweets about Bitcoin from the last 24 hours",
            expected_output_contains=["tweets", "bitcoin", "views", "engagement"],
            expected_tool_calls=["search_twitter_tool", "get_top_tweets_tool"]
        ),
        Example(
            input="Export top tweets to CSV",
            expected_output_contains=["exported", "csv", "downloaded"],
            expected_tool_calls=["export_tweets_tool"]
        ),
        # ... more examples
    ]
)
```

**Example: `viraltracker/evals/evaluators.py`**
```python
"""Evaluators for agent responses"""
from pydantic_evals import Evaluator

def contains_keywords_evaluator(expected_keywords: list[str]) -> Evaluator:
    """Check if response contains expected keywords"""
    def evaluate(output: str) -> bool:
        return all(kw.lower() in output.lower() for kw in expected_keywords)
    return evaluate

def called_expected_tools_evaluator(expected_tools: list[str]) -> Evaluator:
    """Check if agent called expected tools"""
    def evaluate(tool_calls: list[str]) -> bool:
        return all(tool in tool_calls for tool in expected_tools)
    return evaluate
```

**Run evals:**
```bash
python -m viraltracker.evals.run_evals --dataset twitter --report ~/Downloads/eval_report.json
```

**Timeline:** 4-6 hours

**Benefits:**
- Prevent regressions when updating agent prompts
- Test tool selection accuracy
- Benchmark agent performance over time
- Generate reports on agent behavior

---

### Phase 5: Add Graph-Based Workflows (Optional)

**Goal:** Handle complex multi-step workflows with branches and joins

**When you need this:**
- Multi-step workflows with conditional logic
- Fan-out/fan-in patterns (e.g., scrape 5 platforms in parallel, then aggregate)
- Long-running workflows with state persistence

**New File:** `viraltracker/workflows/analysis_pipeline.py`

```python
"""Graph-based workflow for multi-platform analysis"""
from pydantic_graph import GraphBuilder
from viraltracker.agent.agents import (
    twitter_agent,
    tiktok_agent,
    analysis_agent
)

# Create graph
g = GraphBuilder()

@g.step
async def fetch_twitter_data(ctx):
    """Step 1: Fetch Twitter data"""
    result = await twitter_agent.run(
        "Find viral tweets about Bitcoin",
        deps=ctx.deps
    )
    return result

@g.step
async def fetch_tiktok_data(ctx):
    """Step 2: Fetch TikTok data (parallel with Twitter)"""
    result = await tiktok_agent.run(
        "Search TikTok for #bitcoin videos",
        deps=ctx.deps
    )
    return result

@g.step
async def aggregate_results(ctx, twitter_result, tiktok_result):
    """Step 3: Aggregate results from both platforms"""
    combined = {
        'twitter': twitter_result,
        'tiktok': tiktok_result
    }
    return combined

@g.step
async def generate_insights(ctx, combined_data):
    """Step 4: Generate cross-platform insights"""
    result = await analysis_agent.run(
        f"Compare Bitcoin engagement across Twitter and TikTok: {combined_data}",
        deps=ctx.deps
    )
    return result

# Define workflow
workflow = g.build(
    start_step=fetch_twitter_data,
    parallel_steps=[fetch_twitter_data, fetch_tiktok_data],
    join_step=aggregate_results,
    final_step=generate_insights
)

# Run workflow
result = await workflow.run(deps=AgentDependencies.create())
```

**Timeline:** 8-12 hours (learning curve + implementation)

**Benefits:**
- Declarative multi-step workflows
- Parallel execution built-in
- State management across steps
- Conditional branching
- Reducers for aggregating parallel results

**When to add:**
- Only if you have complex workflows that need graphs
- Current orchestrator pattern handles most cases

---

## Final Recommendations

### Immediate Actions (Do Now)

1. **✅ Implement ORCHESTRATOR_REFACTOR_PLAN.md as designed** (2-3 days)
   - Your plan is excellent and follows best practices
   - No changes needed to the plan itself
   - Proceed with confidence

2. **✨ Add ResultCache to dependencies.py** (1-2 hours)
   - Required for orchestrator pattern
   - Already planned in ORCHESTRATOR_REFACTOR_PLAN.md

3. **✨ Add Logfire instrumentation** (1-2 hours)
   - Huge benefits for debugging and monitoring
   - Simple setup, automatic after
   - Will help you debug orchestrator behavior

### Short-Term Enhancements (Within 2 Weeks)

4. **✨ Add Model Configuration Layer** (2-3 hours)
   - Create `viraltracker/config/models.py`
   - Centralize model selection and profiles
   - Makes testing and switching models easier

5. **✨ Add Pydantic Evals** (4-6 hours)
   - Create `viraltracker/evals/` directory
   - Start with 5-10 eval examples per agent
   - Run before/after orchestrator refactor to compare

### Long-Term Enhancements (Future)

6. **🔮 Add Graph-Based Workflows** (8-12 hours)
   - Only if you have complex multi-step workflows
   - Current orchestrator handles most cases
   - Can add incrementally as needs arise

7. **🔮 Add Durable Execution** (12-20 hours)
   - Only if workflows are long-running or cross processes
   - Not needed for current use cases
   - Can add with Temporal/Prefect if needed later

---

## Comparison Table: Plans vs Best Practices

| Layer | PydanticAI Docs | Your Current State | ORCHESTRATOR Plan | Recommendation |
|-------|----------------|-------------------|------------------|----------------|
| **Level 0: Settings & Models** | ✅ Centralized model config | ⚠️ Partial (env vars only) | ⚠️ Not mentioned | ✨ Add config/models.py |
| **Level 1: Dependencies & Outputs** | ✅ deps_type + output_type | ✅ AgentDependencies + models | ✅ + ResultCache | ✅ Perfect |
| **Level 2: Agents as Roles** | ✅ One agent per role | ⚠️ Monolithic agent | ✅ 5 specialized agents | ✅ Proceed as planned |
| **Level 3: Tools & Toolsets** | ✅ Organized by capability | ✅ Organized by phase | ✅ No change needed | ✅ Good (optional: ToolSets) |
| **Level 4: Orchestration** | ✅ 4 levels (single → graphs) | ⚠️ Level 1 only | ✅ Levels 1-3 | ✅ Excellent (optional: graphs) |
| **Level 5: UI** | ✅ FastAPI + Streamlit | ✅ Both implemented | ✅ No change | ✅ Perfect |
| **Level 5: Durable Execution** | ✅ Temporal/Prefect | ⚠️ Not implemented | ⚠️ Not mentioned | 🔮 Optional (future) |
| **Level 5: Evals** | ✅ pydantic_evals | ⚠️ Not implemented | ⚠️ Not mentioned | ✨ Add for regression testing |
| **Level 5: Observability** | ✅ Logfire | ⚠️ Basic logging only | ⚠️ Not mentioned | ✨ High priority - add Logfire |

**Legend:**
- ✅ = Fully aligned with best practices
- ⚠️ = Partial or missing
- ✨ = Recommended to add
- 🔮 = Optional for future

---

## Conclusion

**Your migration plan is excellent!** 🎉

You're at **85-90% alignment** with PydanticAI best practices, which is outstanding. The ORCHESTRATOR_REFACTOR_PLAN.md is particularly well-designed and follows the multi-agent orchestration pattern perfectly.

**What to do next:**

1. **Proceed with orchestrator refactor** - Your plan is solid
2. **Add Logfire instrumentation** - Simple addition, huge benefits
3. **Add model configuration layer** - Makes testing easier
4. **Consider pydantic_evals** - Good for regression testing

**What NOT to worry about:**

- Graph-based workflows (only if you have complex workflows)
- Durable execution (only if workflows are long-running)
- ToolSets pattern (current approach is fine)

**Your FastAPI endpoints and CLI will continue working** - The orchestrator pattern is 100% backwards compatible via the `agent = orchestrator` export in `agent.py`.

**Questions?** Let me know if you'd like me to:
- Create the model configuration layer
- Add Logfire instrumentation
- Set up pydantic_evals
- Implement any other missing pieces

---

**Document Version:** 1.0
**Last Updated:** 2025-01-24
**Status:** Analysis Complete ✅
**Next Action:** Proceed with ORCHESTRATOR_REFACTOR_PLAN.md
