-- Migration: Cluster Builder provenance columns on seo_clusters
-- Date: 2026-06-11
-- Purpose: Let the Cluster Builder (Top Movers -> "Build out this cluster") mark
--          clusters it creates and remember which winning article seeded them, so
--          re-running the build is idempotent (reuse the same cluster instead of
--          creating a duplicate) and builder-created clusters are auditable.
--
-- Note: seo_clusters has NO organization_id; tenant isolation is via
--       seo_projects(organization_id). These columns are nullable and additive
--       (no backfill required).

ALTER TABLE seo_clusters
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS created_from_article_id UUID
        REFERENCES seo_articles(id) ON DELETE SET NULL;

COMMENT ON COLUMN seo_clusters.source IS
    'Provenance of the cluster, e.g. ''cluster_builder'' when built from a Top Mover. NULL for manually-created clusters.';
COMMENT ON COLUMN seo_clusters.created_from_article_id IS
    'The winning (Top Mover) article this cluster was built from, if any. Drives idempotent re-runs of the Cluster Builder.';

-- Idempotency / reuse lookup: find the builder cluster for a given seed article.
CREATE INDEX IF NOT EXISTS idx_seo_clusters_created_from_article
    ON seo_clusters (created_from_article_id)
    WHERE created_from_article_id IS NOT NULL;
