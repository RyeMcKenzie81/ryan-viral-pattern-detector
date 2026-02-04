#!/usr/bin/env python3
"""Test script for VideoAnalysisService deep analysis.

Usage:
    python scripts/test_video_analysis.py

Requires a video ad to be downloaded in meta_ad_assets for Wonder Paws.
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import UUID


async def main():
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.video_analysis_service import (
        VideoAnalysisService,
        compute_input_hash,
        compute_hook_fingerprint,
        validate_analysis_timestamps,
    )

    supabase = get_supabase_client()
    service = VideoAnalysisService(supabase)

    # Wonder Paws brand ID
    brand_id = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

    # Get org_id for Wonder Paws
    brand_result = supabase.table("brands").select("organization_id").eq(
        "id", str(brand_id)
    ).limit(1).execute()

    if not brand_result.data:
        print("ERROR: Wonder Paws brand not found")
        return

    org_id = UUID(brand_result.data[0]["organization_id"])
    print(f"Brand ID: {brand_id}")
    print(f"Org ID: {org_id}")

    # Find a video asset to test with
    assets_result = supabase.table("meta_ad_assets").select(
        "meta_ad_id, storage_path, meta_video_id, created_at"
    ).eq(
        "brand_id", str(brand_id)
    ).eq(
        "asset_type", "video"
    ).eq(
        "status", "downloaded"
    ).limit(5).execute()

    if not assets_result.data:
        print("ERROR: No downloaded video assets found for Wonder Paws")
        print("Run 'Download Assets' from the Ad Performance page first")
        return

    print(f"\nFound {len(assets_result.data)} video assets:")
    for asset in assets_result.data:
        print(f"  - {asset['meta_ad_id']}: {asset['storage_path']}")

    # Test with first video
    test_asset = assets_result.data[0]
    meta_ad_id = test_asset["meta_ad_id"]
    print(f"\n{'='*60}")
    print(f"Testing deep analysis for: {meta_ad_id}")
    print(f"{'='*60}")

    # Get ad name for context (ad_copy column doesn't exist, ad_name is fallback)
    ad_result = supabase.table("meta_ads_performance").select(
        "ad_name"
    ).eq(
        "meta_ad_id", meta_ad_id
    ).limit(1).execute()

    ad_copy = ad_result.data[0].get("ad_name") if ad_result.data else None
    print(f"Ad name (used as copy): {ad_copy[:100] if ad_copy else '(none)'}...")

    # Run deep analysis
    print("\nRunning deep analysis (this may take 1-2 minutes)...")
    result = await service.deep_analyze_video(
        meta_ad_id=meta_ad_id,
        brand_id=brand_id,
        organization_id=org_id,
        ad_copy=ad_copy,
    )

    if not result:
        print("ERROR: Analysis returned None")
        return

    print(f"\n{'='*60}")
    print("ANALYSIS RESULT")
    print(f"{'='*60}")
    print(f"Status: {result.status}")
    if result.error_message:
        print(f"Error: {result.error_message}")
    if result.validation_errors:
        print(f"Validation errors: {result.validation_errors}")

    print(f"\nInput hash: {result.input_hash[:16]}...")
    print(f"Prompt version: {result.prompt_version}")
    print(f"Storage path: {result.storage_path}")

    print(f"\n--- Transcript ---")
    print(f"Full transcript: {result.full_transcript[:200] if result.full_transcript else '(none)'}...")
    print(f"Segments: {len(result.transcript_segments or [])} segments")

    print(f"\n--- Hooks ---")
    print(f"Spoken hook: {result.hook_transcript_spoken}")
    print(f"Overlay hook: {result.hook_transcript_overlay}")
    print(f"Hook type: {result.hook_type}")
    print(f"Hook fingerprint: {result.hook_fingerprint[:16] if result.hook_fingerprint else '(none)'}...")
    print(f"Effectiveness signals: {result.hook_effectiveness_signals}")
    print(f"\n--- Visual Hook ---")
    print(f"Visual description: {result.hook_visual_description}")
    print(f"Visual elements: {result.hook_visual_elements}")
    print(f"Visual type: {result.hook_visual_type}")

    print(f"\n--- Storyboard ---")
    print(f"Scenes: {len(result.storyboard or [])} scenes")
    if result.storyboard:
        for scene in result.storyboard[:3]:
            print(f"  {scene.get('timestamp_sec')}s: {scene.get('scene_description', '')[:60]}...")

    print(f"\n--- Messaging ---")
    print(f"Benefits: {result.benefits_shown}")
    print(f"Features: {result.features_demonstrated}")
    print(f"Pain points: {result.pain_points_addressed}")
    print(f"Angles: {result.angles_used}")
    print(f"JTBDs: {result.jobs_to_be_done}")

    print(f"\n--- Classification ---")
    print(f"Awareness level: {result.awareness_level}")
    print(f"Confidence: {result.awareness_confidence}")
    print(f"Format type: {result.format_type}")
    print(f"Production quality: {result.production_quality}")
    print(f"Duration: {result.video_duration_sec}s")

    # Save to database if status is ok
    if result.status == "ok":
        print(f"\n{'='*60}")
        print("Saving to database...")
        analysis_id = await service.save_video_analysis(result, org_id)
        if analysis_id:
            print(f"Saved! Analysis ID: {analysis_id}")
        else:
            print("ERROR: Failed to save")
    else:
        print(f"\nNot saving due to status: {result.status}")

    # Test idempotency - run again
    print(f"\n{'='*60}")
    print("Testing idempotency (running again)...")
    result2 = await service.deep_analyze_video(
        meta_ad_id=meta_ad_id,
        brand_id=brand_id,
        organization_id=org_id,
        ad_copy=ad_copy,
    )
    if result2 and result.input_hash == result2.input_hash:
        print("✓ Idempotency check passed - same input_hash, should have skipped Gemini call")
    else:
        print("✗ Idempotency check may have failed")


if __name__ == "__main__":
    asyncio.run(main())
