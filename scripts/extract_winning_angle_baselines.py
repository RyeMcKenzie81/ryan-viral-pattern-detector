#!/usr/bin/env python3
"""
Extract winning-ad baselines for the angle-driven-ad-creator V1.

Pulls top performers from Meta ads performance data for a chosen brand
(optionally filtered by ad_name prefix) and produces a baseline reference set
that the new AngleGeneratorService output will be compared against.

Two ranking populations are reported (and deduped on overlap):
  - Top N by weighted ROAS (filter: total spend >= --min-spend over the window)
  - Top N by total spend (no ROAS filter — captures proven-to-scale ads)

Premium-intent winners + proven-to-scale winners are different populations and
they test different angles. Capturing both gives the angle generator a broader
reference set when calibration time comes.

Default behavior is --list-only: prints the ranked tables to stdout, no LLM
calls, no markdown output. Pass --extract-angles to additionally run Claude
Opus 4.7 angle inference on each winning ad and write the markdown baseline
to docs/plans/angle-driven-ad-creator/BASELINE_WINNERS.md.

Usage:
    # Step 1 — see what's there
    python scripts/extract_winning_angle_baselines.py \\
        --brand-name "Martin Clinic" --ad-name-prefix "m5-" --list-only

    # Step 2 — once happy with the list, run angle inference
    python scripts/extract_winning_angle_baselines.py \\
        --brand-name "Martin Clinic" --ad-name-prefix "m5-" --extract-angles

Reads OPENAI_API_KEY + ANTHROPIC_API_KEY from env (only needed with --extract-angles).
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = "docs/plans/angle-driven-ad-creator/BASELINE_WINNERS.md"
DEFAULT_TOP_N = 5
DEFAULT_DAYS = 60
DEFAULT_MIN_SPEND = 150.0


def resolve_brand_id(supabase, brand_name: str) -> str:
    """Look up brand_id by name (exact match). Raises if not found or ambiguous."""
    result = (
        supabase.table("brands")
        .select("id, name")
        .ilike("name", brand_name)
        .execute()
        .data
        or []
    )
    if not result:
        raise ValueError(f"No brand found matching name: {brand_name!r}")
    if len(result) > 1:
        names = [r["name"] for r in result]
        raise ValueError(
            f"Multiple brands match {brand_name!r}: {names}. Pass --brand-id <UUID> instead."
        )
    logger.info(f"Resolved brand_name={brand_name!r} → brand_id={result[0]['id']}")
    return result[0]["id"]


def fetch_ad_performance(
    supabase,
    brand_id: str,
    ad_name_filter: str,
    match_mode: str,
    days: int,
):
    """
    Pull meta_ads_performance rows for the brand + name filter + window.
    Returns aggregated metrics per meta_ad_id.

    Args:
        ad_name_filter: substring to search for in ad_name (case-insensitive).
            Empty string disables the filter (returns all brand ads).
        match_mode: how to apply the filter — one of 'prefix', 'contains', 'suffix'.
            Ad ops teams often embed a creator tag (e.g. "_m5-") mid-name rather
            than as a true prefix; default 'contains' handles both cases.

    Aggregation per meta_ad_id:
        total_spend = sum(spend)
        total_purchase_value = sum(purchase_value)
        total_impressions = sum(impressions)
        total_purchases = sum(purchases)
        weighted_roas = total_purchase_value / total_spend (only if spend > 0)
        ad_name = most recent non-null ad_name in the window
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    if match_mode == "prefix":
        pattern = f"{ad_name_filter}%"
    elif match_mode == "suffix":
        pattern = f"%{ad_name_filter}"
    else:  # contains (default)
        pattern = f"%{ad_name_filter}%"

    # Paginate to handle large result sets (Supabase default limit is 1000)
    all_rows = []
    offset = 0
    while True:
        query = (
            supabase.table("meta_ads_performance")
            .select("meta_ad_id, ad_name, date, spend, impressions, purchases, purchase_value, roas")
            .eq("brand_id", brand_id)
            .gte("date", since)
        )
        if ad_name_filter:
            query = query.ilike("ad_name", pattern)
        rows = query.limit(1000).offset(offset).execute().data or []
        all_rows.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    logger.info(
        f"Fetched {len(all_rows)} performance rows "
        f"(brand_id={brand_id}, filter={ad_name_filter!r}, mode={match_mode}, since={since})"
    )

    # Aggregate per ad
    agg = defaultdict(lambda: {
        "spend": 0.0, "purchase_value": 0.0, "impressions": 0,
        "purchases": 0, "ad_name": None, "latest_date": None,
    })
    for r in all_rows:
        mid = r["meta_ad_id"]
        a = agg[mid]
        a["spend"] += float(r.get("spend") or 0)
        a["purchase_value"] += float(r.get("purchase_value") or 0)
        a["impressions"] += int(r.get("impressions") or 0)
        a["purchases"] += int(r.get("purchases") or 0)
        # Keep the most recent non-null ad_name
        name = r.get("ad_name")
        date = r.get("date")
        if name and (a["latest_date"] is None or date > a["latest_date"]):
            a["ad_name"] = name
            a["latest_date"] = date

    # Compute weighted ROAS per ad
    ads = []
    for mid, a in agg.items():
        weighted_roas = a["purchase_value"] / a["spend"] if a["spend"] > 0 else 0.0
        ads.append({
            "meta_ad_id": mid,
            "ad_name": a["ad_name"] or "(no name)",
            "total_spend": round(a["spend"], 2),
            "weighted_roas": round(weighted_roas, 4),
            "total_impressions": a["impressions"],
            "total_purchases": a["purchases"],
            "purchase_value": round(a["purchase_value"], 2),
        })

    logger.info(f"Aggregated to {len(ads)} unique ads")
    return ads


def rank_winners(ads: list, top_n: int, min_spend: float):
    """Return (top_by_roas, top_by_spend, deduped_union)."""
    # Top by ROAS — filter by min spend first
    roas_pool = [a for a in ads if a["total_spend"] >= min_spend]
    top_roas = sorted(roas_pool, key=lambda x: x["weighted_roas"], reverse=True)[:top_n]

    # Top by spend — no ROAS filter
    top_spend = sorted(ads, key=lambda x: x["total_spend"], reverse=True)[:top_n]

    # Dedupe — preserve first-seen order from concatenation (roas first, then spend)
    seen_ids = set()
    union = []
    for a in top_roas + top_spend:
        if a["meta_ad_id"] not in seen_ids:
            union.append(a)
            seen_ids.add(a["meta_ad_id"])

    return top_roas, top_spend, union


def fetch_generated_ad_metadata(supabase, ad_names: list) -> dict:
    """
    Try to match Meta ad_names to generated_ads rows via storage_path basename.
    Returns dict {ad_name: {hook_text, prompt_spec, ...}} for matched rows.

    The match is best-effort — many Meta ads won't have a corresponding
    generated_ads row (older flows, hand-uploaded ads), and that's fine.
    """
    if not ad_names:
        return {}

    # generated_ads.storage_path contains a path whose basename often matches ad_name
    # We can't do a Supabase string-function query cheaply, so pull recent generated_ads
    # and match in Python. Bounded to last 180 days for sanity.
    since = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    rows = (
        supabase.table("generated_ads")
        .select("storage_path, hook_text, meta_headline, meta_primary_text, angle_id, prompt_spec, created_at")
        .gte("created_at", since)
        .limit(5000)
        .execute()
        .data
        or []
    )

    # Build basename index
    by_basename = {}
    for r in rows:
        sp = r.get("storage_path") or ""
        basename = sp.rsplit("/", 1)[-1].rsplit(".", 1)[0]  # strip directory + extension
        if basename:
            by_basename[basename] = r

    matched = {}
    for name in ad_names:
        # Try exact basename, then prefix match
        if name in by_basename:
            matched[name] = by_basename[name]
        else:
            # Prefix match: maybe ad_name is the basename without a suffix
            for bn, row in by_basename.items():
                if bn.startswith(name) or name.startswith(bn):
                    matched[name] = row
                    break

    logger.info(f"Matched {len(matched)}/{len(ad_names)} ads to generated_ads metadata")
    return matched


def print_ranked_table(title: str, ads: list):
    """Print a markdown-ish ranked table to stdout."""
    print(f"\n=== {title} ===")
    if not ads:
        print("  (no ads qualify)")
        return
    print(f"  {'#':<3} {'ad_name':<40} {'spend':>10} {'roas':>8} {'purchases':>10}")
    print(f"  {'-'*3} {'-'*40} {'-'*10} {'-'*8} {'-'*10}")
    for i, a in enumerate(ads, 1):
        name = a["ad_name"][:38] + ".." if len(a["ad_name"]) > 40 else a["ad_name"]
        print(f"  {i:<3} {name:<40} ${a['total_spend']:>9,.2f} {a['weighted_roas']:>8.2f} {a['total_purchases']:>10}")


def infer_angles(union_ads: list, ad_metadata: dict):
    """Call Claude Opus 4.7 to reverse-engineer the angle from each ad's hook + metadata."""
    import anthropic
    client = anthropic.Anthropic()

    results = []
    for ad in union_ads:
        meta = ad_metadata.get(ad["ad_name"], {})
        hook_text = meta.get("hook_text") or "(no hook_text — Meta ad not linked to generated_ads)"
        meta_headline = meta.get("meta_headline") or ""
        meta_primary_text = meta.get("meta_primary_text") or ""

        prompt = f"""You are reverse-engineering the strategic ANGLE behind a Facebook ad
that performed well. The angle is the underlying BELIEF the ad is built on (not
the hook copy, not the offer). Look at the hook + ad copy and infer:

1. The CORE BELIEF the ad is testing (one sentence, in the format
   "X is what's holding the customer back; Y is what unlocks the result")
2. The IMPLICIT VILLAIN (what the customer has been blaming/believing that this
   ad reframes — one short phrase)
3. The PRIMARY DESIRE category (one of: survival/life-extension, freedom-from-fear,
   social-approval, superiority-status, comfortable-living, care-protection,
   self-actualization)
4. The TRANSFORMATION promised (current state → desired state, one sentence)

AD DATA:
  Hook text: {hook_text}
  Meta headline: {meta_headline}
  Meta primary text: {meta_primary_text}

Return strict JSON with fields: belief, villain, desire, transformation. No preamble."""

        try:
            response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            results.append({"ad": ad, "metadata": meta, "inferred": text})
        except Exception as e:
            logger.error(f"Angle inference failed for {ad['ad_name']}: {e}")
            results.append({"ad": ad, "metadata": meta, "inferred": f"ERROR: {e}"})

    return results


def write_baseline_markdown(output_path: Path, results: list, top_roas: list, top_spend: list, args):
    """Write the BASELINE_WINNERS.md report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        f.write(f"# Baseline Winners — {args.brand_name or args.brand_id}\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Window: last {args.days} days  |  Ad-name prefix: `{args.ad_name_prefix}`\n")
        f.write(f"Top N: {args.top_n}  |  Min spend for ROAS ranking: ${args.min_spend:,.2f}\n\n")
        f.write("Two ranking populations are captured: top by weighted ROAS (premium-intent)\n")
        f.write("and top by total spend (proven-to-scale). The angle generator's V1 output\n")
        f.write("must at least match the angles represented in these winners.\n\n")

        f.write("## Top by Weighted ROAS\n\n")
        for i, a in enumerate(top_roas, 1):
            f.write(f"{i}. **{a['ad_name']}** — ROAS {a['weighted_roas']:.2f}, spend ${a['total_spend']:,.2f}, "
                    f"{a['total_purchases']} purchases\n")

        f.write("\n## Top by Total Spend\n\n")
        for i, a in enumerate(top_spend, 1):
            f.write(f"{i}. **{a['ad_name']}** — spend ${a['total_spend']:,.2f}, ROAS {a['weighted_roas']:.2f}, "
                    f"{a['total_purchases']} purchases\n")

        f.write("\n---\n\n## Reverse-Engineered Angles\n\n")
        for r in results:
            ad = r["ad"]
            f.write(f"### {ad['ad_name']}\n")
            f.write(f"- Spend: ${ad['total_spend']:,.2f}  |  ROAS: {ad['weighted_roas']:.2f}  |  Purchases: {ad['total_purchases']}\n")
            if r["metadata"].get("hook_text"):
                f.write(f"- Hook: _{r['metadata']['hook_text']}_\n")
            f.write(f"\n**Inferred angle:**\n```json\n{r['inferred']}\n```\n\n")

    logger.info(f"Wrote {output_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--brand-name", type=str, help="Brand name to look up (case-insensitive)")
    group.add_argument("--brand-id", type=str, help="Brand UUID (skip name lookup)")
    parser.add_argument("--ad-name-filter", type=str, default="",
                        help="Filter ads by ad_name substring (e.g. 'm5-'). Empty = all brand ads.")
    parser.add_argument("--match-mode", type=str, default="contains",
                        choices=["prefix", "contains", "suffix"],
                        help="How to interpret --ad-name-filter (default: contains). "
                             "Ad ops teams often embed creator tags mid-name (e.g. '_m5-' "
                             "inside 'Ryan Antibiotics_m5-MC-XX-...'), so 'contains' is the "
                             "safe default. Use 'prefix' only when the tag actually starts the name.")
    # Back-compat alias for the original --ad-name-prefix flag (forces match-mode='prefix')
    parser.add_argument("--ad-name-prefix", type=str, default=None,
                        help="(Deprecated) Alias for --ad-name-filter with --match-mode prefix")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Look-back window in days (default: {DEFAULT_DAYS})")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help=f"Top N to keep in each ranking (default: {DEFAULT_TOP_N})")
    parser.add_argument("--min-spend", type=float, default=DEFAULT_MIN_SPEND,
                        help=f"Min total spend (USD) for ROAS-ranking eligibility (default: ${DEFAULT_MIN_SPEND})")
    parser.add_argument("--list-only", action="store_true", default=True,
                        help="Print ranked lists to stdout, skip LLM angle inference + markdown output (DEFAULT)")
    parser.add_argument("--extract-angles", action="store_true",
                        help="Override --list-only: run Claude Opus 4.7 angle inference and write markdown")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT,
                        help=f"Output markdown path when --extract-angles (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    if args.extract_angles:
        args.list_only = False

    # Back-compat: if old --ad-name-prefix was used, route to filter+prefix mode
    if args.ad_name_prefix is not None and not args.ad_name_filter:
        args.ad_name_filter = args.ad_name_prefix
        args.match_mode = "prefix"

    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()

    brand_id = args.brand_id or resolve_brand_id(supabase, args.brand_name)

    ads = fetch_ad_performance(
        supabase,
        brand_id=brand_id,
        ad_name_filter=args.ad_name_filter,
        match_mode=args.match_mode,
        days=args.days,
    )
    if not ads:
        logger.info("No ads found. Exiting.")
        return 0

    top_roas, top_spend, union = rank_winners(ads, top_n=args.top_n, min_spend=args.min_spend)

    print_ranked_table(f"TOP {args.top_n} BY WEIGHTED ROAS (min spend ${args.min_spend:,.2f})", top_roas)
    print_ranked_table(f"TOP {args.top_n} BY TOTAL SPEND", top_spend)
    print(f"\nDeduped union: {len(union)} unique ads")

    if args.list_only:
        print(
            "\n--list-only mode: skipping LLM angle inference and markdown output. "
            "Re-run with --extract-angles to perform reverse-engineering on the union set."
        )
        return 0

    logger.info("Fetching generated_ads metadata for hook_text + copy linkage...")
    ad_metadata = fetch_generated_ad_metadata(supabase, [a["ad_name"] for a in union])

    logger.info(f"Running Claude Opus 4.7 angle inference on {len(union)} ads...")
    results = infer_angles(union, ad_metadata)

    output_path = Path(args.output)
    write_baseline_markdown(output_path, results, top_roas, top_spend, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
