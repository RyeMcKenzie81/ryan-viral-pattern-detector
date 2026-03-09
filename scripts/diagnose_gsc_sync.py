#!/usr/bin/env python3
"""
Diagnostic script for GSC site-wide analytics issues.

Checks each step of the GSC sync pipeline to identify where data is being lost:
1. GSC API response (raw row count)
2. Discovered articles in DB
3. Analytics rows for discovered vs tracked articles
4. URL normalization mismatches

Usage:
    python scripts/diagnose_gsc_sync.py <brand_id> [--sync]

    --sync: Run a fresh sync with verbose logging (default: just check DB state)
"""

import argparse
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from viraltracker.core.database import get_supabase_client
from viraltracker.services.seo_pipeline.utils import normalize_url_path


def diagnose(brand_id: str, run_sync: bool = False):
    supabase = get_supabase_client()

    print(f"\n{'='*60}")
    print(f"GSC Sync Diagnostic — Brand: {brand_id}")
    print(f"{'='*60}\n")

    # 1. Check brand exists
    brand = supabase.table("brands").select("name, organization_id").eq("id", brand_id).execute()
    if not brand.data:
        print(f"ERROR: Brand {brand_id} not found")
        return
    brand_name = brand.data[0]["name"]
    org_id = brand.data[0]["organization_id"]
    print(f"Brand: {brand_name}")
    print(f"Org ID: {org_id}\n")

    # 2. Check GSC integration
    integration = (
        supabase.table("brand_integrations")
        .select("config")
        .eq("brand_id", brand_id)
        .eq("platform", "gsc")
        .execute()
    )
    if not integration.data:
        print("ERROR: No GSC integration found for this brand")
        return
    config = integration.data[0]["config"]
    site_url = config.get("site_url", "NOT SET")
    has_token = bool(config.get("access_token"))
    has_refresh = bool(config.get("refresh_token"))
    print(f"GSC Site URL: {site_url}")
    print(f"Has access_token: {has_token}")
    print(f"Has refresh_token: {has_refresh}\n")

    # 3. Check articles
    all_articles = (
        supabase.table("seo_articles")
        .select("id, status, published_url, keyword")
        .eq("brand_id", brand_id)
        .execute()
    ).data or []

    tracked = [a for a in all_articles if a.get("status") != "discovered"]
    discovered = [a for a in all_articles if a.get("status") == "discovered"]

    print(f"--- Articles ---")
    print(f"Total articles: {len(all_articles)}")
    print(f"Tracked (non-discovered): {len(tracked)}")
    print(f"Discovered (GSC auto-created): {len(discovered)}")

    # Check how many have published_url
    tracked_with_url = [a for a in tracked if a.get("published_url")]
    print(f"Tracked with published_url: {len(tracked_with_url)}")

    if tracked_with_url:
        print(f"  Sample tracked URLs:")
        for a in tracked_with_url[:3]:
            path = normalize_url_path(a["published_url"])
            print(f"    {a['published_url']} → normalized: {path}")

    if discovered:
        print(f"  Sample discovered URLs:")
        for a in discovered[:3]:
            path = normalize_url_path(a.get("published_url", ""))
            print(f"    {a.get('published_url', 'NONE')} → normalized: {path}")
    print()

    # 4. Check analytics rows
    tracked_ids = [a["id"] for a in tracked]
    discovered_ids = [a["id"] for a in discovered]

    def count_analytics(article_ids, label):
        if not article_ids:
            print(f"  {label}: 0 rows (no article IDs)")
            return 0
        # Query in batches to avoid URL length issues
        total_impressions = 0
        total_rows = 0
        batch_size = 50
        for i in range(0, len(article_ids), batch_size):
            batch = article_ids[i:i + batch_size]
            rows = (
                supabase.table("seo_article_analytics")
                .select("impressions, clicks")
                .eq("source", "gsc")
                .in_("article_id", batch)
                .execute()
            ).data or []
            total_rows += len(rows)
            total_impressions += sum(r.get("impressions", 0) for r in rows)
        print(f"  {label}: {total_rows} analytics rows, {total_impressions:,} total impressions")
        return total_impressions

    print(f"--- Analytics (seo_article_analytics, source='gsc') ---")
    tracked_imp = count_analytics(tracked_ids, "Tracked articles")
    discovered_imp = count_analytics(discovered_ids, "Discovered articles")
    print(f"  Combined: {tracked_imp + discovered_imp:,} impressions")
    print()

    # 5. Check for "Discovered Pages (GSC)" project
    project = (
        supabase.table("seo_projects")
        .select("id, name")
        .eq("brand_id", brand_id)
        .eq("name", "Discovered Pages (GSC)")
        .execute()
    ).data or []
    if project:
        print(f"Discovered project exists: {project[0]['id']}")
    else:
        print("Discovered project: NOT FOUND (will be created on next sync)")
    print()

    # 6. Optionally run a sync
    if run_sync:
        print(f"{'='*60}")
        print("Running GSC sync with verbose logging...")
        print(f"{'='*60}\n")

        # Enable verbose logging
        logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
        logging.getLogger("viraltracker.services.seo_pipeline").setLevel(logging.DEBUG)

        from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
        gsc = GSCService()

        try:
            result = gsc.sync_to_db(brand_id, org_id, days_back=28)
            print(f"\nSync result: {result}")
        except Exception as e:
            print(f"\nSync FAILED: {e}")
            import traceback
            traceback.print_exc()

        # Re-check state after sync
        print(f"\n{'='*60}")
        print("Post-sync state:")
        print(f"{'='*60}\n")

        all_articles_after = (
            supabase.table("seo_articles")
            .select("id, status")
            .eq("brand_id", brand_id)
            .execute()
        ).data or []
        discovered_after = [a for a in all_articles_after if a.get("status") == "discovered"]
        tracked_after = [a for a in all_articles_after if a.get("status") != "discovered"]
        print(f"Articles: {len(tracked_after)} tracked, {len(discovered_after)} discovered")

        discovered_ids_after = [a["id"] for a in discovered_after]
        print(f"\nPost-sync analytics:")
        count_analytics([a["id"] for a in tracked_after], "Tracked")
        count_analytics(discovered_ids_after, "Discovered")
    else:
        print("Tip: Run with --sync to trigger a fresh sync with verbose logging")
        print(f"  python scripts/diagnose_gsc_sync.py {brand_id} --sync")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose GSC sync issues")
    parser.add_argument("brand_id", help="Brand UUID to diagnose")
    parser.add_argument("--sync", action="store_true", help="Run a fresh sync")
    args = parser.parse_args()
    diagnose(args.brand_id, args.sync)
