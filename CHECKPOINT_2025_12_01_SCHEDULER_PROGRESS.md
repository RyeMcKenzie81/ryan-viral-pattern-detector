# Checkpoint: Ad Scheduler Build Progress

**Date:** 2025-12-01
**Branch:** `feature/ad-scheduler`
**Last Commit:** `3d2ddd7`

---

## Build Order Status

| # | Item | Status |
|---|------|--------|
| 1 | Email & Slack Services | ✅ Complete |
| 2 | Export Destination in Ad Creator | ✅ Complete (has bug) |
| 3 | Database Tables | ⏳ Next |
| 4 | Scheduler UI Page | Pending |
| 5 | Background Worker | Pending |
| 6 | Template Usage Tracking | Pending |

---

## Known Bug to Fix

**Issue:** In Ad Creator (`viraltracker/ui/pages/5_🎨_Ad_Creator.py`), the email/Slack input fields don't appear when selecting export destination until form submission fails.

**Root Cause:** The export destination radio buttons and conditional input fields are inside `st.form()`. Streamlit forms don't rerun on widget changes - they only submit all values at once. So the conditional `if export_destination in ["email", "both"]` check doesn't trigger a rerun to show the email field.

**Fix Required:** Move the export destination section OUTSIDE the form (like we did for product/image selection), or use session state to persist values and show fields based on session state.

**Location:** Lines ~661-725 in `viraltracker/ui/pages/5_🎨_Ad_Creator.py`

---

## Files Created/Modified This Session

### New Files
- `viraltracker/services/email_service.py` - EmailService with Resend
- `viraltracker/services/slack_service.py` - SlackService with Webhooks

### Modified Files
- `viraltracker/core/config.py` - Added RESEND_API_KEY, EMAIL_FROM, SLACK_WEBHOOK_URL
- `viraltracker/agent/dependencies.py` - Added email, slack services
- `viraltracker/agent/agents/ad_creation_agent.py` - Added send_ads_email, send_ads_slack tools
- `viraltracker/ui/pages/5_🎨_Ad_Creator.py` - Added export destination UI (needs fix)
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

1. **Fix the export field visibility bug** in Ad Creator
2. **Create database tables** (scheduled_jobs, scheduled_job_runs, product_template_usage)
3. Continue with Scheduler UI, Background Worker, Template Usage Tracking

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
