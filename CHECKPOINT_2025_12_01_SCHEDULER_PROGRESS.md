# Checkpoint: Ad Scheduler Build Progress

**Date:** 2025-12-01
**Branch:** `feature/ad-scheduler`
**Last Commit:** `5beb359`

---

## Build Order Status

| # | Item | Status |
|---|------|--------|
| 1 | Email & Slack Services | ✅ Complete |
| 2 | Export Destination in Ad Creator | ✅ Complete |
| 3 | Database Tables | ✅ Complete |
| 4 | Scheduler UI Page | ✅ Complete |
| 5 | Background Worker | ✅ Complete |
| 6 | Template Usage Tracking | ✅ Complete (in worker) |

---

## Completed This Session

### Bug Fix: Export Destination Fields Not Showing

**Issue:** Email/Slack input fields didn't appear when selecting export destination until form submission failed.

**Solution:** Moved export destination section (Section 4) OUTSIDE the `st.form()`, using session state for persistence. The section now shows conditional fields (email input, Slack webhook) immediately when the user selects email/Slack export.

**Changes Made:**
- Moved export destination radio + conditional inputs to lines 677-749 (outside form)
- Added unique widget keys to prevent conflicts
- Updated section numbering (Content Source is now 5, Variations is 6, Color Scheme is 7)
- Removed duplicate export section that was inside the form

### Database Tables Created

Created `sql/create_scheduler_tables.sql` with:
- `scheduled_jobs` - Job configuration and scheduling
- `scheduled_job_runs` - Execution history and logs
- `product_template_usage` - Track which templates used per product
- Indexes for efficient querying
- Helper views (`v_active_scheduled_jobs`, `v_recent_job_runs`)
- `updated_at` trigger for scheduled_jobs

### Scheduler UI Page Created

Created `viraltracker/ui/pages/8_📅_Ad_Scheduler.py` with three views:

**1. Schedule List View:**
- Filterable by brand, product, status
- Shows job cards with schedule info, run counts, next run time
- Quick actions to view details

**2. Create/Edit Schedule View:**
- Product selection
- Job name
- Schedule configuration (recurring: daily/weekly/monthly or one-time)
- Run limits (optional max runs)
- Template mode: "unused" (auto-select) or "specific" (manual selection)
- Ad creation parameters (variations, content source, color mode, image mode)
- Export destination (none/email/slack/both)

**3. Schedule Detail View:**
- Full job configuration display
- Action buttons: Pause/Resume, Edit, Delete
- Run history with status, timestamps, logs

### Background Worker Created

Created `viraltracker/worker/scheduler_worker.py`:

**Features:**
- Polls `scheduled_jobs` table every 60 seconds for due jobs
- Executes jobs sequentially (one template at a time)
- Creates `scheduled_job_runs` records with full logging
- Template selection: "unused" mode auto-selects templates not used for product
- Records template usage in `product_template_usage` table
- Handles email/Slack exports after each ad run
- Calculates and updates `next_run_at` for recurring jobs
- Marks jobs as "completed" when max_runs reached or one-time job finishes
- Graceful shutdown on SIGTERM/SIGINT signals

**Run with:**
```bash
python -m viraltracker.worker.scheduler_worker
```

---

## Files Created/Modified This Session

### New Files
- `viraltracker/services/email_service.py` - EmailService with Resend
- `viraltracker/services/slack_service.py` - SlackService with Webhooks
- `sql/create_scheduler_tables.sql` - Scheduler database tables
- `viraltracker/ui/pages/8_📅_Ad_Scheduler.py` - Scheduler UI page
- `viraltracker/worker/__init__.py` - Worker package
- `viraltracker/worker/scheduler_worker.py` - Background worker for scheduled jobs

### Modified Files
- `viraltracker/core/config.py` - Added RESEND_API_KEY, EMAIL_FROM, SLACK_WEBHOOK_URL
- `viraltracker/agent/dependencies.py` - Added email, slack services
- `viraltracker/agent/agents/ad_creation_agent.py` - Added send_ads_email, send_ads_slack tools
- `viraltracker/ui/pages/5_🎨_Ad_Creator.py` - Export destination UI (fixed conditional fields bug)
- `.env.example` - Added email/Slack config
- `requirements.txt` - Added resend==2.19.0

---

## Environment Variables Configured

```bash
RESEND_API_KEY=<configured in .env>
EMAIL_FROM=hello@ryanmckenzie.com
SLACK_WEBHOOK_URL=<configured in .env>
```

---

## Next Steps

1. **Deploy worker to Railway** - Add as separate process in railway.json or Procfile
2. **Test end-to-end** - Create a schedule, wait for execution, verify results
3. **Optional: Track template usage in Ad Creator** - So manual runs also mark templates as "used"

---

## Reference: Database Schema (from plan)

```sql
-- scheduled_jobs table
CREATE TABLE scheduled_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id),
    brand_id UUID NOT NULL,
    name TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('one_time', 'recurring')),
    cron_expression TEXT,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    max_runs INT,
    runs_completed INT DEFAULT 0,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed')),
    template_mode TEXT NOT NULL CHECK (template_mode IN ('unused', 'specific', 'uploaded')),
    template_count INT,
    template_ids TEXT[],
    parameters JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    tenant_id UUID
);

-- scheduled_job_runs table
CREATE TABLE scheduled_job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_job_id UUID NOT NULL REFERENCES scheduled_jobs(id),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,
    ad_run_ids UUID[],
    templates_used TEXT[],
    logs TEXT,
    tenant_id UUID
);

-- product_template_usage table
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
