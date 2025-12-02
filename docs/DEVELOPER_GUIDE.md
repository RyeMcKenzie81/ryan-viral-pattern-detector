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
8. [Streamlit Authentication](#streamlit-authentication)

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
- Put business logic in agent tools
- Duplicate code between layers
- Call agents from services (only services from agents)

**Always**:
- Reuse services across all interfaces
- Keep tools thin (orchestration only)
- Use type hints everywhere

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

## Streamlit Authentication

The Streamlit UI is password-protected with persistent cookie-based sessions.

### Configuration

Set the `STREAMLIT_PASSWORD` environment variable in Railway:
```
STREAMLIT_PASSWORD=your-secure-password
```

Optional settings:
```
STREAMLIT_COOKIE_KEY=custom-signing-key    # Auto-generated if not set
STREAMLIT_COOKIE_EXPIRY_DAYS=30            # How long sessions last
```

### How It Works

1. Users visit any page and see a login form
2. After entering the correct password, a signed token is stored in localStorage
3. The token persists for 30 days (configurable)
4. Users can logout via the sidebar button

### Creating a Protected Page

All pages are protected by default. Add this after `st.set_page_config()`:

```python
st.set_page_config(page_title="My Page", page_icon="📄", layout="wide")

# Authentication - add this line
from viraltracker.ui.auth import require_auth
require_auth()

# Rest of your page code...
st.title("My Protected Page")
```

### Creating a Public Page (No Auth Required)

**Option 1: Use the `public` parameter**
```python
from viraltracker.ui.auth import require_auth
require_auth(public=True)  # Skip authentication for this page
```

**Option 2: Add to the whitelist**

Edit `viraltracker/ui/auth.py` and add your page filename to `PUBLIC_PAGES`:
```python
# Pages that don't require authentication
PUBLIC_PAGES = [
    "Client_Gallery.py",
    "Public_Report.py",
]
```

### Token-Based Client Access (Future Enhancement)

For client-facing pages with per-client tokens:
```python
# Check for client token in URL
client_token = st.query_params.get("token")
if not verify_client_token(client_token):
    st.error("Invalid or expired link")
    st.stop()
```

This allows sharing links like:
```
https://yourapp.railway.app/Client_Gallery?token=abc123
```

## Resources

- [Architecture Overview](ARCHITECTURE.md) - System design
- [Claude Code Guide](CLAUDE_CODE_GUIDE.md) - AI-assisted development
- [CLI Guide](CLI_GUIDE.md) - Command reference
- [Pydantic AI Docs](https://ai.pydantic.dev/) - Framework documentation
- [Documentation Index](README.md) - Return to main documentation hub
