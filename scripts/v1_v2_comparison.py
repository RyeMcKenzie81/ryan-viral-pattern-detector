"""
V1 vs V2 Ad Creation Pipeline Comparison Script.

Runs both V1 and V2 pipelines on the same templates with the same params,
then compares approval rates, failure rates, and completion status.

Usage:
    # Dry run - show plan without calling LLMs
    python scripts/v1_v2_comparison.py --product-id UUID --template-count 3 --dry-run

    # Live run - actually execute both pipelines
    python scripts/v1_v2_comparison.py --product-id UUID --template-count 3 --live

    # Specific templates
    python scripts/v1_v2_comparison.py --product-id UUID --template-ids UUID1 UUID2 --live

Pass criteria (from plan):
    - V2 approval rate within 5% of V1 (N >= 30 paired comparisons)
    - V2 job completion rate >= 95% (over >= 20 consecutive jobs)
    - Template scoring returns scored list with composite + per-scorer breakdown
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def fetch_templates(template_ids: Optional[List[str]] = None, count: int = 3) -> List[dict]:
    """Fetch templates for comparison.

    Args:
        template_ids: Specific template UUIDs, or None for random selection.
        count: Number to fetch if template_ids is None.

    Returns:
        List of template dicts with id, name, storage_path, bucket.
    """
    db = get_supabase_client()

    if template_ids:
        result = db.table("scraped_templates").select(
            "id, name, storage_path"
        ).in_("id", template_ids).execute()
    else:
        result = db.table("scraped_templates").select(
            "id, name, storage_path"
        ).eq("is_active", True).limit(count).execute()

    templates = []
    for t in (result.data or []):
        storage_path = t.get('storage_path', '')
        parts = storage_path.split('/', 1) if storage_path else ['scraped-assets', '']
        bucket = parts[0] if len(parts) == 2 else 'scraped-assets'
        path = parts[1] if len(parts) == 2 else storage_path
        templates.append({
            'id': t['id'],
            'name': t.get('name', 'Template'),
            'storage_path': path,
            'bucket': bucket,
            'full_storage_path': storage_path,
        })

    return templates


def download_template_base64(template: dict) -> Optional[str]:
    """Download a template and return as base64."""
    import base64
    try:
        db = get_supabase_client()
        bucket = template.get('bucket', 'scraped-assets')
        path = template.get('storage_path', '')
        data = db.storage.from_(bucket).download(path)
        return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download template {template.get('name')}: {e}")
        return None


async def run_v1_pipeline(
    product_id: str,
    template_base64: str,
    template_name: str,
    num_variations: int,
    deps,
) -> Dict:
    """Run V1 pipeline and return results."""
    from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation

    start = time.time()
    try:
        result = await run_ad_creation(
            product_id=product_id,
            reference_ad_base64=template_base64,
            reference_ad_filename=template_name,
            num_variations=num_variations,
            content_source="hooks",
            color_mode="original",
            image_resolution="2K",
            deps=deps,
        )
        elapsed = time.time() - start
        return {
            "pipeline": "v1",
            "success": True,
            "approved": result.get("approved_count", 0),
            "rejected": result.get("rejected_count", 0),
            "flagged": result.get("flagged_count", 0),
            "ad_run_id": result.get("ad_run_id"),
            "elapsed_seconds": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "pipeline": "v1",
            "success": False,
            "approved": 0,
            "rejected": 0,
            "flagged": 0,
            "ad_run_id": None,
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e),
        }


async def run_v2_pipeline(
    product_id: str,
    template_base64: str,
    template_name: str,
    template_id: str,
    num_variations: int,
    deps,
) -> Dict:
    """Run V2 pipeline and return results."""
    from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2

    start = time.time()
    try:
        result = await run_ad_creation_v2(
            product_id=product_id,
            reference_ad_base64=template_base64,
            reference_ad_filename=template_name,
            template_id=template_id,
            num_variations=num_variations,
            content_source="hooks",
            canvas_sizes=["1080x1080px"],
            color_modes=["original"],
            image_resolution="2K",
            deps=deps,
        )
        elapsed = time.time() - start
        return {
            "pipeline": "v2",
            "success": True,
            "approved": result.get("approved_count", 0),
            "rejected": result.get("rejected_count", 0),
            "flagged": result.get("flagged_count", 0),
            "ad_run_id": result.get("ad_run_id"),
            "pipeline_version": result.get("pipeline_version"),
            "prompt_version": result.get("prompt_version"),
            "elapsed_seconds": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "pipeline": "v2",
            "success": False,
            "approved": 0,
            "rejected": 0,
            "flagged": 0,
            "ad_run_id": None,
            "pipeline_version": None,
            "prompt_version": None,
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e),
        }


def test_template_scoring(product_id: str) -> Dict:
    """Test template scoring returns correct structure."""
    try:
        from viraltracker.services.template_scoring_service import (
            fetch_template_candidates, prefetch_product_asset_tags,
            select_templates_with_fallback, SelectionContext,
            SMART_SELECT_WEIGHTS,
        )

        loop = asyncio.new_event_loop()

        asset_tags = loop.run_until_complete(prefetch_product_asset_tags(product_id))
        candidates = loop.run_until_complete(fetch_template_candidates(product_id))

        context = SelectionContext(
            product_id=UUID(product_id),
            brand_id=UUID(product_id),  # Fallback
            product_asset_tags=asset_tags,
        )

        result = select_templates_with_fallback(
            candidates=candidates,
            context=context,
            weights=SMART_SELECT_WEIGHTS,
            count=3,
        )

        loop.close()

        return {
            "pass": not result.empty and len(result.scores) > 0,
            "templates_selected": len(result.templates),
            "candidates_total": result.candidates_before_gate,
            "has_composite_scores": all("composite" in s for s in result.scores),
            "has_per_scorer_breakdown": all(
                "asset_match" in s and "unused_bonus" in s and "category_match" in s
                for s in result.scores
            ),
            "empty": result.empty,
            "reason": result.reason,
        }
    except Exception as e:
        return {"pass": False, "error": str(e)}


def print_comparison_table(results: List[Dict]):
    """Print comparison results as a formatted table."""
    print("\n" + "=" * 80)
    print("V1 vs V2 COMPARISON RESULTS")
    print("=" * 80)

    v1_results = [r for r in results if r["pipeline"] == "v1"]
    v2_results = [r for r in results if r["pipeline"] == "v2"]

    # Per-template comparison
    print(f"\n{'Template':<30} {'V1 Approved':<15} {'V2 Approved':<15} {'V1 Time':<10} {'V2 Time':<10}")
    print("-" * 80)

    for i in range(0, len(results), 2):
        if i + 1 >= len(results):
            break
        v1 = results[i]
        v2 = results[i + 1]
        template = v1.get("template_name", "Unknown")[:28]
        v1_approved = f"{v1['approved']}" if v1['success'] else "FAIL"
        v2_approved = f"{v2['approved']}" if v2['success'] else "FAIL"
        print(f"{template:<30} {v1_approved:<15} {v2_approved:<15} "
              f"{v1['elapsed_seconds']:<10} {v2['elapsed_seconds']:<10}")

    # Summary
    print("\n" + "-" * 80)
    print("SUMMARY")
    print("-" * 80)

    v1_total_approved = sum(r['approved'] for r in v1_results)
    v2_total_approved = sum(r['approved'] for r in v2_results)
    v1_total_attempted = sum(r.get('num_variations', 5) for r in v1_results if r['success'])
    v2_total_attempted = sum(r.get('num_variations', 5) for r in v2_results if r['success'])
    v1_successes = sum(1 for r in v1_results if r['success'])
    v2_successes = sum(1 for r in v2_results if r['success'])

    v1_rate = (v1_total_approved / v1_total_attempted * 100) if v1_total_attempted > 0 else 0
    v2_rate = (v2_total_approved / v2_total_attempted * 100) if v2_total_attempted > 0 else 0
    rate_diff = abs(v2_rate - v1_rate)

    print(f"V1: {v1_total_approved} approved / {v1_total_attempted} attempted ({v1_rate:.1f}%) | "
          f"{v1_successes}/{len(v1_results)} completed")
    print(f"V2: {v2_total_approved} approved / {v2_total_attempted} attempted ({v2_rate:.1f}%) | "
          f"{v2_successes}/{len(v2_results)} completed")
    print(f"Rate difference: {rate_diff:.1f}%")

    # Pass/fail verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    total_pairs = len(v1_results)
    completion_rate = (v2_successes / len(v2_results) * 100) if v2_results else 0

    checks = []
    if total_pairs >= 30:
        rate_pass = rate_diff <= 5.0
        checks.append(f"  {'PASS' if rate_pass else 'FAIL'} - Approval rate within 5%: "
                       f"diff={rate_diff:.1f}% (need <= 5%, N={total_pairs})")
    else:
        checks.append(f"  SKIP - Approval rate check needs >= 30 pairs (have {total_pairs})")

    if len(v2_results) >= 20:
        completion_pass = completion_rate >= 95
        checks.append(f"  {'PASS' if completion_pass else 'FAIL'} - Completion rate >= 95%: "
                       f"{completion_rate:.1f}%")
    else:
        checks.append(f"  SKIP - Completion check needs >= 20 runs (have {len(v2_results)})")

    for check in checks:
        print(check)

    # V2-specific checks
    v2_has_pipeline_version = all(r.get('pipeline_version') == 'v2' for r in v2_results if r['success'])
    v2_has_prompt_version = all(r.get('prompt_version') is not None for r in v2_results if r['success'])
    print(f"  {'PASS' if v2_has_pipeline_version else 'FAIL'} - V2 ads have pipeline_version='v2'")
    print(f"  {'PASS' if v2_has_prompt_version else 'FAIL'} - V2 ads have prompt_version field")

    print("=" * 80)


def run_dry_run(product_id: str, templates: List[dict], num_variations: int):
    """Show what would be run without executing."""
    print("\n" + "=" * 80)
    print("DRY RUN — Plan (no LLM calls)")
    print("=" * 80)

    print(f"\nProduct ID: {product_id}")
    print(f"Templates: {len(templates)}")
    print(f"Variations per template: {num_variations}")
    print(f"Total ads per pipeline: {len(templates) * num_variations}")
    print(f"Total ads both pipelines: {len(templates) * num_variations * 2}")

    print("\nTemplates:")
    for i, t in enumerate(templates, 1):
        print(f"  {i}. {t['name']} (ID: {t['id'][:8]}...)")

    print("\nFor each template, will run:")
    print("  1. V1 pipeline (run_ad_creation)")
    print("  2. V2 pipeline (run_ad_creation_v2)")
    print("  3. Compare: approved_count, rejected_count, flagged_count, completion status")

    # Run template scoring test (doesn't require LLM)
    print("\n--- Template Scoring Test ---")
    scoring_result = test_template_scoring(product_id)
    print(f"  Scoring test: {'PASS' if scoring_result.get('pass') else 'FAIL'}")
    for k, v in scoring_result.items():
        if k != 'pass':
            print(f"    {k}: {v}")

    # Run V1 untouched check
    print("\n--- V1 Untouched Check ---")
    import subprocess
    diff = subprocess.run(
        ["git", "diff", "--stat", "viraltracker/pipelines/ad_creation/"],
        capture_output=True, text=True
    )
    if diff.stdout.strip():
        print(f"  FAIL - V1 has changes:\n{diff.stdout}")
    else:
        print("  PASS - V1 directory untouched")

    # Compile checks
    print("\n--- Compile Checks ---")
    import glob
    v2_files = glob.glob("viraltracker/pipelines/ad_creation_v2/**/*.py", recursive=True)
    v2_files.append("viraltracker/services/template_scoring_service.py")

    all_pass = True
    for f in v2_files:
        result = subprocess.run(
            ["python3", "-m", "py_compile", f],
            capture_output=True, text=True
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        if result.returncode != 0:
            all_pass = False
        print(f"  {status} - {f}")

    print(f"\n  Overall compile: {'PASS' if all_pass else 'FAIL'}")

    # Import check
    print("\n--- Import Check ---")
    result = subprocess.run(
        ["python3", "-c",
         "from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2; "
         "print('Import OK')"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  PASS - {result.stdout.strip()}")
    else:
        print(f"  FAIL - {result.stderr.strip()[:200]}")
        print("  (pydantic_graph may not be installed locally — this is OK if py_compile passes)")


async def run_live(product_id: str, templates: List[dict], num_variations: int):
    """Run live comparison of V1 and V2."""
    from viraltracker.agent.dependencies import AgentDependencies

    deps = AgentDependencies.create(project_name="v1_v2_comparison")
    results = []

    for i, template in enumerate(templates, 1):
        logger.info(f"\n--- Template {i}/{len(templates)}: {template['name']} ---")

        # Download template
        template_base64 = download_template_base64(template)
        if not template_base64:
            logger.error(f"Skipping template {template['name']} — download failed")
            continue

        # Run V1
        logger.info(f"Running V1 pipeline...")
        v1_result = await run_v1_pipeline(
            product_id=product_id,
            template_base64=template_base64,
            template_name=template['name'],
            num_variations=num_variations,
            deps=deps,
        )
        v1_result["template_name"] = template['name']
        v1_result["num_variations"] = num_variations
        results.append(v1_result)
        logger.info(f"V1: {'OK' if v1_result['success'] else 'FAIL'} - "
                     f"{v1_result['approved']} approved in {v1_result['elapsed_seconds']}s")

        # Run V2
        logger.info(f"Running V2 pipeline...")
        v2_result = await run_v2_pipeline(
            product_id=product_id,
            template_base64=template_base64,
            template_name=template['name'],
            template_id=template['id'],
            num_variations=num_variations,
            deps=deps,
        )
        v2_result["template_name"] = template['name']
        v2_result["num_variations"] = num_variations
        results.append(v2_result)
        logger.info(f"V2: {'OK' if v2_result['success'] else 'FAIL'} - "
                     f"{v2_result['approved']} approved in {v2_result['elapsed_seconds']}s")

    # Print comparison
    print_comparison_table(results)

    # Also test template scoring
    print("\n--- Template Scoring Test ---")
    scoring_result = test_template_scoring(product_id)
    print(f"  Scoring: {'PASS' if scoring_result.get('pass') else 'FAIL'}")
    for k, v in scoring_result.items():
        if k != 'pass':
            print(f"    {k}: {v}")

    return results


def main():
    parser = argparse.ArgumentParser(description="V1 vs V2 Ad Creation Comparison")
    parser.add_argument("--product-id", required=True, help="Product UUID")
    parser.add_argument("--template-ids", nargs="*", help="Specific template UUIDs")
    parser.add_argument("--template-count", type=int, default=3, help="Number of templates (if not specifying IDs)")
    parser.add_argument("--num-variations", type=int, default=5, help="Variations per template")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without calling LLMs")
    parser.add_argument("--live", action="store_true", help="Actually run both pipelines")

    args = parser.parse_args()

    if not args.dry_run and not args.live:
        print("Error: specify --dry-run or --live")
        sys.exit(1)

    # Fetch templates
    templates = fetch_templates(
        template_ids=args.template_ids,
        count=args.template_count,
    )

    if not templates:
        print("Error: No templates found")
        sys.exit(1)

    print(f"Found {len(templates)} templates")

    if args.dry_run:
        run_dry_run(args.product_id, templates, args.num_variations)
    elif args.live:
        asyncio.run(run_live(args.product_id, templates, args.num_variations))


if __name__ == "__main__":
    main()
