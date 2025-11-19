# Task 2.8: Refactor Remaining CLI Commands

**Status:** ⏸️ PARTIALLY COMPLETE (Phase 1 Done)
**Priority:** ⭐⭐ MEDIUM (Non-blocking for MVP)
**Date Started:** 2025-11-18
**Date Phase 1 Completed:** 2025-11-18
**Branch:** phase-2-polish-and-organization
**Estimated Time:** 15-20 hours (2-3 days)
**Time Spent:** ~3 hours (Phase 1)

---

## Overview

Complete the CLI refactoring started in Task 1.11 by migrating the remaining 6 Twitter commands to use the services layer. This ensures all CLI commands follow the same modern architecture pattern.

---

## Current State Analysis

### ✅ Already Refactored (Task 1.11)
- `find-outliers` (viraltracker/cli/twitter.py:1264) - Uses TwitterService + StatsService
- `analyze-hooks` (viraltracker/cli/twitter.py:1547) - Uses TwitterService + GeminiService

### 🔄 Needs Refactoring (Task 2.8)
| Command | Line | Complexity | Est. Time | Dependencies |
|---------|------|------------|-----------|--------------|
| `search` | 178 | Medium | 3-4h | SearchService (new) |
| `generate-comments` | 402 | High | 4-5h | CommentService (new) |
| `export-comments` | 812 | Low | 2h | ExportService or extend TwitterService |
| `analyze-search-term` | 1104 | Medium | 2-3h | AnalysisService (new) |
| `generate-content` | 1751 | Medium | 3-4h | ContentService (new) |
| `export-content` | 2001 | Low | 1-2h | ExportService |

**Total:** 6 commands, 15-20 hours

---

## Implementation Strategy

### Phase 1: Create New Services (6-8 hours)

#### 1.1: SearchService
**File:** `viraltracker/services/search_service.py`

**Purpose:** Handle Twitter search/scraping operations

**Methods:**
```python
class SearchService:
    async def search_twitter(
        self,
        keyword: str,
        hours_back: int = 24,
        max_results: int = 100,
        project_id: Optional[str] = None
    ) -> List[Tweet]:
        """Search Twitter and save results to database"""

    async def check_semantic_duplicates(
        self,
        project_id: str,
        tweet_embeddings: List[List[float]],
        threshold: float = 0.95
    ) -> List[bool]:
        """Check for semantic duplicates using pgvector"""

    async def store_tweet_embedding(
        self,
        project_id: str,
        tweet_id: str,
        embedding: List[float]
    ):
        """Store tweet embedding for deduplication"""
```

**Dependencies:**
- TwitterScraper (existing)
- Embedder (existing)
- get_supabase_client()

---

#### 1.2: CommentService
**File:** `viraltracker/services/comment_service.py`

**Purpose:** Handle comment generation and opportunity detection

**Methods:**
```python
class CommentService:
    async def find_comment_opportunities(
        self,
        project_id: str,
        hours_back: int = 48,
        min_green_flags: int = 3,
        max_candidates: int = 100
    ) -> List[CommentOpportunity]:
        """Find high-quality comment opportunities"""

    async def score_tweet(
        self,
        tweet: Tweet,
        config: dict
    ) -> TweetScore:
        """Score tweet for comment suitability"""

    async def generate_comment_suggestions(
        self,
        tweet: Tweet,
        product_context: dict
    ) -> List[str]:
        """Generate AI comment suggestions"""

    async def save_suggestions(
        self,
        project_id: str,
        tweet_id: str,
        suggestions: List[str]
    ):
        """Save comment suggestions to database"""
```

**Dependencies:**
- CommentGenerator (existing)
- fetch_recent_tweets (existing)
- score_tweet (existing)
- GeminiService

---

#### 1.3: AnalysisService
**File:** `viraltracker/services/analysis_service.py`

**Purpose:** Handle search term and keyword analysis

**Methods:**
```python
class AnalysisService:
    async def analyze_search_term(
        self,
        keyword: str,
        project_id: str,
        hours_back: int = 24
    ) -> SearchTermAnalysis:
        """Analyze keyword engagement patterns"""

    async def calculate_engagement_stats(
        self,
        tweets: List[Tweet]
    ) -> Dict[str, Any]:
        """Calculate engagement statistics"""

    async def identify_top_performers(
        self,
        tweets: List[Tweet],
        limit: int = 10
    ) -> List[Tweet]:
        """Identify top performing tweets"""
```

**Dependencies:**
- TwitterService
- StatsService

---

#### 1.4: ContentService
**File:** `viraltracker/services/content_service.py`

**Purpose:** Handle long-form content generation from viral hooks

**Methods:**
```python
class ContentService:
    async def generate_content(
        self,
        hooks: List[HookAnalysis],
        content_type: str = "thread",
        product_context: Optional[dict] = None
    ) -> str:
        """Generate long-form content from viral hooks"""

    async def get_viral_hooks(
        self,
        project_id: str,
        hours_back: int = 24,
        limit: int = 10
    ) -> List[HookAnalysis]:
        """Get recent viral hooks for content generation"""
```

**Dependencies:**
- GeminiService
- TwitterService

---

#### 1.5: ExportService
**File:** `viraltracker/services/export_service.py`

**Purpose:** Handle data export operations

**Methods:**
```python
class ExportService:
    async def export_comments(
        self,
        project_id: str,
        hours_back: int = 48,
        format: str = "json",
        label_filter: Optional[str] = None
    ) -> str:
        """Export comment opportunities"""

    async def export_content(
        self,
        content: str,
        format: str = "markdown"
    ) -> str:
        """Export generated content"""

    async def export_to_file(
        self,
        data: Any,
        filepath: Path,
        format: str = "json"
    ):
        """Export data to file"""
```

**Dependencies:**
- json, csv libraries
- Path operations

---

### Phase 2: Refactor CLI Commands (9-12 hours)

#### 2.1: Refactor `search` Command
**Current:** Lines 178-401 (~223 lines)
**Target:** ~80-100 lines

**Before:**
```python
@twitter_group.command(name="search")
def twitter_search(...):
    # Direct database queries
    # Inline scraping logic
    # Direct embedding calculations
```

**After:**
```python
@twitter_group.command(name="search")
def twitter_search(...):
    async def run():
        search_svc = SearchService()
        tweets = await search_svc.search_twitter(
            keyword=keyword,
            hours_back=hours_back,
            max_results=max_results,
            project_id=project_id
        )
        # Display results

    asyncio.run(run())
```

**Changes:**
- Remove direct TwitterScraper usage → Use SearchService
- Remove inline embedding logic → SearchService handles it
- Remove direct database writes → SearchService handles it
- Keep CLI interface unchanged

---

#### 2.2: Refactor `generate-comments` Command
**Current:** Lines 402-811 (~409 lines)
**Target:** ~100-120 lines

**Before:**
```python
@twitter_group.command(name="generate-comments")
def generate_comments(...):
    # Direct tweet fetching
    # Inline scoring logic
    # Direct AI calls
    # Direct database writes
```

**After:**
```python
@twitter_group.command(name="generate-comments")
def generate_comments(...):
    async def run():
        comment_svc = CommentService()
        opportunities = await comment_svc.find_comment_opportunities(
            project_id=project_id,
            hours_back=hours_back,
            min_green_flags=min_green_flags,
            max_candidates=max_candidates
        )

        for opp in opportunities:
            suggestions = await comment_svc.generate_comment_suggestions(
                tweet=opp.tweet,
                product_context=product_context
            )
            await comment_svc.save_suggestions(...)

        # Display results

    asyncio.run(run())
```

**Changes:**
- Remove direct tweet fetching → Use CommentService
- Remove inline scoring → CommentService handles it
- Remove direct AI calls → CommentService handles it
- Keep all CLI flags and options

---

#### 2.3: Refactor `export-comments` Command
**Current:** Lines 812-1103 (~291 lines)
**Target:** ~70-80 lines

**Before:**
```python
@twitter_group.command(name="export-comments")
def export_comments(...):
    # Direct database queries
    # Inline CSV/JSON generation
    # Direct file writes
```

**After:**
```python
@twitter_group.command(name="export-comments")
def export_comments(...):
    async def run():
        export_svc = ExportService()
        filepath = await export_svc.export_comments(
            project_id=project_id,
            hours_back=hours_back,
            format=format,
            label_filter=label_filter
        )

        click.echo(f"💾 Exported to {filepath}")

    asyncio.run(run())
```

**Changes:**
- Remove direct database queries → Use ExportService
- Remove inline export logic → ExportService handles it
- Keep all export formats (JSON, CSV, Markdown)

---

#### 2.4: Refactor `analyze-search-term` Command
**Current:** Lines 1104-1263 (~159 lines)
**Target:** ~60-70 lines

**Before:**
```python
@twitter_group.command(name="analyze-search-term")
def analyze_search_term(...):
    # Direct database queries
    # Inline statistics calculations
    # Direct engagement analysis
```

**After:**
```python
@twitter_group.command(name="analyze-search-term")
def analyze_search_term(...):
    async def run():
        analysis_svc = AnalysisService()
        analysis = await analysis_svc.analyze_search_term(
            keyword=keyword,
            project_id=project_id,
            hours_back=hours_back
        )

        # Display analysis results
        click.echo(f"📊 Search Term Analysis: {keyword}")
        click.echo(f"Total Tweets: {analysis.total_tweets}")
        click.echo(f"Avg Engagement: {analysis.avg_engagement}")
        # ...

    asyncio.run(run())
```

**Changes:**
- Remove direct database queries → Use AnalysisService
- Remove inline stats → AnalysisService + StatsService
- Keep output format

---

#### 2.5: Refactor `generate-content` Command
**Current:** Lines 1751-2000 (~249 lines)
**Target:** ~80-90 lines

**Before:**
```python
@twitter_group.command(name="generate-content")
def generate_content(...):
    # Direct hook fetching
    # Inline AI content generation
    # Direct file writes
```

**After:**
```python
@twitter_group.command(name="generate-content")
def generate_content(...):
    async def run():
        content_svc = ContentService()

        # Get viral hooks
        hooks = await content_svc.get_viral_hooks(
            project_id=project_id,
            hours_back=hours_back,
            limit=limit
        )

        # Generate content
        content = await content_svc.generate_content(
            hooks=hooks,
            content_type=content_type,
            product_context=product_context
        )

        click.echo(content)

    asyncio.run(run())
```

**Changes:**
- Remove direct hook queries → Use ContentService
- Remove inline AI calls → ContentService handles it
- Keep content types (thread, article)

---

#### 2.6: Refactor `export-content` Command
**Current:** Lines 2001-END (~small)
**Target:** ~40-50 lines

**Before:**
```python
@twitter_group.command(name="export-content")
def export_content(...):
    # Direct file operations
    # Inline format conversion
```

**After:**
```python
@twitter_group.command(name="export-content")
def export_content(...):
    async def run():
        export_svc = ExportService()
        filepath = await export_svc.export_content(
            content=content,
            format=format
        )

        click.echo(f"💾 Exported to {filepath}")

    asyncio.run(run())
```

**Changes:**
- Remove direct file ops → Use ExportService
- Keep all export formats

---

## Testing Plan

### Unit Tests
```python
# tests/services/test_search_service.py
async def test_search_twitter():
    service = SearchService()
    tweets = await service.search_twitter("AI", hours_back=24, max_results=10)
    assert len(tweets) <= 10
    assert all(isinstance(t, Tweet) for t in tweets)

# tests/services/test_comment_service.py
async def test_find_comment_opportunities():
    service = CommentService()
    opps = await service.find_comment_opportunities("project-id", hours_back=48)
    assert all(hasattr(opp, 'score') for opp in opps)
```

### Integration Tests
```bash
# Test each command maintains same CLI interface
viraltracker twitter search --keyword "AI" --hours 24
viraltracker twitter generate-comments --project yakety-pack --hours-back 48
viraltracker twitter export-comments --project yakety-pack --format json
viraltracker twitter analyze-search-term --keyword "productivity"
viraltracker twitter generate-content --hours-back 24 --type thread
viraltracker twitter export-content --format markdown
```

### Regression Tests
- Compare outputs before/after refactoring
- Verify all CLI flags still work
- Check database writes are identical
- Validate export file formats

---

## Success Criteria

✅ All 6 commands refactored to use services layer
✅ CLI interface unchanged (backwards compatible)
✅ All existing CLI tests pass
✅ New service unit tests written and passing
✅ Integration tests verify end-to-end functionality
✅ Documentation updated
✅ Code reduced by ~40% (from monolithic to thin wrappers)

---

## Files to Create

1. `viraltracker/services/search_service.py` (~200 lines)
2. `viraltracker/services/comment_service.py` (~300 lines)
3. `viraltracker/services/analysis_service.py` (~150 lines)
4. `viraltracker/services/content_service.py` (~200 lines)
5. `viraltracker/services/export_service.py` (~150 lines)

**Total New Code:** ~1,000 lines

## Files to Modify

1. `viraltracker/cli/twitter.py` - Reduce from ~2,000 lines to ~800 lines

**Code Reduction:** ~1,200 lines removed (moved to services)

---

## Risks & Mitigation

### Risk 1: Breaking Existing Workflows
**Impact:** HIGH - Users may have production scripts
**Mitigation:**
- Keep exact same CLI interface
- Test with real user workflows
- Document any subtle differences

### Risk 2: Different Results
**Impact:** MEDIUM - Services might calculate differently
**Mitigation:**
- Use exact same algorithms
- Compare outputs before/after
- Unit test all calculations

### Risk 3: Performance Changes
**Impact:** LOW - Async overhead minimal
**Mitigation:**
- Benchmark before/after
- Services already async
- Optimize if needed

---

## Time Breakdown

### Phase 1: Services (6-8 hours)
- SearchService: 2 hours
- CommentService: 2.5 hours
- AnalysisService: 1.5 hours
- ContentService: 1.5 hours
- ExportService: 1 hour

### Phase 2: CLI Refactoring (9-12 hours)
- search: 3-4 hours
- generate-comments: 4-5 hours
- export-comments: 2 hours
- analyze-search-term: 2-3 hours
- generate-content: 3-4 hours
- export-content: 1-2 hours

### Phase 3: Testing & Documentation (2-3 hours)
- Unit tests: 1 hour
- Integration tests: 1 hour
- Documentation: 1 hour

**Total:** 17-23 hours (2-3 days)

---

## Next Steps

### Option A: Implement All 6 Commands (2-3 days)
**Pros:** Complete refactoring, consistent architecture
**Cons:** Time-intensive, delays Phase 3

### Option B: Implement High-Priority Commands Only (1 day)
**Focus on:**
1. generate-comments (most used)
2. search (most used)
3. export-comments (simple)

**Defer:**
- analyze-search-term
- generate-content
- export-content

**Pros:** Faster to Phase 3, covers 80% use cases
**Cons:** Incomplete refactoring

### Option C: Skip Task 2.8, Move to Phase 3 (immediate)
**Pros:** Fastest path to deployment
**Cons:** Inconsistent architecture, tech debt

---

## Recommendation

**Option B: Implement High-Priority Commands (1 day)**

**Rationale:**
1. `generate-comments` is heavily used in production (see background bash jobs)
2. `search` is core functionality
3. `export-comments` is simple and quick
4. Remaining 3 commands can be refactored later as needed
5. Gets 80% of benefits in 33% of time

**Next Session Plan:**
1. Create CommentService (2.5 hours)
2. Refactor generate-comments command (4 hours)
3. Create SearchService (2 hours)
4. Refactor search command (3 hours)
5. Refactor export-comments command (2 hours)
6. Test and document (2 hours)

**Total:** ~15.5 hours (1 full day)

---

## How to Continue

```bash
# Start working on Task 2.8
cd /Users/ryemckenzie/projects/viraltracker
source venv/bin/activate

# Verify current branch
git branch  # Should show phase-2-polish-and-organization

# Start with CommentService (most critical)
# Create viraltracker/services/comment_service.py
```

---

**Task 2.8 Status:** 🔄 PLANNING COMPLETE, READY FOR IMPLEMENTATION
**Recommendation:** Option B - High-priority commands (1 day)
**Branch:** phase-2-polish-and-organization
**Next:** Create CommentService
