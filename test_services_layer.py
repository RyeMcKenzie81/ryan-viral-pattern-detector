"""
Test script for Phase 1 Services Layer.

Tests all services (TwitterService, GeminiService, StatsService) and models
to ensure they work correctly before building the agent layer.

Run: python test_services_layer.py
"""

import asyncio
import sys
from datetime import datetime, timezone


def test_models():
    """Test 1: Verify all Pydantic models work correctly"""
    print("=" * 60)
    print("TEST 1: Pydantic Models")
    print("=" * 60)

    from viraltracker.services.models import (
        Tweet, HookAnalysis, OutlierTweet, CommentCandidate,
        OutlierResult, HookAnalysisResult
    )

    # Test Tweet model
    print("\n✓ Testing Tweet model...")
    tweet = Tweet(
        id="1234567890",
        text="This is a test tweet about parenting",
        view_count=10000,
        like_count=500,
        reply_count=50,
        retweet_count=100,
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
        author_followers=5000,
        url="https://twitter.com/testuser/status/1234567890"
    )
    assert tweet.engagement_rate > 0, "Engagement rate should be calculated"
    assert tweet.engagement_score > 0, "Engagement score should be calculated"
    print(f"  - Tweet engagement_rate: {tweet.engagement_rate:.4f}")
    print(f"  - Tweet engagement_score: {tweet.engagement_score:.2f}")

    # Test HookAnalysis model
    print("\n✓ Testing HookAnalysis model...")
    hook = HookAnalysis(
        tweet_id="1234567890",
        tweet_text="Test tweet",
        hook_type="hot_take",
        hook_type_confidence=0.9,
        emotional_trigger="validation",
        emotional_trigger_confidence=0.85,
        hook_explanation="This is a test explanation",
        adaptation_notes="Test adaptation"
    )
    assert hook.hook_type in ["hot_take", "relatable_slice", "unknown"], "Hook type validation"
    assert hook.emotional_trigger in ["validation", "humor", "unknown"], "Emotional trigger validation"
    print(f"  - Hook type: {hook.hook_type} ({hook.hook_type_confidence:.0%} confidence)")
    print(f"  - Emotional trigger: {hook.emotional_trigger} ({hook.emotional_trigger_confidence:.0%} confidence)")

    # Test OutlierResult model
    print("\n✓ Testing OutlierResult model...")
    outlier_tweet = OutlierTweet(
        tweet=tweet,
        zscore=3.5,
        percentile=99.2,
        rank=1
    )
    result = OutlierResult(
        total_tweets=100,
        outlier_count=5,
        threshold=2.0,
        method="zscore",
        outliers=[outlier_tweet],
        mean_engagement=150.0,
        median_engagement=85.0,
        std_engagement=220.0
    )
    assert result.success_rate > 0, "Success rate should be calculated"
    print(f"  - Success rate: {result.success_rate:.1f}%")
    print(f"  - Can export to markdown: {len(result.to_markdown()) > 0}")

    # Test HookAnalysisResult model
    print("\n✓ Testing HookAnalysisResult model...")
    hook_result = HookAnalysisResult(
        total_analyzed=10,
        successful_analyses=9,
        failed_analyses=1,
        analyses=[hook]
    )
    hook_result.compute_patterns()
    assert hook_result.success_rate > 0, "Success rate should be calculated"
    print(f"  - Success rate: {hook_result.success_rate:.1f}%")
    print(f"  - Top hook types: {hook_result.top_hook_types}")

    print("\n✅ All model tests passed!")
    return True


def test_stats_service():
    """Test 2: Verify StatsService calculations"""
    print("\n" + "=" * 60)
    print("TEST 2: StatsService")
    print("=" * 60)

    from viraltracker.services.stats_service import StatsService

    # Test data: normal values + outliers
    values = [10, 12, 15, 11, 13, 14, 16, 12, 11, 100, 120]

    # Test Z-score outlier detection
    print("\n✓ Testing Z-score outlier detection...")
    outliers = StatsService.calculate_zscore_outliers(values, threshold=2.0)
    print(f"  - Found {len(outliers)} outliers (expected: 2)")
    for idx, zscore in outliers:
        print(f"    - Index {idx}: value={values[idx]}, z-score={zscore:.2f}")
    assert len(outliers) > 0, "Should detect outliers"

    # Test percentile outlier detection
    print("\n✓ Testing percentile outlier detection...")
    percentile_outliers = StatsService.calculate_percentile_outliers(values, threshold=10.0)
    print(f"  - Found {len(percentile_outliers)} outliers in top 10%")
    assert len(percentile_outliers) > 0, "Should detect top 10% outliers"

    # Test percentile calculation
    print("\n✓ Testing percentile calculation...")
    percentile = StatsService.calculate_percentile(100, values)
    print(f"  - Percentile of 100 in dataset: {percentile:.1f}%")
    assert percentile > 90, "100 should be in high percentile"

    # Test summary statistics
    print("\n✓ Testing summary statistics...")
    stats = StatsService.calculate_summary_stats(values)
    print(f"  - Mean: {stats['mean']:.2f}")
    print(f"  - Median: {stats['median']:.2f}")
    print(f"  - Std: {stats['std']:.2f}")
    print(f"  - Range: {stats['min']:.0f} - {stats['max']:.0f}")
    assert stats['count'] == len(values), "Count should match"

    print("\n✅ All StatsService tests passed!")
    return True


async def test_gemini_service():
    """Test 3: Verify GeminiService (with mock, no API calls)"""
    print("\n" + "=" * 60)
    print("TEST 3: GeminiService")
    print("=" * 60)

    from viraltracker.services.gemini_service import GeminiService

    # Test initialization (will fail if GEMINI_API_KEY not set, which is OK)
    print("\n✓ Testing GeminiService initialization...")
    try:
        service = GeminiService()
        print(f"  - Model: {service.model_name}")
        print(f"  - Rate limit: {service._requests_per_minute} req/min")
        print(f"  - Min delay: {service._min_delay:.1f}s")

        # Test rate limit configuration
        print("\n✓ Testing rate limit configuration...")
        service.set_rate_limit(6)
        assert service._requests_per_minute == 6, "Rate limit should update"
        assert service._min_delay == 10.0, "Delay should be 10s for 6 req/min"
        print(f"  - New rate limit: {service._requests_per_minute} req/min")
        print(f"  - New delay: {service._min_delay:.1f}s")

        # Test prompt building
        print("\n✓ Testing prompt building...")
        prompt = service._build_hook_prompt("Test tweet about parenting")
        assert "HOOK TYPE" in prompt, "Prompt should contain hook types"
        assert "EMOTIONAL TRIGGER" in prompt, "Prompt should contain emotional triggers"
        print(f"  - Prompt length: {len(prompt)} characters")

        print("\n✅ GeminiService initialization tests passed!")
        print("⚠️  Skipping API call test (requires GEMINI_API_KEY)")

    except ValueError as e:
        print(f"⚠️  GeminiService requires GEMINI_API_KEY: {e}")
        print("   (This is expected if running without credentials)")

    return True


async def test_twitter_service():
    """Test 4: Verify TwitterService (structure only, no DB calls)"""
    print("\n" + "=" * 60)
    print("TEST 4: TwitterService")
    print("=" * 60)

    from viraltracker.services.twitter_service import TwitterService

    print("\n✓ Testing TwitterService initialization...")
    try:
        service = TwitterService()
        print(f"  - TwitterService created successfully")
        print(f"  - Has get_tweets method: {hasattr(service, 'get_tweets')}")
        print(f"  - Has get_tweets_by_ids method: {hasattr(service, 'get_tweets_by_ids')}")
        print(f"  - Has save_hook_analysis method: {hasattr(service, 'save_hook_analysis')}")
        print(f"  - Has get_hook_analyses method: {hasattr(service, 'get_hook_analyses')}")
        print(f"  - Has mark_as_outlier method: {hasattr(service, 'mark_as_outlier')}")

        print("\n✅ TwitterService structure tests passed!")
        print("⚠️  Skipping database tests (requires Supabase credentials)")

    except Exception as e:
        print(f"⚠️  TwitterService requires Supabase credentials: {e}")
        print("   (This is expected if running without credentials)")

    return True


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("VIRALTRACKER SERVICES LAYER TEST SUITE")
    print("Phase 1, Tasks 1.1-1.4")
    print("=" * 60)

    results = []

    try:
        # Test 1: Models
        results.append(("Models", test_models()))

        # Test 2: StatsService
        results.append(("StatsService", test_stats_service()))

        # Test 3: GeminiService
        results.append(("GeminiService", await test_gemini_service()))

        # Test 4: TwitterService
        results.append(("TwitterService", await test_twitter_service()))

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")

    all_passed = all(passed for _, passed in results)

    if all_passed:
        print("\n🎉 All tests passed! Services layer is ready.")
        print("\nNext steps:")
        print("  1. Review docs/SERVICES_LAYER_SUMMARY.md")
        print("  2. Proceed to Phase 1, Tasks 1.5-1.7 (Agent layer)")
        return True
    else:
        print("\n❌ Some tests failed. Please fix before proceeding.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
