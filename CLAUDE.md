# ViralTracker Development Guidelines

> **Full Documentation**: See [docs/README.md](docs/README.md) for complete documentation index.

## Required Reading

Before making changes, review these docs:
- `/docs/architecture.md` - System design and layered architecture
- `/docs/claude_code_guide.md` - Tool development patterns and best practices

---

## Development Workflow (ALWAYS FOLLOW)

For every task, follow this workflow:

### 1. Plan
- Understand the requirement fully before coding
- Identify affected files and systems
- Consider edge cases and error handling
- Use TodoWrite to track multi-step tasks
- **CRITICAL: Research third-party tools before implementing** (see below)

### 2. Implement
- Follow the architecture patterns below
- Keep changes focused and minimal
- Don't over-engineer or add unnecessary features

### 3. Document
- Update docstrings for any modified functions
- Update relevant docs in `/docs/` if behavior changes
- Add inline comments only where logic isn't self-evident

### 4. Test
- Verify syntax: `python3 -m py_compile <file>`
- Test the feature manually if possible
- Check for regressions in related functionality

### 5. QA & Cleanup
- Remove any debug code or print statements
- Ensure no unused imports or variables
- Verify error handling is appropriate

### 6. Update External Documentation
- If you changed behavior, check if these need updates:
  - `/docs/architecture.md`
  - `/docs/claude_code_guide.md`
  - `/docs/README.md`
  - Any checkpoint files in `/docs/archive/`
- Documentation should always reflect current system state

---

## Third-Party Tool Research (CRITICAL)

**Before implementing anything that uses external tools or libraries, ALWAYS:**

1. **Search for official documentation** using WebSearch or WebFetch
2. **Look for common pitfalls and best practices** - search for "[tool] best practices" or "[tool] common issues"
3. **Verify the approach** before writing code - don't assume you know the right way

### Why This Matters

We've learned this lesson the hard way. Example: FFmpeg has multiple ways to concatenate videos:
- **Concat demuxer** (`-f concat -c copy`) - fast but has known audio sync bugs with mixed sources
- **Concat filter** (`-filter_complex "concat=n=X:v=1:a=1"`) - slower but reliable

We spent 3+ hours debugging audio sync issues that would have been avoided by reading FFmpeg docs first.

### Tools That Require Research

| Tool | Research Before |
|------|-----------------|
| FFmpeg | Video/audio processing, concatenation, filters |
| ImageMagick | Image manipulation, compositing |
| Supabase | Storage, RLS policies, edge functions |
| OpenAI/Anthropic APIs | Rate limits, best practices, token optimization |
| Any new library | Check docs for gotchas and recommended patterns |

### How to Research

```
# Good search queries:
"FFmpeg concat audio sync issues"
"FFmpeg best practice video concatenation"
"[library] common mistakes"
"[library] official documentation [specific feature]"
```

**Take the extra 5 minutes to research. It saves hours of debugging.**

---

## Core Architecture (3 Layers)

```
Agent Layer (PydanticAI) → Tools = thin orchestration, LLM decides when to call
Service Layer           → Business logic, deterministic preprocessing, reusable
Interface Layer         → CLI, API, Streamlit UI (all call services)
```

### File Locations
```
viraltracker/
├── agent/
│   ├── agents/           # Specialist agents (tools defined here)
│   ├── orchestrator.py   # Main routing agent
│   └── dependencies.py   # AgentDependencies (service container)
├── services/             # Business logic layer
│   ├── ad_creation_service.py
│   ├── gemini_service.py
│   ├── twitter_service.py
│   └── models.py         # Pydantic models
└── ui/
    └── pages/            # Streamlit UI pages
```

---

## Pydantic-AI Best Practices

### Tool vs Service Decision
| Question | Yes → | No → |
|----------|-------|------|
| Does LLM decide when to call this? | Tool | Service |
| Must always run (deterministic)? | Service | Could be Tool |
| Reusable across agents/interfaces? | Service | Tool OK |

### Thin Tools Pattern (CRITICAL)
```python
# ✅ CORRECT: Tool calls service
@agent.tool(...)
async def my_tool(ctx: RunContext[AgentDependencies], ...):
    result = ctx.deps.my_service.do_business_logic(...)
    return result

# ❌ WRONG: Business logic in tool or helper in agent file
def helper_function(...):  # Should be in service!
    pass
```

### Key Rules
1. **Tools** = `@agent.tool()` decorator, thin orchestration only
2. **Services** = Business logic in `viraltracker/services/`
3. **deps_type** = Service container (`AgentDependencies`)
4. **Docstrings** = Sent to LLM (be clear and comprehensive)
5. **Metadata** = System config only (rate limits, categories)

---

## Python Workflow Examples

### Example 1: Adding a New Service Method

```python
# viraltracker/services/ad_creation_service.py

class AdCreationService:
    def my_new_method(self, param1: str, param2: Dict[str, Any]) -> Dict[str, Any]:
        """
        Brief description of what this method does.

        Args:
            param1: Description of param1
            param2: Description of param2

        Returns:
            Description of return value
        """
        # Business logic here
        result = self._process_data(param1, param2)
        logger.info(f"Processed: {param1}")
        return result
```

### Example 2: Adding a New Tool (Thin Wrapper)

```python
# viraltracker/agent/agents/ad_creation_agent.py

@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': ['Use case 1', 'Use case 2'],
        'examples': ['Example query 1', 'Example query 2']
    }
)
async def my_new_tool(
    ctx: RunContext[AgentDependencies],
    param1: str,
    param2: int = 10
) -> Dict:
    """
    Clear description for the LLM about when to use this tool.

    Args:
        ctx: Run context with AgentDependencies
        param1: Description of param1
        param2: Description with default (default: 10)

    Returns:
        Dictionary with results
    """
    # Thin wrapper - delegate to service
    result = ctx.deps.ad_creation.my_new_method(param1, {"count": param2})
    return result
```

### Example 3: Adding a Streamlit UI Component

```python
# viraltracker/ui/pages/01_🎨_Ad_Creator.py

def render_my_section():
    """Render a new UI section."""
    st.subheader("Section Title")

    # Get data from service (not direct DB calls)
    service = get_ad_creation_service()
    data = service.get_data()

    # Render UI
    if data:
        for item in data:
            st.write(item)
    else:
        st.info("No data available")
```

### Example 4: Database Migration

```sql
-- migrations/YYYY-MM-DD_description.sql

-- Migration: Brief description
-- Date: YYYY-MM-DD
-- Purpose: Detailed explanation

ALTER TABLE table_name ADD COLUMN IF NOT EXISTS new_column TYPE;

COMMENT ON COLUMN table_name.new_column IS 'Description of the column';
```

---

## Commit Message Format

```
type: Brief description

Longer explanation if needed.
- Bullet points for multiple changes
- Keep it concise

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

---

## Common Patterns

### Accessing Services in Tools
```python
ctx.deps.ad_creation    # AdCreationService
ctx.deps.gemini         # GeminiService
ctx.deps.twitter        # TwitterService
```

### Error Handling
```python
try:
    result = await ctx.deps.service.method()
    return result
except ValueError as e:
    logger.error(f"Validation error: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise Exception(f"Failed to process: {e}")
```

### Logging
```python
import logging
logger = logging.getLogger(__name__)

logger.info(f"Processing: {item}")      # Normal operations
logger.warning(f"Unexpected: {item}")   # Non-fatal issues
logger.error(f"Failed: {e}")            # Errors
```

---

## Streamlit UI Patterns

### Shared Brand Selector (ALWAYS USE)

Use `render_brand_selector()` from `viraltracker/ui/utils.py` for all brand selection. This ensures:
- Brand selection persists across pages in the same browser session
- Consistent UI across all pages
- Single source of truth for brand state

```python
# viraltracker/ui/pages/XX_My_Page.py

# Import shared utility
from viraltracker.ui.utils import render_brand_selector

# Basic usage - just brand selector
brand_id = render_brand_selector(key="my_page_brand_selector")
if not brand_id:
    st.stop()

# With product selector
brand_id, product_id = render_brand_selector(
    key="my_page_brand_selector",
    include_product=True,
    product_key="my_page_product_selector"
)

# If you need brand name for display/prompts
brands = get_brands()
brand_name = next((b['name'] for b in brands if b['id'] == brand_id), "Unknown")
```

**Session State Key**: Uses `st.session_state.selected_brand_id` internally - do NOT create page-specific brand selection keys.

### Page Structure Pattern

```python
# 1. Page config (must be first Streamlit call)
st.set_page_config(page_title="My Page", page_icon="📊", layout="wide")

# 2. Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# 3. Session state initialization
if 'my_state' not in st.session_state:
    st.session_state.my_state = None

# 4. Helper functions
def get_my_service():
    from viraltracker.services.my_service import MyService
    return MyService()

# 5. UI rendering functions
def render_my_section(brand_id: str):
    st.subheader("My Section")
    # ...

# 6. Main page content
st.title("📊 My Page")

# 7. Brand selector (shared utility)
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="my_page_brand_selector")
if not brand_id:
    st.stop()

# 8. Render sections
render_my_section(brand_id)
```

### Sidebar Page Organization

Pages are organized by feature area with numbered prefixes:
- `01-05`: Brands (Manager, Products, Personas, URL Mapping, Brand Research)
- `10-13`: Competitors (Competitors, Research, Analysis)
- `20-29`: Ads (Library, Planning, Executor, etc.)
- `40-49`: Content (Pipeline, etc.)
- `60-69`: System (Settings, etc.)

---

## Checklist Before Completing Any Task

- [ ] Code follows thin-tools pattern (business logic in services)
- [ ] Syntax verified with `python3 -m py_compile`
- [ ] Docstrings updated for modified functions
- [ ] Relevant `/docs/` files updated if behavior changed
- [ ] No debug code or unused imports
- [ ] Error handling appropriate
- [ ] Changes committed with descriptive message
- [ ] Changes pushed to GitHub

---

## Content Pipeline Feature Guidelines

> **Plan Document**: See `docs/plans/trash-panda-content-pipeline/PLAN.md`
> **Checkpoints**: See `docs/plans/trash-panda-content-pipeline/CHECKPOINT_*.md`

### Pydantic-Graph Pattern (CRITICAL)

Follow existing pattern in `viraltracker/pipelines/`:

```python
# states.py - State dataclass
@dataclass
class ContentPipelineState:
    # Input params
    brand_id: UUID
    # Populated by nodes
    topics: List[Dict] = field(default_factory=list)
    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None

# nodes/topic_discovery.py - Thin node
@dataclass
class TopicDiscoveryNode(BaseNode[ContentPipelineState]):
    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> "TopicEvaluationNode":
        # Delegate to service (THIN!)
        topics = await ctx.deps.content_pipeline.topic_service.discover_topics(...)
        ctx.state.topics = topics
        return TopicEvaluationNode()
```

### File Structure

```
viraltracker/services/content_pipeline/
├── __init__.py
├── state.py                 # ContentPipelineState dataclass
├── orchestrator.py          # Graph definition (small!)
├── nodes/                   # Thin node wrappers
│   ├── __init__.py
│   ├── topic_discovery.py
│   ├── topic_evaluation.py
│   └── ...
└── services/                # Business logic (reusable)
    ├── __init__.py
    ├── topic_service.py
    ├── script_service.py
    └── ...
```

### User Preferences (MUST FOLLOW)

1. **Checkpoints every ~40K tokens** - Save progress to CHECKPOINT_*.md
2. **Test and QA as you go** - `python3 -m py_compile` after each file
3. **Cleanup files as you go** - No debug code, no unused imports
4. **Ask questions instead of assuming** - When in doubt, ask user
5. **Make services reusable** - Don't make them too feature-specific
6. **JSON prompts for images** - Simple JSON structure for Gemini prompts
7. **MVP first** - Build minimal testable pieces, then expand

### Human Checkpoints Pattern

For steps that pause for human input:
```python
# Return End with "awaiting_human" status
return End({
    "status": "awaiting_human",
    "checkpoint": "topic_selection",
    "data": {...}
})

# UI checks status and shows approval UI
# On approval, resume graph from next node
```

### Models & AI

| Task | Model |
|------|-------|
| Topic Discovery | ChatGPT 5.1 (extended thinking) |
| Scripts, SEO, Comic Audio | Claude Opus 4.5 |
| Images, Comics, Assets | Gemini 3 Pro Image Preview |
| Evaluations | Gemini |

### Knowledge Base

- `trash-panda-bible`: Bible + 6 YouTube docs (use RAG - too big to inject)
- `comic-production`: 20 comic docs (use RAG with tagged chunks)

### Quick Reference

- **Plan**: `docs/plans/trash-panda-content-pipeline/PLAN.md`
- **Visualization**: `docs/plans/trash-panda-content-pipeline/WORKFLOW_VISUALIZATION.md`
- **Checkpoints**: `docs/plans/trash-panda-content-pipeline/CHECKPOINT_*.md`
- **Existing Graph Example**: `viraltracker/pipelines/brand_onboarding.py`
