-- Migration: meta_ad_destination_status (destination-URL fetch outcomes)
-- Date: 2026-06-02
-- Purpose: Track per-ad destination-URL fetch OUTCOMES so the sync stops
--   re-fetching ads that definitively have no resolvable URL, and so DCO /
--   multi-URL ads can be flagged.
--
-- Why a separate table: meta_ad_destinations.destination_url / canonical_url are
-- NOT NULL and only ever hold *found* URLs, so a "tried, none found" marker has
-- nowhere to live there. Today sync_ad_destinations_to_db recomputes "missing"
-- as "no row in meta_ad_destinations" every run, so no-URL ads are retried
-- forever and burn the per-run budget before high-spend ads with real URLs get
-- processed. This mirrors the proven meta_ad_assets.not_downloadable pattern.
--
-- status values:
--   'no_url'    -- TERMINAL: the creative was fetched OK but carried no link in
--                  any known location. Excluded from future fetch selection
--                  (until the creative changes — creative_id is stored to allow
--                  a future re-check).
--   'multi_url' -- INFO/FLAG: a URL WAS found (and stored in meta_ad_destinations)
--                  but the creative carried >1 distinct link (DCO asset_feed_spec).
--                  Only the first link is attributed today; this flags the ad so
--                  it isn't silently mis-attributed to one funnel.
-- A transient failure (rate-limit / 5xx / network) writes NO row, so the ad is
-- retried next run — never poison a transient error into a permanent give-up.

CREATE TABLE IF NOT EXISTS meta_ad_destination_status (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    brand_id        uuid NOT NULL,
    meta_ad_id      text NOT NULL,
    status          text NOT NULL,
    reason          text,
    creative_id     text,
    url_count       integer NOT NULL DEFAULT 0,
    attempted_at    timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT meta_ad_destination_status_brand_ad_uniq UNIQUE (brand_id, meta_ad_id),
    CONSTRAINT meta_ad_destination_status_status_chk
        CHECK (status IN ('no_url', 'multi_url'))
);

-- Selection filter: "ads for this brand whose status is terminal no_url".
CREATE INDEX IF NOT EXISTS idx_mad_status_brand_status
    ON meta_ad_destination_status (brand_id, status);

COMMENT ON TABLE meta_ad_destination_status IS
    'Per-ad destination-URL fetch outcomes (terminal no_url markers + multi_url/DCO flags). Companion to meta_ad_destinations, which only holds found URLs.';
COMMENT ON COLUMN meta_ad_destination_status.status IS
    'no_url = terminal (creative fetched, no link found); multi_url = found but creative had >1 distinct link (DCO).';
COMMENT ON COLUMN meta_ad_destination_status.creative_id IS
    'Creative ID seen at fetch time; lets a future job re-check no_url ads whose creative has since changed.';
COMMENT ON COLUMN meta_ad_destination_status.url_count IS
    'Distinct destination links seen in the creative (>1 => DCO/multi-URL, flagged).';
