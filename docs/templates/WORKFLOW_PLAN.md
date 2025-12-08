# Workflow Plan: {FEATURE_NAME}

**Branch**: `feature/{feature-slug}`
**Created**: {DATE}
**Status**: Phase 1 - Intake

> **Branch created with**:
> ```bash
> git checkout main && git pull origin main
> git checkout -b feature/{feature-slug}
> ```

---

## Phase 1: INTAKE

### 1.1 Original Request

> {Paste the original idea or requirement here}

### 1.2 Clarifying Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | What is the desired end result? | |
| 2 | Who/what triggers this? (UI, API, cron, chat) | |
| 3 | What inputs are required? | |
| 4 | What outputs are expected? | |
| 5 | Error cases to handle? | |
| 6 | Should this be chat-routable? | |
| 7 | {Additional questions...} | |

### 1.3 Desired Outcome

**User Story**: As a {user type}, I want to {action} so that {benefit}.

**Success Criteria**:
- [ ] {Criterion 1}
- [ ] {Criterion 2}
- [ ] {Criterion 3}

### 1.4 Phase 1 Approval

- [ ] User confirmed requirements are complete
- [ ] No assumptions made - all questions answered

---

## Phase 2: ARCHITECTURE DECISION

### 2.1 Workflow Type Decision

**Chosen**: [ ] pydantic-graph / [ ] Python workflow

**Reasoning**:

| Question | Answer |
|----------|--------|
| Who decides what happens next - AI or user? | |
| Autonomous or interactive? | |
| Needs pause/resume capability? | |
| Complex branching logic? | |

### 2.2 High-Level Flow

```
Step 1: {description}
    ↓
Step 2: {description}
    ↓
Step 3: {description}
    ↓
Result: {output}
```

### 2.3 Phase 2 Approval

- [ ] User confirmed architecture approach

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components to Reuse

| Component | Type | Location | How We'll Use It |
|-----------|------|----------|------------------|
| | Service | | |
| | Tool | | |
| | Pipeline | | |

### 3.2 Database Evaluation

**Existing Tables to Use**:
| Table | Purpose in This Feature |
|-------|------------------------|
| | |

**Schema Check Completed**:
- [ ] Queried `information_schema.tables` for existing tables
- [ ] Verified no naming collisions for proposed tables
- [ ] Checked if existing tables can be extended instead

**New Tables/Columns Needed**:
| Table/Column | Purpose | Collision Check |
|--------------|---------|-----------------|
| | | ✅ No collision |

### 3.3 New Components to Build

| Component | Type | Purpose | Reusability Notes |
|-----------|------|---------|-------------------|
| | Service | | |
| | Tool | | |
| | Pipeline | | |
| | Migration | | |

### 3.4 Phase 3 Approval

- [ ] User confirmed component list
- [ ] Database impact assessed and approved

---

## Phase 4: BUILD

### 4.1 Build Order

1. [ ] {Component 1} - {type}
2. [ ] {Component 2} - {type}
3. [ ] {Component 3} - {type}

### 4.2 Component Details

#### Component: {Name}

**File**: `viraltracker/{path}/{file}.py`

**Quality Gate**:
- [ ] Syntax check passed
- [ ] Docstrings complete
- [ ] Type hints complete
- [ ] Error handling appropriate
- [ ] No debug code

**User Review**: [ ] Approved / [ ] Changes Requested

---

#### Component: {Name}

**File**: `viraltracker/{path}/{file}.py`

**Quality Gate**:
- [ ] Syntax check passed
- [ ] Docstrings complete
- [ ] Type hints complete
- [ ] Error handling appropriate
- [ ] No debug code

**User Review**: [ ] Approved / [ ] Changes Requested

---

### 4.3 Database Migration

**File**: `sql/{date}_{description}.sql`

- [ ] Uses `IF NOT EXISTS` guards
- [ ] Includes `COMMENT ON` statements
- [ ] Reviewed by user

---

## Phase 5: INTEGRATION & TEST

### 5.1 Shared Files Modified

| File | Change |
|------|--------|
| `dependencies.py` | |
| `__init__.py` | |
| Other: | |

### 5.2 Local Testing

```bash
# Commands run and results:
```

- [ ] All imports work
- [ ] Service instantiation works
- [ ] Basic functionality works

### 5.3 Railway Staging

**Deployment URL**: `https://{branch}.up.railway.app`

**Tests Performed**:
- [ ] {Test 1}: Pass/Fail
- [ ] {Test 2}: Pass/Fail
- [ ] {Test 3}: Pass/Fail

### 5.4 Phase 5 Approval

- [ ] User validated on Railway staging

---

## Phase 6: MERGE & CLEANUP

### 6.1 Final Checklist

- [ ] All syntax checks pass
- [ ] All Railway tests pass
- [ ] Database migrations run successfully
- [ ] Docstrings complete
- [ ] No debug code or unused imports
- [ ] This PLAN.md updated with final state

### 6.2 Commit Message

```
feat: {Title}

- {Change 1}
- {Change 2}
- Database: {migration description if any}

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### 6.3 Merge Commands

```bash
git checkout main
git pull origin main
git merge feature/{feature-slug}
git push origin main

# Production migration (if needed)
psql $PRODUCTION_DATABASE_URL -f sql/{migration}.sql
```

### 6.4 Completion

- [ ] Merged to main
- [ ] Production migration run (if applicable)
- [ ] This plan moved to `docs/archive/`

---

## Questions Log

| Date | Question | Answer |
|------|----------|--------|
| | | |

---

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| {DATE} | 1 | Initial plan created |
| | | |
