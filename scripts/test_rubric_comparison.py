"""
Incremental rubric scoring — expands the cached dataset by scoring new ads.
Pulls top N + bottom N by ROAS, skips already-cached ads, scores new ones, merges.
"""

import asyncio
import json
import os
import sys
import time
sys.path.insert(0, '.')

CACHE_FILE = "/tmp/rubric_scored_cache.json"

# Config: how many to pull from each end
TOP_N = 30
BOTTOM_N = 30
MIN_SPEND_TOP = 50.0
MIN_SPEND_BOTTOM = 100.0


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return []


def save_cache(scored):
    with open(CACHE_FILE, 'w') as f:
        json.dump(scored, f, indent=2)


async def main():
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
    from viraltracker.services.rubric_scoring_service import RubricScoringService

    supabase = get_supabase_client()

    print("=" * 80)
    print(f"INCREMENTAL RUBRIC SCORING — Top {TOP_N} + Bottom {BOTTOM_N}")
    print("=" * 80)

    # Load existing cache
    cached = load_cache()
    cached_ids = {s['meta_ad_id'] for s in cached}
    print(f"Cache: {len(cached)} ads already scored")

    # Find brand
    brand_result = supabase.table('brands').select('id, name').ilike('name', '%martin%').limit(1).execute()
    if not brand_result.data:
        print("ERROR: Martin Clinic not found")
        return
    brand = brand_result.data[0]
    brand_id = brand['id']
    print(f"Brand: {brand['name']}")

    # Fetch ads from both ends
    perf_service = AdPerformanceQueryService(supabase)

    top_result = perf_service.get_top_ads(
        brand_id=brand_id, sort_by='roas', sort_order='desc',
        days_back=90, limit=TOP_N, min_spend=MIN_SPEND_TOP, status_filter='all',
    )
    bottom_result = perf_service.get_top_ads(
        brand_id=brand_id, sort_by='roas', sort_order='asc',
        days_back=90, limit=BOTTOM_N, min_spend=MIN_SPEND_BOTTOM, status_filter='all',
    )

    # Deduplicate and find new ads
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
        print("Nothing new to score. Re-run analysis with scripts/test_rubric_awareness.py")
        return

    # Score new ads
    rubric_service = RubricScoringService(supabase=supabase)
    new_scored = []
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
            continue

        r = await rubric_service.score_ad(
            image_data=image_bytes,
            headline=ad.get('ad_name', ''),
            body_text=ad.get('ad_copy', '') or '',
            product_info="Martin Clinic - Health supplements",
            model="sonnet",
        )

        if r.error:
            print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x ${spend:>5.0f}   ERR")
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

    # Merge into cache
    merged = cached + new_scored
    save_cache(merged)

    print(f"\n{'=' * 80}")
    print(f"Scored {len(new_scored)} new ads in {elapsed:.0f}s")
    print(f"Cache now has {len(merged)} total scored ads")
    print(f"{'=' * 80}")
    print(f"\nRun analysis: python3 scripts/test_rubric_awareness.py")


if __name__ == "__main__":
    asyncio.run(main())
