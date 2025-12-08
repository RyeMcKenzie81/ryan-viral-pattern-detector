# Feature Development Framework

**Version**: 1.0.0
**Purpose**: Structured workflow for planning and building new features without impacting core infrastructure

> **Required Reading**: Before using this framework, review:
> - [Architecture](architecture.md) - System design and layered architecture
> - [Claude Code Guide](claude_code_guide.md) - Tool development patterns and best practices

---

## Overview

This framework ensures new workflows, services, tools, and agents are built:
- With clear planning and user confirmation at each phase
- Following Pydantic AI best practices
- Reusable by other components
- Without breaking existing functionality
- With minimal merge conflicts

---

## The 6 Phases

### Phase 1: INTAKE

**Goal**: Understand the requirement completely before any design work.

**Rules**:
- ASK QUESTIONS instead of making assumptions
- Document the desired outcome explicitly
- Identify all stakeholders and use cases
- Get user confirmation before proceeding

**Questions to Ask**:
1. What is the desired end result?
2. Who/what triggers this workflow? (UI button, API call, cron, chat)
3. What inputs are required?
4. What outputs are expected?
5. Are there error cases to handle?
6. Should this be chat-routable via orchestrator?

**Create Feature Branch** (after questions answered):
```bash
# Create and switch to feature branch
git checkout main
git pull origin main
git checkout -b feature/{feature-slug}

# Create plan directory
mkdir -p docs/plans/{feature-slug}
```

**Deliverable**:
- Feature branch created: `feature/{feature-slug}`
- Plan file created: `docs/plans/{feature-slug}/PLAN.md` Section 1 completed

---

### Phase 2: ARCHITECTURE DECISION

**Goal**: Determine the right implementation pattern.

**Decision: pydantic-graph vs Python Workflow**

| Use pydantic-graph when... | Use Python workflow when... |
|---------------------------|----------------------------|
| AI makes decisions on next steps | User controls the flow |
| Autonomous/background execution | Interactive UI-driven |
| Complex branching logic | Linear sequential steps |
| State needs persistence/resume | Short synchronous operation |
| Multiple AI-powered steps | Single orchestration function |

**Questions to Ask**:
1. Who decides what happens next - the AI or the user?
2. Does this run autonomously or interactively?
3. Does it need to pause and resume?
4. How complex is the branching logic?

**Deliverable**: Architecture decision documented with reasoning

---

### Phase 3: INVENTORY & GAP ANALYSIS

**Goal**: Maximize reuse, minimize new code.

**Step 3.1: Inventory Existing Components**

Check these locations for reusable components:

```
Services:     viraltracker/services/*.py
Tools:        viraltracker/agent/agents/*.py
Pipelines:    viraltracker/pipelines/*.py
Models:       viraltracker/services/models.py
```

**Step 3.2: Database Schema Evaluation**

**CRITICAL**: Before designing any new tables or columns:

1. **Query existing schema**:
   ```sql
   -- List all tables
   SELECT table_name FROM information_schema.tables
   WHERE table_schema = 'public';

   -- Check if table exists
   SELECT * FROM information_schema.tables
   WHERE table_name = 'proposed_table_name';

   -- View table structure
   SELECT column_name, data_type, is_nullable
   FROM information_schema.columns
   WHERE table_name = 'existing_table';
   ```

2. **Check for existing functionality**:
   - Does a table already store this data?
   - Can we add columns to existing tables instead?
   - Are there existing foreign key relationships to leverage?

3. **Naming collision prevention**:
   - Search codebase for proposed table/column names
   - Check `sql/` folder for existing migrations
   - Verify no service already references this name

**Step 3.3: Gap Analysis**

For each capability needed:
- [ ] Can we use an existing service method?
- [ ] Can we extend an existing service?
- [ ] Do we need a new service?
- [ ] Can we use existing tools?
- [ ] Do we need new tools?
- [ ] Can we use existing database tables?
- [ ] Do we need new tables/columns?

**Step 3.4: Design for Reusability**

New services should be:
- Single responsibility (one domain)
- Stateless where possible
- Well-documented with docstrings
- Usable by CLI, API, UI, and agents

**Deliverable**: Component list with reuse/build decisions, database impact assessment

---

### Phase 4: BUILD

**Goal**: Build each component with quality gates.

**For Each Component**:

1. **Create the file** in the correct location:
   - Service → `viraltracker/services/{name}_service.py`
   - Pipeline → `viraltracker/pipelines/{name}.py`
   - Agent → `viraltracker/agent/agents/{name}_agent.py`
   - Models → In the service file OR `services/models.py` if shared
   - Migration → `sql/{date}_{description}.sql`

2. **Follow the patterns**:
   ```python
   # Services: Business logic, reusable
   class MyService:
       def __init__(self, supabase: Client):
           self.supabase = supabase

       def my_method(self, param: str) -> Result:
           """Docstring with Args, Returns, Raises."""
           pass

   # Tools: Thin wrappers, delegate to services
   @agent.tool(metadata={...})
   async def my_tool(ctx: RunContext[AgentDependencies], ...) -> Result:
       """Docstring for LLM."""
       return ctx.deps.my_service.my_method(...)

   # Pipelines: State + Nodes
   @dataclass
   class MyState:
       input: str
       result: Optional[str] = None

   @dataclass
   class MyNode(BaseNode[MyState]):
       async def run(self, ctx: GraphRunContext[MyState, AgentDependencies]):
           pass
   ```

3. **Database Migrations** (if needed):
   ```sql
   -- sql/YYYY-MM-DD_add_feature_tables.sql

   -- Migration: Add tables for {feature}
   -- Date: YYYY-MM-DD
   -- Purpose: {detailed explanation}
   -- VERIFIED: No naming collisions with existing tables

   -- Check doesn't exist before creating
   CREATE TABLE IF NOT EXISTS my_table (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       created_at TIMESTAMPTZ DEFAULT NOW(),
       -- columns...
   );

   -- Add column only if it doesn't exist
   ALTER TABLE existing_table
   ADD COLUMN IF NOT EXISTS new_column TYPE;

   -- Document the column
   COMMENT ON TABLE my_table IS 'Description of table purpose';
   COMMENT ON COLUMN my_table.column IS 'Description of column';
   ```

4. **Quality Gate** (before moving to next component):
   - [ ] Syntax check: `python3 -m py_compile <file>`
   - [ ] Docstrings complete (Google format)
   - [ ] Type hints on all parameters and returns
   - [ ] Error handling appropriate
   - [ ] No debug code or print statements
   - [ ] Migration uses IF NOT EXISTS / IF EXISTS guards

**Deliverable**: Working components with passing quality gates

---

### Phase 5: INTEGRATION & TEST

**Goal**: Wire components into the system and validate.

**Step 5.1: Update Shared Files**

Only touch these files, only where necessary:

| File | When to Modify |
|------|----------------|
| `agent/dependencies.py` | Adding new service to AgentDependencies |
| `orchestrator.py` | Adding chat-routable agent (routing tool) |
| `services/__init__.py` | Exporting new service |
| `pipelines/__init__.py` | Exporting new pipeline |
| `agent/agents/__init__.py` | Exporting new agent |

**Step 5.2: Run Database Migrations**

```bash
# Review migration first
cat sql/YYYY-MM-DD_add_feature_tables.sql

# Run on staging database
psql $STAGING_DATABASE_URL -f sql/YYYY-MM-DD_add_feature_tables.sql

# Verify tables created
psql $STAGING_DATABASE_URL -c "\dt"
```

**Step 5.3: Local Testing**

```bash
# Syntax check all modified files
python3 -m py_compile viraltracker/services/my_service.py

# Test imports work
python3 -c "from viraltracker.services import MyService"

# Test service instantiation
python3 -c "
from viraltracker.agent.dependencies import AgentDependencies
deps = AgentDependencies.create()
print(deps.my_service)
"
```

**Step 5.4: Railway Staging**

```bash
# Push to feature branch
git push origin feature/my-feature

# Railway auto-deploys feature branches
# Test at: https://my-feature.up.railway.app
```

**Deliverable**: Working integration, passing Railway tests

---

### Phase 6: MERGE & CLEANUP

**Goal**: Clean merge to main with full documentation.

**Checklist**:
- [ ] All syntax checks pass
- [ ] All tests pass on Railway
- [ ] Database migrations run successfully
- [ ] Docstrings complete for all new code
- [ ] No debug code or unused imports
- [ ] PLAN.md updated with final implementation
- [ ] Commit message follows format

**Commit Format**:
```
feat: Add {feature name}

- Added {service/tool/pipeline} for {purpose}
- Integrated with {existing components}
- Database: {new tables/columns if any}
- {Other notable changes}

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Merge**:
```bash
git checkout main
git pull origin main
git merge feature/my-feature
git push origin main
```

**Production Migration**:
```bash
# Run migration on production after merge
psql $PRODUCTION_DATABASE_URL -f sql/YYYY-MM-DD_add_feature_tables.sql
```

**Archive**:
Move `docs/plans/{feature}/` to `docs/archive/` after merge.

---

## Core Architecture Reference

### 3-Layer Architecture

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
├── pipelines/            # pydantic-graph workflows
├── ui/pages/             # Streamlit UI pages
└── sql/                  # Database migrations
```

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

# ❌ WRONG: Business logic in tool
@agent.tool(...)
async def my_tool(ctx: RunContext[AgentDependencies], ...):
    # Don't put business logic here!
    data = fetch_data()
    processed = process(data)
    return processed
```

---

## Database Guidelines

### Before Creating Tables

1. **Always check existing schema first**
2. **Search for naming collisions** in code and migrations
3. **Prefer extending existing tables** over creating new ones
4. **Use consistent naming conventions**:
   - Tables: `snake_case`, plural (`user_accounts`, not `UserAccount`)
   - Columns: `snake_case`
   - Foreign keys: `{referenced_table}_id`

### Migration Safety

```sql
-- Always use guards
CREATE TABLE IF NOT EXISTS ...
ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...
DROP TABLE IF EXISTS ... -- Only in rollback scripts!

-- Always add comments
COMMENT ON TABLE table_name IS 'Purpose of this table';
COMMENT ON COLUMN table_name.column IS 'Purpose of this column';
```

### Common Tables Reference

Before creating new tables, check if these existing tables can be extended:
- `brands` - Brand/company information
- `products` - Products within brands
- `projects` - Grouping for operations
- `posts` - Social media content
- `facebook_ads` - Ad library data
- `ad_assets` - Media files from ads
- `generated_ads` - AI-generated ad creatives

---

## Forbidden Actions

**NEVER do these without explicit user approval**:

1. ❌ Modify `orchestrator.py` system prompt
2. ❌ Change existing service method signatures
3. ❌ Modify existing tool behavior
4. ❌ Delete or rename existing components
5. ❌ Add dependencies to `requirements.txt` without asking
6. ❌ Modify database schema without migration plan
7. ❌ Create tables without checking for naming collisions
8. ❌ Drop or alter existing tables without explicit approval
9. ❌ Make assumptions about requirements - ASK FIRST

---

## Quick Start

To start a new feature:

```bash
/plan-workflow {your feature idea or paste your plan}
```

This will guide you through all 6 phases with checkpoints.
