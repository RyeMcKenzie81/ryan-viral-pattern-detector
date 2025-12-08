# Plan Workflow Command

You are entering **Feature Development Mode**. Your task is to help plan and build a new workflow following the strict 6-phase process.

## Input

**User's idea or plan:**
$ARGUMENTS

---

## Required Reading (Load These First)

Before proceeding, you MUST read these files to understand the system:

1. `/docs/FEATURE_DEVELOPMENT.md` - The 6-phase process you must follow
2. `/docs/architecture.md` - System design and layered architecture
3. `/docs/claude_code_guide.md` - Tool development patterns

---

## Core Rules (CRITICAL)

### Rule 1: ASK, DON'T ASSUME
- **NEVER** make assumptions about requirements
- **ALWAYS** ask clarifying questions before designing
- If something is unclear, ask. If you're unsure, ask.
- Present questions using the `AskUserQuestion` tool when possible

### Rule 2: Follow the Architecture
```
Agent Layer (PydanticAI) → Tools = thin orchestration only
Service Layer           → ALL business logic goes here
Interface Layer         → CLI, API, Streamlit UI
```

### Rule 3: Thin Tools Pattern
- Tools call services, they don't contain business logic
- Services are reusable across all interfaces
- New services should be designed for reusability

### Rule 4: Database Safety
- ALWAYS check existing schema before proposing new tables
- NEVER create tables without verifying no naming collisions
- Use `IF NOT EXISTS` guards in all migrations
- Prefer extending existing tables over creating new ones

### Rule 5: Forbidden Actions
- ❌ Don't modify orchestrator.py system prompt
- ❌ Don't change existing service method signatures
- ❌ Don't modify existing tool behavior
- ❌ Don't add requirements.txt dependencies without asking
- ❌ Don't touch database schema without migration plan

---

## Your Process

### PHASE 1: INTAKE (Start Here)

1. **Read the user's input** (above)

2. **Ask clarifying questions** using AskUserQuestion tool:
   - What is the desired end result?
   - Who/what triggers this workflow? (UI button, API call, cron job, chat command)
   - What inputs are required?
   - What outputs are expected?
   - Are there specific error cases to handle?
   - Should this be accessible via chat (orchestrator routing)?
   - Any other unclear aspects

3. **Wait for answers** before proceeding

4. **Create feature branch** (after questions answered):
   ```bash
   # Ensure we're starting from latest main
   git checkout main
   git pull origin main

   # Create feature branch with descriptive name
   git checkout -b feature/{feature-slug}

   # Create plan directory
   mkdir -p docs/plans/{feature-slug}
   ```

5. **Create the plan file**:
   - Copy template from `docs/templates/WORKFLOW_PLAN.md`
   - Create `docs/plans/{feature-slug}/PLAN.md`
   - Fill in Phase 1 with the gathered requirements

6. **Get Phase 1 approval** before moving to Phase 2

### PHASE 2: ARCHITECTURE DECISION

After Phase 1 approval:

1. **Determine workflow type**:

   | Use pydantic-graph when... | Use Python workflow when... |
   |---------------------------|----------------------------|
   | AI makes decisions on next steps | User controls the flow |
   | Autonomous/background execution | Interactive UI-driven |
   | Complex branching logic | Linear sequential steps |
   | State needs persistence/resume | Short synchronous operation |

2. **Ask the user** which pattern fits better if unclear

3. **Document reasoning** in the plan

4. **Get Phase 2 approval**

### PHASE 3: INVENTORY & GAP ANALYSIS

After Phase 2 approval:

1. **Search existing components**:
   ```
   Services:     viraltracker/services/*.py
   Tools:        viraltracker/agent/agents/*.py
   Pipelines:    viraltracker/pipelines/*.py
   Models:       viraltracker/services/models.py
   ```

2. **Check database schema**:
   - List relevant existing tables
   - Check for naming collisions with proposed tables
   - Identify if existing tables can be extended

3. **Create component list**:
   - What we can reuse
   - What we need to build
   - How new components will be reusable

4. **Get Phase 3 approval**

### PHASE 4: BUILD

After Phase 3 approval:

For each component:
1. Build in correct location following patterns
2. Run syntax check: `python3 -m py_compile <file>`
3. Ensure docstrings are complete (Google format)
4. Ensure type hints are complete
5. Get user review before next component

### PHASE 5: INTEGRATION & TEST

After Phase 4 approval:

1. Update shared files (dependencies.py, __init__.py, etc.)
2. Run local tests
3. Deploy to Railway staging
4. Get user validation on Railway

### PHASE 6: MERGE & CLEANUP

After Phase 5 approval:

1. Final checklist review
2. Create commit with proper message
3. Merge to main
4. Run production migrations if needed
5. Archive plan to docs/archive/

---

## Start Now

Begin by:
1. Reading the required documentation files
2. Analyzing the user's input above
3. Asking clarifying questions for Phase 1

Remember: **ASK FIRST, BUILD SECOND**. No assumptions.
