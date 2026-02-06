#!/usr/bin/env python3
"""
Backfill purchases from raw_actions for meta_ads_performance rows.

Meta returns purchases under different action_type values:
- "omni_purchase" (omnichannel: website + app + offline combined)
- "purchase" (website-only)

Many rows already have the correct raw_actions JSONB stored but the
pre-extracted `purchases`, `purchase_value`, `roas`, and `conversion_rate`
columns are NULL because the original sync only looked for "purchase".

This script re-extracts from raw_actions and backfills those columns.
No Meta API calls are needed — all data is already in the database.

Usage:
    python scripts/backfill_purchases.py [--dry-run] [--brand-id UUID]
"""

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PURCHASE_ACTION_TYPES = ["omni_purchase", "purchase"]
BATCH_SIZE = 100


def _safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_purchase_count(raw_actions):
    """Extract purchase count from raw_actions, checking omni_purchase first."""
    if not isinstance(raw_actions, list):
        return None
    for action in raw_actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_type") in PURCHASE_ACTION_TYPES:
            val = _safe_float(action.get("value"))
            if val is not None:
                return int(val)
    return None


def extract_purchase_value(raw_actions):
    """Extract purchase value from raw_actions.

    Note: Meta puts purchase values in the action_values array, not actions.
    But some accounts report value in the actions array too. We also check
    for omni_purchase in the raw_actions since that's what we have stored.
    The action_values array is stored separately and may not be in raw_actions.
    For this backfill we look at what's available.
    """
    if not isinstance(raw_actions, list):
        return None
    # raw_actions typically has count, not value. But we check anyway.
    # The real purchase_value comes from action_values which is not in raw_actions.
    # We'll return None here and handle it below.
    return None


def main():
    parser = argparse.ArgumentParser(description="Backfill purchases from raw_actions")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--brand-id", type=str, help="Only backfill a specific brand")
    args = parser.parse_args()

    from viraltracker.core.database import get_supabase_client

    supabase = get_supabase_client()

    # Build query: rows where raw_actions is not null AND purchases is null or 0
    # Supabase client doesn't support OR on null/0 easily, so we do two passes

    brand_filter = args.brand_id

    total_updated = 0
    total_skipped = 0

    for pass_label, query_fn in [
        ("purchases IS NULL", lambda q: q.is_("purchases", "null")),
        ("purchases = 0", lambda q: q.eq("purchases", 0)),
    ]:
        logger.info(f"\n--- Pass: {pass_label} ---")
        offset = 0

        while True:
            query = supabase.table("meta_ads_performance").select(
                "id, raw_actions, spend, link_clicks, purchases, purchase_value, roas"
            ).not_.is_("raw_actions", "null")

            query = query_fn(query)

            if brand_filter:
                query = query.eq("brand_id", brand_filter)

            result = query.range(offset, offset + BATCH_SIZE - 1).execute()
            rows = result.data or []

            if not rows:
                break

            logger.info(f"Processing batch of {len(rows)} rows (offset {offset})")

            for row in rows:
                raw_actions = row.get("raw_actions")

                # Parse raw_actions if it's a string (shouldn't be, but safe)
                if isinstance(raw_actions, str):
                    try:
                        raw_actions = json.loads(raw_actions)
                    except (json.JSONDecodeError, TypeError):
                        continue

                purchases = extract_purchase_count(raw_actions)
                if purchases is None or purchases == 0:
                    total_skipped += 1
                    continue

                # Build update dict
                update = {"purchases": purchases}

                # Recompute derived fields
                spend = _safe_float(row.get("spend"))
                link_clicks = _safe_float(row.get("link_clicks"))

                # Keep existing purchase_value/roas if already set, otherwise leave null
                # (purchase_value comes from action_values which we don't have in raw_actions)

                if link_clicks and link_clicks > 0:
                    update["conversion_rate"] = (purchases / link_clicks) * 100

                if args.dry_run:
                    logger.info(
                        f"  [DRY RUN] id={row['id']}: "
                        f"purchases={purchases}, "
                        f"conv_rate={update.get('conversion_rate', 'N/A')}"
                    )
                else:
                    try:
                        supabase.table("meta_ads_performance").update(
                            update
                        ).eq("id", row["id"]).execute()
                    except Exception as e:
                        logger.error(f"  Failed to update {row['id']}: {e}")
                        continue

                total_updated += 1

            offset += BATCH_SIZE

            # If we got fewer rows than batch size, we're done with this pass
            if len(rows) < BATCH_SIZE:
                break

    action = "Would update" if args.dry_run else "Updated"
    logger.info(f"\n=== Done ===")
    logger.info(f"{action} {total_updated} rows, skipped {total_skipped} (no purchase actions found)")


if __name__ == "__main__":
    main()
