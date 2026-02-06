# Multi-Tenant Auth & Usage Tracking Plan

## Overview

Transform ViralTracker from single-tenant to multi-tenant with:
- Organization-based data isolation
- User activity and token usage tracking
- Feature access control per organization
- Usage limits and rate limiting

---

## Architecture Alignment

All phases follow the project's 3-layer architecture:

```
Agent Layer (PydanticAI) → Tools call services via ctx.deps
Service Layer           → Business logic, reusable across interfaces
Interface Layer         → CLI, API, Streamlit UI (thin, call services)
```

### Services to Create

| Service | File | Purpose | Phase |
|---------|------|---------|-------|
| `AuthService` | `services/auth_service.py` | Sign in/out, session management | 1-2 Fix |
| `OrganizationService` | `services/organization_service.py` | Org CRUD, membership | 3 |
| `UsageTracker` | `services/usage_tracker.py` | Track AI/API usage | 4 |
| `FeatureService` | `services/feature_service.py` | Feature flags per org | 6 |
| `UsageLimitService` | `services/usage_limit_service.py` | Rate limiting | 7 |

### AgentDependencies Evolution

```python
# viraltracker/agent/dependencies.py
@dataclass
class AgentDependencies:
    # Existing services
    twitter: TwitterService
    gemini: GeminiService
    ad_creation: AdCreationService
    # ... other existing services

    # Phase 1-2 Fix: User context
    user_id: Optional[str] = None

    # Phase 3: Organization context
    organization_id: Optional[str] = None
    organizations: Optional[OrganizationService] = None

    # Phase 4: Usage tracking
    usage_tracker: Optional[UsageTracker] = None

    # Phase 6: Feature access
    features: Optional[FeatureService] = None

    # Phase 7: Usage limits
    usage_limits: Optional[UsageLimitService] = None
```

### Pydantic Models

All data structures use Pydantic `BaseModel`, not `@dataclass`:

```python
# viraltracker/services/models.py (add to existing file)

from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class SessionData(BaseModel):
    """Supabase session data for cookie storage."""
    access_token: str
    refresh_token: str
    expires_at: int

class Organization(BaseModel):
    """Organization/tenant model."""
    id: UUID
    name: str
    slug: Optional[str] = None
    owner_user_id: UUID
    created_at: datetime

class UserOrganization(BaseModel):
    """User membership in an organization."""
    user_id: UUID
    organization_id: UUID
    role: str  # 'owner', 'admin', 'member', 'viewer'
    created_at: datetime

class UsageRecord(BaseModel):
    """Single AI/API usage event."""
    provider: str
    model: str
    tool_name: Optional[str] = None
    operation: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    units: Optional[float] = None
    unit_type: Optional[str] = None
    cost_usd: Optional[Decimal] = None
    request_metadata: Optional[dict] = None
    duration_ms: Optional[int] = None

class FeatureFlag(BaseModel):
    """Feature flag for an organization."""
    organization_id: UUID
    feature_key: str
    enabled: bool = False
    config: Optional[dict] = None

class UsageLimit(BaseModel):
    """Usage limit configuration."""
    id: UUID
    organization_id: UUID
    user_id: Optional[UUID] = None
    limit_type: str  # 'monthly_tokens', 'monthly_cost', 'daily_ads'
    limit_value: Decimal
    period: str  # 'daily', 'monthly'
```

---

## Completed Phases

### Phase 1: Supabase Auth Foundation ✅
- Replaced password auth with Supabase email/password
- Added `get_anon_client()` for RLS-enforced operations
- Commit: `dd6055a`

### Phase 2: Session Persistence ✅
- Cookie-based session storage via `streamlit-cookies-controller`
- Sessions survive page refresh and browser close
- Auto-refresh of expired tokens

### Phase 3: Organization Schema ✅
- Created `organizations` and `user_organizations` tables
- Added `organization_id` to brands with backfill
- Auto-create org trigger on user signup
- Created `OrganizationService`
- Added org selector utilities to `utils.py`
- Commit: `8b80bab`

---

## Implementation Order (Updated)

**Note**: Phase 5 is being implemented before Phase 4 to complete multi-tenant isolation first.

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1-2 | ✅ Complete | Supabase Auth + Sessions |
| Phase 3 | ✅ Complete | Organization Schema |
| **Phase 5** | 🔄 Next | Python Org Filtering + Superuser |
| Phase 4 | ⏸️ Deferred | Usage Tracking |
| Phase 6 | Pending | Feature Access Control |
| Phase 7 | Pending | Usage Limits |
| Phase 8 | Pending | RLS Policies |

### Phase 1-2 Fixes Required ⚠️

The implementation needs refactoring to follow service layer pattern:

**Current state** (violates 3-layer architecture):
```
viraltracker/ui/auth.py  # Contains business logic (sign_in, sign_out, etc.)
```

**Target state**:
```
viraltracker/services/auth_service.py  # Business logic
viraltracker/ui/auth.py                # Thin UI helpers only
```

**Changes needed:**

1. **Create `AuthService`** (`viraltracker/services/auth_service.py`):
```python
from pydantic import BaseModel
from typing import Optional, Tuple
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class AuthService:
    """Authentication service using Supabase Auth."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    def sign_in(self, email: str, password: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Sign in with email and password.

        Args:
            email: User email
            password: User password

        Returns:
            Tuple of (success, error_message, session_data)
        """
        try:
            response = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            if response and response.session:
                session_data = {
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "expires_at": response.session.expires_at,
                    "user": response.user,
                }
                logger.info(f"User signed in: {response.user.email}")
                return True, None, session_data
        except Exception as e:
            error_msg = str(e)
            if "Invalid login credentials" in error_msg:
                return False, "Invalid email or password", None
            logger.warning(f"Sign in failed: {e}")
            return False, f"Sign in failed: {error_msg}", None
        return False, "Sign in failed", None

    def sign_out(self) -> None:
        """Sign out the current user."""
        try:
            self.client.auth.sign_out()
        except Exception as e:
            logger.debug(f"Sign out API call failed: {e}")
        logger.info("User signed out")

    def refresh_session(self, refresh_token: str) -> Tuple[bool, Optional[dict]]:
        """
        Refresh session using refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            Tuple of (success, session_data)
        """
        try:
            response = self.client.auth.refresh_session(refresh_token)
            if response and response.session:
                return True, {
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "expires_at": response.session.expires_at,
                    "user": response.user,
                }
        except Exception as e:
            logger.debug(f"Session refresh failed: {e}")
        return False, None

    def set_session(self, access_token: str, refresh_token: str) -> Tuple[bool, Optional[dict]]:
        """
        Set/restore session from tokens.

        Args:
            access_token: The access token
            refresh_token: The refresh token

        Returns:
            Tuple of (success, user_data)
        """
        try:
            response = self.client.auth.set_session(access_token, refresh_token)
            if response and response.user:
                return True, {"user": response.user, "session": response.session}
        except Exception as e:
            logger.debug(f"Set session failed: {e}")
        return False, None
```

2. **Update `auth.py`** to be thin UI layer:
```python
# viraltracker/ui/auth.py - thin wrapper

def _get_auth_service() -> AuthService:
    """Get AuthService instance."""
    from viraltracker.services.auth_service import AuthService
    from viraltracker.core.database import get_anon_client
    return AuthService(get_anon_client())

def sign_in(email: str, password: str) -> tuple[bool, Optional[str]]:
    """Sign in - delegates to AuthService."""
    service = _get_auth_service()
    success, error, session_data = service.sign_in(email, password)
    if success and session_data:
        _save_session_to_state(session_data)
        _save_session_to_cookie(session_data)
    return success, error
```

3. **Move cookie expiry to Config**:
```python
# viraltracker/core/config.py
COOKIE_EXPIRY_DAYS: int = int(os.getenv('COOKIE_EXPIRY_DAYS', '30'))
```

4. **Remove dead code**: Delete `sign_up()` function

---

## Remaining Phases

### Phase 3: Organization Schema

**Goal**: Create database structure for organizations and link to users

**Migration**: `migrations/2026-01-XX_organizations.sql`
```sql
-- Organizations (tenants)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    owner_user_id UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User-Organization memberships
CREATE TABLE user_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, organization_id)
);

-- Indexes
CREATE INDEX idx_user_orgs_user ON user_organizations(user_id);
CREATE INDEX idx_user_orgs_org ON user_organizations(organization_id);

-- Add organization_id to brands
ALTER TABLE brands ADD COLUMN organization_id UUID REFERENCES organizations(id);

-- Create default organization for existing data
INSERT INTO organizations (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default Workspace', 'default');

-- Backfill existing brands
UPDATE brands SET organization_id = '00000000-0000-0000-0000-000000000001'
WHERE organization_id IS NULL;

-- Make NOT NULL after backfill
ALTER TABLE brands ALTER COLUMN organization_id SET NOT NULL;
CREATE INDEX idx_brands_org ON brands(organization_id);

-- Trigger: Auto-create organization on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
    new_org_id UUID;
BEGIN
    -- Create personal organization
    INSERT INTO organizations (name, owner_user_id)
    VALUES (NEW.email || '''s Workspace', NEW.id)
    RETURNING id INTO new_org_id;

    -- Add user as owner
    INSERT INTO user_organizations (user_id, organization_id, role)
    VALUES (NEW.id, new_org_id, 'owner');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
```

**Service**: `viraltracker/services/organization_service.py`
```python
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class OrganizationService:
    """Service for organization/tenant operations."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    def get_user_organizations(self, user_id: str) -> List[dict]:
        """
        Get all organizations a user belongs to.

        Args:
            user_id: The user's ID

        Returns:
            List of organizations with membership info
        """
        result = self.client.table("user_organizations").select(
            "role, organization:organizations(id, name, slug, owner_user_id)"
        ).eq("user_id", user_id).execute()
        return result.data

    def get_organization(self, org_id: str) -> Optional[dict]:
        """Get organization by ID."""
        result = self.client.table("organizations").select("*").eq("id", org_id).single().execute()
        return result.data

    def get_user_role(self, user_id: str, org_id: str) -> Optional[str]:
        """Get user's role in an organization."""
        result = self.client.table("user_organizations").select("role").eq(
            "user_id", user_id
        ).eq("organization_id", org_id).single().execute()
        return result.data.get("role") if result.data else None

    def create_organization(self, name: str, owner_id: str) -> dict:
        """Create a new organization with owner."""
        # Create org
        org_result = self.client.table("organizations").insert({
            "name": name,
            "owner_user_id": owner_id
        }).execute()
        org = org_result.data[0]

        # Add owner membership
        self.client.table("user_organizations").insert({
            "user_id": owner_id,
            "organization_id": org["id"],
            "role": "owner"
        }).execute()

        logger.info(f"Created organization: {name} for user {owner_id}")
        return org
```

**UI Integration** (`viraltracker/ui/utils.py`):
```python
def get_current_organization_id() -> Optional[str]:
    """Get current organization ID from session state."""
    return st.session_state.get("current_organization_id")

def set_current_organization_id(org_id: str) -> None:
    """Set current organization ID in session state."""
    st.session_state["current_organization_id"] = org_id

def render_organization_selector(key: str = "org_selector") -> Optional[str]:
    """
    Render organization selector in sidebar.

    Returns:
        Selected organization ID or None
    """
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.services.organization_service import OrganizationService
    from viraltracker.core.database import get_supabase_client

    user_id = get_current_user_id()
    if not user_id:
        return None

    service = OrganizationService(get_supabase_client())
    orgs = service.get_user_organizations(user_id)

    if not orgs:
        st.sidebar.warning("No organizations found")
        return None

    if len(orgs) == 1:
        # Auto-select single org
        org_id = orgs[0]["organization"]["id"]
        set_current_organization_id(org_id)
        return org_id

    # Multiple orgs - show selector
    org_options = {o["organization"]["name"]: o["organization"]["id"] for o in orgs}

    # Get current selection or default to first
    current_org_id = get_current_organization_id()
    current_name = next(
        (name for name, id in org_options.items() if id == current_org_id),
        list(org_options.keys())[0]
    )

    selected_name = st.sidebar.selectbox(
        "Workspace",
        list(org_options.keys()),
        index=list(org_options.keys()).index(current_name),
        key=key
    )

    selected_id = org_options[selected_name]
    set_current_organization_id(selected_id)
    return selected_id
```

**Data Flow**:
```
User logs in
    → auth.py stores user_id in session_state
    → UI page calls render_organization_selector()
    → OrganizationService.get_user_organizations(user_id)
    → User selects org (or auto-selected if only one)
    → organization_id stored in session_state
    → All service calls include organization_id filter
```

---

### Phase 4: Usage Tracking

**Goal**: Track all AI/API usage for billing and limits

See: `PHASE_4_USAGE_TRACKING.md` (updated with Pydantic models and AgentDependencies)

---

### Phase 5: Python Org Filtering + Superuser Support

**Goal**: Filter all data queries by organization, with superuser override

---

#### 5.1: User Profiles & Superuser Flag

**Migration**: `migrations/2026-01-23_user_profiles.sql`
```sql
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    is_superuser BOOLEAN DEFAULT false,
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Make existing admin user a superuser
INSERT INTO user_profiles (user_id, is_superuser)
VALUES ('54093883-c9de-40a3-b940-86cc52825365', true);
```

**Helper Function** (`viraltracker/ui/utils.py`):
```python
def is_superuser(user_id: str) -> bool:
    """Check if user is a superuser."""
    from viraltracker.core.database import get_supabase_client
    result = get_supabase_client().table("user_profiles").select(
        "is_superuser"
    ).eq("user_id", user_id).single().execute()
    return result.data.get("is_superuser", False) if result.data else False
```

---

#### 5.2: Organization Selector with "All Organizations" Option

**Update** `render_organization_selector()` in `utils.py`:
```python
def render_organization_selector(key: str = "org_selector") -> Optional[str]:
    user_id = get_current_user_id()
    if not user_id:
        return None

    service = OrganizationService(get_supabase_client())
    orgs = service.get_user_organizations(user_id)

    if not orgs:
        st.sidebar.warning("No organizations found")
        return None

    # Build options
    org_options = {o["organization"]["name"]: o["organization"]["id"] for o in orgs}

    # Superuser gets "All Organizations" option
    if is_superuser(user_id):
        org_options = {"All Organizations": "all", **org_options}

    # Single org (non-superuser) - auto-select
    if len(org_options) == 1:
        org_id = list(org_options.values())[0]
        set_current_organization_id(org_id)
        return org_id

    # Multiple orgs - show selector
    # ... rest of selector logic
```

---

#### 5.3: Update Data Query Functions

**Pattern for `get_brands()` and similar**:
```python
def get_brands(organization_id: str = None) -> List[dict]:
    """
    Get brands, filtered by organization.

    Args:
        organization_id: Org to filter by, or "all" for superuser mode

    Returns:
        List of brands
    """
    query = db.table("brands").select("id, name, organization_id")

    if organization_id and organization_id != "all":
        query = query.eq("organization_id", organization_id)

    return query.order("name").execute().data or []
```

---

#### 5.4: User Access Modes

| User Type | Org Selector Shows | Data Access |
|-----------|-------------------|-------------|
| Normal (1 org) | Auto-selected | Their org only |
| Normal (multi-org) | Dropdown of their orgs | Selected org only |
| Superuser | "All Organizations" + their orgs | All data or selected org |

---

#### 5.5: Files to Modify

| File | Changes |
|------|---------|
| `migrations/2026-01-23_user_profiles.sql` | NEW - user_profiles table |
| `viraltracker/ui/utils.py` | Add `is_superuser()`, update `render_organization_selector()`, update `get_brands()` |
| `viraltracker/ui/pages/*.py` | Add org selector call where missing |

---

#### 5.6: Implementation Order

1. Create `user_profiles` migration
2. Add `is_superuser()` helper to utils.py
3. Update `render_organization_selector()` with superuser support
4. Update `get_brands()` to filter by org (with "all" support)
5. Test with superuser and normal user

---

### Phase 6: Feature Access Control

**Goal**: Control which tools/features each organization can access

**Migration**: `migrations/2026-01-XX_feature_flags.sql`
```sql
CREATE TABLE org_features (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    enabled BOOLEAN DEFAULT false,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (organization_id, feature_key)
);

CREATE INDEX idx_org_features_org ON org_features(organization_id);

-- Default features for existing organizations
INSERT INTO org_features (organization_id, feature_key, enabled)
SELECT id, 'ad_creator', true FROM organizations;
-- Add more default features as needed
```

**Feature Keys** (define in code):
```python
# viraltracker/services/feature_service.py

class FeatureKey:
    """Feature flag keys."""
    AD_CREATOR = "ad_creator"
    VEO_AVATARS = "veo_avatars"
    AD_SCHEDULER = "ad_scheduler"
    COMPETITOR_RESEARCH = "competitor_research"
    REDDIT_RESEARCH = "reddit_research"
    CONTENT_PIPELINE = "content_pipeline"
    BELIEF_CANVAS = "belief_canvas"
    # Add more as needed
```

**Service**: `viraltracker/services/feature_service.py`
```python
from typing import Optional, List
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class FeatureKey:
    """Feature flag keys."""
    AD_CREATOR = "ad_creator"
    VEO_AVATARS = "veo_avatars"
    AD_SCHEDULER = "ad_scheduler"
    COMPETITOR_RESEARCH = "competitor_research"
    REDDIT_RESEARCH = "reddit_research"
    CONTENT_PIPELINE = "content_pipeline"
    BELIEF_CANVAS = "belief_canvas"

class FeatureService:
    """Service for feature flag management."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client
        self._cache: dict = {}  # Simple in-memory cache

    def has_feature(self, organization_id: str, feature_key: str) -> bool:
        """
        Check if organization has a feature enabled.

        Args:
            organization_id: Organization ID
            feature_key: Feature to check (use FeatureKey constants)

        Returns:
            True if feature is enabled
        """
        cache_key = f"{organization_id}:{feature_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self.client.table("org_features").select("enabled").eq(
            "organization_id", organization_id
        ).eq("feature_key", feature_key).single().execute()

        enabled = result.data.get("enabled", False) if result.data else False
        self._cache[cache_key] = enabled
        return enabled

    def get_org_features(self, organization_id: str) -> List[dict]:
        """Get all feature flags for an organization."""
        result = self.client.table("org_features").select("*").eq(
            "organization_id", organization_id
        ).execute()
        return result.data

    def set_feature(self, organization_id: str, feature_key: str, enabled: bool, config: dict = None) -> None:
        """Enable or disable a feature for an organization."""
        self.client.table("org_features").upsert({
            "organization_id": organization_id,
            "feature_key": feature_key,
            "enabled": enabled,
            "config": config or {}
        }).execute()

        # Clear cache
        cache_key = f"{organization_id}:{feature_key}"
        self._cache.pop(cache_key, None)

        logger.info(f"Feature {feature_key} {'enabled' if enabled else 'disabled'} for org {organization_id}")

    def clear_cache(self) -> None:
        """Clear the feature cache."""
        self._cache.clear()
```

**UI Pattern** (decorator approach):
```python
# viraltracker/ui/utils.py

def require_feature(feature_key: str):
    """
    Decorator/helper to require a feature for a page.

    Usage:
        # At top of page after require_auth()
        require_feature(FeatureKey.VEO_AVATARS)
    """
    from viraltracker.services.feature_service import FeatureService
    from viraltracker.core.database import get_supabase_client

    org_id = get_current_organization_id()
    if not org_id:
        st.error("No organization selected")
        st.stop()

    service = FeatureService(get_supabase_client())
    if not service.has_feature(org_id, feature_key):
        st.error(f"This feature is not enabled for your organization.")
        st.info("Contact your administrator to enable this feature.")
        st.stop()
```

**Page Integration**:
```python
# viraltracker/ui/pages/47_🎬_Veo_Avatars.py

st.set_page_config(...)
require_auth()

# Check feature access
from viraltracker.ui.utils import require_feature
from viraltracker.services.feature_service import FeatureKey
require_feature(FeatureKey.VEO_AVATARS)

# Rest of page...
```

---

### Phase 7: Usage Limits & Enforcement

**Goal**: Rate limit usage per organization/user

**Migration**: `migrations/2026-01-XX_usage_limits.sql`
```sql
CREATE TABLE usage_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,  -- NULL = org-wide
    limit_type TEXT NOT NULL,  -- 'monthly_tokens', 'monthly_cost', 'daily_ads'
    limit_value NUMERIC NOT NULL,
    period TEXT NOT NULL DEFAULT 'monthly',  -- 'daily', 'monthly'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, user_id, limit_type)
);

CREATE INDEX idx_usage_limits_org ON usage_limits(organization_id);
```

**Service**: `viraltracker/services/usage_limit_service.py`
```python
from typing import Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class LimitType:
    """Usage limit types."""
    MONTHLY_TOKENS = "monthly_tokens"
    MONTHLY_COST = "monthly_cost"
    DAILY_ADS = "daily_ads"
    DAILY_REQUESTS = "daily_requests"

class UsageLimitService:
    """Service for usage limit management and enforcement."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    def get_limit(
        self,
        organization_id: str,
        limit_type: str,
        user_id: Optional[str] = None
    ) -> Optional[Decimal]:
        """
        Get usage limit for org (or specific user).

        Args:
            organization_id: Organization ID
            limit_type: Type of limit (use LimitType constants)
            user_id: Optional user ID for user-specific limits

        Returns:
            Limit value or None if no limit set
        """
        query = self.client.table("usage_limits").select("limit_value").eq(
            "organization_id", organization_id
        ).eq("limit_type", limit_type)

        if user_id:
            query = query.eq("user_id", user_id)
        else:
            query = query.is_("user_id", "null")

        result = query.single().execute()
        return Decimal(str(result.data["limit_value"])) if result.data else None

    def check_limit(
        self,
        organization_id: str,
        limit_type: str,
        current_usage: Decimal,
        user_id: Optional[str] = None
    ) -> Tuple[bool, Optional[Decimal], Optional[Decimal]]:
        """
        Check if usage is within limit.

        Args:
            organization_id: Organization ID
            limit_type: Type of limit
            current_usage: Current usage value
            user_id: Optional user ID

        Returns:
            Tuple of (is_within_limit, limit_value, remaining)
        """
        limit = self.get_limit(organization_id, limit_type, user_id)
        if limit is None:
            return True, None, None  # No limit set

        remaining = limit - current_usage
        is_within = current_usage < limit
        return is_within, limit, remaining

    def get_current_period_usage(
        self,
        organization_id: str,
        limit_type: str,
        period: str = "monthly"
    ) -> Decimal:
        """
        Get usage for current period from token_usage table.

        Args:
            organization_id: Organization ID
            limit_type: Type of usage to sum
            period: 'daily' or 'monthly'

        Returns:
            Total usage for current period
        """
        if period == "daily":
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            start_date = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Map limit type to column
        column_map = {
            LimitType.MONTHLY_TOKENS: "total_tokens",
            LimitType.MONTHLY_COST: "cost_usd",
            LimitType.DAILY_ADS: "id",  # count
            LimitType.DAILY_REQUESTS: "id",  # count
        }

        column = column_map.get(limit_type, "total_tokens")

        if limit_type in [LimitType.DAILY_ADS, LimitType.DAILY_REQUESTS]:
            # Count records
            result = self.client.table("token_usage").select(
                "id", count="exact"
            ).eq("organization_id", organization_id).gte(
                "created_at", start_date.isoformat()
            ).execute()
            return Decimal(result.count or 0)
        else:
            # Sum column
            result = self.client.rpc("sum_usage", {
                "org_id": organization_id,
                "column_name": column,
                "start_date": start_date.isoformat()
            }).execute()
            return Decimal(str(result.data or 0))

    def enforce_limit(
        self,
        organization_id: str,
        limit_type: str,
        user_id: Optional[str] = None
    ) -> None:
        """
        Check limit and raise exception if exceeded.

        Args:
            organization_id: Organization ID
            limit_type: Type of limit
            user_id: Optional user ID

        Raises:
            UsageLimitExceeded: If limit is exceeded
        """
        period = "daily" if "daily" in limit_type.lower() else "monthly"
        current_usage = self.get_current_period_usage(organization_id, limit_type, period)
        is_within, limit, remaining = self.check_limit(
            organization_id, limit_type, current_usage, user_id
        )

        if not is_within:
            raise UsageLimitExceeded(
                f"Usage limit exceeded: {current_usage}/{limit} ({limit_type})"
            )

class UsageLimitExceeded(Exception):
    """Raised when usage limit is exceeded."""
    pass
```

**Integration Pattern**:
```python
# Before expensive operation
try:
    ctx.deps.usage_limits.enforce_limit(
        organization_id=ctx.deps.organization_id,
        limit_type=LimitType.MONTHLY_COST
    )
except UsageLimitExceeded as e:
    return {"error": str(e), "limit_exceeded": True}

# Proceed with operation...
```

**Alert System** (add to UsageLimitService):
```python
def check_and_alert(
    self,
    organization_id: str,
    limit_type: str,
    alert_threshold: float = 0.8  # Alert at 80%
) -> Optional[str]:
    """
    Check usage and return alert message if approaching limit.

    Returns:
        Alert message or None
    """
    period = "daily" if "daily" in limit_type.lower() else "monthly"
    current_usage = self.get_current_period_usage(organization_id, limit_type, period)
    limit = self.get_limit(organization_id, limit_type)

    if limit is None:
        return None

    usage_ratio = float(current_usage / limit)

    if usage_ratio >= 1.0:
        return f"Usage limit EXCEEDED: {current_usage}/{limit} ({limit_type})"
    elif usage_ratio >= alert_threshold:
        pct = int(usage_ratio * 100)
        return f"Usage at {pct}% of limit: {current_usage}/{limit} ({limit_type})"

    return None
```

---

### Phase 8: RLS Policies (Optional, Future)

**Goal**: Database-level security as defense-in-depth

**Prerequisites**:
- All phases 1-7 complete
- Extensive testing of Python filtering
- Backup and rollback plan

**Migration**: `migrations/2026-01-XX_rls_policies.sql`
```sql
-- Enable RLS on key tables
ALTER TABLE brands ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_organizations ENABLE ROW LEVEL SECURITY;

-- Helper function: Get user's organization IDs
CREATE OR REPLACE FUNCTION auth.user_organization_ids()
RETURNS SETOF UUID AS $$
    SELECT organization_id
    FROM user_organizations
    WHERE user_id = auth.uid()
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- Brands: Users see brands in their organizations
CREATE POLICY "brands_select_policy" ON brands
    FOR SELECT USING (
        organization_id IN (SELECT auth.user_organization_ids())
    );

CREATE POLICY "brands_insert_policy" ON brands
    FOR INSERT WITH CHECK (
        organization_id IN (SELECT auth.user_organization_ids())
    );

CREATE POLICY "brands_update_policy" ON brands
    FOR UPDATE USING (
        organization_id IN (SELECT auth.user_organization_ids())
    );

CREATE POLICY "brands_delete_policy" ON brands
    FOR DELETE USING (
        organization_id IN (
            SELECT organization_id FROM user_organizations
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Organizations: Users see their organizations
CREATE POLICY "organizations_select_policy" ON organizations
    FOR SELECT USING (
        id IN (SELECT auth.user_organization_ids())
    );

-- User Organizations: Users see their own memberships
CREATE POLICY "user_orgs_select_policy" ON user_organizations
    FOR SELECT USING (user_id = auth.uid());
```

**UI Changes Required**:
1. Switch from `get_supabase_client()` to `get_anon_client()` in UI pages
2. Pass user's access token to Supabase client for each request
3. Handle RLS errors gracefully

**Testing Plan**:
1. Create two test users in different organizations
2. Verify User A cannot see User B's data
3. Verify User A cannot insert into User B's organization
4. Test edge cases: user with multiple orgs, admin vs member roles
5. Load test to ensure RLS doesn't cause performance issues

---

## Implementation Order

| Phase | Dependencies | Effort |
|-------|--------------|--------|
| **1-2 Fix** | None | Low |
| **Phase 3** | 1-2 Fix | Medium |
| **Phase 4** | Phase 3 | High |
| **Phase 5** | Phase 3 | Medium |
| **Phase 6** | Phase 3 | Medium |
| **Phase 7** | Phase 4 | Medium |
| **Phase 8** | All above | High |

---

## File Locations

```
docs/plans/multi-tenant-auth/
├── PLAN.md                      # This file
├── PHASE_4_USAGE_TRACKING.md    # Detailed Phase 4 plan
└── CHECKPOINT_*.md              # Progress checkpoints

viraltracker/services/
├── auth_service.py              # Phase 1-2 Fix (NEW)
├── organization_service.py      # Phase 3 (NEW)
├── usage_tracker.py             # Phase 4 (NEW)
├── feature_service.py           # Phase 6 (NEW)
├── usage_limit_service.py       # Phase 7 (NEW)
└── models.py                    # Add Pydantic models

migrations/
├── 2026-01-XX_organizations.sql
├── 2026-01-XX_usage_tracking.sql
├── 2026-01-XX_feature_flags.sql
├── 2026-01-XX_usage_limits.sql
└── 2026-01-XX_rls_policies.sql
```
