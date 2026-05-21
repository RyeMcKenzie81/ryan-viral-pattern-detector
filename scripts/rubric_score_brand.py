"""
Rubric scoring for any brand — pulls top N + bottom N by ROAS, scores with Sonnet.
Usage: python3 scripts/rubric_score_brand.py "Infinite Age" [--top 30] [--bottom 30]
"""

import argparse
import asyncio
import json
import os
import sys
import time
sys.path.insert(0, '.')


def cache_path(brand_name):
    slug = brand_name.lower().replace(' ', '_')
    return f"/tmp/rubric_scored_{slug}.json"


def load_cache(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_cache(path, scored):
    with open(path, 'w') as f:
        json.dump(scored, f, indent=2)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('brand', help='Brand name (partial match)')
    parser.add_argument('--top', type=int, default=30)
    parser.add_argument('--bottom', type=int, default=30)
    parser.add_argument('--min-spend-top', type=float, default=50.0)
    parser.add_argument('--min-spend-bottom', type=float, default=100.0)
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--model', default='sonnet')
    parser.add_argument('--images-only', action='store_true', help='Skip video ads (filter by ad name)')
    args = parser.parse_args()

    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
    from viraltracker.services.rubric_scoring_service import RubricScoringService

    supabase = get_supabase_client()

    # Find brand
    brand_result = supabase.table('brands').select('id, name').ilike('name', f'%{args.brand}%').limit(1).execute()
    if not brand_result.data:
        print(f"ERROR: Brand matching '{args.brand}' not found")
        return
    brand = brand_result.data[0]
    brand_id = brand['id']
    brand_name = brand['name']

    cpath = cache_path(brand_name)
    cached = load_cache(cpath)
    cached_ids = {s['meta_ad_id'] for s in cached}

    print("=" * 80)
    print(f"RUBRIC SCORING — {brand_name}")
    print(f"Top {args.top} + Bottom {args.bottom} | Last {args.days} days | Model: {args.model}")
    print("=" * 80)
    print(f"Cache: {len(cached)} ads already scored")

    # Fetch ads
    perf_service = AdPerformanceQueryService(supabase)

    def _is_video(ad):
        name = (ad.get('ad_name') or '').lower()
        return any(tag in name for tag in ['[video]', '[tiktok]', '[silja]', '[polly][gif', 'ugc', '.mp4', '.mov', 'catalog ad'])

    if args.images_only:
        # Pull ALL ads, filter to images, then take top/bottom from filtered set
        all_result = perf_service.get_top_ads(
            brand_id=brand_id, sort_by='roas', sort_order='desc',
            days_back=args.days, limit=500, min_spend=min(args.min_spend_top, args.min_spend_bottom), status_filter='all',
        )
        # Dedupe and filter to images
        seen_ids = set()
        image_ads = []
        for ad in all_result.get('ads', []):
            mid = ad.get('meta_ad_id')
            if mid and mid not in seen_ids and not _is_video(ad):
                seen_ids.add(mid)
                image_ads.append(ad)
        # Already sorted desc by ROAS — take top N and bottom N
        all_top = image_ads[:args.top]
        all_bottom = list(reversed(image_ads[-args.bottom:])) if len(image_ads) > args.top else []
        # Remove overlap if total images < top + bottom
        bottom_ids = {a.get('meta_ad_id') for a in all_top}
        all_bottom = [a for a in all_bottom if a.get('meta_ad_id') not in bottom_ids]
        all_ads = all_top + all_bottom
        print(f"Filtered to image-only: {len(image_ads)} total, {len(all_top)} top, {len(all_bottom)} bottom")
    else:
        top_result = perf_service.get_top_ads(
            brand_id=brand_id, sort_by='roas', sort_order='desc',
            days_back=args.days, limit=args.top, min_spend=args.min_spend_top, status_filter='all',
        )
        bottom_result = perf_service.get_top_ads(
            brand_id=brand_id, sort_by='roas', sort_order='asc',
            days_back=args.days, limit=args.bottom, min_spend=args.min_spend_bottom, status_filter='all',
        )
        seen_ids = set()
        all_ads = []
        for ad in top_result.get('ads', []) + bottom_result.get('ads', []):
            mid = ad.get('meta_ad_id')
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_ads.append(ad)

    new_ads = [ad for ad in all_ads if ad['meta_ad_id'] not in cached_ids]
    already = len(all_ads) - len(new_ads)
    print(f"Total unique ads: {len(all_ads)} ({already} already cached, {len(new_ads)} new to score)")

    if not new_ads:
        print("Nothing new to score.")
        return

    # Score
    rubric_service = RubricScoringService(supabase=supabase)
    new_scored = []
    skipped = 0
    total_start = time.time()

    print(f"\n{'#':<3} {'Ad Name':<45} {'ROAS':>6} {'Spend':>7} {'Score':>6} {'Grade':>5}")
    print("-" * 75)

    for i, ad in enumerate(new_ads, 1):
        meta_ad_id = ad['meta_ad_id']
        ad_name = (ad.get('ad_name') or 'Unnamed')[:43]
        roas = ad.get('roas', 0) or 0
        spend = ad.get('spend', 0) or 0

        image_bytes = await rubric_service._download_ad_image(meta_ad_id, brand_id)
        if not image_bytes:
            print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x ${spend:>5.0f}   SKIP")
            skipped += 1
            continue

        r = await rubric_service.score_ad(
            image_data=image_bytes,
            headline=ad.get('ad_name', ''),
            body_text=ad.get('ad_copy', '') or '',
            product_info=f"{brand_name} - Health supplements",
            model=args.model,
        )

        if r.error:
            print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x ${spend:>5.0f}   ERR: {r.error[:30]}")
            skipped += 1
            continue

        dim_scores = {}
        dim_rationales = {}
        for gate in r.gates:
            for dim_name, score in gate.dimensions.items():
                dim_scores[f"G{gate.gate_number}_{dim_name}"] = score
                dim_rationales[f"G{gate.gate_number}_{dim_name}"] = gate.rationales.get(dim_name, "")

        entry = {
            "meta_ad_id": meta_ad_id,
            "ad_name": ad_name,
            "roas": roas,
            "spend": spend,
            "purchases": ad.get('purchases', 0) or 0,
            "ctr": ad.get('ctr', 0) or 0,
            "cpm": ad.get('cpm', 0) or 0,
            "cpc": ad.get('cpc', 0) or 0,
            "impressions": ad.get('impressions', 0) or 0,
            "link_clicks": ad.get('link_clicks', 0) or 0,
            "add_to_carts": ad.get('add_to_carts', 0) or 0,
            "conversion_rate": ad.get('conversion_rate', 0) or 0,
            "rubric_score": r.final_score,
            "raw_score": r.raw_score,
            "grade": r.letter_grade,
            "gates": {str(k): v for k, v in r.gate_scores_dict.items()},
            "dim_scores": dim_scores,
            "dim_rationales": dim_rationales,
            "multipliers": {
                "strategic_coherence": r.multipliers.strategic_coherence,
                "offer_alignment": r.multipliers.offer_alignment,
                "belief_distance": r.multipliers.belief_distance,
                "combined": r.multipliers.combined,
            },
            "hard_fails": r.hard_fails,
            "caps": r.gate_caps_applied,
        }
        new_scored.append(entry)
        print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x ${spend:>5.0f} {r.final_score:>5.0f}  {r.letter_grade:<4}")

    elapsed = time.time() - total_start

    merged = cached + new_scored
    save_cache(cpath, merged)

    print(f"\n{'=' * 80}")
    print(f"Scored {len(new_scored)} new ads ({skipped} skipped) in {elapsed:.0f}s")
    print(f"Cache: {cpath} ({len(merged)} total)")
    print(f"{'=' * 80}")
    print(f"\nNext: python3 scripts/rubric_analyze_brand.py \"{brand_name}\"")


if __name__ == "__main__":
    asyncio.run(main())
