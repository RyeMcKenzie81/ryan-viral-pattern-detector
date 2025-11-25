# Documentation Improvement Checkpoint

**Date**: 2025-01-24
**Status**: Ready for implementation
**Context Remaining**: 7% (need fresh session)

---

## What Was Completed

### ✅ Phase 14: Pydantic AI Migration Documentation Update

1. **Updated `docs/CLAUDE_CODE_GUIDE.md`** (Commit: `06187df`)
   - Version: 2.0.0 → 3.0.0
   - Status: "Pydantic AI Migration Complete ✅"
   - Removed all references to deprecated `tools_registered.py` and `@tool_registry.register()`
   - Updated Quick Start to show only `@agent.tool()` pattern
   - Updated Migration Guide to reflect completion status
   - Updated File Location Reference with deprecated folders
   - All code examples now show production-ready pattern

2. **Archived Deprecated Files** (Commit: `15bac11`)
   - Moved 18 PHASE_*.md files to `docs/archive/pydantic-ai-refactor/`
   - Moved deprecated code to `viraltracker/agent/deprecated/`
   - Moved deprecated API to `viraltracker/api/deprecated/`

3. **Backup and Merge** (Commit: `fc0c6a3`)
   - Created backup branch: `backup/main-before-pydantic-ai-refactor`
   - Merged `refactor/pydantic-ai-alignment` to main
   - Pushed all changes to remote

---

## What Needs to Be Done Next

### 🎯 Primary Goal: Create Master Documentation Structure

The project lacks a central navigation system for documentation. We need to create three new documents that work together to guide anyone (Claude Code, developers, users) to the right information.

### 📋 Three Documents to Create

#### 1. **`docs/README.md`** - Master Table of Contents
**Purpose**: Central navigation hub for all documentation
**Target Audience**: Everyone (first stop for any documentation need)

**Content Structure**:
```markdown
# ViralTracker Documentation

Welcome to the ViralTracker documentation! Choose your path:

## 🎯 Quick Navigation

### For Developers
- [Developer Guide](DEVELOPER_GUIDE.md) - Setup, contributing, testing
- [Architecture Overview](ARCHITECTURE.md) - System design and patterns

### For AI-Assisted Development (Claude Code)
- [Claude Code Guide](CLAUDE_CODE_GUIDE.md) - How to create agents, tools, and services

### For Users
- [User README](../README.md) - Features and getting started
- [CLI Guide](CLI_GUIDE.md) - Command-line reference

### For Architects & Technical Leadership
- [Architecture Overview](ARCHITECTURE.md) - System design, data flow, decisions
- [Pydantic AI Migration](archive/pydantic-ai-refactor/) - Historical context

## 📚 Document Index

### Core Documentation
| Document | Purpose | Audience |
|----------|---------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design & patterns | Architects, Senior Devs |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Dev setup & workflows | New contributors |
| [CLAUDE_CODE_GUIDE.md](CLAUDE_CODE_GUIDE.md) | AI-assisted development | Claude Code, AI tools |
| [CLI_GUIDE.md](CLI_GUIDE.md) | Command reference | End users |

### Specialized Guides
- [Hook Analysis Guide](HOOK_ANALYSIS_GUIDE.md) - Statistical analysis methods
- [Deployment Guide](../DEPLOYMENT.md) - Production deployment

### Historical/Archive
- [Pydantic AI Refactor](archive/pydantic-ai-refactor/) - Migration history
- [Legacy Docs](archive/) - Session summaries and old checkpoints
```

#### 2. **`docs/ARCHITECTURE.md`** - System Architecture Overview
**Purpose**: Explain how the entire system works at a high level
**Target Audience**: Architects, senior developers, technical stakeholders

**Content Structure**:
```markdown
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
```

#### 3. **`docs/DEVELOPER_GUIDE.md`** - Developer Onboarding
**Purpose**: Help new developers get started quickly
**Target Audience**: New contributors, junior developers

**Content Structure**:
```markdown
# Developer Guide

Welcome to ViralTracker development! This guide will help you set up your environment and understand how to contribute.

## Table of Contents
1. [Quick Start](#quick-start)
2. [Development Setup](#development-setup)
3. [Project Structure](#project-structure)
4. [Adding New Features](#adding-new-features)
5. [Testing Strategy](#testing-strategy)
6. [Code Organization](#code-organization)
7. [Common Tasks](#common-tasks)

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git
cd viraltracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Test the setup
python -m viraltracker.agent.chat
```

## Development Setup

### Prerequisites
- Python 3.13+
- FFmpeg (for video processing)
- Node.js 18+ (for scorer module)
- Supabase account
- API keys: Google Gemini, Apify, Clockworks

### Environment Variables
Required keys in `.env`:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key
GOOGLE_GEMINI_API_KEY=your-gemini-api-key
APIFY_API_TOKEN=your-apify-token
CLOCKWORKS_API_KEY=your-clockworks-key
```

## Project Structure

```
viraltracker/
├── viraltracker/              # Core Python package
│   ├── agent/                 # Agent layer (Pydantic AI)
│   │   ├── orchestrator.py    # Main routing agent
│   │   ├── agents/            # Specialized agents (tools defined here)
│   │   ├── tool_metadata.py   # Metadata schema
│   │   └── dependencies.py    # Shared agent context
│   ├── services/              # Service layer (business logic)
│   │   ├── twitter_service.py # Twitter DB operations
│   │   ├── gemini_service.py  # AI analysis
│   │   └── ...
│   ├── cli/                   # CLI commands
│   ├── api/                   # FastAPI endpoints
│   └── ui/                    # Streamlit interface
├── docs/                      # Documentation
└── migrations/                # Database migrations
```

## Adding New Features

### Adding a New Tool

**For Claude Code**: See [CLAUDE_CODE_GUIDE.md](CLAUDE_CODE_GUIDE.md) for detailed instructions.

**Quick Steps**:
1. Choose the appropriate agent file (e.g., `twitter_agent.py`)
2. Add tool function with `@agent.tool()` decorator
3. Include ToolMetadata (category, rate_limit, use_cases)
4. Write comprehensive docstring (sent to LLM)
5. Test via CLI, API, or chat interface

Example:
```python
@twitter_agent.tool(
    metadata=ToolMetadata(
        category='Ingestion',
        platform='Twitter',
        rate_limit='20/minute',
        use_cases=['Search tweets'],
        examples=['Find tweets about Python']
    )
)
async def my_new_tool(ctx: RunContext[AgentDependencies], keyword: str):
    """
    Tool description for the LLM.

    Args:
        ctx: Pydantic AI context
        keyword: Search keyword

    Returns:
        SearchResult with matching tweets
    """
    # Implementation here
```

### Adding a New Service

1. Create service file in `viraltracker/services/`
2. Define service class with clear methods
3. Add to `AgentDependencies` if needed by agents
4. Write unit tests

### Adding a New Agent

1. Create agent file in `viraltracker/agent/agents/`
2. Define agent with system prompt
3. Add tools using `@agent.tool()` decorator
4. Register with orchestrator for routing
5. Update tool counts in README

## Testing Strategy

### Manual Testing

**Test via CLI**:
```bash
# Test Twitter agent
./vt twitter search --terms "test" --count 100 --project test-project
```

**Test via Agent Chat**:
```bash
python -m viraltracker.agent.chat
# Try: "Find 100 tweets about Python"
```

**Test via API**:
```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find tweets about AI", "project_name": "test"}'
```

### Tool Registration Test
```python
from viraltracker.agent.agents.twitter_agent import twitter_agent

# Verify tool count
tools = twitter_agent._function_toolset.tools
print(f"Total tools: {len(tools)}")
print(f"Tool names: {list(tools.keys())}")
```

## Code Organization

### Layered Architecture Principles

1. **Agent Layer** - Only handles LLM interaction and routing
2. **Service Layer** - Contains all business logic
3. **Interface Layer** - CLI/API/UI calls services directly

**Never**:
- ❌ Put business logic in agent tools
- ❌ Duplicate code between layers
- ❌ Call agents from services (only services from agents)

**Always**:
- ✅ Reuse services across all interfaces
- ✅ Keep tools thin (orchestration only)
- ✅ Use type hints everywhere

### Import Patterns

```python
# Agent tool imports
from pydantic_ai import RunContext
from ..dependencies import AgentDependencies
from ..tool_metadata import ToolMetadata
from ...services.models import YourResultModel

# Service imports
from ..core.database import Database
from ..services.gemini_service import GeminiService
```

## Common Tasks

### Running Development Servers

```bash
# FastAPI server
uvicorn viraltracker.api.app:app --reload --port 8000

# Streamlit UI
streamlit run viraltracker/ui/app.py

# Agent chat
python -m viraltracker.agent.chat
```

### Database Migrations

```bash
# Apply migration
psql $SUPABASE_URL -f migrations/2025-01-24_migration.sql

# Verify migration
psql $SUPABASE_URL -c "SELECT * FROM information_schema.tables WHERE table_schema = 'public';"
```

### Checking Tool Discovery

```bash
# List all tools
python -c "
from viraltracker.agent.tool_collector import get_all_tools
tools = get_all_tools()
for name, info in tools.items():
    print(f'{info.platform} - {name}: {info.description}')
"
```

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/my-new-feature

# Make changes, commit frequently
git add .
git commit -m "feat: Add new feature"

# Push and create PR
git push origin feature/my-new-feature
```

## Resources

- [Architecture Overview](ARCHITECTURE.md) - System design
- [Claude Code Guide](CLAUDE_CODE_GUIDE.md) - AI-assisted development
- [CLI Guide](CLI_GUIDE.md) - Command reference
- [Pydantic AI Docs](https://ai.pydantic.dev/) - Framework documentation
```

---

## Implementation Instructions for Next Session

### Step 1: Create the Three Documents

Use the content structures above to create:
1. `docs/README.md` - Master table of contents
2. `docs/ARCHITECTURE.md` - System architecture overview
3. `docs/DEVELOPER_GUIDE.md` - Developer onboarding guide

### Step 2: Update Existing Documents

**Update `README.md` (root)**:
- Add pointer to `docs/README.md` at the top:
  ```markdown
  # ViralTracker

  > 📚 **Documentation**: See [docs/README.md](docs/README.md) for complete documentation index
  ```

**Update `docs/CLI_GUIDE.md`**:
- Add pointer to `docs/README.md` at the top
- Ensure it's focused on user commands only

**Update `docs/CLAUDE_CODE_GUIDE.md`**:
- Already updated ✅
- Just add cross-reference to ARCHITECTURE.md in introduction

### Step 3: Verify Documentation Flow

Test the navigation:
1. Start at root README → Should point to docs/README.md
2. docs/README.md → Should guide to all other docs
3. Each specialized doc → Should link back to docs/README.md

### Step 4: Commit and Push

```bash
git add docs/README.md docs/ARCHITECTURE.md docs/DEVELOPER_GUIDE.md
git add README.md docs/CLI_GUIDE.md docs/CLAUDE_CODE_GUIDE.md
git commit -m "docs: Add master documentation structure with architecture and developer guides"
git push origin main
```

---

## Key Points to Remember

1. **docs/README.md** is the central hub - everything points here
2. **ARCHITECTURE.md** explains the "what" and "why" of the system
3. **DEVELOPER_GUIDE.md** explains the "how" of contributing
4. **CLAUDE_CODE_GUIDE.md** (already done) explains the "how" of AI development
5. **CLI_GUIDE.md** explains commands for end users

## Success Criteria

✅ Any developer can find what they need within 2 clicks from docs/README.md
✅ Claude Code knows to read CLAUDE_CODE_GUIDE.md for creating agents/tools
✅ New contributors can follow DEVELOPER_GUIDE.md to get started
✅ Technical stakeholders can understand the system from ARCHITECTURE.md
✅ All docs cross-reference each other appropriately

---

**Next Steps**: Create a new Claude Code session and use the prompt below to complete this work.
