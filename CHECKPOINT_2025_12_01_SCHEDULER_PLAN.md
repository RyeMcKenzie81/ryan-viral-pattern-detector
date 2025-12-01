# Checkpoint: Ad Scheduler System Plan

**Date:** 2025-12-01
**Status:** Planning Complete - Ready to Build
**Branch:** Create `feature/ad-scheduler` before starting

---

## Overview

Building a cron/scheduling system for automated ad generation with:
- Scheduled jobs per product
- Multiple templates per run
- Email & Slack export destinations
- Full run history and logging

---

## Build Order

1. **Email & Slack Services** (new services + agent tools)
2. **Export Destination in Ad Creator** (add to existing workflow)
3. **Database Tables** (scheduled_jobs, scheduled_job_runs, product_template_usage)
4. **Scheduler UI Page** (`8_📅_Ad_Scheduler.py`)
5. **Background Worker** (Railway worker process)
6. **Template Usage Tracking** (for "unused templates" feature)

---

## Requirements Summary

### What Gets Scheduled
- Per-product scheduled jobs
- Uses X templates per run (e.g., 10)
- Template source options:
  - "Use X unused templates" (auto-select from pool not yet used for this product)
  - "Use specific existing templates" (manual selection)
  - "Upload new templates" (for this schedule)

### Parameters (same as Ad Creator + extras)
- num_variations (per template)
- content_source (hooks / recreate_template)
- color_mode (original / brand)
- image_selection_mode (auto / manual)
- export_destination (none / email / slack) **NEW**
- template_count (how many templates per run)

### Scheduling Options
- **Recurring:** Daily, Weekly (pick day), Monthly (1st), with time (PST)
- **One-time:** Specific date/time
- **Run limits:** Optional max runs (e.g., 4), then mark "completed"
- **All times in PST**

### Execution
- Sequential ad_runs (one template at a time, not async)
- 10 templates = 10 separate ad_runs
- Runs on Railway background worker

### UI Views (Streamlit page: `8_📅_Ad_Scheduler.py`)
1. **Schedule List** - Filterable by brand/product, shows next run, status
2. **Create/Edit Schedule** - Form with all parameters
3. **Schedule Detail** - Config summary, run history, click to see ad_runs

### Run History
- Show generated ads (like Ad History)
- Show logs
- Show errors if failed

---

## Database Schema

### Table: `scheduled_jobs`
```sql
CREATE TABLE scheduled_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id),
    brand_id UUID NOT NULL,  -- Denormalized for filtering
    name TEXT NOT NULL,

    -- Schedule configuration
    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('one_time', 'recurring')),
    cron_expression TEXT,  -- For recurring (e.g., "0 9 * * 1" = Mondays 9am PST)
    scheduled_at TIMESTAMP WITH TIME ZONE,  -- For one-time
    next_run_at TIMESTAMP WITH TIME ZONE,

    -- Run limits
    max_runs INT,  -- NULL = unlimited
    runs_completed INT DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed')),

    -- Template configuration
    template_mode TEXT NOT NULL CHECK (template_mode IN ('unused', 'specific', 'uploaded')),
    template_count INT,  -- If mode='unused'
    template_ids TEXT[],  -- If mode='specific' or 'uploaded'

    -- Ad creation parameters (JSONB)
    parameters JSONB NOT NULL,
    -- {
    --   "num_variations": 5,
    --   "content_source": "hooks",
    --   "color_mode": "original",
    --   "image_selection_mode": "auto",
    --   "export_destination": "slack"
    -- }

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Future: tenant_id UUID for multi-tenancy
    tenant_id UUID
);
```

### Table: `scheduled_job_runs`
```sql
CREATE TABLE scheduled_job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_job_id UUID NOT NULL REFERENCES scheduled_jobs(id),

    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,

    -- Links to created ad_runs
    ad_run_ids UUID[],
    templates_used TEXT[],

    -- Execution logs
    logs TEXT,

    tenant_id UUID
);
```

### Table: `product_template_usage`
```sql
CREATE TABLE product_template_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id),
    template_storage_name TEXT NOT NULL,

    used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ad_run_id UUID REFERENCES ad_runs(id),

    tenant_id UUID,

    UNIQUE(product_id, template_storage_name)
);
```

---

## New Services

### EmailService
- Send emails with attachments (generated ad images)
- Support HTML templates
- Use SendGrid, AWS SES, or similar

### SlackService
- Post to Slack channels
- Upload images
- Support rich formatting (blocks)

Both services should be:
- Standalone services in `viraltracker/services/`
- Also registered as agent tools (can be called via natural language)
- Used by ad creation workflow for export

---

## Files to Create/Modify

### New Files
| File | Description |
|------|-------------|
| `viraltracker/services/email_service.py` | EmailService class |
| `viraltracker/services/slack_service.py` | SlackService class |
| `viraltracker/ui/pages/8_📅_Ad_Scheduler.py` | Scheduler UI |
| `viraltracker/worker/scheduler_worker.py` | Background worker |
| `sql/create_scheduler_tables.sql` | Database migration |

### Modified Files
| File | Changes |
|------|---------|
| `viraltracker/agent/dependencies.py` | Add email, slack deps |
| `viraltracker/agent/agents/ad_creation_agent.py` | Add email/slack tools, export_destination param |
| `viraltracker/ui/pages/5_🎨_Ad_Creator.py` | Add export destination selector |

---

## Pydantic AI Patterns to Follow

From `docs/CLAUDE_CODE_GUIDE.md`:

1. **`@agent.tool()` decorator** with `ToolMetadata`
2. **Google-style docstrings** (sent to LLM)
3. **Structured Pydantic models** for returns
4. **Type hints** on all parameters
5. **Error handling + logging**
6. **Access deps via `ctx.deps`**

### Example Tool Pattern
```python
@ad_creation_agent.tool(
    metadata=ToolMetadata(
        category='Export',
        platform='All',
        rate_limit='10/minute',
        use_cases=['Send ads via email', 'Export results to email'],
        examples=['Email the generated ads to marketing@company.com']
    )
)
async def send_email(
    ctx: RunContext[AgentDependencies],
    to_email: str,
    subject: str,
    body: str,
    attachment_paths: List[str] = None
) -> EmailResult:
    """
    Send an email with optional attachments.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        to_email: Recipient email address
        subject: Email subject line
        body: Email body (HTML supported)
        attachment_paths: Optional list of storage paths to attach

    Returns:
        EmailResult with send status and message ID
    """
    return await ctx.deps.email.send(...)
```

---

## Multi-Tenancy Prep

All new tables include `tenant_id` column for future multi-tenancy:
- Currently nullable (single tenant)
- When multi-tenant: add RLS policies, make non-null
- Filter all queries by tenant_id

---

## UI Schedule Presets (PST)

Simple frequency options:
- Daily at [time]
- Weekly on [Monday-Sunday] at [time]
- Monthly on 1st at [time]
- One-time: [date picker] at [time]

Time picker: Hour selector (9am, 10am, etc.) in PST

---

## Background Worker Architecture

```
Railway Worker Process
│
├── Polls scheduled_jobs every minute
│   └── WHERE next_run_at <= NOW() AND status = 'active'
│
├── For each due job:
│   ├── Create scheduled_job_run (status='running')
│   ├── Get templates (unused, specific, or uploaded)
│   ├── For each template (sequential):
│   │   ├── Call complete_ad_workflow()
│   │   ├── Record ad_run_id
│   │   ├── Track template usage
│   │   └── Handle export (email/slack)
│   ├── Update scheduled_job_run (status='completed')
│   ├── Increment runs_completed
│   ├── Calculate next_run_at
│   └── If max_runs reached: status='completed'
│
└── Error handling:
    ├── Log errors to scheduled_job_run
    ├── Set status='failed'
    └── Continue to next job
```

---

## Today's Session Accomplishments (Before This Plan)

1. Fixed "Use Existing Template" feature
2. Deduplicated templates (100 → 30 unique)
3. Added thumbnail grid for template selection
4. Added pagination ("Load More")
5. Removed legacy image columns from products table

---

## Next Steps

1. Create branch: `git checkout -b feature/ad-scheduler`
2. Build EmailService
3. Build SlackService
4. Add as agent tools
5. Add export destination to Ad Creator
6. Create database tables
7. Build Scheduler UI
8. Build background worker
9. Test end-to-end

---

## Important Notes

- Keep scheduler parameters in sync with Ad Creator
- Follow pydantic.ai best practices for eventual graph migration
- All times in PST
- Sequential execution (not async) to avoid API overload
