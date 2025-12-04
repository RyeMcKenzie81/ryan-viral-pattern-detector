"""
Test Script: Brand Research Pipeline

Tests the full brand onboarding pipeline:
1. Scrape ads from Facebook Ad Library
2. Download images/videos to Supabase storage
3. Analyze images with Claude Vision
4. Synthesize insights into brand research summary

Run with:
    python test_brand_research_pipeline.py

Uses the same test URL from Phase 1 E2E test (Wuffes page).
"""

import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def test_pipeline_step_by_step():
    """Test pipeline step by step for debugging."""
    print("\n" + "="*70)
    print("BRAND RESEARCH PIPELINE - STEP BY STEP TEST")
    print("="*70)

    from viraltracker.pipelines import (
        brand_onboarding_graph,
        ScrapeAdsNode,
        BrandOnboardingState
    )
    from viraltracker.agent.dependencies import AgentDependencies

    # Test URL - Wuffes page (same as Phase 1 E2E test)
    test_url = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&is_targeted_country=false&media_type=all&search_type=page&view_all_page_id=470900729771745"

    print(f"\nTest URL: {test_url[:60]}...")
    print(f"Max ads: 10 (to limit API costs)")

    # Create dependencies
    print("\n" + "-"*70)
    print("Initializing dependencies...")
    print("-"*70)

    deps = AgentDependencies.create()
    print("✓ AgentDependencies created")

    # Create initial state
    state = BrandOnboardingState(
        ad_library_url=test_url,
        brand_id=None,  # No brand for testing
        max_ads=10,  # Limit to 10 for cost control
        analyze_videos=False  # Skip video analysis for now
    )

    print(f"✓ State initialized: max_ads={state.max_ads}, analyze_videos={state.analyze_videos}")

    # Run the pipeline
    print("\n" + "-"*70)
    print("Running pipeline...")
    print("-"*70)

    try:
        result = await brand_onboarding_graph.run(
            ScrapeAdsNode(),
            state=state,
            deps=deps
        )

        print("\n" + "-"*70)
        print("PIPELINE RESULTS")
        print("-"*70)

        output = result.output
        print(f"Status: {output.get('status')}")

        if output.get('status') == 'success':
            print("\n✓ Pipeline completed successfully!")

            metrics = output.get('metrics', {})
            print(f"\nMetrics:")
            print(f"  Ads scraped: {metrics.get('ads_scraped', 0)}")
            print(f"  Images analyzed: {metrics.get('images_analyzed', 0)}")
            print(f"  Videos analyzed: {metrics.get('videos_analyzed', 0)}")

            summary = output.get('summary', {})
            if summary:
                print(f"\nBrand Research Summary:")
                print(f"  Top Benefits: {len(summary.get('top_benefits', []))}")
                print(f"  Top USPs: {len(summary.get('top_usps', []))}")
                print(f"  Pain Points: {len(summary.get('common_pain_points', []))}")
                print(f"  Hooks: {len(summary.get('recommended_hooks', []))}")

                # Show some examples
                if summary.get('top_benefits'):
                    print(f"\n  Example benefits:")
                    for b in summary['top_benefits'][:3]:
                        print(f"    - {b}")

                if summary.get('recommended_hooks'):
                    print(f"\n  Example hooks:")
                    for h in summary['recommended_hooks'][:2]:
                        print(f"    - {h.get('hook_template', h)}")

            product_data = output.get('product_data', {})
            if product_data:
                print(f"\nProduct Data (for onboarding):")
                print(f"  Benefits: {len(product_data.get('benefits', []))}")
                print(f"  USPs: {len(product_data.get('unique_selling_points', []))}")
                print(f"  Hooks: {len(product_data.get('hooks', []))}")

        elif output.get('status') == 'error':
            print(f"\n✗ Pipeline failed!")
            print(f"  Step: {output.get('step')}")
            print(f"  Error: {output.get('error')}")

        elif output.get('status') == 'no_ads':
            print(f"\n⚠ No ads found at the URL")
            print(f"  Message: {output.get('message')}")

        elif output.get('status') == 'no_analyses':
            print(f"\n⚠ No analyses could be performed")
            print(f"  Message: {output.get('message')}")
            metrics = output.get('metrics', {})
            print(f"  Ads scraped: {metrics.get('ads_scraped', 0)}")
            print(f"  Images downloaded: {metrics.get('images_downloaded', 0)}")

    except Exception as e:
        print(f"\n✗ Pipeline execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


async def test_quick_validation():
    """Quick validation that pipeline can be imported and initialized."""
    print("\n" + "="*70)
    print("QUICK VALIDATION TEST")
    print("="*70)

    try:
        from viraltracker.pipelines import (
            brand_onboarding_graph,
            run_brand_onboarding,
            BrandOnboardingState,
            ScrapeAdsNode,
            DownloadAssetsNode,
            AnalyzeImagesNode,
            SynthesizeNode
        )
        print("✓ All pipeline components import successfully")

        from viraltracker.services.brand_research_service import BrandResearchService
        print("✓ BrandResearchService imports successfully")

        from viraltracker.agent.dependencies import AgentDependencies
        deps = AgentDependencies.create()
        print("✓ AgentDependencies.create() works")

        assert hasattr(deps, 'brand_research'), "Missing brand_research service"
        print("✓ deps.brand_research is available")

        assert deps.brand_research is not None
        print("✓ BrandResearchService is initialized")

        print("\n✓ All validation checks passed!")
        return True

    except Exception as e:
        print(f"\n✗ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run tests."""
    print("\n" + "="*70)
    print("BRAND RESEARCH PIPELINE - TEST SUITE")
    print("="*70)

    # First run quick validation
    validation_passed = await test_quick_validation()

    if not validation_passed:
        print("\n⚠ Validation failed - skipping full pipeline test")
        return

    # Ask before running full pipeline (costs API tokens)
    print("\n" + "-"*70)
    print("The full pipeline test will:")
    print("  - Scrape ~10 ads from Facebook Ad Library (Apify)")
    print("  - Download assets to Supabase storage")
    print("  - Analyze images with Claude Vision (API cost)")
    print("  - Synthesize insights with Claude (API cost)")
    print("-"*70)

    response = input("\nRun full pipeline test? (y/n): ").strip().lower()
    if response == 'y':
        await test_pipeline_step_by_step()
    else:
        print("Skipping full pipeline test.")

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
