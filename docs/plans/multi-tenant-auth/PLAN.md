# Multi-Tenant Auth & Usage Tracking Plan

## Overview

Transform ViralTracker from single-tenant to multi-tenant with:
- Organization-based data isolation
- User activity and token usage tracking
- Feature access control per organization
- Usage limits and rate limiting

## Completed

### Phase 1: Supabase Auth Foundation ✅
- Replaced password auth with Supabase email/password
- Added `get_anon_client()` for RLS-enforced operations
- Commit: `dd6055a`

### Phase 2: Session Persistence ✅
- Cookie-based session storage via `streamlit-cookies-controller`
- Sessions survive page refresh and browser close
- Auto-refresh of expired tokens

---

## Remaining Phases

### Phase 3: Organization Schema
**Goal**: Create database structure for organizations

**Tables**:
```sql
organizations (
    id UUID PRIMARY KEY,
    name TEXT,
    slug TEXT UNIQUE,
    owner_user_id UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ
)

user_organizations (
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID REFERENCES organizations(id),
    role TEXT CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ,
    UNIQUE(user_id, organization_id)
)
```

**Work**:
- Create migration for tables
- Add `organization_id` to `brands` table
- Backfill existing brands to a "Default" organization
- Update Python code to filter by org

---

### Phase 4: Usage Tracking
**Goal**: Track all AI/API usage for billing and limits

See: `PHASE_4_USAGE_TRACKING.md`

---

### Phase 5: Python Org Filtering
**Goal**: Filter data by organization in application code

**Work**:
- Add org context to session state
- Update `get_brands()` and similar functions to filter by org
- Add org selector to sidebar (for users with multiple orgs)

---

### Phase 6: Feature Access Control
**Goal**: Control which tools each organization can access

**Tables**:
```sql
org_features (
    organization_id UUID REFERENCES organizations(id),
    feature_key TEXT,  -- 'veo_avatars', 'ad_scheduler', etc.
    enabled BOOLEAN DEFAULT false,
    config JSONB,      -- Feature-specific settings
    PRIMARY KEY (organization_id, feature_key)
)
```

**Work**:
- Create migration
- Add `has_feature(org_id, feature_key)` helper
- Add feature checks to relevant pages
- Create admin UI for managing features

---

### Phase 7: Usage Limits & Enforcement
**Goal**: Rate limit usage per organization/user

**Tables**:
```sql
usage_limits (
    id UUID PRIMARY KEY,
    organization_id UUID REFERENCES organizations(id),
    user_id UUID,  -- NULL = org-wide limit
    limit_type TEXT,  -- 'monthly_tokens', 'monthly_cost', 'daily_ads'
    limit_value NUMERIC,
    period TEXT,  -- 'daily', 'monthly'
    created_at TIMESTAMPTZ
)
```

**Work**:
- Create migration
- Add limit checking before expensive operations
- Add UI for viewing usage vs limits
- Add alerts when approaching limits

---

### Phase 8: RLS Policies (Optional, Future)
**Goal**: Database-level security as defense-in-depth

**Work**:
- Add RLS policies to `brands`, `organizations`, etc.
- Switch UI to use anon key with user JWT
- Test extensively before enabling

**Note**: This is optional. Python filtering + service key is secure as long as app code is correct. RLS adds defense-in-depth.

---

## Architecture Decisions

### Service Key vs Anon Key

| Client | Key | RLS | Use Case |
|--------|-----|-----|----------|
| `get_supabase_client()` | Service | Bypassed | Workers, agents, backend |
| `get_anon_client()` | Anon | Enforced | Auth operations |

Currently, UI uses service key. This means:
- RLS doesn't affect UI queries
- Org filtering must be done in Python
- This is intentional for now (safer, easier to debug)

### Python Filtering vs RLS

Both will coexist:
- **Python**: Application logic, UI behavior, org selector
- **RLS**: Security safety net (Phase 8, optional)

---

## File Locations

```
docs/plans/multi-tenant-auth/
├── PLAN.md                      # This file
├── PHASE_4_USAGE_TRACKING.md    # Detailed Phase 4 plan
└── CHECKPOINT_*.md              # Progress checkpoints
```
