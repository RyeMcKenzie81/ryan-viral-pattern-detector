# Handoff: Task 1.11 - Refactor CLI to Use Services

**Date:** 2025-11-17
**Branch:** `feature/pydantic-ai-agent`
**Previous Task:** Task 1.10 - Conversation Context (✅ COMPLETE)
**Current Task:** Task 1.11 - Refactor CLI to Use Services (🔄 NEXT)

---

## What Was Just Completed

### Task 1.10: Conversation Context ✅

**Summary:** Added conversation context management to the Streamlit UI, enabling natural multi-turn conversations where the agent can reference previous tool results.

**Implementation:**

1. **Session State Storage** (`viraltracker/ui/app.py:73-74`)
   - Added `tool_results` list to store last 10 interactions
   - Each entry contains: timestamp, user_query, agent_response, message_count

2. **Context Building** (`viraltracker/ui/app.py:37-72`)
   - `build_conversation_context()` function creates context from last 3 results
   - Shows 800 characters of each previous response (enough for usernames/tweet details)
   - Includes explicit instructions for agent on how to interpret references

3. **Context Injection** (`viraltracker/ui/app.py:300-307`)
   - Context prepended to every user prompt before calling agent
   - Format: `{context}## Current Query:\n{prompt}`

4. **Result Storage** (`viraltracker/ui/app.py:75-98`)
   - `store_tool_result()` captures agent responses after each interaction
   - Keeps last 10 results, prevents unbounded growth

5. **Agent System Prompt Update** (`viraltracker/agent/agent.py:110-115`)
   - Added "Conversation Context" section explaining how to handle references
   - Instructs agent to look for "those tweets", "their hooks", etc. in context

**Testing Results:**
- ✅ **Test 1 (Failed):** Initial 300-character context was too short
- ✅ **Test 2 (Success):** Increased to 800 chars, agent successfully referenced previous tweets
- ✅ Scenario: "Show top 5 tweets" → "Analyze their hooks" works correctly

**Files Modified:**
- `viraltracker/ui/app.py` - Added context management (60+ lines)
- `viraltracker/agent/agent.py` - Updated system prompt (6 lines)

**Commit:**
- Hash: `454a7ca`
- Message: "feat: Complete Tasks 1.9 & 1.10 - Streamlit UI with Conversation Context"
- Files changed: 9 files, 1669 insertions(+), 1 deletion(-)
- **Status:** ✅ Pushed to GitHub

---

## Current State: End of Phase 1 Day 4

### Phase 1 Progress

| Task | Status | Duration | Notes |
|------|--------|----------|-------|
| 1.1 - Service Models | ✅ | 2h | Pydantic models with validation |
| 1.2 - TwitterService | ✅ | 4h | Database access layer |
| 1.3 - GeminiService | ✅ | 3h | AI API with rate limiting |
| 1.4 - StatsService | ✅ | 1h | Statistical calculations |
| 1.5 - Dependencies | ✅ | 1h | Dependency injection |
| 1.6 - Agent Tools | ✅ | 4h | find_outliers, analyze_hooks, export_results |
| 1.7 - Agent | ✅ | 2h | Pydantic AI agent with tools |
| 1.8 - CLI Chat | ✅ | 2h | Terminal chat interface |
| 1.9 - Streamlit UI | ✅ | 6h | Web chat interface |
| 1.10 - Context | ✅ | 4h | Multi-turn conversations |
| **TOTAL** | **10/12** | **29h** | **83% Phase 1 Complete** |

### What's Working

1. ✅ **Services Layer** - Clean data access with Pydantic models
2. ✅ **Pydantic AI Agent** - GPT-4o with 3 registered tools
3. ✅ **CLI Chat** - `viraltracker chat` command for terminal use
4. ✅ **Streamlit UI** - Full-featured web interface at `localhost:8501`
5. ✅ **Multi-turn Conversations** - Agent remembers previous results

### What's NOT Working Yet

1. ❌ **CLI Commands Still Old** - `viraltracker twitter find-outliers` doesn't use services yet
2. ❌ **No Integration Tests** - Haven't verified all access methods work together
3. ❌ **No Phase 1 Documentation** - Missing comprehensive end-to-end docs

---

## Next Task: Task 1.11 - Refactor CLI to Use Services

### Objective

Refactor the existing CLI commands in `viraltracker/cli/twitter.py` to use the new services layer instead of directly accessing the database and calling analysis code.

**Why This Matters:**
- Ensures CLI and agent use the same business logic (single source of truth)
- Makes CLI commands backwards compatible while using modern architecture
- Proves the services layer is reusable across all interfaces
- Prepares for Phase 2/3 where API will also use services

### Current CLI Architecture (OLD)

```
viraltracker/cli/twitter.py (monolithic, ~2000 lines)
    ├── find-outliers command
    │   ├── Direct SQLite queries
    │   ├── Inline Z-score calculation
    │   └── Direct file writes
    ├── analyze-hooks command
    │   ├── Direct Gemini API calls
    │   ├── Inline rate limiting
    │   └── Direct database writes
    └── generate-comments command
        ├── Direct database access
        └── Inline scoring logic
```

**Problems:**
- Business logic duplicated between CLI and agent tools
- Hard to test (everything coupled to Click commands)
- Changes to logic require updating multiple places
- No type safety

### Target CLI Architecture (NEW)

```
viraltracker/cli/twitter.py (thin wrapper, ~500 lines)
    ├── find-outliers command
    │   └── Calls TwitterService + StatsService
    ├── analyze-hooks command
    │   └── Calls TwitterService + GeminiService
    └── generate-comments command
        └── Calls TwitterService + GeminiService
```

**Benefits:**
- CLI commands become thin wrappers around services
- Same code paths as agent tools = guaranteed consistency
- Easier to test (can test services independently)
- Type-safe with Pydantic models

---

## Implementation Plan

### Step 1: Refactor `find-outliers` Command

**Current Code:** `viraltracker/cli/twitter.py` (lines vary)

**Target Implementation:**

```python
import asyncio
import click
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.stats_service import StatsService
import json
from datetime import datetime

@twitter_group.command(name="find-outliers")
@click.option('--project', required=True, help='Project name')
@click.option('--days-back', type=int, default=7, help='Days of data to analyze')
@click.option('--threshold', type=float, default=2.0, help='Z-score threshold')
@click.option('--method', type=click.Choice(['zscore', 'percentile']), default='zscore')
@click.option('--min-views', type=int, default=100, help='Minimum view count')
@click.option('--text-only', is_flag=True, help='Only text tweets')
@click.option('--export-json', type=str, help='Export to JSON file')
def find_outliers(
    project: str,
    days_back: int,
    threshold: float,
    method: str,
    min_views: int,
    text_only: bool,
    export_json: Optional[str]
):
    """Find viral outlier tweets using statistical analysis"""

    async def run():
        # Initialize services
        twitter_svc = TwitterService()
        stats_svc = StatsService()

        # Fetch tweets
        click.echo(f"📊 Analyzing {project} (last {days_back} days)...")

        tweets = await twitter_svc.get_tweets(
            project=project,
            hours_back=days_back * 24,
            min_views=min_views,
            text_only=text_only
        )

        if not tweets:
            click.echo(f"❌ No tweets found for {project}")
            return

        click.echo(f"✅ Found {len(tweets)} tweets")

        # Calculate outliers
        view_counts = [t.view_count for t in tweets]
        outlier_indices = stats_svc.calculate_zscore_outliers(
            view_counts,
            threshold=threshold
        )

        if not outlier_indices:
            click.echo(f"❌ No outliers found with threshold {threshold}")
            click.echo(f"💡 Try lowering the threshold (e.g., --threshold 1.5)")
            return

        click.echo(f"✅ Found {len(outlier_indices)} viral outliers")

        # Build results
        outliers = []
        for idx, zscore in outlier_indices:
            tweet = tweets[idx]
            percentile = stats_svc.calculate_percentile(
                tweet.view_count,
                view_counts
            )

            outliers.append({
                'tweet': tweet.model_dump(),
                'zscore': zscore,
                'percentile': percentile
            })

            # Mark in database
            await twitter_svc.mark_as_outlier(
                tweet_id=tweet.id,
                zscore=zscore,
                threshold=threshold
            )

        # Sort by views
        outliers.sort(key=lambda o: o['tweet']['view_count'], reverse=True)

        # Display results
        click.echo("\n📈 Top 10 Viral Tweets:\n")
        for i, outlier in enumerate(outliers[:10], 1):
            tweet = outlier['tweet']
            click.echo(f"{i}. @{tweet['author_username']} - {tweet['view_count']:,} views")
            click.echo(f"   Z-score: {outlier['zscore']:.2f} | Percentile: {outlier['percentile']:.1f}%")
            click.echo(f"   {tweet['text'][:100]}...")
            click.echo(f"   {tweet['url']}\n")

        # Export if requested
        if export_json:
            with open(export_json, 'w') as f:
                json.dump({
                    'project': project,
                    'analysis_date': datetime.now().isoformat(),
                    'total_tweets': len(tweets),
                    'outlier_count': len(outliers),
                    'threshold': threshold,
                    'method': method,
                    'outliers': outliers
                }, f, indent=2, default=str)

            click.echo(f"💾 Exported to {export_json}")

    # Run async function
    asyncio.run(run())
```

**Key Changes:**
1. Removed direct database queries → Use `TwitterService.get_tweets()`
2. Removed inline Z-score logic → Use `StatsService.calculate_zscore_outliers()`
3. Use Pydantic models → `tweet.model_dump()` for JSON export
4. Keep same CLI interface → Users don't see any changes
5. Add async wrapper → All services are async

---

### Step 2: Refactor `analyze-hooks` Command

**Target Implementation:**

```python
@twitter_group.command(name="analyze-hooks")
@click.option('--input-json', type=str, help='Input JSON from find-outliers')
@click.option('--tweet-ids', type=str, help='Comma-separated tweet IDs')
@click.option('--project', type=str, help='Project name (if not using input-json)')
@click.option('--hours-back', type=int, default=24, help='Hours of data')
@click.option('--limit', type=int, default=20, help='Max tweets to analyze')
@click.option('--output-json', type=str, help='Export to JSON file')
def analyze_hooks(
    input_json: Optional[str],
    tweet_ids: Optional[str],
    project: Optional[str],
    hours_back: int,
    limit: int,
    output_json: Optional[str]
):
    """Analyze viral tweet hooks using AI"""

    async def run():
        # Initialize services
        twitter_svc = TwitterService()
        gemini_svc = GeminiService(os.getenv('GEMINI_API_KEY'))
        stats_svc = StatsService()

        # Get tweets to analyze
        tweets = []

        if input_json:
            # Load from previous find-outliers export
            with open(input_json, 'r') as f:
                data = json.load(f)
                tweet_dicts = [o['tweet'] for o in data['outliers']]
                from viraltracker.services.models import Tweet
                tweets = [Tweet(**t) for t in tweet_dicts]

        elif tweet_ids:
            # Specific tweet IDs
            ids = tweet_ids.split(',')
            tweets = await twitter_svc.get_tweets_by_ids(ids)

        elif project:
            # Find outliers automatically
            all_tweets = await twitter_svc.get_tweets(
                project=project,
                hours_back=hours_back,
                min_views=100,
                text_only=True
            )

            view_counts = [t.view_count for t in all_tweets]
            outlier_indices = stats_svc.calculate_zscore_outliers(view_counts, 2.0)
            tweets = [all_tweets[idx] for idx, _ in outlier_indices]
        else:
            click.echo("❌ Must provide --input-json, --tweet-ids, or --project")
            return

        # Limit
        tweets = tweets[:limit]

        click.echo(f"🎣 Analyzing {len(tweets)} viral hooks...")

        # Analyze hooks
        analyses = []

        with click.progressbar(tweets, label='Analyzing') as bar:
            for tweet in bar:
                try:
                    analysis = await gemini_svc.analyze_hook(
                        tweet_text=tweet.text,
                        tweet_id=tweet.id
                    )

                    # Save to database
                    await twitter_svc.save_hook_analysis(analysis)

                    analyses.append(analysis)

                except Exception as e:
                    click.echo(f"\n⚠️  Error analyzing {tweet.id}: {e}")
                    continue

        if not analyses:
            click.echo("❌ No hooks analyzed")
            return

        # Calculate statistics
        from collections import Counter
        hook_types = Counter(a.hook_type for a in analyses)
        triggers = Counter(a.emotional_trigger for a in analyses)
        avg_conf = sum(a.hook_type_confidence for a in analyses) / len(analyses)

        # Display results
        click.echo(f"\n✅ Analyzed {len(analyses)} hooks\n")

        click.echo("📊 Hook Types:")
        for hook_type, count in hook_types.most_common(5):
            pct = (count / len(analyses)) * 100
            click.echo(f"  - {hook_type}: {count} ({pct:.0f}%)")

        click.echo("\n🎭 Emotional Triggers:")
        for trigger, count in triggers.most_common(5):
            pct = (count / len(analyses)) * 100
            click.echo(f"  - {trigger}: {count} ({pct:.0f}%)")

        click.echo(f"\n📈 Average Confidence: {avg_conf:.1%}\n")

        # Export if requested
        if output_json:
            with open(output_json, 'w') as f:
                json.dump({
                    'analysis_date': datetime.now().isoformat(),
                    'total_analyzed': len(analyses),
                    'avg_confidence': avg_conf,
                    'hook_type_distribution': dict(hook_types),
                    'emotional_trigger_distribution': dict(triggers),
                    'analyses': [a.model_dump() for a in analyses]
                }, f, indent=2, default=str)

            click.echo(f"💾 Exported to {output_json}")

    asyncio.run(run())
```

**Key Changes:**
1. Removed direct Gemini API calls → Use `GeminiService.analyze_hook()`
2. Removed inline rate limiting → Service handles it
3. Use Pydantic models → Type-safe results
4. Keep same CLI interface → Backwards compatible

---

### Step 3: Update Imports in `viraltracker/cli/twitter.py`

**Add at top of file:**

```python
# New imports for services
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
from viraltracker.services.models import Tweet, HookAnalysis, OutlierTweet
import asyncio
import os
```

---

### Step 4: Testing Checklist

After refactoring each command:

**Manual Testing:**

```bash
# Test find-outliers
viraltracker twitter find-outliers \
  --project yakety-pack-instagram \
  --days-back 7 \
  --threshold 2.0 \
  --export-json ~/Downloads/test_outliers.json

# Verify:
# - Same results as before refactor
# - JSON export works
# - Output formatting unchanged
# - Database marked correctly

# Test analyze-hooks with input JSON
viraltracker twitter analyze-hooks \
  --input-json ~/Downloads/test_outliers.json \
  --limit 10 \
  --output-json ~/Downloads/test_hooks.json

# Verify:
# - Reads input JSON correctly
# - Analyzes hooks
# - Rate limiting works (no errors)
# - Export works

# Test analyze-hooks with project
viraltracker twitter analyze-hooks \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --limit 5

# Verify:
# - Finds outliers automatically
# - Analyzes them
# - Shows statistics
```

**Automated Testing:**

Create `tests/test_cli_refactor.py`:

```python
import pytest
from click.testing import CliRunner
from viraltracker.cli.twitter import twitter_group

def test_find_outliers_help():
    """Verify find-outliers help still works"""
    runner = CliRunner()
    result = runner.invoke(twitter_group, ['find-outliers', '--help'])
    assert result.exit_code == 0
    assert 'Find viral outlier tweets' in result.output

def test_analyze_hooks_help():
    """Verify analyze-hooks help still works"""
    runner = CliRunner()
    result = runner.invoke(twitter_group, ['analyze-hooks', '--help'])
    assert result.exit_code == 0
    assert 'Analyze viral tweet hooks' in result.output

# Add more tests for actual execution with test database
```

---

## Files to Modify

1. **`viraltracker/cli/twitter.py`** (MAIN FILE)
   - Current: ~2000 lines with business logic
   - Target: ~500 lines as thin wrapper
   - Changes:
     - Import services at top
     - Replace `find-outliers` command (~200 lines → ~80 lines)
     - Replace `analyze-hooks` command (~150 lines → ~70 lines)
     - Optionally refactor `generate-comments` (~300 lines → ~100 lines)

2. **`tests/test_cli_refactor.py`** (NEW FILE)
   - Integration tests for CLI commands
   - Verify backwards compatibility
   - Compare old vs new outputs

3. **`docs/CLI_MIGRATION.md`** (NEW FILE)
   - Document what changed
   - Note for users: CLI interface unchanged
   - Migration guide for developers

---

## Success Criteria

- ✅ `viraltracker twitter find-outliers` produces same results as before
- ✅ `viraltracker twitter analyze-hooks` works with all input methods
- ✅ CLI commands use services (no direct database access in commands)
- ✅ All existing CLI tests still pass
- ✅ New integration tests pass
- ✅ Documentation updated

---

## Time Estimate

**3-4 hours**
- 1.5 hours: Refactor find-outliers command
- 1 hour: Refactor analyze-hooks command
- 0.5 hours: Update imports and helpers
- 1 hour: Testing and verification

---

## Risks and Mitigation

### Risk 1: Breaking Existing Scripts

**Problem:** Users may have scripts calling `viraltracker twitter find-outliers`

**Mitigation:**
- Keep exact same CLI interface (same flags, same output format)
- Test with real user workflows
- Document any subtle differences

### Risk 2: Performance Regression

**Problem:** Services add async overhead

**Mitigation:**
- Services are already async (no change)
- Monitor execution time before/after
- Optimize if needed

### Risk 3: Different Results

**Problem:** Services might calculate differently than old code

**Mitigation:**
- Use same algorithms (just moved to services)
- Test with known data and compare outputs
- Unit test statistical functions

---

## After Task 1.11: What's Next?

### Task 1.12: Integration Testing

**Objective:** Create comprehensive integration tests to verify all access methods work together.

**Files:**
- `tests/test_phase1_integration.py`
- `docs/PHASE1_COMPLETE.md`

**Testing:**
- CLI commands work
- Agent tools work
- Streamlit UI works
- All use same services
- Results are consistent

**Time Estimate:** 2 hours

---

### Phase 1 Completion

After Tasks 1.11 and 1.12, Phase 1 will be **100% complete**:

✅ Services layer
✅ Agent with tools
✅ CLI chat
✅ Streamlit UI with context
✅ CLI refactored to use services
✅ Integration tests pass

**Next:** Phase 1.5 or Phase 2 (depending on priorities)

---

## How to Continue

### Environment Setup

```bash
# Navigate to project
cd /Users/ryemckenzie/projects/viraltracker

# Activate venv
source venv/bin/activate

# Verify on correct branch
git branch  # Should show feature/pydantic-ai-agent

# Check current status
git status
```

### Start Working on Task 1.11

```bash
# 1. Read current CLI implementation
cat viraltracker/cli/twitter.py | head -100

# 2. Identify find-outliers command (search for decorator)
grep -n "def find_outliers" viraltracker/cli/twitter.py

# 3. Read the current implementation
# Take note of:
# - Current parameters
# - Database queries
# - Statistical calculations
# - Output format

# 4. Start refactoring
# - Add service imports
# - Replace database queries with service calls
# - Keep output format identical

# 5. Test incrementally
viraltracker twitter find-outliers --project yakety-pack-instagram --days-back 1 --threshold 2.0
```

---

## Continuation Prompt for Next Session

**Use this prompt to continue work on Task 1.11:**

```
I'm continuing work on the Pydantic AI migration for Viraltracker.

Current status:
- ✅ Phase 1 Tasks 1.1-1.10 complete
- ✅ Task 1.10 (Conversation Context) completed and pushed to GitHub (commit 454a7ca)
- 🔄 Working on Task 1.11: Refactor CLI to Use Services

Task 1.11 objective:
Refactor the existing CLI commands in viraltracker/cli/twitter.py to use the new services layer (TwitterService, GeminiService, StatsService) instead of directly accessing the database and calling analysis code.

This ensures:
- CLI and agent use the same business logic
- Single source of truth for all access methods
- Type safety with Pydantic models
- Easier testing and maintenance

Files to modify:
1. viraltracker/cli/twitter.py - Replace find-outliers and analyze-hooks commands
2. tests/test_cli_refactor.py - Add integration tests
3. docs/CLI_MIGRATION.md - Document changes

Please help me implement Task 1.11 by:
1. Reading the current CLI implementation in viraltracker/cli/twitter.py
2. Refactoring find-outliers command to use TwitterService + StatsService
3. Refactoring analyze-hooks command to use TwitterService + GeminiService
4. Testing that CLI commands produce identical results
5. Updating documentation

Reference: /Users/ryemckenzie/projects/viraltracker/docs/HANDOFF_TASK_1.11.md
```

---

## Questions or Blockers?

If you encounter issues:

1. **CLI output format different?**
   - Compare line-by-line with old implementation
   - May need to adjust formatting in new version
   - Output should be visually identical to users

2. **Async/await issues in Click commands?**
   - Use `asyncio.run(async_function())` pattern shown above
   - All service calls are async
   - Click commands themselves are sync

3. **Performance slower?**
   - Services already use async (no overhead)
   - Check if rate limiting is slowing things down
   - Compare execution times before/after

4. **Tests failing?**
   - Check service initialization
   - Verify environment variables set
   - Use test database to avoid conflicts

---

**Ready to start Task 1.11!** 🚀

This will complete the Phase 1 refactoring and ensure all interfaces use the same robust services layer.

See `docs/PYDANTIC_AI_MIGRATION_PLAN.md` for full context.
