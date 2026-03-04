#!/usr/bin/env python3
"""
Phase 0 Cleanup Script
Deactivates duplicate scraped_templates rows and deletes orphaned product_template_usage rows.

Fix #3: 12 storage_paths have 2 active scraped_templates rows each (from scrape runs
on 2026-01-15 and 2026-01-23). Deactivate the older (2026-01-15) row for each pair.

Fix #4: 53 product_template_usage rows have NULL template_id — orphaned legacy records
whose template_storage_name doesn't match any scraped_templates.storage_path. Delete them.
"""

import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from viraltracker.core.database import get_supabase_client


def fix_duplicate_templates(db, dry_run: bool = True):
    """
    Fix #3: Deactivate older duplicate scraped_templates rows.

    For each storage_path with 2 active rows, deactivate the one with the
    earlier created_at (2026-01-15 run), keeping the newer one (2026-01-23 run).
    """
    print("=" * 60)
    print("FIX #3: Deactivate duplicate scraped_templates rows")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("-" * 60)

    # Fetch all active templates
    result = db.table("scraped_templates") \
        .select("id,storage_path,created_at,is_active") \
        .eq("is_active", True) \
        .execute()

    # Find storage_paths with duplicates
    paths = [r["storage_path"] for r in result.data if r.get("storage_path")]
    counts = Counter(paths)
    duplicate_paths = {path for path, cnt in counts.items() if cnt > 1}

    if not duplicate_paths:
        print("  No duplicate storage_paths found. Nothing to do.")
        return 0

    print(f"  Found {len(duplicate_paths)} storage_paths with duplicates")

    # For each duplicate path, find the older row to deactivate
    deactivated = 0
    for path in sorted(duplicate_paths):
        rows = [r for r in result.data if r["storage_path"] == path]
        rows.sort(key=lambda r: r["created_at"])

        # Deactivate all but the newest
        for row in rows[:-1]:
            row_id = row["id"]
            created = row["created_at"][:10]
            print(f"  Deactivating: {path}")
            print(f"    ID: {row_id}, created: {created}")

            if not dry_run:
                db.table("scraped_templates") \
                    .update({"is_active": False}) \
                    .eq("id", row_id) \
                    .execute()

            deactivated += 1

    action = "Would deactivate" if dry_run else "Deactivated"
    print(f"\n  {action} {deactivated} rows")
    return deactivated


def fix_orphaned_usage_rows(db, dry_run: bool = True):
    """
    Fix #4: Delete orphaned product_template_usage rows.

    These are legacy rows where template_id IS NULL — their template_storage_name
    doesn't match any scraped_templates.storage_path, so template_id will never
    be populated. They're inert tracking records from the old workflow.
    """
    print("\n" + "=" * 60)
    print("FIX #4: Delete orphaned product_template_usage rows")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("-" * 60)

    # Find rows with NULL template_id
    result = db.table("product_template_usage") \
        .select("id,template_storage_name,product_id", count="exact") \
        .is_("template_id", "null") \
        .execute()

    count = result.count if result.count is not None else len(result.data)

    if count == 0:
        print("  No orphaned usage rows found. Nothing to do.")
        return 0

    print(f"  Found {count} orphaned usage rows (template_id IS NULL)")

    # Show a sample
    for row in result.data[:5]:
        print(f"    ID: {row['id']}, storage_name: {row.get('template_storage_name', 'N/A')}")
    if count > 5:
        print(f"    ... and {count - 5} more")

    if not dry_run:
        # Delete in batches by ID
        ids_to_delete = [row["id"] for row in result.data]
        batch_size = 50
        deleted = 0
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i + batch_size]
            db.table("product_template_usage") \
                .delete() \
                .in_("id", batch) \
                .execute()
            deleted += len(batch)
        print(f"\n  Deleted {deleted} rows")
        return deleted
    else:
        print(f"\n  Would delete {count} rows")
        return count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 0 cleanup: fix duplicates and orphans")
    parser.add_argument("--live", action="store_true",
                        help="Actually perform changes (default is dry run)")
    args = parser.parse_args()

    dry_run = not args.live

    print("\nPhase 0 Cleanup Script")
    print("=" * 60)
    if dry_run:
        print("MODE: DRY RUN (use --live to apply changes)")
    else:
        print("MODE: LIVE — changes will be applied!")
    print()

    db = get_supabase_client()

    fix_duplicate_templates(db, dry_run=dry_run)
    fix_orphaned_usage_rows(db, dry_run=dry_run)

    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    if dry_run:
        print("Re-run with --live to apply changes.")
    print("=" * 60)


if __name__ == "__main__":
    main()
