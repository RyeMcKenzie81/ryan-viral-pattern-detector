# Tool Registry System - Auto-Generate API Endpoints

**Version**: 1.0.0
**Date**: 2025-11-18
**Status**: Design Complete, Demo Implementation Ready

## Overview

The Tool Registry system automatically generates FastAPI endpoints for every Pydantic AI agent tool. This eliminates the need to manually create and maintain separate API endpoints for each tool function.

### Problem Solved

**Before (Manual Approach)**:
```python
# 1. Define tool function in tools.py
async def find_outliers_tool(ctx, hours_back, threshold, ...):
    # Implementation
    pass

# 2. Register with agent in agent.py
agent.tool(find_outliers_tool)

# 3. Create request model in models.py
class FindOutliersRequest(BaseModel):
    project_name: str
    hours_back: int = 24
    threshold: float = 2.0
    # ... repeat all parameters

# 4. Create API endpoint in app.py
@app.post("/tools/find-outliers")
async def find_outliers_endpoint(request: FindOutliersRequest, ...):
    # Duplicate parameter handling
    # Duplicate error handling
    # Duplicate logging
    pass
```

**Result**: 4 separate places to update when adding parameters or changing tools.

**After (Registry Approach)**:
```python
# Single definition creates EVERYTHING
@tool_registry.register(
    name="find_outliers_tool",
    description="Find viral outlier tweets",
    category="Twitter",
    rate_limit="20/minute"
)
async def find_outliers_tool(ctx, hours_back: int = 24, threshold: float = 2.0, ...):
    # Implementation
    pass
```

**Result**: 1 place to define tool = automatic agent registration + API endpoint + request validation + documentation.

---

## Architecture

### Components

1. **tool_registry.py** - Core registry system
   - `ToolRegistry` class: Manages tool registration and endpoint generation
   - `ToolMetadata` dataclass: Stores tool information
   - `tool_registry` singleton: Global registry instance

2. **tools_registered.py** - Tools using new pattern
   - Tool functions decorated with `@tool_registry.register()`
   - Automatic parameter inference from function signatures
   - Type-safe validation via Pydantic

3. **app_with_registry.py** - Demo API using registry
   - Imports `tools_registered` to trigger registration
   - Calls `tool_registry.create_api_router()` for endpoints
   - Includes auto-generated router in FastAPI app

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Tool Definition (tools_registered.py)                    │
│    @tool_registry.register(...)                            │
│    async def my_tool(ctx, param1, param2): ...             │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Registration (tool_registry.py)                          │
│    - Extract function signature                             │
│    - Generate Pydantic request model                        │
│    - Store ToolMetadata                                     │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Agent Registration (agent.py)                            │
│    agent.tool(my_tool)  # Still works!                     │
└─────────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. API Endpoint Generation (app_with_registry.py)          │
│    tool_registry.create_api_router()                        │
│    - Creates POST /tools/my-tool                            │
│    - Adds authentication                                    │
│    - Adds rate limiting                                     │
│    - Generates OpenAPI docs                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Usage Guide

### Creating a New Tool

1. **Define tool function with decorator**:

```python
# viraltracker/agent/tools_registered.py

@tool_registry.register(
    name="search_twitter_tool",
    description="Search Twitter by keyword and save to database",
    category="Twitter",
    rate_limit="15/minute"
)
async def search_twitter_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    hours_back: int = 24,
    max_results: int = 100
) -> SearchResult:
    """
    Search Twitter for keyword.

    Args:
        ctx: Run context with dependencies
        keyword: Search keyword
        hours_back: Hours to search back
        max_results: Max tweets to return

    Returns:
        SearchResult with tweets
    """
    # Implementation...
    pass
```

2. **That's it!** The tool now:
   - ✅ Available to Pydantic AI agent
   - ✅ Has API endpoint at `POST /tools/search-twitter`
   - ✅ Has auto-generated request model
   - ✅ Has rate limiting (15/minute)
   - ✅ Requires authentication
   - ✅ Appears in OpenAPI docs

### Using the Tool

**Via Agent (Natural Language)**:
```python
result = await agent.run(
    "Search Twitter for 'fitness' in last 48 hours",
    deps=deps
)
```

**Via API (Direct Tool Call)**:
```bash
curl -X POST https://api.example.com/tools/search-twitter \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{
    "project_name": "my-project",
    "keyword": "fitness",
    "hours_back": 48,
    "max_results": 100
  }'
```

---

## Decorator Parameters

### `@tool_registry.register()`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | ✅ Yes | - | Unique tool identifier (e.g., `"find_outliers_tool"`) |
| `description` | str | ✅ Yes | - | Human-readable description for docs |
| `category` | str | No | `"General"` | Tool category (e.g., `"Twitter"`, `"TikTok"`) |
| `rate_limit` | str | No | `"20/minute"` | API rate limit (e.g., `"10/minute"`, `"100/hour"`) |
| `requires_auth` | bool | No | `True` | Whether endpoint requires API key |
| `request_model` | Type[BaseModel] | No | Auto-generated | Custom request model (rarely needed) |
| `response_model` | Type[BaseModel] | No | `None` | Custom response model for OpenAPI docs |

### Examples

**Basic Tool**:
```python
@tool_registry.register(
    name="my_tool",
    description="Does something useful"
)
async def my_tool(ctx, param1: str):
    pass
```

**High Rate Limit (Cheap Operation)**:
```python
@tool_registry.register(
    name="quick_lookup_tool",
    description="Fast database lookup",
    category="Database",
    rate_limit="100/minute"
)
async def quick_lookup_tool(ctx, id: str):
    pass
```

**Low Rate Limit (Expensive AI Operation)**:
```python
@tool_registry.register(
    name="analyze_video_tool",
    description="AI video analysis",
    category="TikTok",
    rate_limit="5/minute"  # Expensive!
)
async def analyze_video_tool(ctx, video_url: str):
    pass
```

**Public Endpoint (No Auth)**:
```python
@tool_registry.register(
    name="health_check_tool",
    description="Check service health",
    category="System",
    requires_auth=False  # Public endpoint
)
async def health_check_tool(ctx):
    pass
```

---

## API Endpoint Details

### Auto-Generated Endpoints

For each registered tool, the registry creates:

**Endpoint**: `POST /tools/{kebab-case-name}`
- `find_outliers_tool` → `POST /tools/find-outliers`
- `search_twitter_tool` → `POST /tools/search-twitter`
- `analyze_tiktok_video_tool` → `POST /tools/analyze-tiktok-video`

**Request Body**:
```json
{
  "project_name": "my-project",
  "param1": "value1",
  "param2": 123,
  "param3": true
}
```

**Success Response** (HTTP 200):
```json
{
  "success": true,
  "data": {
    "total_tweets": 42,
    "outlier_count": 5,
    "outliers": [...]
  },
  "error": null,
  "timestamp": "2025-11-18T12:00:00Z"
}
```

**Error Response** (HTTP 40x/50x):
```json
{
  "success": false,
  "data": {},
  "error": "Error message here",
  "timestamp": "2025-11-18T12:00:00Z"
}
```

### List All Tools

**GET /tools**:
```json
{
  "total_tools": 16,
  "tools": {
    "find_outliers_tool": {
      "name": "find_outliers_tool",
      "description": "Find viral outlier tweets",
      "category": "Twitter",
      "api_path": "/tools/find-outliers",
      "rate_limit": "20/minute",
      "requires_auth": true
    },
    ...
  },
  "categories": ["Twitter", "TikTok", "YouTube", "Facebook"]
}
```

---

## Integration Guide

### Step 1: Update Imports

**Old (Manual)**:
```python
# viraltracker/agent/agent.py
from .tools import find_outliers_tool, analyze_hooks_tool

agent.tool(find_outliers_tool)
agent.tool(analyze_hooks_tool)
```

**New (Registry)**:
```python
# viraltracker/agent/agent.py
from .tools_registered import find_outliers_tool, analyze_hooks_tool

agent.tool(find_outliers_tool)  # Still works!
agent.tool(analyze_hooks_tool)
```

### Step 2: Update API App

**Old (Manual Endpoints)**:
```python
# viraltracker/api/app.py
@app.post("/tools/find-outliers")
async def find_outliers_endpoint(...):
    # Manual implementation
    pass

@app.post("/tools/analyze-hooks")
async def analyze_hooks_endpoint(...):
    # Manual implementation
    pass
```

**New (Auto-Generated)**:
```python
# viraltracker/api/app.py
from ..agent import tools_registered  # Trigger registration
from ..agent.tool_registry import tool_registry

# Generate all endpoints
tool_router = tool_registry.create_api_router(
    limiter=limiter,
    auth_dependency=verify_api_key
)

app.include_router(tool_router)
```

### Step 3: Remove Old Files (Optional)

Once all tools are migrated:
- Move `tools.py` → `tools_old.py` (backup)
- Rename `tools_registered.py` → `tools.py`
- Replace `app.py` → use `app_with_registry.py` pattern

---

## Migration Strategy

### Phase 1: Parallel Operation (Current)
- Keep `tools.py` (old manual tools)
- Create `tools_registered.py` (new registry tools)
- Run both systems in parallel
- Test auto-generated endpoints match manual ones

### Phase 2: Incremental Migration
- Migrate 2-3 tools at a time to registry
- Update agent.py imports
- Test agent and API functionality
- Compare behavior with old implementation

### Phase 3: Complete Migration
- All 16 tools migrated to registry
- Remove manual endpoint definitions
- Delete old `tools.py`
- Rename `tools_registered.py` → `tools.py`

---

## Benefits Summary

### For Developers

✅ **Write Once, Use Everywhere**
- Single tool definition works for both agent and API

✅ **Type Safety**
- Automatic Pydantic validation from function signatures
- No manual request model creation

✅ **Less Code**
- Eliminate ~80% of boilerplate per tool
- 16 tools = ~800 lines of code removed

✅ **Easier Maintenance**
- Change parameters in one place
- Consistent error handling
- Automatic API documentation

✅ **Faster Development**
- Add new tool in minutes, not hours
- No need to learn FastAPI endpoint patterns

### For API Users

✅ **Consistent API**
- All tool endpoints follow same pattern
- Uniform error responses
- Predictable request/response format

✅ **Better Documentation**
- Auto-generated OpenAPI/Swagger docs
- Up-to-date with code
- Clear parameter descriptions

✅ **Discovery**
- `GET /tools` lists all available tools
- Categories for easy browsing

---

## Files Created

### Core System
- `viraltracker/agent/tool_registry.py` - Registry implementation
- `viraltracker/agent/tools_registered.py` - Example tools using registry
- `viraltracker/api/app_with_registry.py` - Demo API implementation

### Documentation
- `docs/TOOL_REGISTRY_GUIDE.md` - This file
- See inline code documentation for details

---

## Next Steps

### To Test the System

1. **Start the demo API**:
```bash
# Stop current API
# Update start.sh to use app_with_registry instead of app

uvicorn viraltracker.api.app_with_registry:app --reload --port 8000
```

2. **Check auto-generated endpoints**:
```bash
# List all tools
curl http://localhost:8000/tools

# View OpenAPI docs
open http://localhost:8000/docs
```

3. **Test a tool endpoint**:
```bash
curl -X POST http://localhost:8000/tools/find-outliers \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "yakety-pack-instagram",
    "hours_back": 24,
    "threshold": 2.0
  }'
```

### To Migrate All Tools

1. Copy tool functions from `tools.py` to `tools_registered.py`
2. Add `@tool_registry.register()` decorator to each
3. Update imports in `agent.py`
4. Test each tool via agent and API
5. Once all working, replace `app.py` with registry version

---

## FAQ

**Q: Does this break existing agent code?**
A: No! The decorated tools work exactly the same with `agent.tool()`.

**Q: Do I have to migrate all tools at once?**
A: No! You can migrate incrementally. Old and new systems work in parallel.

**Q: Can I customize the request/response models?**
A: Yes! Pass `request_model` and `response_model` to the decorator.

**Q: What about tool parameters that shouldn't be in the API?**
A: Tool parameters are automatically extracted. The `ctx` parameter is always excluded.

**Q: Can I disable API generation for specific tools?**
A: Yes! Don't register them. Only use `@agent.tool()` decorator.

**Q: Does this work with the Streamlit UI?**
A: Yes! The UI uses the agent, which works with registered tools.

**Q: What about custom authentication per tool?**
A: Set `requires_auth=False` for public endpoints, or create custom auth dependency.

---

## Support

For questions or issues:
1. Check inline code documentation
2. Review demo files (`app_with_registry.py`, `tools_registered.py`)
3. Test with example endpoints
4. Consult this guide

---

**Status**: ✅ Design Complete | 🚧 Migration Pending | 📝 Documentation Complete
