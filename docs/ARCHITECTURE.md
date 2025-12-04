# ViralTracker Architecture

**Version**: 3.0.0 (Pydantic AI Migration Complete)
**Last Updated**: 2025-01-24

## Table of Contents
1. [System Overview](#system-overview)
2. [Layered Architecture](#layered-architecture)
3. [Agent System](#agent-system)
4. [Database Schema](#database-schema)
5. [Tool Registry Pattern](#tool-registry-pattern)
6. [Data Flow](#data-flow)
7. [Design Decisions](#design-decisions)

## System Overview

ViralTracker is a multi-platform viral content analysis system built on a three-layer architecture:

```
┌─────────────────────────────────────────────┐
│          AGENT LAYER (PydanticAI)           │
│  Natural Language → Intelligent Routing     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────┴──────────────────────────┐
│          SERVICE LAYER (Core)               │
│  Business Logic → Reusable Components       │
└──────────────┬──────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┐
   │           │           │              │
   ▼           ▼           ▼              ▼
┌──────┐  ┌───────┐  ┌─────────┐  ┌────────────┐
│ CLI  │  │ Agent │  │Streamlit│  │ FastAPI    │
│      │  │(Chat) │  │  (UI)   │  │ (Webhooks) │
└──────┘  └───────┘  └─────────┘  └────────────┘
```

## Layered Architecture

### Layer 1: Agent Layer (PydanticAI)
- **Orchestrator Agent**: Routes natural language queries to specialists
- **5 Specialized Agents**: Twitter, TikTok, YouTube, Facebook, Analysis
- **19 Tools**: Organized by data pipeline stages
- **Model**: Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

**Key Pattern**: `@agent.tool(metadata=ToolMetadata(...))` decorator

**Thin Tools Principle**: Tools are orchestration glue—they decide *what* to do based on LLM selection, but delegate *how* to do it to the service layer. Business logic and deterministic preprocessing belong in services, not tools.

### Layer 2: Service Layer (Core Business Logic)
- **TwitterService**: Database operations for Twitter data
- **GeminiService**: AI-powered analysis
- **StatsService**: Statistical calculations
- **ScrapingService**: External API integration (Apify, Clockworks)

**Key Pattern**: Reusable services shared across all interfaces

### Layer 3: Interface Layer
- **CLI**: `vt` command-line tool
- **Agent Chat**: `python -m viraltracker.agent.chat`
- **FastAPI**: `POST /agent/run` endpoint
- **Streamlit**: Web UI with catalogs

## Agent System

### Orchestrator Pattern

The orchestrator analyzes user intent and routes to the appropriate specialist:

```python
# User: "Find 100 viral tweets about AI"
# Orchestrator analyzes → Routes to Twitter Agent
# Twitter Agent executes → search_twitter tool
# Returns results to user
```

### Agent Directory Structure
```
viraltracker/agent/
├── orchestrator.py           # Main routing agent
├── dependencies.py           # AgentDependencies (shared context)
├── tool_metadata.py          # ToolMetadata TypedDict schema
├── tool_collector.py         # Tool discovery utility
│
└── agents/                   # Specialist agents (tools defined here)
    ├── twitter_agent.py      # 8 tools
    ├── tiktok_agent.py       # 5 tools
    ├── youtube_agent.py      # 1 tool
    ├── facebook_agent.py     # 2 tools
    └── analysis_agent.py     # 3 tools
```

### Tool Pipeline Stages
1. **Routing** - Orchestrator routing tools
2. **Ingestion** - Data collection (scraping, API calls)
3. **Filtration** - Data filtering, preprocessing
4. **Discovery** - Pattern detection, outlier analysis
5. **Analysis** - AI-powered insights
6. **Generation** - Content generation
7. **Export** - Data export, reporting

## Database Schema

### Core Tables
- `brands, products, projects` - Multi-tenant organization
- `platforms, accounts, posts` - Social media data
- `video_processing` - Processing status and metrics
- `video_analysis` - AI analysis results (Hook Intelligence)

### Comment Finder Tables (V1.7)
- `generated_comments` - AI-generated suggestions with lifecycle
- `tweet_snapshot` - Historical engagement metrics
- `acceptance_log` - Duplicate prevention with pgvector
- `author_stats` - Author engagement patterns

### Key Relationships
```sql
-- FK constraints
generated_comments.tweet_id → posts.post_id
posts.account_id → accounts.account_id
accounts.platform_id → platforms.platform_id
```

## Tool Registry Pattern

### Current Pattern (Pydantic AI Standard)
Tools are defined directly in agent files using `@agent.tool()` decorator:

```python
@twitter_agent.tool(
    metadata=ToolMetadata(
        category='Ingestion',
        platform='Twitter',
        rate_limit='20/minute',
        use_cases=['Search tweets', 'Collect data'],
        examples=['Find tweets about AI']
    )
)
async def search_twitter(ctx: RunContext[AgentDependencies], keyword: str):
    """Search Twitter for tweets matching a keyword."""
    # Tool implementation
```

### Tool Discovery
- `agent._function_toolset.tools` - Access agent's tools
- `tool_collector.py` - Utility to discover all tools
- `endpoint_generator.py` - Auto-generates FastAPI endpoints

## Data Flow

### Traditional Workflow
```
1. Scraping → posts table (metadata)
2. Processing → video_processing + Supabase Storage
3. AI Analysis → video_analysis (hook_features JSONB)
4. Export → CSV for statistical analysis
5. Advanced Analysis → Playbook generation
```

### Agent Workflow
```
1. User Query → Orchestrator Agent
2. Orchestrator → Routes to Specialized Agent
3. Specialized Agent → Calls Service Layer
4. Service Layer → Database/API/AI
5. Results → Back through agent to user
```

### Comment Finder Workflow (V1.7)
```
Step 1: Scrape & Score (45-60 min, $0)
- Scrape tweets by keyword
- Score ALL tweets (velocity, relevance, openness, author quality)
- Save scores to database (comment_text = '')

Step 2: Generate Comments (10-15 min, ~$0.50-1.00)
- Query saved greens from database
- Filter by min-views (default: 50)
- Generate 3 comment suggestions per green
- Batch mode: 5 concurrent API requests

Step 3: Export to CSV (<1 min, $0)
- Export greens with comments to timestamped CSV
- Auto-update status to 'exported'
```

## Design Decisions

### Why Pydantic AI?
- **Type Safety**: Pydantic models for all tool inputs/outputs
- **Agent Routing**: Natural language → intelligent tool selection
- **Metadata Separation**: Docstrings for LLM, metadata for system config
- **Standard Pattern**: No custom registry, uses Pydantic AI's built-in tools

### Why Layered Architecture?
- **Reusability**: Services shared across CLI, Agent, API, UI
- **Flexibility**: Add new interfaces without changing core logic
- **Testability**: Each layer can be tested independently
- **Maintainability**: Clear separation of concerns

### Why Specialist Agents?
- **Expertise**: Each agent knows its platform deeply
- **Scalability**: Add new platforms without changing orchestrator
- **Tool Organization**: Tools grouped by platform/domain
- **Performance**: Smaller system prompts per agent

### Migration from Registry Pattern
- **Before**: Centralized `tools_registered.py` + `@tool_registry.register()`
- **After**: In-agent definitions with `@agent.tool(metadata=...)`
- **Benefit**: Standard Pydantic AI pattern, simpler, no custom registry code
- **Completion**: Phase 13 (all 5 agents), Phase 14 (cleanup)

### Pydantic-Graph vs Direct Service Calls

When building workflows, choose the appropriate pattern:

| Pattern | When to Use | Examples |
|---------|-------------|----------|
| **pydantic-graph** | Autonomous, multi-step workflows where AI makes decisions | Ad generation pipeline, content analysis pipelines |
| **Direct Service Calls** | User-driven, interactive workflows with UI control | Template approval, form submissions, manual triggers |

**Use pydantic-graph when:**
- The LLM needs to decide what happens next
- Workflow runs autonomously (e.g., cron jobs, background tasks)
- Complex branching logic based on AI analysis
- Multiple AI-powered steps in sequence

**Use direct service calls when:**
- User controls the flow (clicking buttons, filling forms)
- Operations are short and synchronous
- UI presents choices and waits for user input
- Two-step confirmation workflows (AI suggests → user confirms)

**Example - Template Approval Workflow:**
```python
# ❌ WRONG: Using pydantic-graph for user-driven flow
# The graph would try to make autonomous decisions

# ✅ CORRECT: Direct service calls with UI control
# Step 1: User clicks "Approve" → service.start_approval() runs AI
# Step 2: UI shows suggestions → User edits/confirms
# Step 3: User clicks "Confirm" → service.finalize_approval()
```

The key question: **Who decides what happens next—the AI or the user?**

---

**Related Documentation**:
- [Developer Guide](DEVELOPER_GUIDE.md) - How to add agents, tools, services
- [Claude Code Guide](CLAUDE_CODE_GUIDE.md) - AI-assisted development patterns
- [Documentation Index](README.md) - Return to main documentation hub
