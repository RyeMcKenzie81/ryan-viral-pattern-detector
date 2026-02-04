#!/usr/bin/env python3
"""Test script for Phase 4: Classifier Video Integration.

Tests:
1. Classify video ads using deep video analysis
2. Verify video_analysis_id is populated
3. Verify landing_page_id is populated where matched
"""

import asyncio
import os
import sys
from uuid import UUID, uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
    from viraltracker.services.video_analysis_service import VideoAnalysisService

    supabase = get_supabase_client()
    video_analysis_service = VideoAnalysisService(supabase)
    classifier = ClassifierService(
        supabase_client=supabase,
        video_analysis_service=video_analysis_service,
    )

    # Wonder Paws brand
    brand_id = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

    # Get org_id
    brand_result = supabase.table("brands").select("organization_id, name").eq(
        "id", str(brand_id)
    ).limit(1).execute()

    if not brand_result.data:
        print("ERROR: Brand not found")
        return

    org_id = UUID(brand_result.data[0]["organization_id"])
    brand_name = brand_result.data[0]["name"]
    run_id = uuid4()

    # Create run record (required by FK constraint)
    from datetime import date, timedelta
    today = date.today()
    run_record = {
        "id": str(run_id),
        "organization_id": str(org_id),
        "brand_id": str(brand_id),
        "date_range_start": str(today - timedelta(days=30)),
        "date_range_end": str(today),
        "goal": "test",
        "status": "running",
    }
    supabase.table("ad_intelligence_runs").insert(run_record).execute()

    print(f"Brand: {brand_name}")
    print(f"Run ID: {run_id}")

    # Get video ads
    video_ads_result = supabase.table("meta_ads_performance").select(
        "meta_ad_id, ad_name, meta_video_id"
    ).eq("brand_id", str(brand_id)).eq("is_video", True).limit(5).execute()

    if not video_ads_result.data:
        print("ERROR: No video ads found")
        return

    ad_ids = list(set(r["meta_ad_id"] for r in video_ads_result.data))
    print(f"\nFound {len(ad_ids)} video ads to test")

    # Test classification
    print(f"\n{'='*60}")
    print("TEST: Classify Video Ads")
    print(f"{'='*60}")

    results = []
    for meta_ad_id in ad_ids[:5]:
        try:
            result = await classifier.classify_ad(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                org_id=org_id,
                run_id=run_id,
                video_budget_remaining=5,
            )
            results.append(result)

            print(f"\n  Ad: {meta_ad_id}")
            print(f"  Source: {result.source}")
            print(f"  Video Analysis ID: {result.video_analysis_id}")
            print(f"  Landing Page ID: {result.landing_page_id}")
            print(f"  Awareness: {result.creative_awareness_level}")

        except Exception as e:
            print(f"\n  Ad: {meta_ad_id}")
            print(f"  ERROR: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    with_video_id = sum(1 for r in results if r.video_analysis_id)
    with_lp_id = sum(1 for r in results if r.landing_page_id)

    print(f"Ads classified: {len(results)}")
    print(f"With video_analysis_id: {with_video_id}")
    print(f"With landing_page_id: {with_lp_id}")


if __name__ == "__main__":
    asyncio.run(main())
