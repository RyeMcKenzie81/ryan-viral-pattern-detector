"""
Test Suite for Agent Tools - Task 1.6

Tests all 3 Pydantic AI tools with mocked services to verify:
- Tool signatures and parameter validation
- Service integrations (TwitterService, GeminiService, StatsService)
- Output formatting and error handling
- Edge cases and failure scenarios

Run with: python test_agent_tools.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

# Add project root to path
sys.path.insert(0, '/Users/ryemckenzie/projects/viraltracker')

from viraltracker.agent.tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.services.models import Tweet, HookAnalysis
from pydantic_ai import RunContext


# ============================================================================
# Test Data Fixtures
# ============================================================================

def create_mock_tweet(
    tweet_id: str = "1234567890",
    text: str = "This is a test tweet",
    view_count: int = 1000,
    like_count: int = 50,
    reply_count: int = 10,
    retweet_count: int = 20
) -> Tweet:
    """Create a mock Tweet object for testing"""
    return Tweet(
        id=tweet_id,
        text=text,
        view_count=view_count,
        like_count=like_count,
        reply_count=reply_count,
        retweet_count=retweet_count,
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
        author_followers=5000,
        url=f"https://twitter.com/testuser/status/{tweet_id}"
    )


def create_mock_hook_analysis(
    tweet_id: str = "1234567890",
    tweet_text: str = "Test tweet",
    hook_type: str = "hot_take",
    emotional_trigger: str = "validation"
) -> HookAnalysis:
    """Create a mock HookAnalysis object for testing"""
    return HookAnalysis(
        tweet_id=tweet_id,
        tweet_text=tweet_text,
        hook_type=hook_type,
        hook_type_confidence=0.85,
        emotional_trigger=emotional_trigger,
        emotional_trigger_confidence=0.80,
        content_pattern="statement",
        content_pattern_confidence=0.75,
        hook_explanation="This is a test explanation of why the hook works.",
        adaptation_notes="This is a test adaptation note for long-form content.",
        has_emoji=False,
        has_hashtags=False,
        has_question_mark=False,
        word_count=3
    )


# ============================================================================
# Test Tool 1: find_outliers_tool
# ============================================================================

async def test_find_outliers_basic():
    """Test find_outliers_tool with normal data"""
    print("\n[TEST] find_outliers_tool - Basic Functionality")

    # Create mock tweets (10 normal + 2 outliers)
    mock_tweets = [
        create_mock_tweet(f"tweet_{i}", f"Normal tweet {i}", view_count=100 + i*10, like_count=5+i)
        for i in range(10)
    ]
    # Add outliers with much higher engagement
    mock_tweets.append(create_mock_tweet("outlier_1", "Viral tweet 1", view_count=10000, like_count=500))
    mock_tweets.append(create_mock_tweet("outlier_2", "Viral tweet 2", view_count=8000, like_count=400))

    # Create mock dependencies
    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"

    # Mock TwitterService
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)
    mock_deps.twitter.mark_as_outlier = AsyncMock()

    # Mock StatsService
    mock_deps.stats = MagicMock()
    # Simulating z-score calculation returning indices of outliers
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[
        (10, 3.5),  # outlier_1 with z-score 3.5
        (11, 3.2)   # outlier_2 with z-score 3.2
    ])
    mock_deps.stats.calculate_percentile = MagicMock(return_value=99.0)
    mock_deps.stats.calculate_summary_stats = MagicMock(return_value={
        "mean": 150.0,
        "median": 120.0,
        "std": 250.5,
        "min": 100,
        "max": 10000,
        "count": 12,
        "q25": 110,
        "q75": 180
    })

    # Create mock RunContext
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    # Call the tool
    result = await find_outliers_tool(mock_ctx, hours_back=24, threshold=2.0)

    # Verify results
    assert isinstance(result, str), "Result should be a string"
    assert "2 viral outliers" in result or "2" in result, f"Should find 2 outliers, got: {result}"
    assert "outlier" in result.lower(), "Result should mention outliers"
    assert "Viral tweet" in result, "Result should include tweet text"

    # Verify service calls
    mock_deps.twitter.get_tweets.assert_called_once()
    assert mock_deps.stats.calculate_zscore_outliers.called
    assert mock_deps.twitter.mark_as_outlier.call_count == 2

    print("✅ PASS - Basic outlier detection works")
    return True


async def test_find_outliers_no_tweets():
    """Test find_outliers_tool when no tweets found"""
    print("\n[TEST] find_outliers_tool - No Tweets Found")

    # Create mock dependencies
    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "empty-project"
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=[])

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    # Call the tool
    result = await find_outliers_tool(mock_ctx, hours_back=24)

    # Verify results
    assert isinstance(result, str)
    assert "No tweets found" in result or "no tweets" in result.lower()
    assert "empty-project" in result

    print("✅ PASS - Handles no tweets gracefully")
    return True


async def test_find_outliers_no_outliers():
    """Test find_outliers_tool when no outliers detected"""
    print("\n[TEST] find_outliers_tool - No Outliers Detected")

    # Create mock tweets with similar engagement
    mock_tweets = [
        create_mock_tweet(f"tweet_{i}", f"Normal tweet {i}", view_count=100 + i, like_count=5)
        for i in range(10)
    ]

    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)

    # No outliers detected
    mock_deps.stats = MagicMock()
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[])

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    result = await find_outliers_tool(mock_ctx, hours_back=24, threshold=2.0)

    assert isinstance(result, str)
    assert "No outliers found" in result or "no outliers" in result.lower()
    assert "Suggestions" in result or "Try" in result  # Should provide suggestions

    print("✅ PASS - Handles no outliers with suggestions")
    return True


# ============================================================================
# Test Tool 2: analyze_hooks_tool
# ============================================================================

async def test_analyze_hooks_basic():
    """Test analyze_hooks_tool with normal data"""
    print("\n[TEST] analyze_hooks_tool - Basic Functionality")

    # Create mock tweets
    mock_tweets = [
        create_mock_tweet("tweet_1", "Hot take: screen time isn't the enemy", view_count=5000),
        create_mock_tweet("tweet_2", "This relatable moment changed everything", view_count=4500),
        create_mock_tweet("tweet_3", "Can you believe this happened?", view_count=4000)
    ]

    # Create mock hook analyses
    mock_analyses = [
        create_mock_hook_analysis("tweet_1", mock_tweets[0].text, "hot_take", "validation"),
        create_mock_hook_analysis("tweet_2", mock_tweets[1].text, "relatable_slice", "validation"),
        create_mock_hook_analysis("tweet_3", mock_tweets[2].text, "question_curiosity", "curiosity")
    ]

    # Create mock dependencies
    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"

    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)
    mock_deps.twitter.save_hook_analysis = AsyncMock()

    mock_deps.gemini = AsyncMock()
    # Return analyses in sequence
    mock_deps.gemini.analyze_hook = AsyncMock(side_effect=mock_analyses)

    mock_deps.stats = MagicMock()
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[(0, 2.5), (1, 2.3), (2, 2.1)])

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    # Call the tool
    result = await analyze_hooks_tool(mock_ctx, hours_back=24, limit=20)

    # Verify results
    assert isinstance(result, str)
    assert "3" in result or "Successfully" in result  # Should analyze 3 tweets
    assert "hot_take" in result or "Hook Types" in result
    assert "validation" in result or "Emotional Triggers" in result

    # Verify service calls
    assert mock_deps.gemini.analyze_hook.call_count == 3
    assert mock_deps.twitter.save_hook_analysis.call_count == 3

    print("✅ PASS - Basic hook analysis works")
    return True


async def test_analyze_hooks_with_tweet_ids():
    """Test analyze_hooks_tool with specific tweet IDs"""
    print("\n[TEST] analyze_hooks_tool - Specific Tweet IDs")

    tweet_ids = ["tweet_1", "tweet_2"]
    mock_tweets = [
        create_mock_tweet("tweet_1", "Test tweet 1"),
        create_mock_tweet("tweet_2", "Test tweet 2")
    ]

    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets_by_ids = AsyncMock(return_value=mock_tweets)
    mock_deps.twitter.save_hook_analysis = AsyncMock()

    mock_deps.gemini = AsyncMock()
    mock_deps.gemini.analyze_hook = AsyncMock(side_effect=[
        create_mock_hook_analysis("tweet_1", "Test tweet 1"),
        create_mock_hook_analysis("tweet_2", "Test tweet 2")
    ])

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    result = await analyze_hooks_tool(mock_ctx, tweet_ids=tweet_ids)

    assert isinstance(result, str)
    assert "2" in result or "Analyzing 2" in result

    # Should use get_tweets_by_ids, not get_tweets
    mock_deps.twitter.get_tweets_by_ids.assert_called_once_with(tweet_ids)
    assert not mock_deps.twitter.get_tweets.called

    print("✅ PASS - Specific tweet IDs work")
    return True


async def test_analyze_hooks_partial_failure():
    """Test analyze_hooks_tool when some analyses fail"""
    print("\n[TEST] analyze_hooks_tool - Partial Failure")

    mock_tweets = [
        create_mock_tweet("tweet_1", "Success tweet"),
        create_mock_tweet("tweet_2", "Fail tweet"),
        create_mock_tweet("tweet_3", "Success tweet 2")
    ]

    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)
    mock_deps.twitter.save_hook_analysis = AsyncMock()

    mock_deps.stats = MagicMock()
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[(0, 2.5), (1, 2.3), (2, 2.1)])

    # Mock Gemini to fail on second tweet
    mock_deps.gemini = AsyncMock()

    async def mock_analyze_side_effect(*args, **kwargs):
        tweet_id = kwargs.get('tweet_id', '')
        if tweet_id == "tweet_2":
            raise Exception("API quota exceeded")
        return create_mock_hook_analysis(tweet_id, kwargs.get('tweet_text', ''))

    mock_deps.gemini.analyze_hook = AsyncMock(side_effect=mock_analyze_side_effect)

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    result = await analyze_hooks_tool(mock_ctx, hours_back=24)

    assert isinstance(result, str)
    # Should successfully analyze 2 out of 3
    assert ("2" in result and "3" in result) or "Failed: 1" in result

    print("✅ PASS - Handles partial failures gracefully")
    return True


# ============================================================================
# Test Tool 3: export_results_tool
# ============================================================================

async def test_export_results_basic():
    """Test export_results_tool with markdown format"""
    print("\n[TEST] export_results_tool - Basic Functionality")

    # Create mock tweets and outliers
    mock_tweets = [
        create_mock_tweet("tweet_1", "Viral tweet", view_count=10000, like_count=500),
        create_mock_tweet("tweet_2", "Normal tweet", view_count=100, like_count=5)
    ]

    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"

    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)
    mock_deps.twitter.save_hook_analysis = AsyncMock()

    mock_deps.stats = MagicMock()
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[(0, 3.5)])
    mock_deps.stats.calculate_percentile = MagicMock(return_value=99.5)
    mock_deps.stats.calculate_summary_stats = MagicMock(return_value={
        "mean": 5050.0,
        "median": 5050.0,
        "std": 4950.0,
        "min": 100,
        "max": 10000,
        "count": 2,
        "q25": 2575,
        "q75": 7525
    })

    mock_deps.gemini = AsyncMock()
    mock_deps.gemini.analyze_hook = AsyncMock(return_value=create_mock_hook_analysis("tweet_1", "Viral tweet"))

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    # Call the tool
    result = await export_results_tool(mock_ctx, hours_back=24, include_hooks=True)

    # Verify markdown format
    assert isinstance(result, str)
    assert "# Viral Tweet Analysis Report" in result
    assert "test-project" in result
    assert "## Outlier Analysis" in result or "Outlier" in result
    assert "## Hook Analysis" in result or "Hook" in result
    assert "**" in result  # Markdown formatting

    print("✅ PASS - Basic export with markdown works")
    return True


async def test_export_results_without_hooks():
    """Test export_results_tool without hook analysis"""
    print("\n[TEST] export_results_tool - Without Hook Analysis")

    mock_tweets = [
        create_mock_tweet("tweet_1", "Viral tweet", view_count=10000)
    ]

    mock_deps = MagicMock(spec=AgentDependencies)
    mock_deps.project_name = "test-project"
    mock_deps.twitter = AsyncMock()
    mock_deps.twitter.get_tweets = AsyncMock(return_value=mock_tweets)

    mock_deps.stats = MagicMock()
    mock_deps.stats.calculate_zscore_outliers = MagicMock(return_value=[(0, 3.5)])
    mock_deps.stats.calculate_percentile = MagicMock(return_value=99.5)
    mock_deps.stats.calculate_summary_stats = MagicMock(return_value={
        "mean": 10000.0, "median": 10000.0, "std": 0.0,
        "min": 10000, "max": 10000, "count": 1, "q25": 10000, "q75": 10000
    })

    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = mock_deps

    result = await export_results_tool(mock_ctx, hours_back=24, include_hooks=False)

    assert isinstance(result, str)
    assert "Outlier" in result
    # Should NOT have hook analysis section
    assert "Hook Analysis" not in result or result.count("##") == 1  # Only outlier section

    print("✅ PASS - Export without hooks works")
    return True


# ============================================================================
# Test Suite Runner
# ============================================================================

async def run_all_tests():
    """Run all tests and report results"""
    print("=" * 70)
    print("AGENT TOOLS TEST SUITE - Task 1.6")
    print("=" * 70)

    tests = [
        # Tool 1: find_outliers_tool
        test_find_outliers_basic,
        test_find_outliers_no_tweets,
        test_find_outliers_no_outliers,

        # Tool 2: analyze_hooks_tool
        test_analyze_hooks_basic,
        test_analyze_hooks_with_tweet_ids,
        test_analyze_hooks_partial_failure,

        # Tool 3: export_results_tool
        test_export_results_basic,
        test_export_results_without_hooks,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            failed += 1
            error_msg = f"{test.__name__}: {str(e)}"
            errors.append(error_msg)
            print(f"❌ FAIL - {test.__name__}: {e}")

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total Tests: {len(tests)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if errors:
        print("\nFailed Tests:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\n🎉 All tests passed! Agent tools are ready.")

    print("=" * 70)

    return failed == 0


def main():
    """Main entry point"""
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
