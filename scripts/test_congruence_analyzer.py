#!/usr/bin/env python3
"""Test script for Phase 5: Deep Congruence Analysis.

Tests:
1. CongruenceAnalyzer standalone with sample data
2. CongruenceAnalyzer integrated with classifier
3. Verify congruence_components are populated
"""

import asyncio
import os
import sys
from uuid import UUID, uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_standalone():
    """Test CongruenceAnalyzer standalone with mock data."""
    from viraltracker.services.ad_intelligence.congruence_analyzer import (
        CongruenceAnalyzer,
    )

    print("=" * 60)
    print("TEST 1: CongruenceAnalyzer Standalone")
    print("=" * 60)

    analyzer = CongruenceAnalyzer()

    # Sample video analysis data
    video_data = {
        "awareness_level": "problem_aware",
        "hook_transcript_spoken": "Is your dog struggling with joint pain?",
        "hook_transcript_overlay": "Joint Pain Solution",
        "hook_visual_description": "Dog struggling to climb stairs",
        "benefits_shown": ["Improved mobility", "Less pain", "More energy"],
        "angles_used": ["Problem agitation", "Transformation"],
        "claims_made": [
            {"claim": "93% of dogs show improvement in 2 weeks", "proof_shown": True}
        ],
        "pain_points_addressed": ["Joint pain", "Limited mobility", "Aging"],
    }

    # Sample copy data
    copy_data = {
        "copy_awareness_level": "problem_aware",
        "primary_cta": "Shop Now",
    }

    # Sample LP data
    lp_data = {
        "page_title": "Wonder Paws Joint Support - Natural Dog Mobility Solution",
        "product_name": "Wonder Paws Joint Support",
        "benefits": ["Improved mobility", "Reduced inflammation", "Joint health"],
        "features": ["Collagen peptides", "Glucosamine", "Natural ingredients"],
        "call_to_action": "Buy Now",
        "raw_markdown": """
# Natural Joint Support for Your Dog

Is your furry friend slowing down? Our scientifically formulated joint support helps dogs regain their mobility and enjoy life again.

## Benefits
- Improved mobility
- Reduced inflammation
- Better joint health

## Try Risk-Free
93% of dogs show improvement within 2 weeks.
        """,
    }

    print("\nInput data:")
    print(f"  Video awareness: {video_data['awareness_level']}")
    print(f"  Copy awareness: {copy_data['copy_awareness_level']}")
    print(f"  Video benefits: {video_data['benefits_shown']}")
    print(f"  LP benefits: {lp_data['benefits']}")

    print("\nRunning analysis...")
    result = await analyzer.analyze_congruence(video_data, copy_data, lp_data)

    print(f"\nResults:")
    print(f"  Overall score: {result.overall_score}")
    print(f"  Model used: {result.model_used}")
    print(f"  Error: {result.error}")

    print("\nPer-dimension assessments:")
    for comp in result.components:
        print(f"\n  {comp.dimension}:")
        print(f"    Assessment: {comp.assessment}")
        print(f"    Explanation: {comp.explanation[:80]}..." if len(comp.explanation) > 80 else f"    Explanation: {comp.explanation}")
        if comp.suggestion:
            print(f"    Suggestion: {comp.suggestion[:80]}..." if len(comp.suggestion) > 80 else f"    Suggestion: {comp.suggestion}")

    return result


async def test_integrated():
    """Test CongruenceAnalyzer integrated into classifier."""
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
    from viraltracker.services.ad_intelligence.congruence_analyzer import CongruenceAnalyzer
    from viraltracker.services.video_analysis_service import VideoAnalysisService
    from datetime import date, timedelta

    print("\n" + "=" * 60)
    print("TEST 2: Integrated Classifier + CongruenceAnalyzer")
    print("=" * 60)

    supabase = get_supabase_client()
    video_analysis_service = VideoAnalysisService(supabase)
    congruence_analyzer = CongruenceAnalyzer()

    classifier = ClassifierService(
        supabase_client=supabase,
        video_analysis_service=video_analysis_service,
        congruence_analyzer=congruence_analyzer,
    )

    # Wonder Paws brand
    brand_id = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

    # Get org_id
    brand_result = supabase.table("brands").select("organization_id, name").eq(
        "id", str(brand_id)
    ).limit(1).execute()

    if not brand_result.data:
        print("ERROR: Brand not found")
        return None

    org_id = UUID(brand_result.data[0]["organization_id"])
    brand_name = brand_result.data[0]["name"]
    run_id = uuid4()

    # Create run record (required by FK constraint)
    today = date.today()
    run_record = {
        "id": str(run_id),
        "organization_id": str(org_id),
        "brand_id": str(brand_id),
        "date_range_start": str(today - timedelta(days=30)),
        "date_range_end": str(today),
        "goal": "test_congruence",
        "status": "running",
    }
    supabase.table("ad_intelligence_runs").insert(run_record).execute()

    print(f"\nBrand: {brand_name}")
    print(f"Run ID: {run_id}")

    # Find an ad that has:
    # 1. Video analysis (video_analysis_id populated in a previous classification)
    # 2. Landing page data
    print("\nLooking for ads with video analysis AND landing page...")

    # Check for existing classifications with video_analysis_id
    existing_cls = supabase.table("ad_creative_classifications").select(
        "meta_ad_id, video_analysis_id, landing_page_id"
    ).eq(
        "brand_id", str(brand_id)
    ).not_.is_("video_analysis_id", "null").limit(10).execute()

    if not existing_cls.data:
        print("No ads found with video analysis - need to run classification first")

        # Try to classify a video ad
        video_ads_result = supabase.table("meta_ads_performance").select(
            "meta_ad_id, ad_name"
        ).eq("brand_id", str(brand_id)).eq("is_video", True).limit(3).execute()

        if not video_ads_result.data:
            print("ERROR: No video ads found")
            return None

        meta_ad_id = video_ads_result.data[0]["meta_ad_id"]
        print(f"\nClassifying ad: {meta_ad_id}")

        result = await classifier.classify_ad(
            meta_ad_id=meta_ad_id,
            brand_id=brand_id,
            org_id=org_id,
            run_id=run_id,
            video_budget_remaining=1,
            scrape_missing_lp=True,
        )

        print(f"  Source: {result.source}")
        print(f"  Video Analysis ID: {result.video_analysis_id}")
        print(f"  Landing Page ID: {result.landing_page_id}")
        print(f"  Congruence Components: {len(result.congruence_components)}")

        if result.congruence_components:
            print("\n  Congruence Analysis Results:")
            for comp in result.congruence_components:
                print(f"    {comp.get('dimension')}: {comp.get('assessment')}")
                if comp.get('explanation'):
                    expl = comp['explanation'][:60] + "..." if len(comp['explanation']) > 60 else comp['explanation']
                    print(f"      {expl}")

        return result

    else:
        # Found existing classifications with video analysis
        ads_with_analysis = existing_cls.data
        print(f"Found {len(ads_with_analysis)} ads with video analysis")

        # Find one that also has LP
        ad_with_both = None
        for ad in ads_with_analysis:
            if ad.get("landing_page_id"):
                ad_with_both = ad
                break

        if ad_with_both:
            meta_ad_id = ad_with_both["meta_ad_id"]
            print(f"\nRe-classifying ad with both video and LP: {meta_ad_id}")

            result = await classifier.classify_ad(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                org_id=org_id,
                run_id=run_id,
                force=True,  # Force reclassification to run congruence
                video_budget_remaining=0,  # Skip video analysis (already have it)
            )

            print(f"  Source: {result.source}")
            print(f"  Video Analysis ID: {result.video_analysis_id}")
            print(f"  Landing Page ID: {result.landing_page_id}")
            print(f"  Congruence Components: {len(result.congruence_components)}")

            if result.congruence_components:
                print("\n  Congruence Analysis Results:")
                for comp in result.congruence_components:
                    print(f"    {comp.get('dimension')}: {comp.get('assessment')}")

            return result

        else:
            # Have video analysis but no LP - try with scrape_missing_lp
            meta_ad_id = ads_with_analysis[0]["meta_ad_id"]
            print(f"\nClassifying ad with video but no LP: {meta_ad_id}")
            print("Using scrape_missing_lp=True to get LP data...")

            result = await classifier.classify_ad(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                org_id=org_id,
                run_id=run_id,
                force=True,
                video_budget_remaining=0,
                scrape_missing_lp=True,
            )

            print(f"  Source: {result.source}")
            print(f"  Video Analysis ID: {result.video_analysis_id}")
            print(f"  Landing Page ID: {result.landing_page_id}")
            print(f"  Congruence Components: {len(result.congruence_components)}")

            if result.congruence_components:
                print("\n  Congruence Analysis Results:")
                for comp in result.congruence_components:
                    print(f"    {comp.get('dimension')}: {comp.get('assessment')}")

            return result


async def test_query_verification():
    """Verify congruence data in database."""
    from viraltracker.core.database import get_supabase_client

    print("\n" + "=" * 60)
    print("TEST 3: Database Verification Query")
    print("=" * 60)

    supabase = get_supabase_client()
    brand_id = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

    # Query for classifications with congruence components
    result = supabase.table("ad_creative_classifications").select(
        "meta_ad_id, congruence_components, congruence_score, video_analysis_id, landing_page_id"
    ).eq(
        "brand_id", str(brand_id)
    ).not_.is_("congruence_components", "null").order(
        "classified_at", desc=True
    ).limit(5).execute()

    if not result.data:
        print("No classifications found with congruence_components")
        return

    print(f"\nFound {len(result.data)} classifications with congruence data:")

    for row in result.data:
        print(f"\n  Ad: {row['meta_ad_id']}")
        print(f"  Congruence Score: {row.get('congruence_score')}")
        print(f"  Video Analysis ID: {row.get('video_analysis_id')}")
        print(f"  Landing Page ID: {row.get('landing_page_id')}")

        components = row.get("congruence_components", [])
        if components:
            print(f"  Components ({len(components)}):")
            for comp in components:
                if isinstance(comp, dict):
                    dim = comp.get('dimension', 'unknown')
                    assess = comp.get('assessment', 'unknown')
                    print(f"    - {dim}: {assess}")


async def main():
    print("=" * 60)
    print("PHASE 5: Deep Congruence Analysis Test")
    print("=" * 60)

    # Test 1: Standalone (always works, uses Gemini)
    try:
        standalone_result = await test_standalone()
        print("\n[PASS] Standalone test completed")
    except Exception as e:
        print(f"\n[FAIL] Standalone test failed: {e}")

    # Test 2: Integrated (requires database + Gemini)
    try:
        integrated_result = await test_integrated()
        if integrated_result and integrated_result.congruence_components:
            print("\n[PASS] Integrated test completed with congruence data")
        else:
            print("\n[WARN] Integrated test completed but no congruence data")
    except Exception as e:
        print(f"\n[FAIL] Integrated test failed: {e}")
        import traceback
        traceback.print_exc()

    # Test 3: Verification query
    try:
        await test_query_verification()
        print("\n[PASS] Verification query completed")
    except Exception as e:
        print(f"\n[FAIL] Verification query failed: {e}")

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("Check the results above for per-dimension congruence assessments.")
    print("Expected dimensions: awareness_alignment, hook_headline, benefits_match,")
    print("                     messaging_angle, claims_consistency")


if __name__ == "__main__":
    asyncio.run(main())
