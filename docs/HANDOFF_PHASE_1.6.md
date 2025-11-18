# Phase 1.6 Handoff: TikTok Platform Support

**Status:** ✅ COMPLETE
**Date:** 2025-01-17
**Branch:** feature/pydantic-ai-agent
**Commit:** TBD (awaiting final commit)

## Overview

Phase 1.6 extends the Viraltracker Pydantic AI agent with complete TikTok platform coverage, adding **5 new tools**, **1 new service**, and **1 new Pydantic model**. The agent now has **13 total tools** (8 from Phases 1-1.5 + 5 from Phase 1.6) providing comprehensive multi-platform viral content analysis.

This phase marks the transition from Twitter-only analysis to **true multi-platform support**, enabling users to analyze viral content across both Twitter and TikTok through a single conversational interface.

## What Was Built

### New Pydantic Models (1)

#### TikTokVideo (`viraltracker/services/models.py`)
```python
class TikTokVideo(BaseModel):
    """TikTok video data model with engagement metrics."""

    # Identifiers
    id: str = Field(..., description="TikTok video ID (post_id)")
    url: str = Field(..., description="Full URL to TikTok video")
    caption: str = Field(default="", description="Video caption/description")

    # Engagement metrics
    views: int = Field(default=0, ge=0, description="Total views/play count")
    likes: int = Field(default=0, ge=0, description="Total likes")
    comments: int = Field(default=0, ge=0, description="Total comments")
    shares: int = Field(default=0, ge=0, description="Total shares")

    # Video metadata
    length_sec: int = Field(default=0, ge=0, description="Video duration in seconds")
    posted_at: Optional[datetime] = Field(None, description="When video was posted")

    # Creator metadata
    username: str = Field(..., description="Creator username (without @)")
    display_name: str = Field(default="", description="Creator display name")
    follower_count: int = Field(default=0, ge=0, description="Creator follower count")
    is_verified: bool = Field(default=False, description="Is creator verified")
    download_url: Optional[str] = Field(None, description="Video download URL")

    @property
    def engagement_rate(self) -> float:
        """Engagement rate: (likes + comments + shares) / views"""
        if self.views == 0:
            return 0.0
        return (self.likes + self.comments + self.shares) / self.views

    @property
    def engagement_score(self) -> float:
        """Weighted engagement score (likes > shares > comments)"""
        return self.likes * 1.0 + self.shares * 0.8 + self.comments * 0.5
```

**Features:**
- Type-safe validation with Pydantic
- Computed properties for engagement rate and score
- Mirrors Tweet model architecture for consistency
- Non-negative constraints on numeric fields

### New Services (1)

#### TikTokService (`viraltracker/services/tiktok_service.py`)
- **Purpose:** TikTok scraping and analysis operations via agent
- **Pattern:** Wraps `TikTokScraper` with async interface, returns Pydantic models
- **Architecture:** Lazy initialization, thread pool execution for blocking I/O

**Key Methods:**
```python
async def search_keyword(
    keyword: str,
    project: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000,
    save_to_db: bool = True
) -> List[TikTokVideo]
    """Search TikTok by keyword with viral filtering."""

async def search_hashtag(
    hashtag: str,
    project: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000,
    save_to_db: bool = True
) -> List[TikTokVideo]
    """Search TikTok by hashtag with viral filtering."""

async def scrape_user(
    username: str,
    project: str,
    count: int = 50,
    save_to_db: bool = True
) -> List[TikTokVideo]
    """Scrape posts from a TikTok creator (no filtering)."""

async def fetch_video_by_url(
    url: str,
    project: str,
    save_to_db: bool = True
) -> Optional[TikTokVideo]
    """Fetch single TikTok video by URL."""

async def fetch_videos_by_urls(
    urls: List[str],
    project: str,
    save_to_db: bool = True
) -> List[TikTokVideo]
    """Batch fetch TikTok videos by URLs."""
```

**Implementation Details:**
- Lazy initialization: TikTokScraper created only when needed
- Thread pool execution: `loop.run_in_executor()` for blocking Apify calls
- Automatic DB linking: Looks up project_id from slug, links videos to projects
- DataFrame conversion: Converts pandas DataFrames to typed TikTokVideo models
- Graceful error handling: Logs failures, continues processing other videos

### New Agent Tools (5)

All tools in `viraltracker/agent/tools_phase16.py`:

#### 1. search_tiktok_tool
```python
async def search_tiktok_tool(
    ctx: RunContext[AgentDependencies],
    keyword: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str
```
- **Maps to CLI:** `tiktok search --keyword "keyword"`
- **Purpose:** Search TikTok by keyword, filter for viral videos
- **Defaults:** 50 videos, 100K+ views, last 10 days, micro-influencers (<50K followers)
- **Returns:** Summary stats + top 5 videos by engagement score

#### 2. search_tiktok_hashtag_tool
```python
async def search_tiktok_hashtag_tool(
    ctx: RunContext[AgentDependencies],
    hashtag: str,
    count: int = 50,
    min_views: int = 100000,
    max_days: int = 10,
    max_followers: int = 50000
) -> str
```
- **Maps to CLI:** `tiktok hashtag --hashtag "hashtag"`
- **Purpose:** Track TikTok hashtag performance, find viral content
- **Features:** Auto-strips '#' prefix, shows hashtag analytics
- **Returns:** Hashtag performance summary + top 5 videos by views

#### 3. scrape_tiktok_user_tool
```python
async def scrape_tiktok_user_tool(
    ctx: RunContext[AgentDependencies],
    username: str,
    count: int = 50
) -> str
```
- **Maps to CLI:** `tiktok user --username "user"`
- **Purpose:** Analyze TikTok creator content, competitive analysis
- **Features:** No filtering (fetches all posts), account statistics
- **Returns:** Account stats + top 5 videos by views

#### 4. analyze_tiktok_video_tool
```python
async def analyze_tiktok_video_tool(
    ctx: RunContext[AgentDependencies],
    url: str
) -> str
```
- **Maps to CLI:** `tiktok analyze-url --url "..."`
- **Purpose:** Deep analysis of single viral TikTok video
- **Features:** Detailed metrics, engagement insights, performance classification
- **Returns:** Full video analysis with actionable insights

#### 5. analyze_tiktok_batch_tool
```python
async def analyze_tiktok_batch_tool(
    ctx: RunContext[AgentDependencies],
    urls: List[str]
) -> str
```
- **Maps to CLI:** `tiktok analyze-urls --urls "url1" "url2"`
- **Purpose:** Bulk import and analyze multiple TikTok videos
- **Features:** Batch processing, aggregate metrics, failure tracking
- **Returns:** Batch summary with success/failure counts + all videos analyzed

### Infrastructure Updates

#### AgentDependencies Enhancement
```python
@dataclass
class AgentDependencies:
    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    scraping: ScrapingService
    comment: CommentService
    tiktok: TikTokService  # NEW - Phase 1.6
    project_name: str = "yakety-pack-instagram"
```

#### Agent Registration
- All 5 Phase 1.6 tools registered with `agent.tool()`
- System prompt updated with comprehensive TikTok tool descriptions
- Tools organized by phase (Phase 1 + 1.5 + 1.6)
- Agent now supports 13 total tools across 2 platforms

## File Manifest

### New Files
```
viraltracker/services/tiktok_service.py              (370 lines)
viraltracker/agent/tools_phase16.py                  (462 lines)
docs/HANDOFF_PHASE_1.6.md                            (this file)
```

### Modified Files
```
viraltracker/services/models.py                      (+67 lines, TikTokVideo model)
viraltracker/agent/dependencies.py                   (+10 lines, TikTokService integration)
viraltracker/agent/agent.py                          (+38 lines, tool registration + prompt)
```

## Agent Capabilities Summary

### Before Phase 1.6 (8 tools - Twitter only)
**Phase 1 (Core Twitter):**
1. Find viral outlier tweets
2. Analyze tweet hooks with AI
3. Export analysis reports

**Phase 1.5 (Complete Twitter):**
4. Search/scrape Twitter by keyword
5. Find comment opportunities
6. Export comment opportunities
7. Analyze keyword engagement
8. Generate content from hooks

### After Phase 1.6 (13 tools - Multi-platform)
**Phase 1 + 1.5 (Twitter - 8 tools):** *(unchanged)*

**Phase 1.6 (TikTok - 5 tools):**
9. **Search TikTok by keyword** ✨ NEW
10. **Search TikTok by hashtag** ✨ NEW
11. **Scrape TikTok user posts** ✨ NEW
12. **Analyze single TikTok video** ✨ NEW
13. **Batch analyze TikTok videos** ✨ NEW

## Example Conversations

### Example 1: TikTok Keyword Research
```
User: "Find viral TikTok videos about 'productivity apps' from the last week"
Agent: [Calls search_tiktok_tool("productivity apps", count=50, max_days=7)]
       Returns: "Found 47 viral TikTok videos for 'productivity apps'
                 Total Views: 12.3M | Average Engagement Rate: 8.4%
                 Top 5 videos by engagement..."
```

### Example 2: Hashtag Tracking
```
User: "Track the #morningroutine hashtag on TikTok"
Agent: [Calls search_tiktok_hashtag_tool("morningroutine")]
       Returns: "Found 50 viral videos for #morningroutine
                 Hashtag Performance: 45M total views
                 Top 5 performing videos..."
```

### Example 3: Creator Analysis
```
User: "Analyze the TikTok creator @productivity.guru"
Agent: [Calls scrape_tiktok_user_tool("productivity.guru", count=50)]
       Returns: "Scraped 50 videos from @productivity.guru
                 Account Statistics: 23.4K followers
                 Average Views: 145K | Median: 89K
                 Top 5 videos by views..."
```

### Example 4: Single Video Deep Dive
```
User: "Analyze this TikTok: https://www.tiktok.com/@user/video/1234567890"
Agent: [Calls analyze_tiktok_video_tool("https://www.tiktok.com/@user/video/1234567890")]
       Returns: "TikTok Video Analysis
                 Creator: @user (12.3K followers)
                 Views: 1.2M | Likes: 145K | Comments: 3.2K
                 Engagement Rate: 12.3% (Exceptional!)
                 Analysis: This video resonated strongly..."
```

### Example 5: Batch Import
```
User: "Analyze these 5 TikTok videos: [URLs]"
Agent: [Calls analyze_tiktok_batch_tool([url1, url2, url3, url4, url5])]
       Returns: "Batch Analysis Complete
                 URLs Provided: 5 | Videos Fetched: 4 | Failed: 1
                 Aggregate Metrics: 3.2M total views
                 Videos Analyzed: [list of 4 videos with stats]"
```

### Example 6: Cross-Platform Analysis
```
User: "Compare viral content on Twitter vs TikTok for 'dog training'"
Agent: [Calls search_twitter_tool("dog training", hours_back=24, max_results=100)]
       [Calls search_tiktok_tool("dog training", count=50, max_days=1)]
       Returns: "Twitter: 87 tweets, avg 1.2K views
                 TikTok: 43 videos, avg 234K views
                 TikTok shows 200x higher average views..."
```

## Testing Status

### Manual Testing
- ✅ All 5 tools compile without errors
- ✅ TikTokService instantiates correctly
- ✅ TikTokVideo model validates data properly
- ✅ AgentDependencies.create() initializes TikTokService
- ✅ Tool imports registered successfully
- ⏳ Live integration tests pending (requires Apify credits)

### Phase 1 + 1.5 Regression
- ⏳ Need to verify all 8 previous tools still work
- ⏳ Twitter functionality should be unaffected

## Technical Design Decisions

### 1. Service Layer Consistency
- **Decision:** TikTokService follows same pattern as ScrapingService/CommentService
- **Rationale:** Architectural consistency, predictable interface for future platforms
- **Pattern:** Wrap scraper, async interface, return Pydantic models, save to DB

### 2. Viral Filtering Defaults
- **Decision:** Default min_views=100K, max_followers=50K for search tools
- **Rationale:** Focus on viral content from micro-influencers (more actionable)
- **Customizable:** Users can adjust thresholds via tool parameters
- **Trade-off:** May miss some viral content, but improves signal-to-noise ratio

### 3. User Scraping (No Filtering)
- **Decision:** scrape_tiktok_user_tool fetches ALL posts without viral filtering
- **Rationale:** Enables outlier detection, competitive analysis, pattern identification
- **Use Case:** "Show me which of this creator's videos went viral"

### 4. Engagement Score Weighting
- **Decision:** `engagement_score = likes*1.0 + shares*0.8 + comments*0.5`
- **Rationale:** Likes are most common, shares indicate virality, comments vary
- **Alternative:** Could use engagement_rate (total/views) for normalization
- **Future:** May add configurable weighting or multiple scoring methods

### 5. Lazy Scraper Initialization
- **Decision:** TikTokScraper created on first use, not in __init__
- **Rationale:** Avoid Apify client initialization if tools never called
- **Performance:** Saves resources, faster startup time
- **Pattern:** Consistent with other service lazy initialization patterns

### 6. Thread Pool for Blocking I/O
- **Decision:** Use `loop.run_in_executor()` for Apify scraper calls
- **Rationale:** TikTokScraper is synchronous, agent is async
- **Alternative:** Could rewrite scraper as async, but significant refactor
- **Trade-off:** Thread pool adds overhead but maintains clean service interface

### 7. DataFrame to Pydantic Conversion
- **Decision:** Convert pandas DataFrames to TikTokVideo models in service layer
- **Rationale:** Type safety, validation, cleaner agent tool code
- **Benefit:** Tools work with typed objects, not raw dictionaries
- **Pattern:** Same as Tweet model conversion in TwitterService

## Known Limitations

1. **Apify Dependency:** TikTok scraping requires Apify credits and Clockworks actor
2. **Rate Limiting:** No rate limiting on TikTok scraping (relies on Apify)
3. **Search Quality:** Keyword search depends on Apify actor's search implementation
4. **No Hook Analysis:** TikTok videos not analyzed for hooks like tweets (future Phase?)
5. **Synchronous Scraper:** TikTokScraper is blocking, wrapped with thread pool
6. **No Tests:** Integration tests not yet added (requires Apify mock or credits)
7. **Hashtag Normalization:** Basic # stripping, doesn't handle complex hashtag queries
8. **User Verification:** Assumes username exists, minimal error guidance if not found
9. **Batch Size Limits:** No pagination for large batch imports (list must fit in memory)

## Next Steps

### Immediate (before merge)
1. Add basic integration test for Phase 1.6 tools (or Apify mock)
2. Run full test suite to verify no regressions (Phases 1 + 1.5)
3. Test cross-platform workflows (Twitter + TikTok in same conversation)
4. Create commit with all Phase 1.6 changes

### Future Enhancements (Phase 1.6.1+)
1. **TikTok Hook Analysis:** Extend analyze_hooks_tool to work with TikTok captions
2. **Cross-Platform Outliers:** Find outliers across both Twitter and TikTok
3. **Engagement Comparison:** Compare engagement patterns between platforms
4. **Rate Limiting:** Add configurable rate limits for TikTok scraping
5. **Better Error Messages:** Improve user feedback when scraping fails

### Phase 1.7 (YouTube & Facebook)
1. Create YouTubeService (wraps YouTube scraper)
2. Create FacebookService (wraps Facebook Ads scraper)
3. Add Pydantic models: YouTubeVideo, FacebookAd
4. Implement 3 tools:
   - search_youtube_tool
   - scrape_facebook_page_ads_tool
   - search_facebook_ads_tool
5. Update AgentDependencies with YouTube + Facebook services

### Phase 1.8 (Integration & Testing)
1. Update Streamlit UI with platform selector (Twitter/TikTok/YouTube/Facebook)
2. Add comprehensive integration tests (40+ tests across all platforms)
3. End-to-end multi-platform workflow tests
4. Performance benchmarks (response time, Apify credit usage)
5. Final documentation and examples
6. Production readiness review

## Success Criteria

Phase 1.6 is considered complete when:

- ✅ 5 new TikTok agent tools implemented and registered
- ✅ TikTokService created with 5 async methods
- ✅ TikTokVideo Pydantic model added to models.py
- ✅ AgentDependencies updated with TikTokService
- ✅ System prompt updated with TikTok tool descriptions
- ✅ Tools compile and import successfully
- ⏳ Basic integration test added (or decision to skip until Phase 1.8)
- ⏳ Phase 1 + 1.5 tests still pass (8/8 tools functional)
- ✅ Documentation complete

**Current Status:** 6/9 criteria met (67%)
**Remaining:** Integration tests, regression testing

## How to Use

### Start Chat with TikTok Capabilities
```bash
# From viraltracker root
source venv/bin/activate
python -m viraltracker.cli.main agent chat --project yakety-pack-instagram
```

### Example Prompts to Try

**TikTok-specific:**
```
"Find viral TikTok videos about 'productivity apps'"
"Track the #morningroutine hashtag on TikTok"
"Analyze the TikTok creator @productivity.guru"
"Analyze this TikTok: [URL]"
"Compare these 5 TikTok videos: [URLs]"
```

**Cross-platform:**
```
"Compare Twitter and TikTok content for 'dog training'"
"Find viral content on both platforms about 'parenting tips'"
"Which platform performs better for 'productivity' content?"
```

**Multi-step workflows:**
```
"Search TikTok for 'morning routine' videos, then show me the top creator's account stats"
"Find viral TikTok videos about my niche, analyze the best one in detail"
```

### Verifying Tools Work
```python
# In Python REPL or script
from viraltracker.agent.dependencies import AgentDependencies

# Create dependencies
deps = AgentDependencies.create(project_name="yakety-pack-instagram")

# Verify TikTokService initialized
print(deps.tiktok)  # Should show TikTokService instance

# Check all services present
print(deps)  # Should show 6 services including TikTokService
```

### Testing Individual Tools
```python
import asyncio
from viraltracker.agent.dependencies import AgentDependencies
from pydantic_ai import RunContext

# Create dependencies
deps = AgentDependencies.create()

# Create mock context
class MockContext:
    def __init__(self, deps):
        self.deps = deps

ctx = MockContext(deps)

# Test search tool
from viraltracker.agent.tools_phase16 import search_tiktok_tool
result = asyncio.run(search_tiktok_tool(
    ctx,
    keyword="productivity apps",
    count=10,
    min_views=50000
))
print(result)
```

## Questions for Next Developer

1. **TikTok Hook Analysis:** Should we extend Gemini hook analysis to TikTok captions?
2. **Cross-Platform Metrics:** Should engagement rates be normalized across platforms?
3. **Viral Thresholds:** Are the default min_views (100K) appropriate for all niches?
4. **Creator Focus:** Should we add follower growth tracking for TikTok creators?
5. **Hashtag Strategy:** Should we track hashtag performance over time?
6. **Content Downloads:** Should we enable TikTok video downloads via download_url?
7. **Batch Limits:** What's a reasonable limit for batch URL analysis?
8. **Error Handling:** Should tools retry failed Apify scrapes automatically?
9. **Caching:** Should TikTok search results be cached (similar to Twitter)?
10. **Rate Limiting:** What rate limits are appropriate for TikTok scraping?

## Comparison: Twitter vs TikTok Coverage

| Feature | Twitter (Phase 1+1.5) | TikTok (Phase 1.6) |
|---------|----------------------|-------------------|
| **Search by keyword** | ✅ search_twitter_tool | ✅ search_tiktok_tool |
| **Hashtag tracking** | ❌ (uses keyword search) | ✅ search_tiktok_hashtag_tool |
| **User/creator scraping** | ❌ (not yet implemented) | ✅ scrape_tiktok_user_tool |
| **Single post analysis** | ✅ (via find_outliers) | ✅ analyze_tiktok_video_tool |
| **Batch import** | ❌ (not yet implemented) | ✅ analyze_tiktok_batch_tool |
| **Hook analysis** | ✅ analyze_hooks_tool | ❌ (future enhancement) |
| **Comment opportunities** | ✅ find_comment_opportunities_tool | ❌ (not applicable?) |
| **Content generation** | ✅ generate_content_tool | ❌ (future enhancement) |
| **Outlier detection** | ✅ find_outliers_tool | ❌ (future enhancement) |

**Gap Analysis:** TikTok tools focus on data collection, Twitter tools include AI analysis. Future work should extend AI capabilities (hooks, outliers, content generation) to TikTok.

## Related Documents

- [Phase 1 Handoff](./HANDOFF_PHASE1_TASK16.md) - Original 3-tool implementation
- [Phase 1.5 Handoff](./HANDOFF_PHASE_1.5.md) - Complete Twitter coverage (5 tools)
- [Pydantic AI Migration Plan](./PYDANTIC_AI_MIGRATION_PLAN.md) - Overall roadmap
- [CLI TikTok Commands](../viraltracker/cli/tiktok.py) - CLI implementations
- [TikTok Scraper](../viraltracker/scrapers/tiktok.py) - Underlying scraper logic

## Contact

For questions about Phase 1.6 implementation:
- Review code comments in `tools_phase16.py` for tool-specific details
- Check `tiktok_service.py` docstrings for service API documentation
- See system prompt in `agent.py` (lines 196-227) for tool descriptions
- Review `TikTokVideo` model in `models.py` for data structure

## Architecture Diagram

```
User Question (e.g., "Find viral TikTok videos about X")
    ↓
Agent (Pydantic AI) - Uses system prompt to select tool
    ↓
search_tiktok_tool (tools_phase16.py)
    ↓
ctx.deps.tiktok.search_keyword() (TikTokService)
    ↓
loop.run_in_executor() → TikTokScraper.search_by_keyword() (blocking)
    ↓
Apify Clockworks TikTok Scraper Actor
    ↓
pandas DataFrame (raw data)
    ↓
Convert to List[TikTokVideo] (Pydantic validation)
    ↓
Save to Supabase (tiktok_posts table, linked to project)
    ↓
Return List[TikTokVideo] to tool
    ↓
Format as markdown string (stats + top 5 videos)
    ↓
Return to agent
    ↓
Agent returns to user with insights
```

---

**Phase 1.6 Status:** ✅ IMPLEMENTATION COMPLETE | ⏳ TESTING PENDING

Ready to proceed to Phase 1.7 (YouTube & Facebook) after integration tests pass.

**Total Agent Progress:** 13/16 tools implemented (81% to MVP)
- Phase 1: 3/3 tools ✅
- Phase 1.5: 5/5 tools ✅
- Phase 1.6: 5/5 tools ✅
- Phase 1.7: 0/3 tools ⏳
