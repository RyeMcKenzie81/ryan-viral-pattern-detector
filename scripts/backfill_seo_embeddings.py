#!/usr/bin/env python3
"""
Backfill SEO keyword embeddings and cluster centroids.

One-time utility to embed existing keywords that have NULL embedding
and recompute all cluster centroids.

Usage:
    python scripts/backfill_seo_embeddings.py [--project-id UUID] [--dry-run]
"""

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill_keywords(supabase, project_id=None, dry_run=False):
    """Embed all keywords with NULL embedding."""
    from viraltracker.core.embeddings import create_seo_embedder

    query = (
        supabase.table("seo_keywords")
        .select("id, keyword")
        .is_("embedding", "null")
    )
    if project_id:
        query = query.eq("project_id", project_id)

    rows = query.limit(5000).execute().data or []
    logger.info(f"Found {len(rows)} keywords without embeddings")

    if dry_run:
        logger.info("Dry run — would embed %d keywords", len(rows))
        return 0

    if not rows:
        return 0

    embedder = create_seo_embedder()
    embedded = 0

    # Process in batches of 100
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        texts = [r["keyword"] for r in batch]
        ids = [r["id"] for r in batch]

        try:
            vectors = embedder.embed_texts(texts, task_type="CLUSTERING")
            for kw_id, vec in zip(ids, vectors):
                supabase.table("seo_keywords").update(
                    {"embedding": vec}
                ).eq("id", kw_id).execute()
                embedded += 1
        except Exception as e:
            logger.error(f"Batch {i // 100 + 1} failed: {e}")
            continue

        logger.info(f"Embedded {embedded}/{len(rows)} keywords...")

    logger.info(f"Backfill complete: {embedded}/{len(rows)} keywords embedded")
    return embedded


def recompute_centroids(supabase, project_id=None, dry_run=False):
    """Recompute centroids for all clusters."""
    from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService

    query = supabase.table("seo_clusters").select("id, name")
    if project_id:
        query = query.eq("project_id", project_id)

    clusters = query.execute().data or []
    logger.info(f"Found {len(clusters)} clusters to recompute centroids")

    if dry_run:
        logger.info("Dry run — would recompute %d centroids", len(clusters))
        return

    svc = ClusterManagementService(supabase_client=supabase)
    for cluster in clusters:
        try:
            svc.recompute_centroid(cluster["id"])
            logger.info(f"Recomputed centroid for cluster '{cluster['name']}'")
        except Exception as e:
            logger.warning(f"Failed to recompute centroid for {cluster['id']}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Backfill SEO keyword embeddings")
    parser.add_argument("--project-id", help="Limit to a specific project UUID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without changes")
    parser.add_argument("--skip-centroids", action="store_true", help="Skip centroid recomputation")
    args = parser.parse_args()

    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()

    # Step 1: Embed keywords
    embedded = backfill_keywords(supabase, project_id=args.project_id, dry_run=args.dry_run)

    # Step 2: Recompute centroids
    if not args.skip_centroids:
        recompute_centroids(supabase, project_id=args.project_id, dry_run=args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
