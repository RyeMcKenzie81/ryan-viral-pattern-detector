# Phase 1.7 Handoff: YouTube & Facebook Platform Support (IN PROGRESS)

**Status:** 🚧 PARTIAL - Models Complete, Services & Tools Pending
**Date:** 2025-01-17
**Branch:** feature/pydantic-ai-agent
**Commit:** TBD (pending completion)

## Overview

Phase 1.7 adds YouTube and Facebook Ads platform support to the Viraltracker Pydantic AI agent. This phase is **partially complete** - the Pydantic models have been added, but services and tools still need to be implemented.

**Original Goal:** Add 3 new tools (1 YouTube + 2 Facebook)
**Current Progress:** Models added (YouTubeVideo, FacebookAd), remaining implementation needed

## What Was Completed

### New Pydantic Models (2) ✅

Both models added to `viraltracker/services/models.py`:

#### 1. YouTubeVideo Model (55 lines)
```python
class YouTubeVideo(BaseModel):
    """YouTube video data model with engagement metrics."""

    # Identifiers
    id: str  # YouTube video ID
    url: str  # Full URL to video
    title: str
    caption: str  # Description

    # Engagement metrics
    views: int
    likes: int
    comments: int

    # Video metadata
    length_sec: int
    video_type: str  # 'short', 'video', or 'stream'
    posted_at: Optional[datetime]

    # Channel metadata
    channel: str  # Channel name
    subscriber_count: int
    search_query: Optional[str]  # Query that found this video

    @property
    def engagement_rate(self) -> float:
        """(likes + comments) / views"""

    @property
    def engagement_score(self) -> float:
        """likes * 1.0 + comments * 0.5"""
```

**Location:** `viraltracker/services/models.py` lines 160-214
**Pattern:** Mirrors TikTokVideo architecture
**Fields Match:** YouTube scraper normalization output

#### 2. FacebookAd Model (73 lines)
```python
class FacebookAd(BaseModel):
    """Facebook ad data model with spend and reach metrics."""

    # Identifiers
    id: str  # Facebook ad ID
    ad_archive_id: str  # Archive ID (deduplication)
    url: Optional[str]

    # Page metadata
    page_id: Optional[str]
    page_name: str

    # Ad metadata
    is_active: bool
    start_date: Optional[datetime]
    end_date: Optional[datetime]

    # Performance metrics
    currency: Optional[str]  # e.g., USD
    spend: Optional[float]  # Total ad spend
    impressions: Optional[int]
    reach_estimate: Optional[int]

    # Creative data (JSON strings)
    snapshot: Optional[str]  # Creative/visual data
    categories: Optional[str]  # Ad categories
    publisher_platform: Optional[str]  # Where published

    # Political/transparency
    political_countries: Optional[str]
    entity_type: Optional[str]

    @property
    def engagement_score(self) -> float:
        """Average of impressions and reach"""

    @property
    def days_active(self) -> Optional[int]:
        """Number of days ad has been active"""
```

**Location:** `viraltracker/services/models.py` lines 217-290
**Pattern:** Similar to TikTokVideo but with ad-specific metrics
**Fields Match:** Facebook Ads scraper normalization output
**Note:** Many fields are Optional since Facebook Ads API provides variable data

### Research Completed ✅

1. **Examined YouTube CLI** (`viraltracker/cli/youtube.py` - 169 lines)
   - Command: `youtube search --terms "keyword"`
   - Uses `YouTubeSearchScraper` from `scrapers/youtube_search.py`
   - Supports Shorts, regular videos, and streams
   - Filters: views, subscribers, date range, sort order

2. **Examined Facebook CLI** (`viraltracker/cli/facebook.py` - 215 lines)
   - Commands: `facebook search <url>` and `facebook page <url>`
   - Uses `FacebookAdsScraper` from `scrapers/facebook_ads.py`
   - Scrapes from Facebook Ad Library
   - Filters: active status, country, date period

3. **Analyzed Data Structures**
   - YouTube: Flat structure with core engagement (views/likes/comments)
   - Facebook: Rich metadata with financial data, nested JSON fields
   - Both use Apify actors for scraping

## What Remains To Be Done

### Immediate Next Steps (Phase 1.7 Completion)

#### 1. Create YouTubeService (`viraltracker/services/youtube_service.py`)

**Pattern:** Follow TikTokService architecture from Phase 1.6

```python
class YouTubeService:
    """Service for YouTube operations via agent."""

    def __init__(self):
        self.scraper = None  # Lazy initialization

    def _get_scraper(self) -> YouTubeSearchScraper:
        """Lazy init YouTube scraper"""
        if self.scraper is None:
            from ..scrapers.youtube_search import YouTubeSearchScraper
            self.scraper = YouTubeSearchScraper()
        return self.scraper

    async def search_videos(
        self,
        search_terms: List[str],
        project: str,
        max_shorts: int = 100,
        max_videos: int = 0,
        days_back: Optional[int] = None,
        min_views: Optional[int] = None,
        min_subscribers: Optional[int] = None,
        max_subscribers: Optional[int] = None,
        save_to_db: bool = True
    ) -> List[YouTubeVideo]:
        """
        Search YouTube by keyword with viral filtering.

        Wraps YouTubeSearchScraper.scrape_search() with async interface.
        Returns typed YouTubeVideo models.
        """
        loop = asyncio.get_event_loop()
        scraper = self._get_scraper()

        # Run scraper in thread pool (blocking I/O)
        terms_count, videos_count = await loop.run_in_executor(
            None,
            lambda: scraper.scrape_search(
                search_terms=search_terms,
                max_shorts=max_shorts,
                max_videos=max_videos,
                days_back=days_back,
                min_views=min_views,
                min_subscribers=min_subscribers,
                max_subscribers=max_subscribers,
                project_slug=project
            )
        )

        # Fetch saved videos from database and convert to YouTubeVideo models
        # OR: Parse DataFrame directly if scraper returns it
        # TODO: Implement data conversion

        return videos
```

**Estimated Lines:** ~200-250 (similar to TikTokService)
**Key Decision:** Whether to query DB after scraping or convert DataFrame directly

#### 2. Create FacebookService (`viraltracker/services/facebook_service.py`)

**Pattern:** Follow TikTokService architecture

```python
class FacebookService:
    """Service for Facebook Ads operations via agent."""

    def __init__(self):
        self.scraper = None  # Lazy initialization

    async def search_ads(
        self,
        search_url: str,
        project: str,
        count: Optional[int] = None,
        period: str = "",
        save_to_db: bool = True
    ) -> List[FacebookAd]:
        """Search Facebook Ad Library by URL"""

    async def scrape_page_ads(
        self,
        page_url: str,
        project: str,
        count: Optional[int] = None,
        active_status: str = "all",
        save_to_db: bool = True
    ) -> List[FacebookAd]:
        """Scrape all ads run by a Facebook page"""
```

**Estimated Lines:** ~250-300
**Note:** FacebookAdsScraper returns DataFrames, need conversion to FacebookAd models

#### 3. Create Agent Tools (`viraltracker/agent/tools_phase17.py`)

**3 Tools Needed:**

##### Tool 1: search_youtube_tool
```python
async def search_youtube_tool(
    ctx: RunContext[AgentDependencies],
    keywords: str,  # Comma-separated search terms
    max_shorts: int = 100,
    max_videos: int = 0,
    days_back: Optional[int] = None,
    min_views: Optional[int] = 100000,
    max_subscribers: Optional[int] = 50000
) -> str:
    """
    Search YouTube for viral videos by keyword.

    Use when users want to:
    - Find viral YouTube Shorts about a topic
    - Discover YouTube content by keyword
    - Research what's trending on YouTube
    """
```

**Maps to CLI:** `youtube search --terms "keyword" --max-shorts 100`
**Returns:** Formatted summary with top 5 videos by engagement

##### Tool 2: search_facebook_ads_tool
```python
async def search_facebook_ads_tool(
    ctx: RunContext[AgentDependencies],
    search_url: str,  # Facebook Ad Library search URL
    count: Optional[int] = 50,
    period: str = "last30d"
) -> str:
    """
    Search Facebook Ad Library by URL.

    Use when users want to:
    - Find competitor ads by keyword
    - Research ad strategies
    - Monitor ad spend trends
    """
```

**Maps to CLI:** `facebook search <url> --count 50`
**Returns:** Summary with top ads by spend/impressions

##### Tool 3: scrape_facebook_page_ads_tool
```python
async def scrape_facebook_page_ads_tool(
    ctx: RunContext[AgentDependencies],
    page_url: str,  # Facebook page URL
    count: Optional[int] = 50,
    active_status: str = "all"
) -> str:
    """
    Scrape all ads run by a Facebook page.

    Use when users want to:
    - Analyze competitor ad campaigns
    - Study brand advertising strategies
    - Track page ad history
    """
```

**Maps to CLI:** `facebook page <url> --count 50`
**Returns:** Page ad summary with creative insights

**Estimated Lines:** ~400-500 total (all 3 tools)

#### 4. Update AgentDependencies (`viraltracker/agent/dependencies.py`)

```python
from ..services.youtube_service import YouTubeService
from ..services.facebook_service import FacebookService

@dataclass
class AgentDependencies:
    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    scraping: ScrapingService
    comment: CommentService
    tiktok: TikTokService
    youtube: YouTubeService  # NEW - Phase 1.7
    facebook: FacebookService  # NEW - Phase 1.7
    project_name: str = "yakety-pack-instagram"

    @classmethod
    def create(cls, ...):
        # ...existing service initialization...

        # Initialize YouTubeService
        youtube = YouTubeService()
        logger.info("YouTubeService initialized")

        # Initialize FacebookService
        facebook = FacebookService()
        logger.info("FacebookService initialized")

        return cls(
            # ...existing services...
            youtube=youtube,
            facebook=facebook,
            project_name=project_name
        )
```

#### 5. Register Tools & Update System Prompt (`viraltracker/agent/agent.py`)

**Import tools:**
```python
from .tools_phase17 import (
    search_youtube_tool,
    search_facebook_ads_tool,
    scrape_facebook_page_ads_tool
)
```

**Register tools:**
```python
# Phase 1.7 Tools - YouTube & Facebook Platform Support
agent.tool(search_youtube_tool)
logger.info("Registered tool: search_youtube_tool")

agent.tool(search_facebook_ads_tool)
logger.info("Registered tool: search_facebook_ads_tool")

agent.tool(scrape_facebook_page_ads_tool)
logger.info("Registered tool: scrape_facebook_page_ads_tool")
```

**Update system prompt (lines ~230+):**
```python
**Phase 1.7 - YouTube & Facebook Platform Support:**

14. **search_youtube_tool**: Search YouTube for viral videos
    - Use when user wants to "find YouTube videos", "search YouTube for", "discover viral Shorts"
    - Searches viral YouTube content by keyword
    - Parameters: keywords, max_shorts (default: 100), max_videos (default: 0), days_back, min_views (default: 100K), max_subscribers (default: 50K)
    - Returns: Summary of viral YouTube videos with top performers

15. **search_facebook_ads_tool**: Search Facebook Ad Library
    - Use when user wants to "find Facebook ads", "research competitor ads", "monitor ad spend"
    - Searches ads by keyword via Ad Library URL
    - Parameters: search_url, count (default: 50), period (default: "last30d")
    - Returns: Ad performance summary with spend and reach data

16. **scrape_facebook_page_ads_tool**: Scrape ads from Facebook page
    - Use when user wants to "analyze page ads", "study brand campaigns", "track competitor advertising"
    - Scrapes all ads run by a specific Facebook page
    - Parameters: page_url, count (default: 50), active_status (default: "all")
    - Returns: Page advertising strategy summary
```

#### 6. Create Documentation (`docs/HANDOFF_PHASE_1.7.md`)

Follow the pattern from `HANDOFF_PHASE_1.6.md`:
- What was built (services, tools, models)
- File manifest
- Technical design decisions
- Example usage
- Known limitations
- Next steps

## File Manifest

### New Files (Needed)
```
viraltracker/services/youtube_service.py              (~250 lines) - TODO
viraltracker/services/facebook_service.py             (~300 lines) - TODO
viraltracker/agent/tools_phase17.py                   (~500 lines) - TODO
docs/HANDOFF_PHASE_1.7.md                             (full doc) - TODO
```

### Modified Files (Completed)
```
viraltracker/services/models.py                       (+128 lines) ✅
  - Lines 160-214: YouTubeVideo model
  - Lines 217-290: FacebookAd model
```

### Modified Files (Needed)
```
viraltracker/agent/dependencies.py                    (+20 lines) - TODO
viraltracker/agent/agent.py                           (+40 lines) - TODO
```

## Current Agent Status

**Total Tools:** 13 (8 Twitter + 5 TikTok)
**After Phase 1.7:** 16 tools (8 Twitter + 5 TikTok + 1 YouTube + 2 Facebook)
**Progress to MVP:** 13/16 tools implemented (81%)

## Technical Notes for Continuation

### Key Design Decisions

1. **Service Layer Pattern:** Continue using same pattern as TikTok
   - Lazy initialization of scrapers
   - Async wrappers via `loop.run_in_executor()`
   - Convert DataFrames to Pydantic models
   - Automatic database linking via project_id

2. **Model Design:**
   - YouTubeVideo: Simple engagement model (views/likes/comments)
   - FacebookAd: Complex model with financial + political data
   - Both have computed properties for engagement scoring

3. **Tool Defaults:**
   - YouTube: Default to Shorts (max_shorts=100) since more viral
   - YouTube: Default max_subscribers=50K for micro-influencer content
   - Facebook: Default period="last30d" for recent campaigns
   - Facebook: Default count=50 ads to balance coverage vs speed

### Data Conversion Approach

**Option A (Query DB after scraping):**
- Pro: Scraper handles all DB operations
- Con: Extra DB query, might not get all fields
- Best for: Consistency with existing scrapers

**Option B (Convert DataFrame directly):**
- Pro: No extra DB query, full control over fields
- Con: Need to parse DataFrame carefully
- Best for: Performance, type safety

**Recommendation:** Start with Option A for consistency, optimize with Option B later if needed.

### Testing Strategy

1. **Unit Tests:** Test service methods with mock scrapers
2. **Integration Tests:** Test full tool execution with real Apify calls (requires credits)
3. **Manual Testing:** Use CLI to verify scraper outputs match model expectations

```bash
# Test YouTube scraper
python -m viraltracker.cli.main youtube search --terms "productivity" --max-shorts 10

# Test Facebook scraper
python -m viraltracker.cli.main facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=marketing" --count 10 --save
```

## Known Challenges

1. **YouTube Data Quality:**
   - Some fields may be None (e.g., subscriber_count for private channels)
   - Duration parsing can fail for livestreams
   - Need robust None handling in model

2. **Facebook API Complexity:**
   - Ad Library URL format is complex
   - Many fields are optional or region-dependent
   - Political ads have different data than regular ads

3. **Apify Rate Limits:**
   - YouTube scraper can be slow for large datasets
   - Facebook scraper has strict rate limits
   - Need to handle timeouts gracefully

## Next Developer: Quick Start

To complete Phase 1.7:

1. **Create YouTubeService** (~1 hour)
   - Copy `tiktok_service.py` as template
   - Replace TikTokScraper with YouTubeSearchScraper
   - Update method signatures for YouTube-specific params
   - Convert DataFrame to List[YouTubeVideo]

2. **Create FacebookService** (~1 hour)
   - Similar to YouTubeService
   - Handle both search_ads and scrape_page_ads methods
   - Parse complex JSON fields (snapshot, categories, etc.)

3. **Create tools_phase17.py** (~1-2 hours)
   - Copy tools_phase16.py as template
   - Implement 3 tools following established pattern
   - Format output strings with top results + stats

4. **Update Dependencies & Agent** (~30 min)
   - Add YouTube/Facebook services to AgentDependencies
   - Register 3 tools with agent
   - Update system prompt with tool descriptions

5. **Test & Document** (~1 hour)
   - Run manual tests with CLI first
   - Test agent integration
   - Write HANDOFF_PHASE_1.7.md

**Total Estimated Time:** 4-5 hours to completion

## Example Agent Interactions (After Completion)

```
User: "Find viral YouTube Shorts about productivity"
Agent: [Calls search_youtube_tool("productivity", max_shorts=100, min_views=100000)]
       Returns: "Found 87 viral YouTube Shorts for 'productivity'
                 Total Views: 45.2M | Average Engagement: 6.8%
                 Top 5 videos..."

User: "What ads is Nike running on Facebook?"
Agent: [Calls scrape_facebook_page_ads_tool("https://www.facebook.com/Nike", count=50)]
       Returns: "Scraped 50 ads from Nike
                 Total Spend: $125K | Active Ads: 23
                 Top campaigns..."

User: "Compare viral content across all platforms for 'dog training'"
Agent: [Calls search_twitter_tool, search_tiktok_tool, search_youtube_tool]
       Returns: Cross-platform comparison with insights
```

## Related Documents

- [Phase 1.6 Handoff](./HANDOFF_PHASE_1.6.md) - TikTok implementation (reference)
- [Phase 1.5 Handoff](./HANDOFF_PHASE_1.5.md) - Complete Twitter coverage
- [Phase 1 Handoff](./HANDOFF_PHASE1_TASK16.md) - Original 3-tool implementation

---

**Phase 1.7 Status:** 🚧 MODELS COMPLETE | SERVICES & TOOLS PENDING

**Next Session:** Implement YouTubeService, FacebookService, and 3 agent tools following established patterns.

**Completion Estimate:** 4-5 hours of focused development work.
