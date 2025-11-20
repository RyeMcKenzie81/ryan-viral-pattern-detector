# Services Layer Summary - Phase 1 (Tasks 1.1-1.4)

**Branch:** `feature/pydantic-ai-agent`
**Status:** ✅ Complete
**Date:** 2025-11-17

## Overview

The services layer provides clean separation between data access, AI operations, and business logic. All services use Pydantic models for type safety and validation.

## Architecture

```
viraltracker/services/
├── __init__.py           # Module exports
├── models.py             # Pydantic models (6 models)
├── twitter_service.py    # Database operations
├── gemini_service.py     # AI hook analysis
└── stats_service.py      # Statistical calculations
```

## Models (`models.py`)

### 1. Tweet
**Purpose:** Represents a single tweet with engagement metrics

**Key Fields:**
- `id`, `text`, `url`
- Engagement: `view_count`, `like_count`, `reply_count`, `retweet_count`
- Author: `author_username`, `author_followers`, `is_verified`
- Temporal: `created_at`

**Computed Properties:**
- `engagement_rate` = (likes + replies + retweets) / views
- `engagement_score` = weighted composite (likes × 1.0 + retweets × 0.8 + replies × 0.5)

**Example:**
```python
tweet = Tweet(
    id="1234567890",
    text="This is a viral tweet!",
    view_count=50000,
    like_count=2500,
    reply_count=150,
    retweet_count=800,
    created_at=datetime.now(timezone.utc),
    author_username="user",
    author_followers=10000,
    url="https://twitter.com/user/status/1234567890"
)

print(tweet.engagement_rate)   # 0.069 (6.9%)
print(tweet.engagement_score)  # 3215.0
```

### 2. HookAnalysis
**Purpose:** AI-powered classification of what makes a tweet viral

**Classifications:**
- `hook_type`: 14 types (hot_take, relatable_slice, validation_permission, etc.)
- `emotional_trigger`: 10 emotions (validation, humor, curiosity, etc.)
- `content_pattern`: 8 structures (question, statement, story, etc.)

**Features:**
- Confidence scores (0-1) for each classification
- Explanations: `hook_explanation`, `adaptation_notes`
- Metadata: emoji, hashtags, question marks, word count
- Validators: Ensures hook_type/emotional_trigger are valid values

**Example:**
```python
analysis = HookAnalysis(
    tweet_id="1234567890",
    tweet_text="Hot take: screen time isn't the enemy",
    hook_type="hot_take",
    hook_type_confidence=0.95,
    emotional_trigger="validation",
    emotional_trigger_confidence=0.88,
    hook_explanation="Challenges conventional wisdom...",
    adaptation_notes="Could expand into long-form piece..."
)
```

### 3. OutlierTweet
**Purpose:** Tweet + statistical significance metrics

**Fields:**
- `tweet`: Full Tweet model
- `zscore`: Standard deviations above mean
- `percentile`: Percentile rank (0-100)
- `rank`: Rank by engagement (1 = highest)

### 4. OutlierResult
**Purpose:** Aggregated results from outlier detection

**Features:**
- Summary stats: `total_tweets`, `outlier_count`, `mean_engagement`, etc.
- List of `outliers`: List[OutlierTweet]
- `success_rate` property: % of tweets that are outliers
- `to_markdown()` method: Export as markdown report

**Example:**
```python
result = OutlierResult(
    total_tweets=500,
    outlier_count=15,
    threshold=2.0,
    method="zscore",
    outliers=[...],
    mean_engagement=150.5
)

print(result.success_rate)  # 3.0%
markdown = result.to_markdown()  # Full report
```

### 5. HookAnalysisResult
**Purpose:** Aggregated results from hook analysis batch

**Features:**
- Counts: `total_analyzed`, `successful_analyses`, `failed_analyses`
- Pattern summaries: `top_hook_types`, `top_emotional_triggers`
- `compute_patterns()`: Calculate pattern frequencies
- `to_markdown()`: Export as markdown report

### 6. CommentCandidate
**Purpose:** Tweet identified as good commenting opportunity

**Fields:**
- `tweet`: Full Tweet model
- `green_flag_score`: Probability of being receptive (0-1)
- `engagement_score`: Weighted engagement
- `reasoning`: Why it's a good opportunity
- `suggested_comment`: Optional AI-generated comment

---

## TwitterService (`twitter_service.py`)

**Purpose:** Pure data access layer for Supabase

### Methods

#### `get_tweets(project, hours_back, min_views, min_likes, text_only, limit)`
Fetch tweets for a project with filters.

**Returns:** `List[Tweet]`

**Example:**
```python
service = TwitterService()
tweets = await service.get_tweets(
    project="yakety-pack-instagram",
    hours_back=24,
    min_views=100,
    text_only=True
)
```

#### `get_tweets_by_ids(tweet_ids, project)`
Fetch specific tweets by ID.

**Returns:** `List[Tweet]`

#### `save_hook_analysis(analysis, project)`
Save HookAnalysis to database.

**Note:** Requires `hook_analyses` table in Supabase.

#### `get_hook_analyses(project, hours_back, hook_type, limit)`
Fetch saved hook analyses with filters.

**Returns:** `List[HookAnalysis]`

#### `mark_as_outlier(tweet_id, zscore, threshold, method)`
Mark a tweet as viral outlier.

**Note:** Requires `outliers` table in Supabase.

---

## GeminiService (`gemini_service.py`)

**Purpose:** AI-powered hook analysis with intelligent rate limiting

### Features

**Rate Limiting:**
- Default: 9 req/min (free tier safety)
- Configurable via `set_rate_limit(requests_per_minute)`
- Automatic delay between requests

**Retry Logic:**
- Exponential backoff on 429 errors
- Max retries configurable (default: 3)
- Retries: 15s, 30s, 60s

**Response Parsing:**
- Extracts JSON from markdown code blocks
- Validates classifications
- Computes metadata (emoji, hashtags, word count)

### Methods

#### `analyze_hook(tweet_text, tweet_id, max_retries)`
Analyze a single tweet's hook.

**Returns:** `HookAnalysis`

**Example:**
```python
service = GeminiService()
service.set_rate_limit(6)  # 6 req/min

analysis = await service.analyze_hook(
    tweet_text="Hot take: screen time isn't the enemy",
    tweet_id="1234567890"
)

print(analysis.hook_type)  # "hot_take"
print(analysis.hook_type_confidence)  # 0.95
```

#### `set_rate_limit(requests_per_minute)`
Configure rate limiting.

---

## StatsService (`stats_service.py`)

**Purpose:** Pure statistical functions (no side effects)

### Methods

#### `calculate_zscore_outliers(values, threshold, trim_percent)`
Detect outliers using trimmed mean/std.

**Returns:** `List[Tuple[int, float]]` - (index, zscore) pairs

**Example:**
```python
values = [10, 12, 15, 11, 13, 100, 120]
outliers = StatsService.calculate_zscore_outliers(values, threshold=2.0)
# Returns: [(5, 3.2), (6, 3.8)]
```

#### `calculate_percentile_outliers(values, threshold)`
Detect outliers in top N%.

**Returns:** `List[Tuple[int, float, float]]` - (index, value, percentile)

#### `calculate_percentile(value, values)`
Calculate percentile rank of a value.

**Returns:** `float` (0-100)

#### `calculate_zscore(value, values, use_trimmed, trim_percent)`
Calculate z-score for a single value.

**Returns:** `float`

#### `calculate_summary_stats(values)`
Calculate full summary statistics.

**Returns:** `dict` with mean, median, std, min, max, count, q25, q75

---

## Testing

Run the test suite:
```bash
python test_services_layer.py
```

**Tests:**
1. ✅ Pydantic models (validation, computed properties, serialization)
2. ✅ StatsService (z-score, percentile, summary stats)
3. ✅ GeminiService (initialization, rate limiting, prompt building)
4. ✅ TwitterService (initialization, method presence)

**Note:** Full integration tests require credentials (Supabase, Gemini API).

---

## Service Method Patterns

### Metadata Tuples for Agent Tools

**Pattern:** When service methods will be consumed by Pydantic AI agent tools, return `tuple[Data, dict]` to preserve execution metadata for user-facing messages.

#### When to Use

Use metadata tuple return type when:
1. Service method will be consumed by agent tools
2. User-facing messages need context beyond the data itself
3. Execution metadata is important for understanding results
4. Users need to distinguish between different failure modes

#### What to Include in Metadata Dict

**Counts:**
- `requested_count`: What was requested
- `actual_count`: What was returned
- `skipped_count`: Items skipped due to validation/quality issues
- `failed_count`: Items that failed processing

**Quality Metrics:**
- `success_rate`: Percentage of successful operations
- `error_rate`: Percentage of failed operations
- `validation_failures`: Count of validation errors

**Context:**
- `timeframe`: Time window searched (e.g., "last 24 hours")
- `filters_applied`: What filters were used
- `source`: Data source (e.g., "Apify", "Supabase")

**Performance:**
- `duration_ms`: Execution time in milliseconds
- `api_calls_made`: Number of external API calls
- `rate_limit_hits`: Times rate limited

#### Example: ScrapingService.search_twitter()

**Service Layer (returns tuple with metadata):**
```python
async def search_twitter(
    self,
    keyword: str,
    project: str,
    hours_back: int = 24,
    max_results: int = 5000
) -> tuple[List[Tweet], dict]:
    """
    Search Twitter by keyword and save results to database.

    Returns:
        Tuple of (List of Tweet models, metadata dict with scrape stats)
        Metadata includes: tweets_count, skipped_count, requested_count
    """
    # Scrape tweets
    scrape_result = self.scraper.scrape_search(
        search_terms=[keyword],
        project_slug=project,
        max_tweets=max_results
    )

    # Extract data
    tweets_count = scrape_result['tweets_count']
    skipped_count = scrape_result.get('skipped_count', 0)

    # Log for backend visibility
    if skipped_count > 0:
        logger.warning(f"Skipped {skipped_count} malformed tweets")

    # Fetch tweets from database
    tweets = await twitter_service.get_tweets_by_ids(
        tweet_ids=scrape_result['post_ids'],
        project=project
    )

    # Build metadata for agent
    metadata = {
        'tweets_count': tweets_count,
        'skipped_count': skipped_count,
        'requested_count': max_results
    }

    return tweets, metadata
```

**Agent Tool Layer (unpacks and uses metadata):**
```python
async def search_twitter_tool(
    ctx: RunContext,
    keyword: str,
    max_results: int = 50,
    hours_back: int = 24
) -> str:
    """Search Twitter by keyword and return results to user"""

    # Unpack tuple
    tweets, metadata = await ctx.deps.scraping.search_twitter(
        keyword=keyword,
        project=ctx.deps.project_name,
        hours_back=hours_back,
        max_results=max_results
    )

    # Extract metadata
    tweets_count = metadata['tweets_count']
    skipped_count = metadata.get('skipped_count', 0)
    requested_count = metadata['requested_count']

    # Build accurate user-facing message
    response = f"**SCRAPED: {tweets_count} tweets** "
    response += f"(keyword: \"{keyword}\", timeframe: last {hours_back} hours)\n\n"

    # Distinguish between failure modes
    if skipped_count > 0:
        # Data quality issues
        response += f"**Note:** Requested {requested_count} tweets from Apify, "
        response += f"received {requested_count}, but {skipped_count} tweets "
        response += f"were skipped due to malformed data (data quality issues). "
        response += f"Saved {tweets_count} valid tweets to database.\n\n"
    elif tweets_count < requested_count:
        # Timeframe limitation
        response += f"**Note:** Requested {requested_count} tweets, but only "
        response += f"{tweets_count} tweets were available in the last {hours_back} hours.\n\n"
    else:
        # Success
        response += f"Successfully scraped all {requested_count} requested tweets.\n\n"

    return response
```

#### Key Benefits

1. **Accurate User Communication** - Users understand exactly what happened and why
2. **Distinguish Failure Modes** - Clear difference between data quality issues vs. availability issues
3. **Transparency** - Users see the full context of operations
4. **Maintainable** - Metadata in one place, easy to extend
5. **Type Safe** - Explicit tuple return types

#### Documentation Standards

When using metadata tuples, document return types clearly:

```python
async def service_method(...) -> tuple[List[Model], dict]:
    """
    Brief description of what method does.

    Args:
        param1: Description
        param2: Description

    Returns:
        Tuple of (List of Model objects, metadata dict)
        Metadata includes: count, skipped_count, requested_count, duration_ms

    Raises:
        ValueError: If validation fails
    """
```

**See Also:** `docs/SESSION_SUMMARY_AGENT_RESPONSE_FIX.md` for full implementation details.

---

## Usage Examples

### Example 1: Find Outliers
```python
# Initialize services
twitter_svc = TwitterService()
stats_svc = StatsService()

# Fetch tweets
tweets = await twitter_svc.get_tweets(
    project="yakety-pack-instagram",
    hours_back=24,
    min_views=100
)

# Calculate engagement scores
scores = [t.engagement_score for t in tweets]

# Find outliers
outliers = stats_svc.calculate_zscore_outliers(scores, threshold=2.0)

# Build result
outlier_tweets = [
    OutlierTweet(
        tweet=tweets[idx],
        zscore=zscore,
        percentile=stats_svc.calculate_percentile(tweets[idx].engagement_score, scores)
    )
    for idx, zscore in outliers
]

result = OutlierResult(
    total_tweets=len(tweets),
    outlier_count=len(outliers),
    threshold=2.0,
    method="zscore",
    outliers=outlier_tweets
)

print(result.to_markdown())
```

### Example 2: Analyze Hooks
```python
# Initialize services
twitter_svc = TwitterService()
gemini_svc = GeminiService()
gemini_svc.set_rate_limit(9)  # 9 req/min

# Fetch viral tweets
tweets = await twitter_svc.get_tweets_by_ids(
    tweet_ids=["1234567890", "0987654321"]
)

# Analyze hooks
analyses = []
for tweet in tweets:
    analysis = await gemini_svc.analyze_hook(
        tweet_text=tweet.text,
        tweet_id=tweet.id
    )

    # Save to database
    await twitter_svc.save_hook_analysis(analysis)

    analyses.append(analysis)

# Build result
result = HookAnalysisResult(
    total_analyzed=len(tweets),
    successful_analyses=len(analyses),
    analyses=analyses
)

result.compute_patterns()
print(result.to_markdown())
```

---

## Next Steps

### Phase 1, Tasks 1.5-1.7: Agent Layer

Now that the services layer is complete, we can build the Pydantic AI agent:

1. **Task 1.5:** Agent dependencies (`viraltracker/agent/dependencies.py`)
2. **Task 1.6:** Agent tools (`viraltracker/agent/tools.py`)
3. **Task 1.7:** Agent configuration (`viraltracker/agent/agent.py`)

The agent will use these services to provide conversational access to viral tweet analysis.

---

## Database Schema Notes

The services layer expects these Supabase tables:

### `posts` (existing)
- Stores tweets/posts
- Fields: `post_id`, `caption`, `views`, `likes`, `comments`, `shares`, `posted_at`, `post_url`, `media_type`
- Relations: `accounts` (author), `project_posts` (project links)

### `hook_analyses` (to be created)
```sql
CREATE TABLE hook_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tweet_id TEXT UNIQUE NOT NULL,
    tweet_text TEXT,
    hook_type TEXT,
    hook_type_confidence FLOAT,
    emotional_trigger TEXT,
    emotional_trigger_confidence FLOAT,
    content_pattern TEXT,
    content_pattern_confidence FLOAT,
    hook_explanation TEXT,
    adaptation_notes TEXT,
    has_emoji BOOLEAN,
    has_hashtags BOOLEAN,
    has_question_mark BOOLEAN,
    word_count INTEGER,
    analyzed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### `outliers` (to be created)
```sql
CREATE TABLE outliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tweet_id TEXT UNIQUE NOT NULL,
    zscore FLOAT,
    threshold FLOAT,
    method TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## Summary

**Status:** ✅ Complete

**Files Created:**
- `viraltracker/services/__init__.py`
- `viraltracker/services/models.py` (540 lines)
- `viraltracker/services/twitter_service.py` (350 lines)
- `viraltracker/services/gemini_service.py` (300 lines)
- `viraltracker/services/stats_service.py` (200 lines)

**Total:** ~1,400 lines of production code

**Ready for:** Phase 1, Tasks 1.5-1.7 (Pydantic AI Agent)
