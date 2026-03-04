-- Migration: Product Visual Playbooks
-- Date: 2026-02-28
-- Purpose: Cache visual playbooks per product for the Image Strategy Pipeline.
--          Playbooks are generated once per product (via Sonnet) and reused across blueprints.

CREATE TABLE IF NOT EXISTS product_visual_playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    playbook JSONB NOT NULL DEFAULT '{}',
    brand_profile_hash TEXT,
    model_used TEXT,
    token_usage JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id)
);

COMMENT ON TABLE product_visual_playbooks IS 'Cached visual playbooks for the Image Strategy Pipeline. One per product, invalidated when brand profile hash changes.';
COMMENT ON COLUMN product_visual_playbooks.brand_profile_hash IS 'SHA256 hash of visually-relevant brand profile fields for cache invalidation.';
COMMENT ON COLUMN product_visual_playbooks.playbook IS 'Visual playbook JSON: archetype, customer_world, trust_visual_language, etc.';

-- RLS policy (required for Supabase API access)
ALTER TABLE product_visual_playbooks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "org_isolation" ON product_visual_playbooks
    USING (organization_id = current_setting('app.current_org_id')::uuid);

-- Updated_at trigger
CREATE TRIGGER set_updated_at BEFORE UPDATE ON product_visual_playbooks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
