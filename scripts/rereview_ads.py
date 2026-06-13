"""Re-review generated ads after a reviewer-model recalibration.

Re-runs review_ad_staged (current pinned model + calibrated thresholds) for
every generated ad in the given window/brand and updates final_status,
claude_review, and review_check_scores in place. Built for the 2026-06-12
gemini-pro-latest drift incident (all ads stuck 'flagged'); reusable for any
future recalibration.

Usage:
    python3 scripts/rereview_ads.py --brand d0cfa5c5-... --since 2026-06-12T00:00:00Z [--dry-run]
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from supabase import create_client  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    ads = (
        sb.table("generated_ads")
        .select("id, ad_run_id, storage_path, hook_text, final_status, prompt_index, ad_runs!inner(product_id, ad_analysis, products!inner(name, brand_id, current_offer))")
        .eq("ad_runs.products.brand_id", args.brand)
        .gte("created_at", args.since)
        .not_.is_("storage_path", "null")
        .execute()
        .data
        or []
    )
    # PostgREST caps a single response at 1000 rows; a silent truncation would
    # look like a complete backfill. Shrink the window instead.
    assert len(ads) < 1000, "window returned >=1000 ads — narrow --since and run in batches"
    print(f"re-reviewing {len(ads)} ads (since {args.since})")

    from viraltracker.pipelines.ad_creation_v2.services.review_service import (
        AdReviewService,
        load_quality_config,
    )

    # Same config source as the live pipeline (org/global DB row, defaults last)
    config = await load_quality_config()
    svc = AdReviewService()
    sem = asyncio.Semaphore(args.concurrency)
    changed = {"n": 0}

    async def one(ad):
        async with sem:
            run = ad["ad_runs"]
            try:
                bucket, _, key = ad["storage_path"].partition("/")
                img = sb.storage.from_(bucket).download(key)
                product = run.get("products") or {}
                res = await svc.review_ad_staged(
                    image_data=img,
                    product_name=product.get("name", ""),
                    hook_text=ad.get("hook_text") or "",
                    ad_analysis=run.get("ad_analysis") or {},
                    config=config,
                    exemplar_context=None,
                    # The live pipeline reviews WITH the product's offer; omitting
                    # it makes C5 grade legitimate pricing as hallucinated.
                    current_offer=product.get("current_offer"),
                )
                new_status = res.get("final_status", "review_failed")
                old_status = ad["final_status"]
                marker = "→" if new_status != old_status else "="
                print(f"  run {ad['ad_run_id'][:8]} #{ad['prompt_index']}: "
                      f"{old_status} {marker} {new_status} "
                      f"(w={res.get('weighted_score')})")
                if not args.dry_run:
                    sb.table("generated_ads").update({
                        "final_status": new_status,
                        "claude_review": res,
                        "review_check_scores": res.get("review_check_scores"),
                    }).eq("id", ad["id"]).execute()
                if new_status != old_status:
                    changed["n"] += 1
            except Exception as e:
                print(f"  run {ad['ad_run_id'][:8]} #{ad['prompt_index']}: ERROR {e}")

    await asyncio.gather(*(one(a) for a in ads))
    print(f"done: {changed['n']}/{len(ads)} statuses changed"
          + (" (dry run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    asyncio.run(main())
