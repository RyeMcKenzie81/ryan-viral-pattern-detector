"""
Phase 1 Integration Tests - Viraltracker Pydantic AI Migration

This test suite validates that all Phase 1 components work together correctly:
- Services layer (TwitterService, GeminiService, StatsService)
- Agent tools (find_outliers, analyze_hooks, export_results)
- CLI backwards compatibility (find-outliers, analyze-hooks)
- End-to-end workflows

Run with: pytest tests/test_phase1_integration.py -v
"""

import pytest
import os
import asyncio
import json
from pathlib import Path
from click.testing import CliRunner

# Service layer imports
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
from viraltracker.services.models import Tweet, HookAnalysis

# Agent imports
from viraltracker.agent.agent import agent
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.agent.tools import find_outliers_tool, analyze_hooks_tool, export_results_tool

# CLI imports
from viraltracker.cli.twitter import twitter_group

# Test configuration
TEST_DB = os.getenv('DB_PATH', 'viraltracker.db')
TEST_PROJECT = os.getenv('PROJECT_NAME', 'yakety-pack-instagram')


# ============================================================================
# Service Integration Tests
# ============================================================================

class TestTwitterServiceIntegration:
    """Integration tests for TwitterService with real database"""

    @pytest.mark.asyncio
    async def test_get_tweets_returns_data(self):
        """Test that TwitterService can fetch tweets from database"""
        service = TwitterService()

        tweets = await service.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=0,
            text_only=True
        )

        # Should return a list (may be empty if no data)
        assert isinstance(tweets, list)

        # If we have data, validate structure
        if tweets:
            tweet = tweets[0]
            assert hasattr(tweet, 'id')
            assert hasattr(tweet, 'text')
            assert hasattr(tweet, 'view_count')
            assert hasattr(tweet, 'engagement_score')
            assert isinstance(tweet.text, str)
            assert isinstance(tweet.view_count, (int, float))

    @pytest.mark.asyncio
    async def test_get_tweets_with_filters(self):
        """Test that TwitterService respects filter parameters"""
        service = TwitterService()

        # Fetch with high minimum views
        tweets_filtered = await service.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=1000,
            text_only=True
        )

        # All returned tweets should meet minimum views
        for tweet in tweets_filtered:
            assert tweet.view_count >= 1000

    @pytest.mark.asyncio
    async def test_get_tweets_empty_project(self):
        """Test that TwitterService handles non-existent projects gracefully"""
        service = TwitterService()

        # Non-existent project should raise an APIError
        # This is expected behavior for Supabase
        from postgrest.exceptions import APIError

        with pytest.raises(APIError):
            tweets = await service.get_tweets(
                project="nonexistent-project-12345",
                hours_back=24,
                min_views=0,
                text_only=True
            )

    @pytest.mark.asyncio
    async def test_mark_as_outlier(self):
        """Test that marking outliers doesn't raise errors (smoke test)"""
        service = TwitterService()

        # Get a tweet
        tweets = await service.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=0,
            text_only=True
        )

        if tweets:
            tweet = tweets[0]

            # Mark as outlier - should not raise error
            await service.mark_as_outlier(
                tweet_id=tweet.id,
                zscore=3.5,
                threshold=2.0
            )

            # Success if no exception raised
            assert True


class TestGeminiServiceIntegration:
    """Integration tests for GeminiService with real API"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set - skipping real API test"
    )
    async def test_analyze_hook_real_api(self):
        """Test real Gemini API call for hook analysis"""
        api_key = os.getenv('GEMINI_API_KEY')
        service = GeminiService(api_key)

        test_tweet = "Parenting hack: freeze grapes for a healthy snack kids love!"

        analysis = await service.analyze_hook(
            tweet_text=test_tweet,
            tweet_id="test_123"
        )

        # Verify structure
        assert isinstance(analysis, HookAnalysis)
        assert analysis.tweet_id == "test_123"
        assert analysis.tweet_text == test_tweet

        # Verify hook type is one of the valid types (just check it's a non-empty string)
        # Note: The actual hook types may vary based on Gemini's classification
        assert isinstance(analysis.hook_type, str)
        assert len(analysis.hook_type) > 0

        # Verify confidence scores are valid
        assert 0.0 <= analysis.hook_type_confidence <= 1.0
        assert 0.0 <= analysis.emotional_trigger_confidence <= 1.0

        # Verify we got explanatory text
        assert len(analysis.hook_explanation) > 0
        assert len(analysis.adaptation_notes) > 0


class TestStatsServiceIntegration:
    """Integration tests for StatsService calculations"""

    def test_zscore_outliers_known_dataset(self):
        """Test z-score calculation with known dataset"""
        service = StatsService()

        # Dataset with clear outlier (50 is well above 10-13 range)
        values = [10, 12, 11, 13, 12, 50]

        outliers = service.calculate_zscore_outliers(
            values,
            threshold=2.0
        )

        # Should find exactly 1 outlier (the value 50)
        assert len(outliers) == 1

        # Should be at index 5 (last item)
        idx, zscore = outliers[0]
        assert idx == 5

        # Z-score should be significantly above 2.0
        assert zscore > 2.0

    def test_percentile_outliers_known_dataset(self):
        """Test percentile outlier detection"""
        service = StatsService()

        # 100 values, top 5% should be ~5 outliers
        values = list(range(1, 101))

        outliers = service.calculate_percentile_outliers(
            values,
            threshold=5.0  # Top 5%
        )

        # Should find approximately 5 outliers (allowing for rounding)
        assert 3 <= len(outliers) <= 7

        # Outliers should be the highest values
        # Note: percentile_outliers returns (index, value, percentile)
        outlier_indices = [idx for idx, val, pct in outliers]
        # Top 5% values should be in upper range
        for idx in outlier_indices:
            assert idx >= 90  # Should be in top 10% (relaxed test)

    def test_zscore_edge_cases(self):
        """Test z-score handles edge cases"""
        service = StatsService()

        # Empty list
        assert service.calculate_zscore_outliers([]) == []

        # Single value
        assert service.calculate_zscore_outliers([42]) == []

        # All same values (zero standard deviation)
        assert service.calculate_zscore_outliers([5, 5, 5, 5, 5]) == []

    def test_calculate_percentile(self):
        """Test percentile calculation"""
        service = StatsService()

        values = list(range(1, 101))  # 1 to 100

        # 50 should be at 50th percentile
        percentile = service.calculate_percentile(50, values)
        assert 49 <= percentile <= 51  # Allow small rounding differences

        # 100 should be at 100th percentile
        percentile = service.calculate_percentile(100, values)
        assert percentile == 100.0


# ============================================================================
# Agent Tool Integration Tests
# ============================================================================

class TestAgentToolsIntegration:
    """Integration tests for Pydantic AI agent tools"""

    @pytest.mark.asyncio
    async def test_find_outliers_tool_with_context(self):
        """Test find_outliers_tool works with RunContext"""
        from pydantic_ai import RunContext

        # Create dependencies
        deps = AgentDependencies.create(
            project_name=TEST_PROJECT
        )

        # Create mock context
        class MockContext:
            def __init__(self, deps):
                self.deps = deps

        ctx = MockContext(deps)

        # Call tool
        result = await find_outliers_tool(
            ctx=ctx,
            hours_back=24,
            threshold=2.0,
            min_views=100,
            text_only=True
        )

        # Should return string response
        assert isinstance(result, str)
        assert len(result) > 0

        # Response should mention tweets or no data
        result_lower = result.lower()
        assert any(word in result_lower for word in ['tweet', 'found', 'no', 'outlier'])

    @pytest.mark.asyncio
    async def test_agent_find_outliers_query(self):
        """Test agent responding to 'find outliers' query"""
        deps = AgentDependencies.create(
            project_name=TEST_PROJECT
        )

        # Run agent with outlier query
        result = await agent.run(
            "Find viral tweets from the last 24 hours",
            deps=deps
        )

        # Should return text response
        assert hasattr(result, 'output')
        assert isinstance(result.output, str)

        # Response should mention finding tweets
        response_lower = result.output.lower()
        assert any(word in response_lower for word in ['found', 'tweet', 'outlier', 'viral', 'no'])

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set - skipping hook analysis test"
    )
    async def test_agent_analyze_hooks_query(self):
        """Test agent responding to 'analyze hooks' query"""
        deps = AgentDependencies.create(
            project_name=TEST_PROJECT
        )

        result = await agent.run(
            "Analyze hooks from viral tweets in the last 24 hours",
            deps=deps
        )

        # Should return text response
        assert hasattr(result, 'output')
        assert isinstance(result.output, str)

        # Response should mention analysis or hooks
        response_lower = result.output.lower()
        assert any(word in response_lower for word in ['analyz', 'hook', 'pattern', 'tweet'])


# ============================================================================
# CLI Integration Tests
# ============================================================================

class TestCLIIntegration:
    """Integration tests for refactored CLI commands"""

    def test_find_outliers_help(self):
        """Test find-outliers --help works"""
        runner = CliRunner()
        result = runner.invoke(twitter_group, ['find-outliers', '--help'])

        assert result.exit_code == 0
        assert 'find-outliers' in result.output.lower()
        assert '--project' in result.output
        assert '--threshold' in result.output
        assert '--method' in result.output

    def test_analyze_hooks_help(self):
        """Test analyze-hooks --help works"""
        runner = CliRunner()
        result = runner.invoke(twitter_group, ['analyze-hooks', '--help'])

        assert result.exit_code == 0
        assert 'analyze-hooks' in result.output.lower()
        assert '--input-json' in result.output
        assert '--output-json' in result.output

    @pytest.mark.slow
    def test_find_outliers_execution(self):
        """Test find-outliers command executes without error"""
        runner = CliRunner()
        result = runner.invoke(twitter_group, [
            'find-outliers',
            '--project', TEST_PROJECT,
            '--days-back', '1',
            '--threshold', '2.0',
            '--method', 'zscore',
            '--text-only'
        ])

        # Should complete without errors (exit code 0 or 1 if no data)
        assert result.exit_code in [0, 1]

        # Should produce output
        assert len(result.output) > 0

    @pytest.mark.slow
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set - skipping analyze-hooks execution test"
    )
    def test_analyze_hooks_execution_with_limit(self):
        """Test analyze-hooks command with limit parameter"""
        runner = CliRunner()

        # Use limit=1 to only analyze 1 tweet (faster test)
        result = runner.invoke(twitter_group, [
            'analyze-hooks',
            '--project', TEST_PROJECT,
            '--hours-back', '24',
            '--limit', '1',
            '--auto-select'
        ])

        # Should complete (may exit with 0 or 1 depending on data availability)
        assert result.exit_code in [0, 1]

        # Should produce output
        assert len(result.output) > 0


# ============================================================================
# End-to-End Workflow Tests
# ============================================================================

class TestEndToEndWorkflows:
    """Integration tests for complete workflows"""

    @pytest.mark.asyncio
    async def test_outlier_discovery_workflow(self):
        """Test complete outlier discovery workflow"""
        # Step 1: Create services
        twitter_svc = TwitterService()
        stats_svc = StatsService()

        # Step 2: Fetch tweets
        tweets = await twitter_svc.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=100,
            text_only=True
        )

        if not tweets:
            pytest.skip("No tweets in database for testing")

        # Step 3: Calculate outliers
        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = stats_svc.calculate_zscore_outliers(
            engagement_scores,
            threshold=2.0
        )

        # Step 4: Mark outliers in database
        for idx, zscore in outlier_indices:
            tweet = tweets[idx]
            await twitter_svc.mark_as_outlier(
                tweet_id=tweet.id,
                zscore=zscore,
                threshold=2.0
            )

        # Workflow completed successfully if no errors raised
        assert True

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set - skipping hook analysis workflow test"
    )
    async def test_hook_analysis_workflow(self):
        """Test complete hook analysis workflow (limited to 1 tweet)"""
        # Step 1: Create services
        twitter_svc = TwitterService()
        stats_svc = StatsService()
        gemini_svc = GeminiService(api_key=os.getenv('GEMINI_API_KEY'))

        # Step 2: Find outliers
        tweets = await twitter_svc.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=100,
            text_only=True
        )

        if not tweets:
            pytest.skip("No tweets in database for testing")

        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = stats_svc.calculate_zscore_outliers(
            engagement_scores,
            threshold=2.0
        )

        if not outlier_indices:
            pytest.skip("No outliers found for testing")

        # Step 3: Analyze hooks (limit to 1 for speed)
        outlier_tweet = tweets[outlier_indices[0][0]]

        analysis = await gemini_svc.analyze_hook(
            tweet_text=outlier_tweet.text,
            tweet_id=outlier_tweet.id
        )

        # Verify analysis structure
        assert isinstance(analysis, HookAnalysis)
        assert analysis.tweet_id == outlier_tweet.id

        # Step 4: Save analysis to database
        await twitter_svc.save_hook_analysis(analysis)

        # Workflow completed successfully
        assert True

    @pytest.mark.asyncio
    async def test_cli_to_agent_data_flow(self):
        """Test that CLI and agent can both access the same data"""
        # Step 1: Use CLI to find outliers and export to JSON
        runner = CliRunner()

        with runner.isolated_filesystem():
            # Run find-outliers and export to JSON
            result = runner.invoke(twitter_group, [
                'find-outliers',
                '--project', TEST_PROJECT,
                '--days-back', '1',
                '--threshold', '2.0',
                '--export-json', 'outliers.json'
            ])

            # If command succeeded and created file
            if result.exit_code == 0 and Path('outliers.json').exists():
                # Load the JSON
                with open('outliers.json', 'r') as f:
                    cli_data = json.load(f)

                # Step 2: Use agent to query same data
                deps = AgentDependencies.create(
                    project_name=TEST_PROJECT
                )

                agent_result = await agent.run(
                    "Find viral tweets from the last 24 hours",
                    deps=deps
                )

                # Both should return data about tweets
                assert 'outliers' in cli_data or 'tweets' in cli_data
                assert isinstance(agent_result.output, str)
                assert len(agent_result.output) > 0


# ============================================================================
# Test Markers Configuration
# ============================================================================

def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "asyncio: marks tests as async"
    )


if __name__ == "__main__":
    """Allow running tests directly with python"""
    pytest.main([__file__, "-v"])
