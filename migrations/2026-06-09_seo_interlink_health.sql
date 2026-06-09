-- Migration: SEO interlink health — coverage snapshots + orphan alert lifecycle
-- Date: 2026-06-09
-- Purpose: §7 Tier-2 increment 1 (hardening plan §11, decisions R4/R6/R8).
--
-- 1. seo_link_coverage_snapshots (R8): link-coverage-over-time, written weekly
--    by the seo_opportunity_scan job. The missing axis for the Link Impact
--    correlation card (position-over-time already exists in
--    seo_article_analytics). One row per article per capture day; re-runs
--    upsert (same idempotency lesson as seo_internal_links, D5.2).
--    `captured_on` is a plain DATE column (not an expression index) so
--    PostgREST upsert(on_conflict="article_id,captured_on") works.
--
-- 2. seo_articles.interlink_exempt (R6): intentional standalone pages. Exempt
--    articles never raise orphan alarms AND the interlinker skips them (no
--    body links added, not listed in Related blocks).
--
-- 3. seo_orphan_alerts (R4/R6): alarm lifecycle, mirroring the proven
--    seo_opportunities.status pattern. One OPEN alert per article (partial
--    unique index); an open alert does NOT re-alarm on later scans; resolving
--    (article gains inbound links, or becomes exempt) closes it; a later
--    re-orphan creates a NEW row and alarms again (identity-level regression
--    detection, not count deltas).
--
-- Code degrades gracefully if this migration is not applied: snapshot/alert
-- writes are non-fatally wrapped in the scan job (failure-budget rule), and
-- interlink_exempt is read via .get() so a missing column reads as not-exempt.

-- 1. Coverage snapshots ------------------------------------------------------
CREATE TABLE IF NOT EXISTS seo_link_coverage_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL,
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    captured_on DATE NOT NULL DEFAULT CURRENT_DATE,
    inbound_count INT NOT NULL DEFAULT 0,
    outbound_count INT NOT NULL DEFAULT 0,
    is_orphan BOOLEAN NOT NULL DEFAULT FALSE,
    -- Exemption state AT CAPTURE TIME, so historical orphan counts (the
    -- burn-down's "was N") can exclude intentional standalones without
    -- depending on the article's CURRENT flag.
    interlink_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_link_cov_snap_article_day
    ON seo_link_coverage_snapshots(article_id, captured_on);
CREATE INDEX IF NOT EXISTS idx_seo_link_cov_snap_brand_time
    ON seo_link_coverage_snapshots(brand_id, captured_at DESC);

COMMENT ON TABLE seo_link_coverage_snapshots IS
    'Weekly per-article interlink coverage history (inbound/outbound implemented links). Written by seo_opportunity_scan; the time axis for the Link Impact card. is_orphan stores the raw fact (0 inbound from the brand''s live set); exemption policy is applied at alert/report time, not here.';

ALTER TABLE seo_link_coverage_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "seo_link_cov_snap_permissive" ON seo_link_coverage_snapshots;
CREATE POLICY "seo_link_cov_snap_permissive" ON seo_link_coverage_snapshots
    USING (true) WITH CHECK (true);

-- 2. Exemption flag ----------------------------------------------------------
ALTER TABLE seo_articles
    ADD COLUMN IF NOT EXISTS interlink_exempt BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN seo_articles.interlink_exempt IS
    'Intentional standalone page: never raises orphan alarms and the interlinker skips it entirely (no contextual links added to its body, not listed in Related blocks). Set from the SEO Dashboard Content Health section.';

-- 3. Orphan alert lifecycle --------------------------------------------------
CREATE TABLE IF NOT EXISTS seo_orphan_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL,
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'identified'
        CHECK (status IN ('identified', 'acknowledged', 'resolved')),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- One OPEN (non-resolved) alert per article: an open alert is updated in
-- place (last_seen_at) instead of re-alarming; a resolved one allows a fresh
-- row (re-orphaned articles alarm again).
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_orphan_alerts_open
    ON seo_orphan_alerts(article_id) WHERE status != 'resolved';
CREATE INDEX IF NOT EXISTS idx_seo_orphan_alerts_brand
    ON seo_orphan_alerts(brand_id, status);

COMMENT ON TABLE seo_orphan_alerts IS
    'Orphan-regression alarm lifecycle (identified/acknowledged/resolved), mirroring seo_opportunities.status. Alarm fires only on row CREATION (new orphan >=7 days post-publish, identity-level); weekly scans refresh last_seen_at on open rows without re-alarming.';

ALTER TABLE seo_orphan_alerts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "seo_orphan_alerts_permissive" ON seo_orphan_alerts;
CREATE POLICY "seo_orphan_alerts_permissive" ON seo_orphan_alerts
    USING (true) WITH CHECK (true);
