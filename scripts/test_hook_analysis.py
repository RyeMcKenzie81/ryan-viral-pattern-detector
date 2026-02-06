#!/usr/bin/env python3
"""Test script for HookAnalysisService.

Usage:
    python scripts/test_hook_analysis.py

Tests hook analysis queries against Wonder Paws data.
Requires video analysis data to exist in ad_video_analysis table.
"""

import asyncio
import os
import sys
from pprint import pprint

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import UUID


# Wonder Paws brand ID
WONDER_PAWS_BRAND_ID = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")


def main():
    """Run hook analysis tests."""
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.ad_intelligence.hook_analysis_service import (
        HookAnalysisService,
    )

    supabase = get_supabase_client()
    service = HookAnalysisService(supabase)

    print("=" * 60)
    print("HookAnalysisService Test Suite")
    print("=" * 60)
    print(f"\nBrand ID: {WONDER_PAWS_BRAND_ID}")

    # Test 1: Top hooks by fingerprint
    print("\n" + "-" * 60)
    print("TEST 1: get_top_hooks_by_fingerprint()")
    print("-" * 60)
    try:
        top_hooks = service.get_top_hooks_by_fingerprint(
            brand_id=WONDER_PAWS_BRAND_ID,
            limit=5,
            min_spend=50,  # Lower threshold for testing
            date_range_days=90,
            sort_by="roas"
        )
        print(f"Found {len(top_hooks)} hooks")
        if top_hooks:
            print("\nTop hook by ROAS:")
            hook = top_hooks[0]
            print(f"  Type: {hook['hook_type']}")
            print(f"  Visual Type: {hook['hook_visual_type']}")
            print(f"  Spoken: {(hook['hook_transcript_spoken'] or '')[:80]}...")
            print(f"  Ad Count: {hook['ad_count']}")
            print(f"  Total Spend: ${hook['total_spend']:,.2f}")
            print(f"  Avg ROAS: {hook['avg_roas']:.2f}x")
            print(f"  Avg Hook Rate: {hook['avg_hook_rate']:.2%}")
        else:
            print("No hooks found. Make sure video analysis data exists.")
        print("PASSED" if top_hooks else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 2: Hooks by type
    print("\n" + "-" * 60)
    print("TEST 2: get_hooks_by_type()")
    print("-" * 60)
    try:
        by_type = service.get_hooks_by_type(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90
        )
        print(f"Found {len(by_type)} hook types")
        if by_type:
            print("\nPerformance by hook type:")
            for t in by_type[:5]:
                print(f"  {t['hook_type']}: {t['ad_count']} ads, ${t['total_spend']:,.0f} spend, {t['avg_roas']:.2f}x ROAS")
        print("PASSED" if by_type else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 3: Hooks by visual type
    print("\n" + "-" * 60)
    print("TEST 3: get_hooks_by_visual_type()")
    print("-" * 60)
    try:
        by_visual = service.get_hooks_by_visual_type(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90
        )
        print(f"Found {len(by_visual)} visual types")
        if by_visual:
            print("\nPerformance by visual type:")
            for v in by_visual[:5]:
                print(f"  {v['hook_visual_type']}: {v['ad_count']} ads, ${v['total_spend']:,.0f} spend")
                if v['common_visual_elements']:
                    print(f"    Common elements: {', '.join(v['common_visual_elements'][:3])}")
        print("PASSED" if by_visual else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 4: Hooks by landing page
    print("\n" + "-" * 60)
    print("TEST 4: get_hooks_by_landing_page()")
    print("-" * 60)
    try:
        by_lp = service.get_hooks_by_landing_page(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90,
            limit=5
        )
        print(f"Found {len(by_lp)} landing pages with hooks")
        if by_lp:
            print("\nHooks by landing page:")
            for lp in by_lp[:3]:
                print(f"  {lp['landing_page_url'] or 'Unknown URL'}")
                print(f"    Hook count: {lp['hook_count']}, Total spend: ${lp['total_spend']:,.0f}")
                if lp['best_hook_fingerprint']:
                    print(f"    Best hook: {lp['best_hook_fingerprint'][:16]}...")
        print("PASSED" if by_lp else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 5: Quadrant analysis
    print("\n" + "-" * 60)
    print("TEST 5: get_hooks_by_quadrant()")
    print("-" * 60)
    try:
        quadrants = service.get_hooks_by_quadrant(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90,
            min_spend=50,
            hook_rate_threshold=0.15,  # Lower for testing
            roas_threshold=0.5  # Lower for testing
        )
        print("\nQuadrant counts:")
        print(f"  Winners (high hook rate, high ROAS): {len(quadrants['winners'])}")
        print(f"  Hidden Gems (low hook rate, high ROAS): {len(quadrants['hidden_gems'])}")
        print(f"  Engaging Not Converting (high hook rate, low ROAS): {len(quadrants['engaging_not_converting'])}")
        print(f"  Losers (low hook rate, low ROAS): {len(quadrants['losers'])}")

        total = sum(len(q) for q in quadrants.values())
        print("PASSED" if total > 0 else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 6: High hook rate, low ROAS
    print("\n" + "-" * 60)
    print("TEST 6: get_high_hook_rate_low_roas()")
    print("-" * 60)
    try:
        problem_hooks = service.get_high_hook_rate_low_roas(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90,
            min_spend=50,
            hook_rate_threshold=0.15,
            roas_threshold=1.0,
            limit=3
        )
        print(f"Found {len(problem_hooks)} hooks with high engagement but low ROAS")
        if problem_hooks:
            hook = problem_hooks[0]
            print(f"\nExample: {hook['hook_type']} hook")
            print(f"  Hook Rate: {hook['avg_hook_rate']:.2%} (good)")
            print(f"  ROAS: {hook['avg_roas']:.2f}x (needs improvement)")
            print(f"  Suggested action: {hook['suggested_action'][:60]}...")
        print("PASSED")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 7: Untested hook types
    print("\n" + "-" * 60)
    print("TEST 7: get_untested_hook_types()")
    print("-" * 60)
    try:
        gaps = service.get_untested_hook_types(brand_id=WONDER_PAWS_BRAND_ID)
        print(f"\nUntested hook types: {len(gaps['untested_hook_types'])}")
        if gaps['untested_hook_types']:
            print(f"  {', '.join(gaps['untested_hook_types'][:5])}")

        print(f"Untested visual types: {len(gaps['untested_visual_types'])}")
        if gaps['untested_visual_types']:
            print(f"  {', '.join(gaps['untested_visual_types'][:5])}")

        print(f"\nSuggestions:")
        for s in gaps['suggestions'][:3]:
            print(f"  - {s}")

        print("PASSED")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 8: Hook insights
    print("\n" + "-" * 60)
    print("TEST 8: get_hook_insights()")
    print("-" * 60)
    try:
        insights = service.get_hook_insights(
            brand_id=WONDER_PAWS_BRAND_ID,
            date_range_days=90
        )
        print("\nSummary stats:")
        if insights.get('summary_stats'):
            stats = insights['summary_stats']
            print(f"  Hooks analyzed: {stats.get('total_hooks_analyzed', 0)}")
            print(f"  Total spend: ${stats.get('total_spend', 0):,.2f}")
            print(f"  Weighted avg ROAS: {stats.get('weighted_avg_roas', 0):.2f}x")

        if insights.get('top_performer'):
            print(f"\nTop performer: {insights['top_performer']['hook_type']}")
            print(f"  ROAS: {insights['top_performer']['avg_roas']:.2f}x")

        print(f"\nRecommendations:")
        for r in insights.get('recommendations', [])[:3]:
            print(f"  - {r[:80]}...")

        print("PASSED" if insights.get('summary_stats') else "SKIPPED (no data)")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 9: Hook details (if we have hooks)
    print("\n" + "-" * 60)
    print("TEST 9: get_hook_details()")
    print("-" * 60)
    try:
        if top_hooks and top_hooks[0].get('hook_fingerprint'):
            fingerprint = top_hooks[0]['hook_fingerprint']
            details = service.get_hook_details(
                brand_id=WONDER_PAWS_BRAND_ID,
                hook_fingerprint=fingerprint
            )
            if details:
                print(f"Details for hook: {fingerprint[:16]}...")
                print(f"  Type: {details['hook_type']}")
                print(f"  Visual Type: {details['hook_visual_type']}")
                print(f"  Ad count: {details['ad_count']}")
                print(f"  Consistency: {details['performance_consistency']}")
                print(f"  Landing pages: {len(details.get('landing_pages', []))}")
                print("PASSED")
            else:
                print("Hook details not found")
                print("SKIPPED")
        else:
            print("No hooks available to test details")
            print("SKIPPED")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test 10: Hook comparison (if we have multiple hooks)
    print("\n" + "-" * 60)
    print("TEST 10: get_hook_comparison()")
    print("-" * 60)
    try:
        if len(top_hooks) >= 2:
            fp_a = top_hooks[0]['hook_fingerprint']
            fp_b = top_hooks[1]['hook_fingerprint']
            comparison = service.get_hook_comparison(
                brand_id=WONDER_PAWS_BRAND_ID,
                fingerprint_a=fp_a,
                fingerprint_b=fp_b
            )
            if not comparison.get('error'):
                print(f"Comparing two hooks:")
                print(f"  Hook A ({comparison['hook_a']['type']}): {comparison['hook_a']['metrics']['avg_roas']:.2f}x ROAS")
                print(f"  Hook B ({comparison['hook_b']['type']}): {comparison['hook_b']['metrics']['avg_roas']:.2f}x ROAS")
                print(f"  Winner by ROAS: {comparison['winner_by']['roas']}")
                print(f"  Statistical confidence: {comparison['statistical_confidence']}")
                print(f"  Recommendation: {comparison['recommendation'][:60]}...")
                print("PASSED")
            else:
                print(f"Comparison error: {comparison.get('error')}")
                print("FAILED")
        else:
            print("Not enough hooks available to test comparison")
            print("SKIPPED")
    except Exception as e:
        print(f"FAILED: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
