# Auto-Generate API Endpoints from Agent Tools - Implementation Plan

**Date**: 2025-11-18
**Status**: Ready to Implement
**Approach**: Pydantic-AI Compliant (Agent-First, Then Auto-Generate)

## Overview

Create a system that automatically generates FastAPI endpoints for all Pydantic AI agent tools WITHOUT using custom decorators or wrapping pydantic-ai's registration system.

## Core Principle

**Agent is the single source of truth**. The API inspects the agent's registered tools and auto-generates endpoints from what the agent already knows.

```
Tool Function → @agent.tool() → Agent (source of truth)
                                    ↓
                            Scan agent._toolset
                                    ↓
                            Auto-generate API endpoints
```

## Architecture

### 1. Current State (Manual)

```python
# viraltracker/agent/tools.py
async def find_outliers_tool(ctx, hours_back=24, ...):
    pass

# viraltracker/agent/agent.py
agent.tool(find_outliers_tool)

# viraltracker/api/models.py
class FindOutliersRequest(BaseModel):
    hours_back: int = 24
    # ... duplicate all parameters

# viraltracker/api/app.py
@app.post("/tools/find-outliers")
async def find_outliers_endpoint(request: FindOutliersRequest, ...):
    # Duplicate implementation
    pass
```

**Problem**: 4 places to update when changing a tool.

### 2. Target State (Automatic)

```python
# viraltracker/agent/tools.py
async def find_outliers_tool(ctx, hours_back: int = 24, ...):
    pass

# viraltracker/agent/agent.py
agent.tool(find_outliers_tool)

# viraltracker/api/app.py
from viraltracker.api.endpoint_generator import generate_tool_endpoints

# Auto-scan agent and create all endpoints
tool_router = generate_tool_endpoints(agent, limiter, verify_api_key)
app.include_router(tool_router)
```

**Result**: 1 place to define tool → automatic agent registration + API endpoint.

## Implementation Steps

### Phase 1: Create Endpoint Generator (New File)

Create `viraltracker/api/endpoint_generator.py`:

**Features**:
- Function: `generate_tool_endpoints(agent, limiter, auth_dependency)`
- Scans `agent._toolset.tools` for all registered tools
- For each tool:
  - Extract function signature using `inspect.signature()`
  - Extract type hints using `typing.get_type_hints()`
  - Auto-generate Pydantic request model
  - Create FastAPI route handler
  - Add to APIRouter

**Input**: Pydantic AI Agent instance
**Output**: FastAPI APIRouter with all tool endpoints

### Phase 2: Update API App (Modify Existing)

Modify `viraltracker/api/app.py`:

**Changes**:
1. Import endpoint generator
2. Replace manual endpoint definitions
3. Call `generate_tool_endpoints(agent, limiter, verify_api_key)`
4. Include returned router in app

**Keep**:
- `/health` endpoint
- `/` root endpoint
- `/agent/run` conversational endpoint
- All middleware, auth, rate limiting

**Remove**:
- Manual `/tools/find-outliers` endpoint
- Manual `/tools/analyze-hooks` endpoint
- Can remove `FindOutliersRequest`, `AnalyzeHooksRequest` from models.py

### Phase 3: Test and Verify

**Tests**:
1. Import test: `from viraltracker.api.endpoint_generator import generate_tool_endpoints`
2. Generation test: Router created with correct number of endpoints
3. Endpoint test: Each tool has POST /tools/{kebab-case-name}
4. Request model test: Auto-generated models validate correctly
5. Integration test: Call endpoint → tool executes → returns result
6. Comparison test: Auto-generated endpoints match manual ones

### Phase 4: Documentation

Update:
- `README.md` - How to add new tools
- `docs/API.md` - Endpoint generation explanation
- Code comments in `endpoint_generator.py`

## Technical Details

### Accessing Agent Tools

```python
from viraltracker.agent.agent import agent

# Access registered tools
toolset = agent._toolset  # or agent.toolset if property
tools = toolset.tools  # Dict[str, Callable]

for tool_name, tool_func in tools.items():
    print(f"Tool: {tool_name}")
    print(f"Function: {tool_func}")
```

### Extracting Function Signature

```python
import inspect
from typing import get_type_hints

sig = inspect.signature(tool_func)
hints = get_type_hints(tool_func)

for param_name, param in sig.parameters.items():
    if param_name == 'ctx':
        continue  # Skip RunContext parameter

    param_type = hints.get(param_name, str)
    default = param.default if param.default != inspect.Parameter.empty else ...

    print(f"{param_name}: {param_type} = {default}")
```

### Auto-Generating Request Model

```python
from pydantic import create_model

def create_request_model(tool_func, tool_name):
    sig = inspect.signature(tool_func)
    hints = get_type_hints(tool_func)

    fields = {}
    for param_name, param in sig.parameters.items():
        if param_name == 'ctx':
            continue

        param_type = hints.get(param_name, Any)
        default = param.default if param.default != inspect.Parameter.empty else ...
        fields[param_name] = (param_type, default)

    # Add project_name (required for all tools)
    fields['project_name'] = (str, 'yakety-pack-instagram')

    model_name = f"{tool_name.replace('_tool', '').title().replace('_', '')}Request"
    return create_model(model_name, **fields)
```

### Creating API Endpoint

```python
def create_tool_endpoint(tool_name, tool_func, request_model, auth_dep):
    async def endpoint(
        request: Request,
        tool_request: request_model,
        authenticated: bool = Depends(auth_dep)
    ):
        try:
            # Extract parameters
            params = tool_request.model_dump()
            project_name = params.pop('project_name')

            # Create dependencies
            deps = AgentDependencies.create(project_name=project_name)
            ctx = RunContext(deps=deps, retry=0, messages=[])

            # Call tool
            result = await tool_func(ctx=ctx, **params)

            return {
                "success": True,
                "data": result.model_dump() if hasattr(result, 'model_dump') else result,
                "error": None,
                "timestamp": datetime.now()
            }
        except Exception as e:
            return {
                "success": False,
                "data": {},
                "error": str(e),
                "timestamp": datetime.now()
            }

    return endpoint
```

### API Path Convention

```python
def tool_name_to_path(tool_name: str) -> str:
    """
    Convert tool function name to API path.

    Examples:
        find_outliers_tool → /tools/find-outliers
        search_twitter_tool → /tools/search-twitter
        analyze_tiktok_video_tool → /tools/analyze-tiktok-video
    """
    # Remove _tool suffix
    name = tool_name.replace('_tool', '')
    # Convert snake_case to kebab-case
    path = name.replace('_', '-')
    return f"/tools/{path}"
```

## File Structure

```
viraltracker/
├── agent/
│   ├── tools.py              # Tool implementations (unchanged)
│   ├── tools_phase15.py      # More tools (unchanged)
│   ├── tools_phase16.py      # More tools (unchanged)
│   ├── tools_phase17.py      # More tools (unchanged)
│   └── agent.py              # Agent with @agent.tool() (unchanged)
├── api/
│   ├── endpoint_generator.py # NEW: Auto-generate endpoints
│   ├── app.py                # MODIFIED: Use generator
│   └── models.py             # SIMPLIFIED: Remove manual request models
└── docs/
    ├── AUTO_API_ENDPOINTS_PLAN.md  # This file
    └── AUTO_API_ENDPOINTS_GUIDE.md # NEW: Usage guide
```

## Benefits

### For Developers

✅ **Single source of truth**: Tool definition = agent + API
✅ **Less code**: Eliminate ~80% of boilerplate per tool
✅ **Type-safe**: Automatic validation from function signatures
✅ **Maintainable**: Change tool once, API updates automatically
✅ **Pydantic-AI compliant**: Respects agent architecture

### For API Users

✅ **Consistent API**: All endpoints follow same pattern
✅ **Auto-discovery**: GET /tools lists all available tools
✅ **Up-to-date docs**: OpenAPI schema auto-generated from code

## Migration Strategy

### Step 1: Implement in Parallel
- Keep existing manual endpoints
- Add endpoint generator
- Generate endpoints alongside manual ones
- Compare behavior

### Step 2: Verify Equivalence
- Test auto-generated endpoints match manual ones
- Verify request/response formats identical
- Check error handling consistency

### Step 3: Switch Over
- Remove manual endpoint definitions
- Remove manual request models
- Keep only auto-generated endpoints

### Step 4: Monitor
- Check Railway production logs
- Verify all endpoints still work
- Monitor for any issues

## Example Output

After implementation, starting the API should show:

```
INFO:     Viraltracker API Starting...
INFO:     Auto-scanning agent for registered tools...
INFO:     Found 16 tools in agent
INFO:     Generated endpoint: POST /tools/find-outliers
INFO:     Generated endpoint: POST /tools/analyze-hooks
INFO:     Generated endpoint: POST /tools/search-twitter
INFO:     Generated endpoint: POST /tools/find-comment-opportunities
INFO:     Generated endpoint: POST /tools/export-comments
INFO:     Generated endpoint: POST /tools/analyze-search-term
INFO:     Generated endpoint: POST /tools/generate-content
INFO:     Generated endpoint: POST /tools/search-tiktok
INFO:     Generated endpoint: POST /tools/search-tiktok-hashtag
INFO:     Generated endpoint: POST /tools/scrape-tiktok-user
INFO:     Generated endpoint: POST /tools/analyze-tiktok-video
INFO:     Generated endpoint: POST /tools/analyze-tiktok-batch
INFO:     Generated endpoint: POST /tools/search-youtube
INFO:     Generated endpoint: POST /tools/search-facebook-ads
INFO:     Generated endpoint: POST /tools/scrape-facebook-page-ads
INFO:     Generated endpoint: POST /tools/export-results
INFO:     Total auto-generated endpoints: 16
INFO:     Docs available at: /docs
```

## Success Criteria

- ✅ Import endpoint_generator without errors
- ✅ Generate router with all 16+ tool endpoints
- ✅ Each endpoint has correct path (POST /tools/{name})
- ✅ Auto-generated request models validate correctly
- ✅ Calling endpoint executes tool and returns result
- ✅ Error handling works (invalid params, tool failures)
- ✅ OpenAPI docs show all endpoints with schemas
- ✅ Railway production deployment works
- ✅ Existing agent functionality unchanged

## Rollback Plan

If issues arise:
1. Keep `endpoint_generator.py` but don't use it
2. Revert `app.py` to use manual endpoints
3. Debug issues in development
4. Try again when fixed

Manual endpoints remain working throughout implementation.

---

**Status**: Ready for implementation
**Next Step**: Create `viraltracker/api/endpoint_generator.py`
