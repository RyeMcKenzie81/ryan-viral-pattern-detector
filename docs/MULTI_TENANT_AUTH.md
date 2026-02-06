# Multi-Tenant Authentication & Authorization

Comprehensive reference for ViralTracker's multi-tenant system. Covers authentication, organization management, data isolation, feature flags, usage tracking, and usage limits.

**Status**: Phases 1-7 complete. Phase 8 (Row-Level Security) planned but not urgent.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Database Schema](#3-database-schema)
4. [Authentication](#4-authentication)
5. [Organizations & Membership](#5-organizations--membership)
6. [Superuser System](#6-superuser-system)
7. [Data Isolation](#7-data-isolation)
8. [Feature Flag System](#8-feature-flag-system)
9. [Usage Tracking](#9-usage-tracking)
10. [Usage Limits & Enforcement](#10-usage-limits--enforcement)
11. [Admin Page](#11-admin-page)
12. [Supabase Client Architecture](#12-supabase-client-architecture)
13. [Session State Reference](#13-session-state-reference)
14. [Data Flow Diagrams](#14-data-flow-diagrams)
15. [Key Files Reference](#15-key-files-reference)
16. [Phase 8: RLS (Planned)](#16-phase-8-rls-planned)
17. [Known Technical Debt](#17-known-technical-debt)

---

## 1. Overview

### What Multi-Tenancy Means in ViralTracker

ViralTracker is a multi-tenant SaaS application where each **organization** is a tenant. Organizations own brands, have member users with roles, and are isolated from one another in data access, feature availability, and usage billing.

### Implementation Timeline

| Phase | Description | Status |
|-------|-------------|--------|
| 1-2 | Supabase Auth + Cookie Sessions | Complete |
| 3 | Organization Schema + Membership | Complete |
| 4 | Usage Tracking (token_usage) | Complete |
| 5 | Python Org Filtering + Superuser | Complete |
| 6 | Feature Access Control (org_features) | Complete |
| 7 | Usage Limits & Enforcement + Admin Page | Complete |
| 7+ | Admin Hardening (stale state, emails, confirmations) | Complete |
| 8 | Row-Level Security Policies | Planned (optional) |

### Phase Summary

- **Phases 1-2**: Replaced plaintext passwords with Supabase email/password auth. Added cookie-based session persistence with auto token refresh.
- **Phase 3**: Created `organizations` and `user_organizations` tables. Linked brands to orgs. Added auto-org-creation trigger on signup.
- **Phase 4**: Created `token_usage` table. Built `UsageTracker` service with cost calculation. Wired into all AI/API services.
- **Phase 5**: Added `user_profiles` with superuser flag. Updated queries to filter by `organization_id`. Built org selector with "All Organizations" mode.
- **Phase 6**: Created `org_features` table. Built two-tier feature flag system (sections=opt-out, pages=opt-in). Integrated into nav builder.
- **Phase 7**: Created `usage_limits` table. Built enforcement with fail-open pattern. Built Admin page with 4 tabs.
- **Phase 7+**: Fixed stale widget state on org switch, added email display, display name editing, owner role confirmation.

---

## 2. Architecture

Multi-tenancy follows the project's 3-layer architecture:

```
Agent Layer (PydanticAI)
  └─ AgentDependencies carries user_id, organization_id, usage_tracker, features, usage_limits

Service Layer
  └─ OrganizationService, FeatureService, UsageTracker, UsageLimitService
  └─ All query methods accept and filter by organization_id

Interface Layer (Streamlit UI)
  └─ auth.py handles login/session
  └─ utils.py provides org selector, brand filtering, feature checks
  └─ nav.py builds sidebar based on feature flags
  └─ Admin page manages all tenant settings
```

### How a Request Flows

```
User opens page
  → require_auth() checks Supabase session
  → app.py renders render_organization_selector() ONCE in sidebar
      (persisted to browser cookie; restored on refresh)
  → render_brand_selector() reads org via get_current_organization_id()
  → nav.py gates sidebar pages by org's feature flags
  → Service calls include organization_id for data isolation
  → AI/API calls tracked to organization via UsageTracker
  → Limits enforced before expensive operations via UsageLimitService
```

---

## 3. Database Schema

### organizations

Created by `migrations/2026-01-23_organizations.sql`. Represents a tenant.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, default `gen_random_uuid()` | Organization ID |
| `name` | TEXT | NOT NULL | Display name |
| `slug` | TEXT | UNIQUE | URL-friendly identifier |
| `owner_user_id` | UUID | FK → `auth.users(id)` | Primary owner |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Creation timestamp |

**Indexes**: `idx_brands_org` on `brands.organization_id`

### user_organizations

Many-to-many membership table.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Row ID |
| `user_id` | UUID | NOT NULL, FK → `auth.users` ON DELETE CASCADE | User |
| `organization_id` | UUID | NOT NULL, FK → `organizations` ON DELETE CASCADE | Organization |
| `role` | TEXT | NOT NULL, CHECK IN (`owner`, `admin`, `member`, `viewer`) | Role |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Join timestamp |

**Constraints**: `UNIQUE(user_id, organization_id)`
**Indexes**: `idx_user_orgs_user` on `user_id`, `idx_user_orgs_org` on `organization_id`

### user_profiles

Created by `migrations/2026-01-23_user_profiles.sql`. Extended user data.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `user_id` | UUID | PK, FK → `auth.users` ON DELETE CASCADE | User |
| `is_superuser` | BOOLEAN | default `false` | Grants "All Organizations" mode |
| `display_name` | TEXT | — | Optional display name |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Created |
| `updated_at` | TIMESTAMPTZ | default `NOW()` | Updated |

**Indexes**: `idx_user_profiles_superuser` WHERE `is_superuser = true`

### org_features

Created by `migrations/2026-01-23_org_features.sql`. Feature flags per org.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `organization_id` | UUID | PK part 1, FK → `organizations` ON DELETE CASCADE | Organization |
| `feature_key` | TEXT | PK part 2 | Feature identifier |
| `enabled` | BOOLEAN | default `false` | Whether enabled |
| `config` | JSONB | default `'{}'` | Optional config |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Created |
| `updated_at` | TIMESTAMPTZ | default `NOW()` | Updated |

**Indexes**: `idx_org_features_org` on `organization_id`

### token_usage

Created by `migrations/2026-01-24_token_usage.sql`. Tracks all AI/API usage.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Record ID |
| `user_id` | UUID | FK → `auth.users` | Who triggered it |
| `organization_id` | UUID | NOT NULL, FK → `organizations` | Which org to bill |
| `provider` | TEXT | NOT NULL | `anthropic`, `openai`, `google`, `elevenlabs` |
| `model` | TEXT | NOT NULL | `claude-opus-4-5`, `gpt-4o`, `gemini-2.0-flash`, etc. |
| `tool_name` | TEXT | — | `ad_creator`, `gemini_service`, etc. |
| `operation` | TEXT | — | `generate_image`, `analyze_text`, etc. |
| `input_tokens` | INT | default 0 | Input token count |
| `output_tokens` | INT | default 0 | Output token count |
| `total_tokens` | INT | GENERATED ALWAYS AS `input + output` | Total tokens |
| `units` | NUMERIC | — | Non-token units (images, seconds) |
| `unit_type` | TEXT | — | `images`, `video_seconds`, `characters` |
| `cost_usd` | NUMERIC(10,6) | — | Calculated cost in USD |
| `request_metadata` | JSONB | — | Additional context (brand_id, ad_id) |
| `duration_ms` | INT | — | API call duration |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Timestamp |

**Indexes**:
- `idx_token_usage_org_created` on `(organization_id, created_at DESC)`
- `idx_token_usage_user_created` on `(user_id, created_at DESC)`
- `idx_token_usage_tool` on `(tool_name, created_at DESC)`
- `idx_token_usage_provider` on `(provider, created_at DESC)`

**Database Function**: `sum_token_usage(p_org_id, p_column, p_start_date)` — sums `cost_usd`, `total_tokens`, `input_tokens`, or `output_tokens` for a given org and time range.

### usage_limits

Created by `migrations/2026-01-27_usage_limits.sql`. Per-org rate limits.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Row ID |
| `organization_id` | UUID | NOT NULL, FK → `organizations` ON DELETE CASCADE | Organization |
| `limit_type` | TEXT | NOT NULL, CHECK IN (`monthly_tokens`, `monthly_cost`, `daily_ads`, `daily_requests`) | Limit type |
| `limit_value` | NUMERIC | NOT NULL | Maximum allowed value |
| `period` | TEXT | default `monthly`, CHECK IN (`daily`, `monthly`) | Limit period |
| `alert_threshold` | NUMERIC | default `0.8` | Warning at this percentage (0-1) |
| `enabled` | BOOLEAN | default `true` | Whether enforced |
| `created_at` | TIMESTAMPTZ | default `NOW()` | Created |
| `updated_at` | TIMESTAMPTZ | default `NOW()` | Updated |

**Constraints**: `UNIQUE(organization_id, limit_type)`
**Indexes**: `idx_usage_limits_org` on `organization_id`

### brands (modified)

The existing `brands` table was modified in Phase 3:

```sql
ALTER TABLE brands ADD COLUMN organization_id UUID NOT NULL REFERENCES organizations(id);
CREATE INDEX idx_brands_org ON brands(organization_id);
```

All brands belong to exactly one organization.

---

## 4. Authentication

### File: `viraltracker/ui/auth.py`

Provides Supabase-based email/password authentication with persistent cookie sessions.

### Session Flow

1. User submits email + password
2. `sign_in()` calls Supabase auth API (via anon client)
3. On success, stores user + session in `st.session_state`
4. Session data (access_token, refresh_token, expires_at) saved to browser cookie
5. On page reload, cookie is read and session is restored
6. Token auto-refreshes when expired using refresh_token

### Key Functions

| Function | Purpose |
|----------|---------|
| `require_auth(public=False)` | Gate a page — shows login form if not authenticated |
| `sign_in(email, password)` | Authenticate, returns `(success, error)` |
| `sign_up(email, password)` | Register new user (email verification may apply) |
| `sign_out()` | Clear session state and cookies |
| `is_authenticated()` | Check auth status without showing login form |
| `get_current_user()` | Get authenticated user object |
| `get_current_user_id()` | Get user UUID string |

### Cookie Configuration

| Setting | Value |
|---------|-------|
| Cookie name | `viraltracker_session` |
| Expiry | 30 days |
| Contents | `access_token`, `refresh_token`, `expires_at` |

### Session State Keys

| Key | Type | Purpose |
|-----|------|---------|
| `_supabase_user` | dict | Current Supabase user object |
| `_supabase_session` | dict | Auth tokens (access, refresh, expiry) |
| `_authenticated` | bool | Whether user is authenticated |

### Auto-Organization Creation

A database trigger (`on_auth_user_created`) fires on new user signup:

```sql
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    -- Create personal organization: "{email}'s Workspace"
    INSERT INTO organizations (name, owner_user_id) VALUES (NEW.email || '''s Workspace', NEW.id)
    RETURNING id INTO new_org_id;

    -- Add user as owner
    INSERT INTO user_organizations (user_id, organization_id, role) VALUES (NEW.id, new_org_id, 'owner');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

---

## 5. Organizations & Membership

### File: `viraltracker/services/organization_service.py`

### Roles

| Role | Access Level |
|------|-------------|
| `owner` | Full control. Can demote anyone. One owner per org (transferable). |
| `admin` | Management privileges. Can manage members and features. |
| `member` | Standard user. Can use enabled features. |
| `viewer` | Read-only. Can view data but not create/modify. |

### Key Methods

```python
class OrganizationService:
    # Lookups
    get_user_organizations(user_id) -> List[dict]  # All orgs user belongs to
    get_organization(org_id) -> Optional[dict]      # Single org details
    get_user_role(user_id, org_id) -> Optional[str] # Role in specific org

    # Management
    create_organization(name, owner_id) -> dict     # Creates org + owner membership
    add_member(org_id, user_id, role="member")       # Add user to org
    remove_member(org_id, user_id) -> bool           # Remove user from org
    update_member_role(org_id, user_id, new_role)    # Change role

    # Admin functions
    get_all_organizations() -> List[dict]            # Superuser: all orgs
    get_org_members(org_id) -> List[dict]             # Members with email + display_name
    update_display_name(user_id, display_name)        # Edit display name
    get_member_count(org_id) -> int                   # Count members
```

### Auto-Creation on Signup

When a user signs up via Supabase Auth, the `handle_new_user()` trigger:
1. Creates a personal organization named `"{email}'s Workspace"`
2. Adds the user as `owner` of that organization

This means every user always has at least one organization.

---

## 6. Superuser System

### How It Works

The `user_profiles.is_superuser` flag grants elevated access:

1. **Organization selector** shows "All Organizations" as an option
2. **Feature checks** return `True` for all features when org is `"all"`
3. **Data queries** skip org filtering when org is `"all"` (see all tenants' data)
4. **Usage tracking** skips recording when org is `"all"` (no billing for superuser actions)
5. **Usage limits** skip enforcement when org is `"all"`

### Implementation

**Check superuser** (`viraltracker/ui/utils.py`):
```python
def is_superuser(user_id: str) -> bool:
    result = get_supabase_client().table("user_profiles").select(
        "is_superuser"
    ).eq("user_id", user_id).single().execute()
    return result.data.get("is_superuser", False) if result.data else False
```

**Org selector with superuser mode** (`viraltracker/ui/utils.py`):
```python
def render_organization_selector() -> Optional[str]:
    # Rendered ONCE in app.py — individual pages use get_current_organization_id()
    # Uses hardcoded widget key "_workspace_selectbox" (single source of truth)
    # on_change callback updates session state + saves to cookie before rerun
    # Superusers see: {"All Organizations": "all", ...actual_orgs}
    # Returns "all" for superuser mode
```

### Superuser Handling Across Services

| Service | Behavior when `org_id == "all"` |
|---------|--------------------------------|
| `FeatureService.has_feature()` | Returns `True` (all features enabled) |
| `UsageTracker.track()` | Skips tracking (no billing) |
| `UsageLimitService.enforce_limit()` | Returns silently (no enforcement) |
| `get_brands()` | Returns all brands across all orgs |
| `nav.py` | Shows all pages in sidebar |

---

## 7. Data Isolation

### Pattern

All org-scoped queries follow this pattern:

```python
def get_brands(organization_id: Optional[str] = None):
    if organization_id is None:
        organization_id = get_current_organization_id()

    query = db.table("brands").select("id, name, organization_id")

    if organization_id and organization_id != "all":
        query = query.eq("organization_id", organization_id)

    return query.order("name").execute().data or []
```

### Rules

| `organization_id` value | Behavior |
|--------------------------|----------|
| `None` | Uses current session org (from `get_current_organization_id()`) |
| `"all"` | Returns all data across all orgs (superuser mode) |
| `"{uuid}"` | Filters to that specific organization |

### Where Isolation Is Applied

- **Brands**: Filtered by `organization_id` on the `brands` table
- **Features**: Checked per org via `org_features` table
- **Usage**: Tagged with `organization_id` on every `token_usage` record
- **Limits**: Configured and enforced per `organization_id`
- **Admin views**: Scoped to current org (or all for superusers)

### Current Enforcement Layer

Data isolation is enforced at the **Python service layer**. Every service method that queries tenant data accepts `organization_id` and filters accordingly. There are no database-level RLS policies yet (see [Phase 8](#16-phase-8-rls-planned)).

---

## 8. Feature Flag System

### Two-Tier Model

| Type | Default | Behavior | Example |
|------|---------|----------|---------|
| **Section keys** (`SECTION_*`) | Visible (opt-out) | Disabling hides all base pages in that section | `section_ads` |
| **Page keys** (everything else) | Hidden (opt-in) | Must be explicitly enabled to appear | `veo_avatars` |

### File: `viraltracker/services/feature_service.py`

### FeatureKey Constants

**Section Keys** (opt-out):
- `SECTION_BRANDS`, `SECTION_COMPETITORS`, `SECTION_ADS`, `SECTION_CONTENT`, `SECTION_SYSTEM`

**Page Keys** (opt-in):

| Section | Keys |
|---------|------|
| Brands | `BRAND_MANAGER`, `PERSONAS`, `URL_MAPPING`, `BRAND_RESEARCH` |
| Competitors | `COMPETITORS`, `COMPETITIVE_ANALYSIS`, `COMPETITOR_RESEARCH`, `REDDIT_RESEARCH` |
| Ads | `AD_CREATOR`, `AD_HISTORY`, `AD_PERFORMANCE`, `AD_LIBRARY`, `AD_SCHEDULER`, `AD_PLANNING`, `BELIEF_CANVAS`, `RESEARCH_INSIGHTS`, `PLAN_LIST`, `PLAN_EXECUTOR`, `TEMPLATE_QUEUE`, `TEMPLATE_EVALUATION`, `TEMPLATE_RECOMMENDATIONS`, `PUBLIC_GALLERY` |
| Content | `CONTENT_PIPELINE`, `COMIC_VIDEO`, `COMIC_JSON_GENERATOR`, `EDITOR_HANDOFF`, `AUDIO_PRODUCTION`, `KNOWLEDGE_BASE`, `VEO_AVATARS`, `SORA_MVP` |
| System | `AGENT_CATALOG`, `SCHEDULED_TASKS`, `TOOLS_CATALOG`, `SERVICES_CATALOG`, `DATABASE_BROWSER`, `PLATFORM_SETTINGS`, `HISTORY`, `CLIENT_ONBOARDING`, `PIPELINE_VISUALIZER`, `USAGE_DASHBOARD`, `ADMIN` |

### FeatureService Methods

```python
class FeatureService:
    has_feature(org_id, feature_key) -> bool  # Check if enabled. "all" -> True.
    get_org_features(org_id) -> List[dict]    # All flags for org
    set_feature(org_id, key, enabled, config=None)  # Upsert flag
    enable_feature(org_id, key)                # Shortcut to enable
    disable_feature(org_id, key)               # Shortcut to disable
    enable_all_features(org_id)                # Enable all (for onboarding)
    clear_cache()                              # Clear in-memory cache
```

**Caching**: In-memory dict with key format `{org_id}:{feature_key}`. Cleared on writes.

### Navigation Gating

**File**: `viraltracker/ui/nav.py`

```python
def build_navigation_pages() -> Dict[str, List[st.Page]]:
    org_id = get_current_organization_id() or _auto_init_organization()
    features = _get_org_features(org_id)

    def has_section(key): return features.get(key, True)    # opt-out
    def has_page(key):    return features.get(key, False)   # opt-in

    def visible(section_key, page_key=None):
        if page_key:
            return has_page(page_key)    # Opt-in: check page key only
        return has_section(section_key)  # Base: follows section

    # Example usage:
    if visible("section_ads", "ad_creator"):  # checks ad_creator flag only
        ads.append(st.Page("pages/21_..."))
```

The `_get_org_features_cached()` function uses `@st.cache_data(ttl=300)` (5-minute cache) for performance.

### Page-Level Guard

For pages that need to enforce feature access even if directly navigated to:

```python
from viraltracker.ui.utils import require_feature
from viraltracker.services.feature_service import FeatureKey

require_feature(FeatureKey.VEO_AVATARS, "Veo Avatars")
# Stops page execution if feature is disabled for current org
```

---

## 9. Usage Tracking

### File: `viraltracker/services/usage_tracker.py`

### Data Models

```python
@dataclass
class UsageRecord:
    provider: str                      # 'anthropic', 'openai', 'google', 'elevenlabs'
    model: str                         # 'claude-opus-4-5', 'gpt-4o', etc.
    tool_name: Optional[str]           # 'ad_creator', 'gemini_service'
    operation: Optional[str]           # 'generate_image', 'analyze_text'
    input_tokens: int = 0
    output_tokens: int = 0
    units: Optional[float] = None      # For non-token APIs (images, seconds)
    unit_type: Optional[str] = None    # 'images', 'video_seconds', 'characters'
    cost_usd: Optional[Decimal] = None # Auto-calculated if not provided
    request_metadata: Optional[dict] = None
    duration_ms: Optional[int] = None

@dataclass
class UsageSummary:
    organization_id: str
    period_start: datetime
    period_end: datetime
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal
    by_provider: dict   # {provider: {tokens, cost}}
    by_tool: dict       # {tool_name: {tokens, cost}}
```

### Key Methods

```python
class UsageTracker:
    track(user_id, organization_id, record: UsageRecord) -> None
        # Fire-and-forget. Skips if org_id=="all".
        # Auto-calculates cost if not provided.
        # Logs warnings on failure (non-fatal).

    get_usage_summary(org_id, start_date, end_date) -> UsageSummary
    get_current_month_usage(org_id) -> UsageSummary
    get_recent_usage(org_id, limit=50) -> List[dict]
```

### Cost Calculation

**Token-based** (LLM calls):
```
cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
```

**Unit-based** (non-token APIs):
```
cost = units * unit_rate
```

Rates configured in `viraltracker/core/config.py` via `Config.get_token_cost()` and `Config.get_unit_cost()`.

### Context Propagation

Usage tracking context is set in `AgentDependencies.create()`:

```python
# viraltracker/agent/dependencies.py
if organization_id:
    usage_tracker = UsageTracker(supabase_client)
    gemini.set_tracking_context(usage_tracker, user_id, organization_id)
```

Services that have tracking wired in:
- `GeminiService` (analyze_hook, generate_image, analyze_image, analyze_text)
- `VeoService` (generate_video)
- `ScriptService` (generate_script, review_script, revise_script)
- `ComicService` (condense_to_comic, evaluate_comic_script, revise_comic)
- `agent_tracking.py` (run_agent_with_tracking, run_agent_sync_with_tracking)

---

## 10. Usage Limits & Enforcement

### File: `viraltracker/services/usage_limit_service.py`

### Limit Types

| Type | Period | What It Limits |
|------|--------|----------------|
| `monthly_tokens` | monthly | Total input + output tokens |
| `monthly_cost` | monthly | Total USD cost |
| `daily_ads` | daily | Number of ad creation operations |
| `daily_requests` | daily | Number of API requests |

### Key Methods

```python
class UsageLimitService:
    # CRUD
    get_limits(org_id) -> List[dict]
    get_limit(org_id, limit_type) -> Optional[dict]
    set_limit(org_id, limit_type, limit_value, period="monthly",
              alert_threshold=0.8, enabled=True) -> dict
    delete_limit(org_id, limit_type) -> bool

    # Checking
    get_current_period_usage(org_id, limit_type) -> dict
        # Returns: {limit_type, limit_value, current_usage, usage_pct,
        #           is_exceeded, is_warning, alert_threshold, enabled}
    check_all_limits(org_id) -> List[dict]

    # Enforcement
    enforce_limit(org_id, limit_type) -> None
        # Raises UsageLimitExceeded if over limit
        # Fails open: returns silently if org_id=="all", no limit configured, or check errors
```

### Enforcement Pattern

```python
# Before an expensive operation
try:
    ctx.deps.usage_limits.enforce_limit(
        organization_id=ctx.deps.organization_id,
        limit_type="monthly_cost"
    )
except UsageLimitExceeded as e:
    return {"error": str(e), "limit_exceeded": True}

# Proceed with operation...
```

### Fail-Open Design

The enforcement pattern is intentionally **fail-open**:
- If `org_id == "all"` (superuser) → returns silently
- If no limit is configured for that type → returns silently
- If the usage check query fails → logs warning, returns silently
- Only raises `UsageLimitExceeded` when a limit is configured, enabled, and the current usage exceeds it

This prevents system outages from blocking legitimate operations due to transient errors.

### Services with Enforcement Wired In

- GeminiService (4 methods)
- VeoService (video generation)
- ScriptService (3 methods)
- ComicService (3 methods)
- `agent_tracking.py` (both sync and async agent runs)

---

## 11. Admin Page

### File: `viraltracker/ui/pages/69_🔧_Admin.py`

### Access Control

- Requires authentication (`require_auth()`)
- User must be **superuser** OR **org owner/admin**
- Non-superusers can only manage their own organization

### Tabs

#### 1. Organizations (superuser only)
- View all organizations with member counts
- Edit org name, slug, owner
- Create new organizations

#### 2. Users
- View all organization members with email, role, join date
- Edit member display name
- Change member role (owner assignment requires typing "CONFIRM")
- Remove members

#### 3. Features
- Toggle section keys (affect all base pages in that section)
- Toggle individual page keys
- "Enable All" / "Disable All" bulk actions

#### 4. Usage Limits
- View/edit limits for each type (monthly_tokens, monthly_cost, daily_ads, daily_requests)
- Set alert threshold (default 80%)
- Enable/disable enforcement per limit
- View current usage vs limit with progress indicators

### Stale State Handling

Streamlit widgets cache their state in `st.session_state`. When switching between organizations in the Admin page, stale values from the previous org could appear. This is solved with:

1. **Prev-org tracking**: `_admin_features_prev_org`, `_admin_limits_prev_org`
2. **Cache flushing**: When org changes, delete all widget keys from session state
3. **Keyed widgets**: Widget keys include `_{tab_org}` and `_{sel_uid}` suffixes

```python
_prev_key = "_admin_features_prev_org"
if st.session_state.get(_prev_key) != tab_org:
    for k in [k for k in st.session_state if k.startswith("admin_section_")]:
        del st.session_state[k]
    st.session_state[_prev_key] = tab_org
```

---

## 12. Supabase Client Architecture

### File: `viraltracker/core/database.py`

Two client types are used:

| Client | Function | Key Used | RLS |
|--------|----------|----------|-----|
| **Service client** | `get_supabase_client()` | `SUPABASE_SERVICE_KEY` | **Bypasses** RLS |
| **Anon client** | `get_anon_client()` | `SUPABASE_ANON_KEY` | **Respects** RLS |

### When Each Is Used

| Context | Client | Why |
|---------|--------|-----|
| UI auth operations (login, signup) | Anon client | Must use anon key for Supabase Auth |
| Services, workers, agents | Service client | Need unrestricted access (no RLS policies yet) |
| Admin operations | Service client | Need cross-org access |

### Current State

Since RLS policies are not yet implemented (Phase 8), both clients effectively have the same data access. The distinction exists as preparation for Phase 8 and to follow Supabase best practices for auth.

---

## 13. Session State Reference

### Authentication Keys

| Key | Type | Set By | Purpose |
|-----|------|--------|---------|
| `_supabase_user` | dict | `auth.py` | Current Supabase user object |
| `_supabase_session` | dict | `auth.py` | Auth tokens (access, refresh, expiry) |
| `_authenticated` | bool | `auth.py` | Whether user is authenticated |

### Organization Keys

| Key | Type | Set By | Purpose |
|-----|------|--------|---------|
| `current_organization_id` | str | `render_organization_selector()` in app.py | Currently selected org UUID or `"all"` |
| `selected_brand_id` | str | `render_brand_selector()` | Currently selected brand (persists across pages) |
| `_org_options_map` | dict | `render_organization_selector()` | Name→ID map for on_change callback |
| `_workspace_selectbox` | str | Streamlit widget | Selected workspace display name |

### Admin Page Keys

| Key Pattern | Purpose |
|-------------|---------|
| `_admin_features_prev_org` | Tracks which org features were last rendered (for stale state detection) |
| `_admin_limits_prev_org` | Tracks which org limits were last rendered |
| `admin_section_{section}` | Feature section toggle widgets |
| `admin_page_{page}` | Feature page toggle widgets |
| `admin_limit_val_{type}_{org}` | Limit value inputs |
| `admin_limit_threshold_{type}_{org}` | Alert threshold inputs |
| `admin_limit_enabled_{type}_{org}` | Limit enabled checkboxes |
| `admin_member_role_{uid}_{org}` | Member role selectboxes |

---

## 14. Data Flow Diagrams

### Authentication Flow

```
Browser                     Streamlit                   Supabase
  │                            │                           │
  │  Open page                 │                           │
  ├──────────────────────────→ │                           │
  │                            │  require_auth()           │
  │                            │  Check session_state      │
  │                            │  Check cookie             │
  │                            │                           │
  │  [No session]              │                           │
  │  Show login form           │                           │
  │                            │                           │
  │  Submit credentials        │                           │
  ├──────────────────────────→ │                           │
  │                            │  sign_in(email, password) │
  │                            ├─────────────────────────→ │
  │                            │                           │  Validate
  │                            │  ← session + user         │
  │                            ├─────────────────────────← │
  │                            │                           │
  │                            │  Store in session_state   │
  │  ← Set cookie              │  Save cookie              │
  │  ← Render page             │                           │
```

### Organization Context Flow

```
Page Load (app.py runs first)
  │
  ├─ require_auth() ← sets _authenticated, _supabase_user
  │
  ├─ render_organization_selector()   ← called ONCE in app.py sidebar
  │     │
  │     ├─ get_current_user_id()
  │     ├─ OrganizationService.get_user_organizations(user_id)
  │     ├─ is_superuser(user_id)
  │     │
  │     ├─ [1 org] → Auto-select (no widget)
  │     ├─ [N orgs] → Show dropdown (key="_workspace_selectbox")
  │     ├─ [Superuser] → Add "All Organizations" option
  │     │
  │     ├─ on_change callback (fires BEFORE rerun):
  │     │     ├─ Updates current_organization_id
  │     │     ├─ Clears selected_brand_id, selected_product_id
  │     │     ├─ Saves org_id to browser cookie (30-day TTL)
  │     │     └─ Clears _get_org_features_cached (nav rebuilds)
  │     │
  │     └─ Store in st.session_state["current_organization_id"]
  │
  ├─ _auto_init_organization() (on first visit / refresh)
  │     ├─ Check workspace cookie first → restore if valid
  │     ├─ Validate "all" is only for superusers
  │     └─ Fall through to first org if cookie empty/stale
  │
  ├─ render_brand_selector()           ← pages call this (NO org selector)
  │     ├─ get_current_organization_id()  ← reads session state (not a selector)
  │     ├─ get_brands(organization_id)    ← filters by org
  │     └─ Store in st.session_state["selected_brand_id"]
  │
  └─ Page content uses brand_id for all operations

Note: Individual pages use get_current_organization_id() — they do NOT
call render_organization_selector(). This prevents duplicate sidebar
selectboxes that would overwrite the workspace value.
```

### Feature Gating Flow

```
nav.py: build_navigation_pages()
  │
  ├─ get_current_organization_id()
  ├─ _get_org_features(org_id)  ← @st.cache_data(ttl=300)
  │     │
  │     ├─ [org_id == "all"] → All features True
  │     └─ [org_id == uuid]  → Query org_features table
  │
  ├─ For each page:
  │     ├─ visible(section_key)        → opt-out check
  │     └─ visible(section_key, page_key) → opt-in check
  │
  └─ Build Dict[section_name, List[st.Page]]
        └─ st.navigation(pages) renders sidebar
```

### Usage Tracking Flow

```
User triggers AI operation
  │
  ├─ Service method called (e.g., GeminiService.generate_image())
  │     │
  │     ├─ [Has tracking context?]
  │     │     ├─ Yes → UsageTracker.track(user_id, org_id, UsageRecord(...))
  │     │     │          ├─ [org_id == "all"] → Skip (superuser)
  │     │     │          ├─ Calculate cost if not provided
  │     │     │          └─ INSERT into token_usage table (fire-and-forget)
  │     │     └─ No  → Skip tracking
  │     │
  │     └─ Return result
  │
  └─ Usage Dashboard queries token_usage for display
```

### Usage Limit Enforcement Flow

```
Before expensive operation
  │
  ├─ UsageLimitService.enforce_limit(org_id, limit_type)
  │     │
  │     ├─ [org_id == "all"] → Return (superuser bypass)
  │     ├─ Query usage_limits for this org + type
  │     ├─ [No limit configured] → Return (no limit)
  │     ├─ [Limit disabled] → Return (disabled)
  │     ├─ Query current period usage from token_usage
  │     │
  │     ├─ [usage < limit] → Return (under limit)
  │     └─ [usage >= limit] → Raise UsageLimitExceeded
  │
  ├─ [Exception caught] → Show error in UI
  └─ [No exception] → Proceed with operation
```

---

## 15. Key Files Reference

| File | Role |
|------|------|
| `viraltracker/ui/auth.py` | Supabase auth, cookie sessions, `require_auth()` |
| `viraltracker/services/organization_service.py` | Org CRUD, member management, roles |
| `viraltracker/services/feature_service.py` | Feature flags: `FeatureKey` constants, `FeatureService` |
| `viraltracker/services/usage_tracker.py` | Track AI/API usage: `UsageTracker`, `UsageRecord`, `UsageSummary` |
| `viraltracker/services/usage_limit_service.py` | Rate limiting: `UsageLimitService`, `UsageLimitExceeded` |
| `viraltracker/ui/utils.py` | Org selector, brand filtering, `is_superuser()`, `require_feature()`, `has_feature()` |
| `viraltracker/ui/nav.py` | Dynamic sidebar builder with feature gating |
| `viraltracker/ui/pages/69_🔧_Admin.py` | Admin interface (orgs, users, features, limits) |
| `viraltracker/ui/pages/68_📊_Usage_Dashboard.py` | Usage metrics and cost display |
| `viraltracker/core/database.py` | Supabase client management (service key vs anon key) |
| `viraltracker/agent/dependencies.py` | `AgentDependencies.create()` — wires usage tracking context |
| `migrations/2026-01-23_organizations.sql` | Schema: orgs, membership, auto-create trigger |
| `migrations/2026-01-23_user_profiles.sql` | Schema: superuser flag |
| `migrations/2026-01-23_org_features.sql` | Schema: feature flags |
| `migrations/2026-01-24_token_usage.sql` | Schema: usage tracking + helper function |
| `migrations/2026-01-27_usage_limits.sql` | Schema: usage limits |

---

## 16. Phase 8: RLS (Planned)

### What It Would Add

Row-Level Security (RLS) adds **database-level** data isolation as defense-in-depth. Even if application code has a bug that forgets to filter by `organization_id`, Postgres policies would prevent cross-tenant data access.

### Why It's Deferred

- All data isolation is currently enforced at the Python service layer
- The platform is internal-only (trusted users)
- RLS adds complexity to development and debugging
- All queries already filter by `organization_id`

### What Would Be Needed

1. Enable RLS on `brands`, `organizations`, `user_organizations`, and other tenant-scoped tables
2. Create `auth.user_organization_ids()` helper function that returns org IDs for the current JWT user
3. Create SELECT/INSERT/UPDATE/DELETE policies per table
4. Switch UI pages from `get_supabase_client()` (service key, bypasses RLS) to `get_anon_client()` (respects RLS)
5. Pass user access tokens to Supabase client per request
6. Extensive testing with multiple users/orgs + rollback plan

### When to Implement

Before onboarding external or untrusted tenants. Not needed while the platform is internal-only.

**Reference**: `docs/TECH_DEBT.md` (item #7), `docs/plans/multi-tenant-auth/PLAN.md` (Phase 8 section)

---

## 17. Known Technical Debt

### 1. auth.py Architecture Violation

**Issue**: `viraltracker/ui/auth.py` contains business logic (session management, token refresh, user lookup) that should live in a service layer `AuthService`.

**Impact**: Low. Works correctly but violates the 3-layer architecture pattern. Makes auth logic harder to reuse from non-UI contexts.

**When to fix**: When auth needs to be called from API endpoints or workers.

### 2. No RLS Policies

**Issue**: All data isolation is enforced in Python. A bug in any query could leak cross-tenant data.

**Impact**: Low while internal-only. High risk if external tenants are onboarded.

**Reference**: [Phase 8](#16-phase-8-rls-planned)

### 3. Service Key Usage in UI

**Issue**: Many UI pages use `get_supabase_client()` (service key) instead of `get_anon_client()`. This bypasses any future RLS policies.

**Impact**: None currently (no RLS). Will need to be changed as part of Phase 8.

### 4. Feature Cache TTL

**Issue**: `nav.py` caches features with `@st.cache_data(ttl=300)` (5 minutes). The `FeatureService` also has its own in-memory cache. Changes in the Admin page may not reflect immediately on other pages.

**Impact**: Low. Users may need to wait up to 5 minutes or refresh to see feature flag changes. The Admin page itself always reads fresh data.
