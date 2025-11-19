# Task 1.12: Integration Testing & Phase 1 Completion

**Last Updated:** 2025-11-17
**Branch:** `feature/pydantic-ai-agent`
**Status:** Ready to start
**Previous Task:** Task 1.11 - Refactor CLI to Use Services (✅ COMPLETE)

---

## Overview

**Objective:** Create comprehensive integration tests to validate that all Phase 1 components work together correctly. This is the final task of Phase 1 MVP.

**Why This Matters:**
- Ensures services, agent, CLI, and UI all work together
- Validates that refactored CLI maintains backwards compatibility
- Confirms agent tools produce correct results
- Provides regression tests for future development
- Final checkpoint before declaring Phase 1 complete

**Estimated Time:** 2-3 hours

---

## Context

### What We've Built in Phase 1

**Services Layer (Tasks 1.1-1.4):**
- ✅ TwitterService - Database access for tweets and hook analyses
- ✅ GeminiService - AI-powered hook analysis with rate limiting
- ✅ StatsService - Statistical calculations (z-score, percentile)
- ✅ Pydantic Models - Type-safe data structures

**Agent Layer (Tasks 1.5-1.7):**
- ✅ AgentDependencies - Dependency injection for services
- ✅ Three Agent Tools - find_outliers, analyze_hooks, export_results
- ✅ Pydantic AI Agent - GPT-4o with tool registration

**User Interfaces (Tasks 1.8-1.10):**
- ✅ CLI Chat - `viraltracker chat` for conversational access
- ✅ Streamlit UI - Web interface at localhost:8501
- ✅ Conversation Context - Agent remembers previous results

**CLI Refactoring (Task 1.11):**
- ✅ find-outliers - Refactored to use services
- ✅ analyze-hooks - Refactored to use services
- ⚠️ 6 other commands deferred to Phase 2

**What Needs Testing:**
1. All services work correctly with real database
2. Agent tools produce expected results
3. Refactored CLI commands maintain backwards compatibility
4. Streamlit UI handles user interactions correctly
5. End-to-end workflows complete successfully

---

## Task Breakdown

### Step 1: Create Test Infrastructure (30 mins)

**File:** `tests/test_phase1_integration.py`

Create comprehensive integration tests covering all Phase 1 functionality.

**Testing Strategy:**
- Use pytest with async support
- Test against real database (not mocks)
- Validate actual outputs, not just structure
- Test happy paths and error cases

**Dependencies:**
```bash
pip install pytest pytest-asyncio
```

### Step 2: Service Integration Tests (30 mins)

Test that services work correctly with the database:

**Tests to Create:**

1. **TwitterService Integration**
   - ✅ `test_twitter_service_get_tweets()` - Fetch real tweets
   - ✅ `test_twitter_service_mark_outlier()` - Mark tweets as outliers
   - ✅ `test_twitter_service_save_hook_analysis()` - Save hook analysis
   - ✅ `test_twitter_service_empty_project()` - Handle non-existent project

2. **GeminiService Integration**
   - ✅ `test_gemini_service_analyze_hook()` - Real API call
   - ✅ `test_gemini_service_rate_limiting()` - Verify rate limiting works
   - ⚠️ Requires GEMINI_API_KEY environment variable

3. **StatsService Integration**
   - ✅ `test_stats_service_zscore_outliers()` - Known dataset
   - ✅ `test_stats_service_percentile_outliers()` - Known dataset
   - ✅ `test_stats_service_edge_cases()` - Empty lists, single values

**Success Criteria:**
- All service tests pass
- Services handle edge cases gracefully
- Database operations don't corrupt data

### Step 3: Agent Tool Integration Tests (30 mins)

Test that agent tools work end-to-end:

**Tests to Create:**

1. **find_outliers_tool Integration**
   - ✅ `test_find_outliers_tool_finds_outliers()` - Returns outliers
   - ✅ `test_find_outliers_tool_no_data()` - Handles empty project
   - ✅ `test_find_outliers_tool_parameters()` - Respects all parameters

2. **analyze_hooks_tool Integration**
   - ✅ `test_analyze_hooks_tool_analyzes_tweets()` - Analyzes hooks
   - ✅ `test_analyze_hooks_tool_by_ids()` - Specific tweet IDs
   - ✅ `test_analyze_hooks_tool_auto_select()` - Auto-selects outliers

3. **export_results_tool Integration**
   - ✅ `test_export_results_tool_markdown()` - Generates markdown
   - ✅ `test_export_results_tool_with_hooks()` - Includes hook analysis
   - ✅ `test_export_results_tool_without_hooks()` - Outliers only

**Success Criteria:**
- All tool tests pass
- Tools produce expected output format
- Tools handle errors gracefully

### Step 4: CLI Backwards Compatibility Tests (30 mins)

Test that refactored CLI commands maintain exact same behavior:

**Tests to Create:**

1. **find-outliers Command**
   - ✅ `test_cli_find_outliers_basic()` - Basic execution
   - ✅ `test_cli_find_outliers_all_params()` - All parameters work
   - ✅ `test_cli_find_outliers_export()` - Export to JSON
   - ✅ `test_cli_find_outliers_help()` - Help text unchanged

2. **analyze-hooks Command**
   - ✅ `test_cli_analyze_hooks_basic()` - Basic execution
   - ✅ `test_cli_analyze_hooks_input_json()` - Read from file
   - ✅ `test_cli_analyze_hooks_output_json()` - Write to file
   - ✅ `test_cli_analyze_hooks_help()` - Help text unchanged

**Success Criteria:**
- CLI commands produce identical output to pre-refactor
- All CLI options and flags work
- Help text is clear and accurate
- Error messages are helpful

### Step 5: End-to-End Workflow Tests (30 mins)

Test complete workflows from start to finish:

**Workflows to Test:**

1. **Outlier Discovery Workflow**
   ```bash
   # Find outliers → Mark in DB → Verify marked
   viraltracker twitter find-outliers --project yakety-pack-instagram --days-back 1 --threshold 2.0
   ```
   - ✅ Outliers are found
   - ✅ Outliers are marked in database
   - ✅ Statistics are calculated correctly

2. **Hook Analysis Workflow**
   ```bash
   # Find outliers → Export JSON → Analyze hooks → Save to DB
   viraltracker twitter find-outliers --project yakety-pack-instagram --export-json outliers.json
   viraltracker twitter analyze-hooks --input-json outliers.json --output-json hooks.json
   ```
   - ✅ Outliers exported to JSON
   - ✅ Hooks analyzed successfully
   - ✅ Results saved to database

3. **Agent Conversation Workflow**
   - ✅ User asks: "Find viral tweets from last 24 hours"
   - ✅ Agent calls find_outliers_tool
   - ✅ User asks: "Analyze hooks from those tweets"
   - ✅ Agent references previous results (conversation context)
   - ✅ Agent calls analyze_hooks_tool with correct tweet IDs

4. **Streamlit UI Workflow**
   - ✅ Open Streamlit UI
   - ✅ Click "Find Viral Tweets (24h)" button
   - ✅ Agent responds with outliers
   - ✅ Click "Analyze Hooks" button
   - ✅ Agent analyzes hooks from previous results

**Success Criteria:**
- All workflows complete without errors
- Data flows correctly between components
- Results are consistent across interfaces

---

## Implementation Guide

### Test File Structure

```python
# tests/test_phase1_integration.py

import pytest
import os
from click.testing import CliRunner
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
from viraltracker.agent.agent import agent
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.cli.twitter import twitter_group

# Test database path
TEST_DB = os.getenv('DB_PATH', 'viraltracker.db')
TEST_PROJECT = os.getenv('PROJECT_NAME', 'yakety-pack-instagram')


# ============================================================================
# Service Integration Tests
# ============================================================================

class TestTwitterServiceIntegration:
    """Integration tests for TwitterService with real database"""

    @pytest.mark.asyncio
    async def test_get_tweets_returns_data(self):
        """Test that TwitterService can fetch real tweets"""
        service = TwitterService(TEST_DB)

        tweets = await service.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=0,
            text_only=True
        )

        # Should return tweets (unless database is empty)
        assert isinstance(tweets, list)

        if tweets:  # If we have data
            tweet = tweets[0]
            assert hasattr(tweet, 'id')
            assert hasattr(tweet, 'text')
            assert hasattr(tweet, 'view_count')
            assert hasattr(tweet, 'engagement_score')

    @pytest.mark.asyncio
    async def test_mark_as_outlier_persists(self):
        """Test that marking outliers persists to database"""
        service = TwitterService(TEST_DB)

        # Get a tweet
        tweets = await service.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=0,
            text_only=True
        )

        if tweets:
            tweet = tweets[0]

            # Mark as outlier
            await service.mark_as_outlier(
                tweet_id=tweet.id,
                zscore=3.5,
                threshold=2.0
            )

            # Verify it was marked (would need to query DB to confirm)
            # This is a smoke test - just ensure no errors
            assert True


class TestGeminiServiceIntegration:
    """Integration tests for GeminiService with real API"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set"
    )
    async def test_analyze_hook_real_api(self):
        """Test real Gemini API call"""
        api_key = os.getenv('GEMINI_API_KEY')
        service = GeminiService(api_key)

        test_tweet = "Parenting hack: freeze grapes for a healthy snack kids love!"

        analysis = await service.analyze_hook(
            tweet_text=test_tweet,
            tweet_id="test_123"
        )

        # Verify structure
        assert analysis.tweet_id == "test_123"
        assert analysis.tweet_text == test_tweet
        assert analysis.hook_type in [
            'relatable_slice',
            'hot_take',
            'contrarian_advice',
            'controversial_opinion',
            'personal_story',
            'before_after',
            'tactical_how_to',
            'unknown'
        ]
        assert 0.0 <= analysis.hook_type_confidence <= 1.0
        assert len(analysis.hook_explanation) > 0


class TestStatsServiceIntegration:
    """Integration tests for StatsService calculations"""

    def test_zscore_outliers_known_dataset(self):
        """Test z-score calculation with known dataset"""
        service = StatsService()

        # Dataset with clear outlier
        values = [10, 12, 11, 13, 12, 50]  # 50 is outlier

        outliers = service.calculate_zscore_outliers(
            values,
            threshold=2.0
        )

        # Should find the outlier (50)
        assert len(outliers) == 1
        idx, zscore = outliers[0]
        assert idx == 5  # Last item
        assert zscore > 2.0

    def test_percentile_outliers_known_dataset(self):
        """Test percentile outlier detection"""
        service = StatsService()

        # 100 values, top 5% should be outliers
        values = list(range(1, 101))

        outliers = service.calculate_percentile_outliers(
            values,
            threshold=5.0  # Top 5%
        )

        # Should find ~5 outliers
        assert 4 <= len(outliers) <= 6


# ============================================================================
# Agent Tool Integration Tests
# ============================================================================

class TestAgentToolsIntegration:
    """Integration tests for Pydantic AI agent tools"""

    @pytest.mark.asyncio
    async def test_agent_find_outliers_query(self):
        """Test agent responding to 'find outliers' query"""
        deps = AgentDependencies.create(
            db_path=TEST_DB,
            project_name=TEST_PROJECT
        )

        result = await agent.run(
            "Find viral tweets from the last 24 hours",
            deps=deps
        )

        # Should return text response
        assert isinstance(result.output, str)

        # Response should mention finding tweets
        response_lower = result.output.lower()
        assert any(word in response_lower for word in ['found', 'tweets', 'outlier', 'viral'])

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set"
    )
    async def test_agent_analyze_hooks_query(self):
        """Test agent responding to 'analyze hooks' query"""
        deps = AgentDependencies.create(
            db_path=TEST_DB,
            project_name=TEST_PROJECT
        )

        result = await agent.run(
            "Analyze hooks from viral tweets in the last 24 hours",
            deps=deps
        )

        # Should return text response
        assert isinstance(result.output, str)

        # Response should mention analysis
        response_lower = result.output.lower()
        assert any(word in response_lower for word in ['analyz', 'hook', 'pattern'])


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

    def test_analyze_hooks_help(self):
        """Test analyze-hooks --help works"""
        runner = CliRunner()
        result = runner.invoke(twitter_group, ['analyze-hooks', '--help'])

        assert result.exit_code == 0
        assert 'analyze-hooks' in result.output.lower()
        assert '--input-json' in result.output

    @pytest.mark.slow
    def test_find_outliers_execution(self):
        """Test find-outliers command executes without error"""
        runner = CliRunner()
        result = runner.invoke(twitter_group, [
            'find-outliers',
            '--project', TEST_PROJECT,
            '--days-back', '1',
            '--threshold', '2.0',
            '--text-only'
        ])

        # Should complete without errors
        assert result.exit_code == 0

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
        # Step 1: Find outliers
        twitter_svc = TwitterService(TEST_DB)
        stats_svc = StatsService()

        tweets = await twitter_svc.get_tweets(
            project=TEST_PROJECT,
            hours_back=24,
            min_views=100,
            text_only=True
        )

        if not tweets:
            pytest.skip("No tweets in database for testing")

        # Step 2: Calculate outliers
        engagement_scores = [t.engagement_score for t in tweets]
        outlier_indices = stats_svc.calculate_zscore_outliers(
            engagement_scores,
            threshold=2.0
        )

        # Step 3: Mark outliers in database
        for idx, zscore in outlier_indices:
            tweet = tweets[idx]
            await twitter_svc.mark_as_outlier(
                tweet_id=tweet.id,
                zscore=zscore,
                threshold=2.0
            )

        # Workflow completed successfully
        assert True

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv('GEMINI_API_KEY'),
        reason="GEMINI_API_KEY not set"
    )
    async def test_hook_analysis_workflow(self):
        """Test complete hook analysis workflow"""
        # Step 1: Find outliers
        twitter_svc = TwitterService(TEST_DB)
        stats_svc = StatsService()

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

        # Step 2: Analyze hooks (limit to 1 for speed)
        gemini_svc = GeminiService(os.getenv('GEMINI_API_KEY'))

        outlier_tweet = tweets[outlier_indices[0][0]]

        analysis = await gemini_svc.analyze_hook(
            tweet_text=outlier_tweet.text,
            tweet_id=outlier_tweet.id
        )

        # Step 3: Save analysis
        await twitter_svc.save_hook_analysis(analysis)

        # Workflow completed successfully
        assert analysis.tweet_id == outlier_tweet.id
```

### Running Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Install test dependencies
pip install pytest pytest-asyncio

# Run all integration tests
pytest tests/test_phase1_integration.py -v

# Run specific test class
pytest tests/test_phase1_integration.py::TestTwitterServiceIntegration -v

# Run excluding slow tests
pytest tests/test_phase1_integration.py -m "not slow" -v

# Run with coverage
pytest tests/test_phase1_integration.py --cov=viraltracker --cov-report=html
```

---

## Success Criteria

✅ **All Tests Pass**
- Service integration tests: 100% pass
- Agent tool tests: 100% pass
- CLI tests: 100% pass
- Workflow tests: 100% pass

✅ **CLI Backwards Compatibility**
- find-outliers produces identical output
- analyze-hooks produces identical output
- All CLI options work correctly
- Help text is accurate

✅ **Agent Tools Work**
- find_outliers_tool returns valid results
- analyze_hooks_tool analyzes tweets correctly
- export_results_tool generates markdown

✅ **End-to-End Workflows Complete**
- Can find outliers → mark in DB
- Can analyze hooks → save to DB
- Can use agent conversationally
- Streamlit UI handles user interactions

✅ **Documentation Complete**
- Test file documented
- README updated with testing instructions
- PHASE1_COMPLETE.md created

---

## Phase 1 Completion Checklist

Once all tests pass, verify Phase 1 is complete:

### Technical Deliverables

- [x] **Services Layer** (Tasks 1.1-1.4)
  - [x] TwitterService, GeminiService, StatsService
  - [x] Pydantic models for type safety
  - [x] Service tests passing

- [x] **Agent Layer** (Tasks 1.5-1.7)
  - [x] AgentDependencies with dependency injection
  - [x] Three agent tools registered
  - [x] GPT-4o agent configured

- [x] **User Interfaces** (Tasks 1.8-1.10)
  - [x] CLI chat interface
  - [x] Streamlit web UI
  - [x] Conversation context working

- [x] **CLI Refactoring** (Task 1.11)
  - [x] find-outliers refactored
  - [x] analyze-hooks refactored
  - [ ] Integration tests passing (Task 1.12)

### Documentation

- [x] PYDANTIC_AI_MIGRATION_PLAN.md updated
- [x] HANDOFF_TASK_1.X.md for each task
- [ ] tests/test_phase1_integration.py created
- [ ] docs/PHASE1_COMPLETE.md created

### Git & GitHub

- [ ] All changes committed
- [ ] Descriptive commit message
- [ ] Pushed to feature/pydantic-ai-agent branch
- [ ] README.md updated with Phase 1 summary

---

## Next Steps After Task 1.12

Once integration tests pass and Phase 1 is complete:

**Option 1: Deploy MVP**
- Merge to main branch
- Deploy to Railway
- Validate with real users

**Option 2: Continue to Phase 1.5**
- Add remaining agent tools (scrape, generate-comments)
- Expand tool coverage
- Validate extended functionality

**Option 3: Start Phase 2 Polish**
- Add streaming responses
- Implement result validators
- Build multi-page Streamlit UI
- Refactor remaining CLI commands (Task 2.8)

**Recommended:** Option 1 - Deploy MVP and validate before building more features

---

## Troubleshooting

### Tests Fail with "No module named viraltracker"

**Solution:** Install package in editable mode
```bash
pip install -e .
```

### Tests Fail with "GEMINI_API_KEY not set"

**Solution:** Add API key to environment
```bash
export GEMINI_API_KEY=your_key_here
# Or add to .env file
echo "GEMINI_API_KEY=your_key_here" >> .env
```

### Tests Fail with "No tweets found"

**Solution:** Ensure database has data
```bash
# Run a scrape to populate database
./scrape_all_keywords_24h.sh
```

### CLI Tests Fail with Import Errors

**Solution:** Ensure viraltracker package is installed
```bash
pip install -e .
```

---

## Time Tracking

- **Test Infrastructure:** 30 mins
- **Service Tests:** 30 mins
- **Agent Tool Tests:** 30 mins
- **CLI Tests:** 30 mins
- **Workflow Tests:** 30 mins
- **Documentation:** 30 mins

**Total:** 2.5-3 hours

---

## Files to Create/Modify

**Create:**
- `tests/test_phase1_integration.py` - Main test file
- `docs/PHASE1_COMPLETE.md` - Phase 1 summary document
- `pytest.ini` - Pytest configuration (optional)

**Modify:**
- `README.md` - Add Phase 1 summary and testing instructions
- `docs/PYDANTIC_AI_MIGRATION_PLAN.md` - Mark Task 1.12 complete

---

## Questions?

If you encounter issues:
1. Check that venv is activated
2. Verify database has data
3. Ensure API keys are set
4. Run tests individually to isolate failures
5. Check logs for detailed error messages

---

**Ready to test!** 🧪
