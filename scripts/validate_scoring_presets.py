#!/usr/bin/env python3
"""
One-time analysis script: Validate scoring presets against real DB data.

Connects to Supabase, fetches template candidates for >= 5 brands,
runs 100 selections per brand per preset (Roll the Dice / Smart Select),
and produces a diversity report.

Usage:
    python scripts/validate_scoring_presets.py
    python scripts/validate_scoring_presets.py --output report.json
    python scripts/validate_scoring_presets.py --min-brands 3

NOT part of CI — manual execution only.
"""

import argparse
import asyncio
import json
import math
import sys
from collections import Counter
from uuid import UUID

import numpy as np


def diversity_score(freq: Counter) -> float:
    """Shannon entropy normalized to [0, 1]."""
    total = sum(freq.values())
    if total == 0 or len(freq) <= 1:
        return 0.0

    max_entropy = math.log(len(freq))
    if max_entropy == 0:
        return 0.0

    entropy = 0.0
    for count in freq.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log(p)

    return entropy / max_entropy


def repeat_rate(freq: Counter, n_runs: int) -> float:
    """Ratio of total selections to unique templates."""
    total = sum(freq.values())
    unique = len(freq)
    if unique == 0:
        return 0.0
    return total / unique


def analyze_preset(
    candidates: list[dict],
    context,
    weights: dict[str, float],
    n_runs: int = 100,
) -> dict:
    """Run n_runs selections and analyze diversity."""
    from viraltracker.services.template_scoring_service import (
        PHASE_4_SCORERS,
        select_templates,
    )

    freq: Counter = Counter()
    category_freq: Counter = Counter()

    for _ in range(n_runs):
        result = select_templates(
            candidates=candidates,
            context=context,
            scorers=PHASE_4_SCORERS,
            weights=weights,
            count=1,
        )
        for t in result.templates:
            freq[t["id"]] += 1
            category_freq[t.get("category", "unknown")] += 1

    top_5 = freq.most_common(5)
    ds = diversity_score(freq)
    rr = repeat_rate(freq, n_runs)

    return {
        "total_candidates": len(candidates),
        "unique_selected": len(freq),
        "diversity_score": round(ds, 4),
        "repeat_rate": round(rr, 2),
        "category_distribution": dict(category_freq),
        "top_5_templates": [
            {"id": tid, "count": cnt, "pct": round(cnt / n_runs * 100, 1)}
            for tid, cnt in top_5
        ],
        "max_dominance_pct": round(
            max(freq.values()) / n_runs * 100, 1
        ) if freq else 0.0,
    }


async def fetch_brands_with_products() -> list[dict]:
    """Fetch brands that have at least one product."""
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    # Get brands
    brands_result = db.table("brands").select("id, name").execute()
    brands = brands_result.data or []

    # Get products per brand
    result = []
    for brand in brands:
        products_result = (
            db.table("products")
            .select("id, name")
            .eq("brand_id", brand["id"])
            .limit(1)
            .execute()
        )
        if products_result.data:
            result.append({
                "brand_id": brand["id"],
                "brand_name": brand["name"],
                "product_id": products_result.data[0]["id"],
                "product_name": products_result.data[0]["name"],
            })

    return result


async def main(min_brands: int = 5, output_file: str | None = None, n_runs: int = 100):
    """Run the validation."""
    from viraltracker.services.template_scoring_service import (
        ROLL_THE_DICE_WEIGHTS,
        SMART_SELECT_WEIGHTS,
        SelectionContext,
        fetch_template_candidates,
        prefetch_product_asset_tags,
    )

    print("=" * 60)
    print("SCORING PRESET VALIDATION REPORT")
    print("=" * 60)

    # Fetch brands
    brands = await fetch_brands_with_products()
    print(f"\nFound {len(brands)} brands with products")

    if len(brands) < min_brands:
        print(f"\nWARNING: Only {len(brands)} brands available (need {min_brands})")
        print("Proceeding with available brands...")

    report = {
        "brands_analyzed": len(brands),
        "selections_per_brand": n_runs,
        "presets": {},
    }

    for preset_name, weights in [
        ("roll_the_dice", ROLL_THE_DICE_WEIGHTS),
        ("smart_select", SMART_SELECT_WEIGHTS),
    ]:
        print(f"\n{'─' * 40}")
        print(f"PRESET: {preset_name}")
        print(f"{'─' * 40}")

        preset_results = []

        for brand in brands:
            print(f"\n  Brand: {brand['brand_name']}")
            print(f"  Product: {brand['product_name']}")

            # Fetch candidates
            candidates = await fetch_template_candidates(brand["product_id"])
            print(f"  Candidates: {len(candidates)}")

            if not candidates:
                print("  SKIPPED (no candidates)")
                continue

            # Fetch asset tags
            asset_tags = await prefetch_product_asset_tags(brand["product_id"])
            print(f"  Asset tags: {len(asset_tags)}")

            context = SelectionContext(
                product_id=UUID(brand["product_id"]),
                brand_id=UUID(brand["brand_id"]),
                product_asset_tags=asset_tags,
            )

            np.random.seed(42)
            analysis = analyze_preset(candidates, context, weights, n_runs)

            print(f"  Unique selected: {analysis['unique_selected']}/{analysis['total_candidates']}")
            print(f"  Diversity score: {analysis['diversity_score']}")
            print(f"  Repeat rate: {analysis['repeat_rate']}")
            print(f"  Max dominance: {analysis['max_dominance_pct']}%")
            print(f"  Categories: {analysis['category_distribution']}")
            print(f"  Top 5: {', '.join(f'{t['id']}({t['pct']}%)' for t in analysis['top_5_templates'])}")

            preset_results.append({
                "brand": brand["brand_name"],
                "product": brand["product_name"],
                **analysis,
            })

        report["presets"][preset_name] = preset_results

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")

    for preset_name, results in report["presets"].items():
        if not results:
            print(f"\n{preset_name}: No results")
            continue

        avg_diversity = sum(r["diversity_score"] for r in results) / len(results)
        avg_repeat = sum(r["repeat_rate"] for r in results) / len(results)
        max_dom = max(r["max_dominance_pct"] for r in results)

        print(f"\n{preset_name}:")
        print(f"  Avg diversity score: {avg_diversity:.4f}")
        print(f"  Avg repeat rate: {avg_repeat:.2f}")
        print(f"  Worst dominance: {max_dom}%")

        # PASS/FAIL
        if max_dom > 40:
            print(f"  VERDICT: FAIL (dominance {max_dom}% > 40%)")
        elif avg_diversity < 0.5:
            print(f"  VERDICT: FAIL (diversity {avg_diversity:.4f} < 0.5)")
        else:
            print("  VERDICT: PASS")

    # Output JSON
    if output_file:
        with open(output_file, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport saved to {output_file}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate scoring presets")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--min-brands", type=int, default=5, help="Minimum brands required")
    parser.add_argument("--n-runs", type=int, default=100, help="Selections per brand per preset")
    args = parser.parse_args()

    asyncio.run(main(
        min_brands=args.min_brands,
        output_file=args.output,
        n_runs=args.n_runs,
    ))
