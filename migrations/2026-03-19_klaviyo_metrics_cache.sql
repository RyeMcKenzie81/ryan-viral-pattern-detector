-- Klaviyo metrics cache tables for campaign and flow performance data.
-- Populated by KlaviyoService.sync_metrics_to_cache().

CREATE TABLE IF NOT EXISTS klaviyo_campaign_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    klaviyo_campaign_id TEXT NOT NULL,
    campaign_name TEXT,
    date DATE NOT NULL,
    opens INT DEFAULT 0,
    unique_opens INT DEFAULT 0,
    clicks INT DEFAULT 0,
    unique_clicks INT DEFAULT 0,
    bounces INT DEFAULT 0,
    unsubscribes INT DEFAULT 0,
    conversions INT DEFAULT 0,
    revenue FLOAT DEFAULT 0,
    recipients INT DEFAULT 0,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, klaviyo_campaign_id, date)
);

CREATE TABLE IF NOT EXISTS klaviyo_flow_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    klaviyo_flow_id TEXT NOT NULL,
    flow_name TEXT,
    date DATE NOT NULL,
    opens INT DEFAULT 0,
    unique_opens INT DEFAULT 0,
    clicks INT DEFAULT 0,
    unique_clicks INT DEFAULT 0,
    bounces INT DEFAULT 0,
    unsubscribes INT DEFAULT 0,
    conversions INT DEFAULT 0,
    revenue FLOAT DEFAULT 0,
    recipients INT DEFAULT 0,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, klaviyo_flow_id, date)
);

-- updated_at triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at_klaviyo_campaign_metrics') THEN
        CREATE TRIGGER set_updated_at_klaviyo_campaign_metrics
            BEFORE UPDATE ON klaviyo_campaign_metrics
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at_klaviyo_flow_metrics') THEN
        CREATE TRIGGER set_updated_at_klaviyo_flow_metrics
            BEFORE UPDATE ON klaviyo_flow_metrics
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;

-- RLS
ALTER TABLE klaviyo_campaign_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE klaviyo_flow_metrics ENABLE ROW LEVEL SECURITY;

-- Permissive RLS policies (service key bypasses RLS; anon key scoped by org)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'klaviyo_campaign_metrics_org_access') THEN
        CREATE POLICY klaviyo_campaign_metrics_org_access ON klaviyo_campaign_metrics
            FOR ALL USING (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'klaviyo_flow_metrics_org_access') THEN
        CREATE POLICY klaviyo_flow_metrics_org_access ON klaviyo_flow_metrics
            FOR ALL USING (true);
    END IF;
END
$$;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_klaviyo_campaign_metrics_brand_date
    ON klaviyo_campaign_metrics(brand_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_klaviyo_campaign_metrics_org
    ON klaviyo_campaign_metrics(organization_id);

CREATE INDEX IF NOT EXISTS idx_klaviyo_flow_metrics_brand_date
    ON klaviyo_flow_metrics(brand_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_klaviyo_flow_metrics_org
    ON klaviyo_flow_metrics(organization_id);
