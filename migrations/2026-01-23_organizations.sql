-- Migration: Organizations and Multi-Tenant Schema
-- Date: 2026-01-23
-- Purpose: Create organization/tenant structure for multi-tenant auth
-- Phase: 3 of Multi-Tenant Auth Plan

-- ============================================================================
-- 1. Create organizations table
-- ============================================================================

CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    owner_user_id UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE organizations IS 'Organizations/tenants - each organization owns brands and users';
COMMENT ON COLUMN organizations.owner_user_id IS 'Primary owner of the organization';
COMMENT ON COLUMN organizations.slug IS 'URL-friendly identifier for the organization';

-- ============================================================================
-- 2. Create user_organizations table (membership)
-- ============================================================================

CREATE TABLE user_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, organization_id)
);

COMMENT ON TABLE user_organizations IS 'User membership in organizations with role-based access';
COMMENT ON COLUMN user_organizations.role IS 'User role: owner, admin, member, viewer';

-- Indexes for efficient lookups
CREATE INDEX idx_user_orgs_user ON user_organizations(user_id);
CREATE INDEX idx_user_orgs_org ON user_organizations(organization_id);

-- ============================================================================
-- 3. Add organization_id to brands table
-- ============================================================================

ALTER TABLE brands ADD COLUMN organization_id UUID REFERENCES organizations(id);

-- ============================================================================
-- 4. Create default organization and backfill existing data
-- ============================================================================

-- Create a default organization for existing brands
INSERT INTO organizations (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default Workspace', 'default');

-- Backfill all existing brands to the default organization
UPDATE brands SET organization_id = '00000000-0000-0000-0000-000000000001'
WHERE organization_id IS NULL;

-- Now make organization_id NOT NULL
ALTER TABLE brands ALTER COLUMN organization_id SET NOT NULL;

-- Index for efficient brand queries by organization
CREATE INDEX idx_brands_org ON brands(organization_id);

-- ============================================================================
-- 5. Trigger: Auto-create organization on user signup
-- ============================================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
    new_org_id UUID;
BEGIN
    -- Create personal organization for new user
    INSERT INTO organizations (name, owner_user_id)
    VALUES (NEW.email || '''s Workspace', NEW.id)
    RETURNING id INTO new_org_id;

    -- Add user as owner of their organization
    INSERT INTO user_organizations (user_id, organization_id, role)
    VALUES (NEW.id, new_org_id, 'owner');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger on new user creation
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
