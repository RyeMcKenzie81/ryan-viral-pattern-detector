"""
Test script for Agent Dependencies (Task 1.5).

Tests AgentDependencies class to ensure it correctly initializes all services
and provides proper dependency injection for the Pydantic AI agent.

Run: python test_agent_dependencies.py
"""

import sys


def test_dependencies_import():
    """Test 1: Verify AgentDependencies can be imported"""
    print("=" * 60)
    print("TEST 1: AgentDependencies Import")
    print("=" * 60)

    try:
        from viraltracker.agent.dependencies import AgentDependencies
        print("\n✓ AgentDependencies imported successfully")
        return True
    except Exception as e:
        print(f"\n❌ Failed to import AgentDependencies: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dependencies_creation():
    """Test 2: Verify AgentDependencies.create() factory method"""
    print("\n" + "=" * 60)
    print("TEST 2: AgentDependencies Factory Method")
    print("=" * 60)

    try:
        from viraltracker.agent.dependencies import AgentDependencies

        # Test with defaults
        print("\n✓ Testing with default parameters...")
        deps = AgentDependencies.create()

        print(f"  - Project name: {deps.project_name}")
        print(f"  - Has TwitterService: {deps.twitter is not None}")
        print(f"  - Has GeminiService: {deps.gemini is not None}")
        print(f"  - Has StatsService: {deps.stats is not None}")

        assert deps.project_name == "yakety-pack-instagram", "Default project name should be yakety-pack-instagram"
        assert deps.twitter is not None, "TwitterService should be initialized"
        assert deps.gemini is not None, "GeminiService should be initialized"
        assert deps.stats is not None, "StatsService should be initialized"

        print("\n✓ Testing with custom project name...")
        deps2 = AgentDependencies.create(project_name="test-project")
        print(f"  - Custom project name: {deps2.project_name}")
        assert deps2.project_name == "test-project", "Custom project name should be set"

        print("\n✓ Testing with custom rate limit...")
        deps3 = AgentDependencies.create(rate_limit_rpm=6)
        print(f"  - GeminiService rate limit: {deps3.gemini._requests_per_minute} req/min")
        assert deps3.gemini._requests_per_minute == 6, "Rate limit should be 6 req/min"

        print("\n✅ All factory method tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Factory method test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dependencies_services():
    """Test 3: Verify all services are properly initialized"""
    print("\n" + "=" * 60)
    print("TEST 3: Service Initialization")
    print("=" * 60)

    try:
        from viraltracker.agent.dependencies import AgentDependencies
        from viraltracker.services.twitter_service import TwitterService
        from viraltracker.services.gemini_service import GeminiService
        from viraltracker.services.stats_service import StatsService

        deps = AgentDependencies.create()

        # Check TwitterService
        print("\n✓ Checking TwitterService...")
        assert isinstance(deps.twitter, TwitterService), "twitter should be TwitterService instance"
        assert hasattr(deps.twitter, 'get_tweets'), "TwitterService should have get_tweets method"
        print(f"  - Is TwitterService: {isinstance(deps.twitter, TwitterService)}")
        print(f"  - Has get_tweets: {hasattr(deps.twitter, 'get_tweets')}")

        # Check GeminiService
        print("\n✓ Checking GeminiService...")
        assert isinstance(deps.gemini, GeminiService), "gemini should be GeminiService instance"
        assert hasattr(deps.gemini, 'analyze_hook'), "GeminiService should have analyze_hook method"
        print(f"  - Is GeminiService: {isinstance(deps.gemini, GeminiService)}")
        print(f"  - Has analyze_hook: {hasattr(deps.gemini, 'analyze_hook')}")
        print(f"  - Model: {deps.gemini.model_name}")
        print(f"  - Rate limit: {deps.gemini._requests_per_minute} req/min")

        # Check StatsService
        print("\n✓ Checking StatsService...")
        assert isinstance(deps.stats, StatsService), "stats should be StatsService instance"
        assert hasattr(deps.stats, 'calculate_zscore_outliers'), "StatsService should have calculate_zscore_outliers"
        print(f"  - Is StatsService: {isinstance(deps.stats, StatsService)}")
        print(f"  - Has calculate_zscore_outliers: {hasattr(deps.stats, 'calculate_zscore_outliers')}")

        print("\n✅ All service initialization tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Service initialization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dependencies_string_repr():
    """Test 4: Verify __str__ and __repr__ methods"""
    print("\n" + "=" * 60)
    print("TEST 4: String Representation")
    print("=" * 60)

    try:
        from viraltracker.agent.dependencies import AgentDependencies

        deps = AgentDependencies.create(project_name="test-project")

        print("\n✓ Testing __str__ method...")
        str_repr = str(deps)
        print(f"  - str(): {str_repr}")
        assert "test-project" in str_repr, "__str__ should contain project name"
        assert "AgentDependencies" in str_repr, "__str__ should contain class name"

        print("\n✓ Testing __repr__ method...")
        repr_str = repr(deps)
        print(f"  - repr(): {repr_str}")
        assert "test-project" in repr_str, "__repr__ should contain project name"

        print("\n✅ String representation tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ String representation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("AGENT DEPENDENCIES TEST SUITE")
    print("Phase 1, Task 1.5")
    print("=" * 60)

    results = []

    try:
        # Test 1: Import
        results.append(("Import", test_dependencies_import()))

        # Test 2: Factory method
        results.append(("Factory Method", test_dependencies_creation()))

        # Test 3: Service initialization
        results.append(("Service Initialization", test_dependencies_services()))

        # Test 4: String representation
        results.append(("String Representation", test_dependencies_string_repr()))

    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
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
        print("\n🎉 All tests passed! Agent dependencies ready.")
        print("\nNext steps:")
        print("  1. Proceed to Task 1.6 (Agent Tools)")
        return True
    else:
        print("\n❌ Some tests failed. Please fix before proceeding.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
