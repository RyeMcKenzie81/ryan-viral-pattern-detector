#!/usr/bin/env python3
"""
Phase 0 Migration Gate Audit
Runs 6 audit queries against Supabase to verify migration readiness.
"""

import sys
import os
from collections import Counter

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from viraltracker.core.database import get_supabase_client


def check_ambiguous_template_mappings(db):
    """
    Query 1: Check for ambiguous template mappings.
    SELECT storage_path, COUNT(*) as cnt
    FROM scraped_templates
    WHERE is_active = TRUE
    GROUP BY storage_path
    HAVING COUNT(*) > 1;
    """
    print("=" * 60)
    print("QUERY 1: Ambiguous template mappings")
    print("  (active scraped_templates with duplicate storage_path)")
    print("-" * 60)

    try:
        result = db.table("scraped_templates") \
            .select("storage_path") \
            .eq("is_active", True) \
            .execute()

        paths = [r["storage_path"] for r in result.data if r.get("storage_path")]
        counts = Counter(paths)
        duplicates = {path: cnt for path, cnt in counts.items() if cnt > 1}

        if duplicates:
            print("  FOUND DUPLICATES:")
            for path, cnt in sorted(duplicates.items(), key=lambda x: -x[1]):
                print(f"    {path}: {cnt} active rows")
            print(f"\n  RESULT: FAIL - {len(duplicates)} ambiguous storage_path(s)")
        else:
            print(f"  Total active templates checked: {len(paths)}")
            print("  RESULT: PASS - No ambiguous template mappings found")
    except Exception as e:
        print(f"  ERROR: {e}")


def check_unmapped_usage_rows(db):
    """
    Query 2: Check for unmapped usage rows.
    SELECT COUNT(*) FROM product_template_usage WHERE template_id IS NULL;
    """
    print("\n" + "=" * 60)
    print("QUERY 2: Unmapped usage rows")
    print("  (product_template_usage where template_id IS NULL)")
    print("-" * 60)

    try:
        result = db.table("product_template_usage") \
            .select("id", count="exact") \
            .is_("template_id", "null") \
            .execute()

        count = result.count if result.count is not None else len(result.data)

        if count > 0:
            print(f"  RESULT: WARN - {count} usage rows with NULL template_id")
        else:
            print(f"  RESULT: PASS - No unmapped usage rows (all have template_id)")
    except Exception as e:
        print(f"  ERROR: {e}")


def check_column_exists(db, table_name, column_name, query_num):
    """
    Queries 3-6: Verify a column exists on a table by attempting to select it.
    """
    print("\n" + "=" * 60)
    print(f"QUERY {query_num}: Column '{column_name}' on '{table_name}'")
    print("-" * 60)

    try:
        # Try selecting just that column with limit 1
        result = db.table(table_name) \
            .select(column_name) \
            .limit(1) \
            .execute()

        # If we get here without error, the column exists
        print(f"  RESULT: PASS - Column '{column_name}' exists on '{table_name}'")
        if result.data:
            sample_val = result.data[0].get(column_name)
            val_type = type(sample_val).__name__ if sample_val is not None else "NULL"
            print(f"  Sample value: {repr(sample_val)} (type: {val_type})")
        else:
            print(f"  (table is empty or no rows returned, but column exists)")
    except Exception as e:
        error_str = str(e)
        if "does not exist" in error_str or "column" in error_str.lower():
            print(f"  RESULT: FAIL - Column '{column_name}' does NOT exist on '{table_name}'")
        else:
            print(f"  RESULT: ERROR - {e}")


def main():
    print("\nPhase 0 Migration Gate Audit")
    print("=" * 60)
    print()

    db = get_supabase_client()

    # Query 1: Ambiguous template mappings
    check_ambiguous_template_mappings(db)

    # Query 2: Unmapped usage rows
    check_unmapped_usage_rows(db)

    # Query 3: campaign_objective on meta_ads_performance
    check_column_exists(db, "meta_ads_performance", "campaign_objective", 3)

    # Query 4: metadata on scheduled_job_runs
    check_column_exists(db, "scheduled_job_runs", "metadata", 4)

    # Query 5: canvas_size on generated_ads
    check_column_exists(db, "generated_ads", "canvas_size", 5)

    # Query 6: template_selection_config on brands
    check_column_exists(db, "brands", "template_selection_config", 6)

    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
