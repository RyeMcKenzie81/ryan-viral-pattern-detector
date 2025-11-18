# Pydantic AI Migration - Handoff for Task 1.6 (Agent Tools)

**Date:** 2025-11-17
**Branch:** `feature/pydantic-ai-agent`
**Status:** Task 1.5 Complete ✅ | Task 1.6 Next ⏭️

---

## 🎯 Quick Start for New Context Window

Copy this prompt to continue:

```
I'm continuing the Pydantic AI migration for Viraltracker. We're migrating from a CLI-only tool to a multi-access platform (CLI + Agent + Streamlit + FastAPI).

Branch: feature/pydantic-ai-agent

Current Status:
✅ Phase 1, Tasks 1.1-1.5 COMPLETE (Services Layer + Agent Dependencies)
⏭️ Phase 1, Task 1.6 NEXT (Agent Tools with Pydantic AI)

What's Been Completed:
- 6 Pydantic models (Tweet, HookAnalysis, OutlierTweet, etc.)
- TwitterService (database operations via Supabase)
- GeminiService (AI hook analysis with rate limiting)
- StatsService (statistical calculations for outlier detection)
- AgentDependencies (typed dependency injection for Pydantic AI)
- Comprehensive test suites (all passing ✅)
- Full documentation for services & dependencies

Key Files Created:
1. viraltracker/services/models.py (540 lines)
2. viraltracker/services/twitter_service.py (350 lines)
3. viraltracker/services/gemini_service.py (300 lines)
4. viraltracker/services/stats_service.py (200 lines)
5. viraltracker/agent/dependencies.py (110 lines)
6. test_services_layer.py (300 lines) ✅
7. test_agent_dependencies.py (150 lines) ✅
8. docs/SERVICES_LAYER_SUMMARY.md
9. docs/AGENT_DEPENDENCIES_SUMMARY.md

Installed Dependencies:
- pydantic-ai>=1.18.0 (installed and ready)

Verification Commands:
cd /Users/ryemckenzie/projects/viraltracker
git branch  # Should show: * feature/pydantic-ai-agent
python test_services_layer.py  # Should pass all tests ✅
python test_agent_dependencies.py  # Should pass all tests ✅

Next Steps (Task 1.6 - Agent Tools):
Create 3 Pydantic AI tools that use our services layer:

1. find_outliers_tool() - Find viral outlier tweets using Z-score analysis
   - Uses: TwitterService + StatsService
   - Returns: Summary string with outlier count and top tweets

2. analyze_hooks_tool() - Analyze tweet hooks with AI
   - Uses: TwitterService + GeminiService
   - Returns: Summary of hook types and patterns

3. export_results_tool() - Format and export analysis results
   - Uses: All services
   - Returns: Markdown-formatted report

Important Notes:
- Updated migration plan includes testing/documentation checkpoints at EVERY step
  See: docs/PYDANTIC_AI_MIGRATION_PLAN.md (lines 197-211)
- Follow the pattern: Code → Test → Document → Verify
- Don't proceed to Task 1.7 until Task 1.6 tests pass
- Services layer and dependencies are production-ready and tested

Reference Documents:
- Migration Plan: docs/PYDANTIC_AI_MIGRATION_PLAN.md
- Services Layer Guide: docs/SERVICES_LAYER_SUMMARY.md
- Agent Dependencies Guide: docs/AGENT_DEPENDENCIES_SUMMARY.md
- Existing Code References:
  - Hook Analyzer: viraltracker/generation/hook_analyzer.py
  - Outlier Detector: viraltracker/generation/outlier_detector.py

Let's create Task 1.6: Agent Tools!
```

---

## 📋 Detailed Context

### What We Just Completed (This Session)

#### Task 1.5: Agent Dependencies ✅

**Files Created:**
1. `viraltracker/agent/__init__.py` - Module exports
2. `viraltracker/agent/dependencies.py` (110 lines) - Typed dependency injection
3. `test_agent_dependencies.py` (150 lines) - Comprehensive test suite
4. `docs/AGENT_DEPENDENCIES_SUMMARY.md` - Full documentation

**What It Does:**
The `AgentDependencies` class provides typed dependency injection for Pydantic AI agent tools. It encapsulates:
- TwitterService (database operations)
- GeminiService (AI hook analysis)
- StatsService (statistical calculations)
- Project configuration

**Key Features:**
- Factory method pattern: `AgentDependencies.create()`
- Sensible defaults for yakety-pack-instagram project
- Configurable rate limiting (default: 9 req/min)
- Environment-aware credential loading

**Testing:**
```bash
python test_agent_dependencies.py
```

**Test Results:**
```
✅ PASS - Import
✅ PASS - Factory Method
✅ PASS - Service Initialization
✅ PASS - String Representation

🎉 All tests passed! Agent dependencies ready.
```

**Usage Example:**
```python
from viraltracker.agent.dependencies import AgentDependencies

# Create with defaults
deps = AgentDependencies.create()

# Access services
tweets = await deps.twitter.get_tweets(project=deps.project_name, hours_back=24)
analysis = await deps.gemini.analyze_hook(tweet_text=tweets[0].text)
outliers = deps.stats.calculate_zscore_outliers([t.engagement_score for t in tweets])
```

#### Package Installation ✅

**Installed:**
- `pydantic-ai>=1.18.0` (with all dependencies)

**Verified:**
```bash
source venv/bin/activate
python -c "from pydantic_ai import Agent; print('✓ Pydantic AI ready')"
```

---

### Architecture Overview

```
viraltracker/
├── services/              ✅ COMPLETE (Tasks 1.1-1.4)
│   ├── __init__.py
│   ├── models.py          # 6 Pydantic models
│   ├── twitter_service.py # Database operations
│   ├── gemini_service.py  # AI hook analysis
│   └── stats_service.py   # Statistical calculations
│
├── agent/                 ✅ PARTIAL (Task 1.5 done, 1.6-1.7 next)
│   ├── __init__.py        # ✅ Task 1.5
│   ├── dependencies.py    # ✅ Task 1.5
│   ├── tools.py           # ⏭️ Task 1.6 (NEXT)
│   └── agent.py           # ⏭️ Task 1.7
│
├── ui/                    ⏭️ AFTER AGENT (Task 1.8)
│   └── app.py             # Streamlit UI
│
├── cli/                   ⏭️ AFTER UI (Task 1.9)
│   └── twitter.py         # Refactor to use services
│
├── tests/
│   ├── test_services_layer.py      ✅ COMPLETE
│   └── test_agent_dependencies.py  ✅ COMPLETE
│
└── docs/
    ├── PYDANTIC_AI_MIGRATION_PLAN.md       ✅ UPDATED
    ├── SERVICES_LAYER_SUMMARY.md           ✅ COMPLETE
    ├── AGENT_DEPENDENCIES_SUMMARY.md       ✅ COMPLETE
    └── HANDOFF_PHASE1_TASK16.md            ✅ THIS FILE
```

---

### What's Next: Task 1.6 - Agent Tools

#### Purpose

Create 3 Pydantic AI tools that wrap our services layer, allowing the agent to:
1. Find viral outlier tweets
2. Analyze tweet hooks with AI
3. Export formatted results

#### File to Create

`viraltracker/agent/tools.py` (~300-400 lines)

#### Tool 1: find_outliers_tool()

**Signature:**
```python
async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    method: str = "zscore",
    min_views: int = 100,
    limit: int = 10
) -> str:
    """
    Find viral outlier tweets using statistical analysis.

    Uses Z-score or percentile method to identify tweets with
    exceptionally high engagement relative to the dataset.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Statistical threshold (default: 2.0 std deviations)
        method: 'zscore' or 'percentile' (default: 'zscore')
        min_views: Minimum view count filter (default: 100)
        limit: Max outliers to return (default: 10)

    Returns:
        Formatted string summary of outlier tweets
    """
```

**Implementation Steps:**
1. Fetch tweets via `ctx.deps.twitter.get_tweets()`
2. Extract engagement scores
3. Calculate outliers via `ctx.deps.stats.calculate_zscore_outliers()`
4. Build OutlierResult model
5. Return formatted summary string

**Expected Output Format:**
```
Found 5 viral outliers from 1,234 tweets (24 hours):

🔥 Top Outliers:
1. [Z=3.2, 99th %ile] "This tweet went viral..." (10K views, 500 likes)
   https://twitter.com/user/status/123

2. [Z=2.8, 98th %ile] "Another viral tweet..." (8K views, 400 likes)
   https://twitter.com/user/status/456

Summary Stats:
- Mean engagement: 150.5
- Outlier threshold: 2.0 std deviations
- Success rate: 0.4% (5/1234)
```

#### Tool 2: analyze_hooks_tool()

**Signature:**
```python
async def analyze_hooks_tool(
    ctx: RunContext[AgentDependencies],
    tweet_ids: Optional[List[str]] = None,
    hours_back: int = 24,
    limit: int = 20
) -> str:
    """
    Analyze tweet hooks using AI classification.

    Uses Gemini AI to classify hook types, emotional triggers,
    and content patterns for viral tweets.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        tweet_ids: Optional list of specific tweet IDs to analyze
        hours_back: Hours to look back if no tweet_ids (default: 24)
        limit: Max tweets to analyze (default: 20)

    Returns:
        Formatted string summary of hook analysis results
    """
```

**Implementation Steps:**
1. If tweet_ids provided: fetch via `ctx.deps.twitter.get_tweets_by_ids()`
2. Else: fetch recent tweets via `ctx.deps.twitter.get_tweets()`
3. Analyze each tweet via `ctx.deps.gemini.analyze_hook()`
4. Build HookAnalysisResult model
5. Save analyses via `ctx.deps.twitter.save_hook_analysis()`
6. Return formatted summary

**Expected Output Format:**
```
Analyzed 20 viral tweet hooks:

🎣 Top Hook Types:
- hot_take: 8 tweets (40%)
- relatable_slice: 5 tweets (25%)
- question_curiosity: 4 tweets (20%)
- story_narrative: 3 tweets (15%)

💡 Top Emotional Triggers:
- validation: 10 tweets (50%)
- curiosity: 6 tweets (30%)
- humor: 4 tweets (20%)

📊 Content Patterns:
- statement: 12 tweets (60%)
- question: 5 tweets (25%)
- story: 3 tweets (15%)

Success rate: 100% (20/20 analyzed successfully)
```

#### Tool 3: export_results_tool()

**Signature:**
```python
async def export_results_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
    threshold: float = 2.0,
    include_hooks: bool = True
) -> str:
    """
    Export comprehensive analysis report in markdown format.

    Combines outlier detection and hook analysis into a
    formatted markdown report.

    Args:
        ctx: Pydantic AI run context with AgentDependencies
        hours_back: Hours to look back (default: 24)
        threshold: Outlier threshold (default: 2.0)
        include_hooks: Include hook analysis (default: True)

    Returns:
        Markdown-formatted report
    """
```

**Implementation Steps:**
1. Run outlier detection (reuse logic from tool 1)
2. Run hook analysis if requested (reuse logic from tool 2)
3. Use `OutlierResult.to_markdown()` and `HookAnalysisResult.to_markdown()`
4. Combine into comprehensive report
5. Return markdown string

**Expected Output Format:**
```markdown
# Viral Tweet Analysis Report
**Project:** yakety-pack-instagram
**Period:** Last 24 hours
**Generated:** 2025-11-17 10:30 UTC

## Outlier Analysis
Found 5 viral outliers from 1,234 tweets

### Top Outliers
1. **[Z=3.2]** "This tweet went viral..."
   - Views: 10,000 | Likes: 500 | Engagement: 5.0%
   - https://twitter.com/user/status/123

...

## Hook Analysis
Analyzed 20 viral tweet hooks

### Hook Type Distribution
- hot_take: 40%
- relatable_slice: 25%
...

### Emotional Triggers
- validation: 50%
- curiosity: 30%
...
```

---

### Testing Protocol (MANDATORY)

**After completing Task 1.6, you MUST:**

1. ✅ **Write Tests** - Create `test_agent_tools.py`
2. 🧪 **Run Tests** - Verify all pass
3. 📝 **Document** - Create `docs/AGENT_TOOLS_SUMMARY.md`
4. ✔️ **Checkpoint** - Don't proceed to Task 1.7 until tests pass

**Test Requirements:**
- Test each tool independently with mocked services
- Test parameter validation
- Test error handling
- Test output format
- Mock TwitterService, GeminiService, StatsService calls

**Example Test Structure:**
```python
async def test_find_outliers_tool():
    """Test find_outliers_tool with mocked services"""
    # Create mock dependencies
    # Call tool
    # Assert output format
    # Assert service calls made correctly
```

---

### Important Implementation Notes

#### Pydantic AI Tool Decoration

Tools must be decorated for Pydantic AI:

```python
from pydantic_ai import RunContext

async def find_outliers_tool(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24
) -> str:
    """Tool docstring becomes tool description in agent."""

    # Access dependencies via ctx.deps
    tweets = await ctx.deps.twitter.get_tweets(
        project=ctx.deps.project_name,
        hours_back=hours_back
    )

    # Use services
    scores = [t.engagement_score for t in tweets]
    outliers = ctx.deps.stats.calculate_zscore_outliers(scores)

    # Return string (agent will see this)
    return f"Found {len(outliers)} outliers from {len(tweets)} tweets"
```

**Key Points:**
- First parameter MUST be `ctx: RunContext[AgentDependencies]`
- Return type should be `str` for simple responses
- Docstring becomes tool description for agent
- Access services via `ctx.deps.service_name`

#### Rate Limiting Considerations

GeminiService has built-in rate limiting (9 req/min default):
- `analyze_hooks_tool` should respect this
- Progress reporting for long-running analyses
- Consider batching for large tweet sets

#### Error Handling

Each tool should:
- Catch and handle service errors gracefully
- Return user-friendly error messages
- Log errors for debugging
- Not crash the agent conversation

---

### Reference Code Patterns

#### From outlier_detector.py

```python
# Fetch tweets
tweets = db.get_posts(
    project=project,
    hours_back=days_back * 24,
    min_views=min_views
)

# Calculate outliers
scores = [calculate_engagement_score(t) for t in tweets]
outliers = calculate_zscore_outliers(scores, threshold)

# Format results
for idx, zscore in outliers:
    tweet = tweets[idx]
    print(f"[Z={zscore:.1f}] {tweet.text[:50]}...")
```

#### From hook_analyzer.py

```python
# Analyze hook
response = model.generate_content(prompt)
analysis = parse_hook_response(response.text)

# Save to database
db.save_hook_analysis(analysis)
```

---

### Commands Cheat Sheet

```bash
# Verify branch
cd /Users/ryemckenzie/projects/viraltracker
git branch  # Should show: * feature/pydantic-ai-agent

# Run tests
python test_services_layer.py
python test_agent_dependencies.py

# Check imports
source venv/bin/activate
python -c "from viraltracker.agent.dependencies import AgentDependencies; print('✓ Ready')"
python -c "from pydantic_ai import Agent, RunContext; print('✓ Pydantic AI ready')"

# View documentation
cat docs/SERVICES_LAYER_SUMMARY.md
cat docs/AGENT_DEPENDENCIES_SUMMARY.md
cat docs/PYDANTIC_AI_MIGRATION_PLAN.md | grep -A 50 "Task 1.6"
```

---

### Current Git Status

```
Branch: feature/pydantic-ai-agent

Staged/Modified:
  (none - all files committed in previous session)

New files (ready to create):
  viraltracker/agent/tools.py
  test_agent_tools.py
  docs/AGENT_TOOLS_SUMMARY.md

Existing files (completed):
  viraltracker/services/__init__.py
  viraltracker/services/models.py
  viraltracker/services/twitter_service.py
  viraltracker/services/gemini_service.py
  viraltracker/services/stats_service.py
  viraltracker/agent/__init__.py
  viraltracker/agent/dependencies.py
  test_services_layer.py
  test_agent_dependencies.py
  docs/SERVICES_LAYER_SUMMARY.md
  docs/AGENT_DEPENDENCIES_SUMMARY.md
  docs/PYDANTIC_AI_MIGRATION_PLAN.md (updated)
```

---

## 🚀 Ready to Continue!

**Current State:**
- ✅ Services layer complete (Tasks 1.1-1.4)
- ✅ Agent dependencies complete (Task 1.5)
- ✅ All tests passing
- ✅ Documentation complete
- ✅ Pydantic AI installed

**Next Task:** Create agent tools (Task 1.6) - ~4 hours estimated

**Time Estimate for Remaining Agent Layer:**
- Task 1.6: 4 hours (agent tools)
- Task 1.7: 2 hours (agent config)
- **Total:** 6 hours to complete agent layer

**Success Criteria:**
- 3 working agent tools
- Tools integrate seamlessly with services
- All tests passing
- Comprehensive documentation
- Ready for Task 1.7 (agent configuration)

Good luck with Task 1.6! 🎯
