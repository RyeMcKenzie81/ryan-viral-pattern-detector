# CHECKPOINT: YouTube Search Implementation Plan
**Date:** 2025-10-16
**Branch:** `master` (ready for new feature branch)
**Status:** 📋 Planning Complete - Ready to Implement

---

## 🎯 Objective

Implement YouTube search functionality (keyword/hashtag search) using the **`streamers/youtube-scraper`** Apify actor. This will enable TikTok-style discovery for YouTube content, complementing the existing channel scraping functionality.

---

## 📊 Current State

### What We Have ✅
1. **YouTube Channel Scraper** (`viraltracker/scrapers/youtube.py`)
   - Uses `streamers/youtube-shorts-scraper` actor
   - Scrapes specific channels linked to a project
   - Follows Instagram pattern (per-channel outlier detection)
   - **Tested and working** on @animemes-collection

2. **TikTok Search Implementation** (reference for this work)
   - Located in `viraltracker/scrapers/tiktok.py`
   - Has `scrape_search()` method for keyword/hashtag discovery
   - Uses absolute filters (>100K views, <10 days old)
   - Pattern to follow for YouTube search

### What We Need ❌
- YouTube search functionality for keyword/hashtag discovery
- Ability to scrape Shorts/videos/streams by search term
- Filter by upload date, views, length, etc.

---

## 🔧 New Apify Actor: `streamers/youtube-scraper`

### Key Capabilities
1. **Scrape by search term** (what we need!)
2. **Scrape by URL** (channel, playlist, video)
3. **Filter by video type:**
   - Regular videos (set to 0 if not wanted)
   - **Shorts** (set to desired count)
   - Streams (set to 0 if not wanted)
4. **Advanced filters:**
   - Date filters (hour, day, week, month, year)
   - Sorting (relevance, rating, date, views)
   - Length filters (under 4min, 4-20min, 20+min)
   - Quality filters (HD, 4K, 360, HDR, VR180)
   - Other filters (subtitles, creative commons, live, 3D)

### Critical Input Parameters

```json
{
  "searchQueries": ["search term 1", "search term 2"],
  "maxResults": 0,              // Regular videos (0 for shorts-only)
  "maxResultsShorts": 50,       // Number of Shorts to scrape
  "maxResultStreams": 0,        // Streams (0 for shorts-only)

  // Filters
  "sortingOrder": "views",      // relevance, rating, date, views
  "dateFilter": "week",         // hour, today, week, month, year
  "lengthFilter": "under4",     // under4, between420, plus20
  "isHD": true,
  "hasSubtitles": false,

  // Advanced (optional)
  "downloadSubtitles": false,
  "subtitlesLanguage": "en"
}
```

### Output Format

Similar to `youtube-shorts-scraper` but with search metadata:

```json
{
  "id": "VIDEO_ID",
  "title": "Video Title",
  "url": "https://www.youtube.com/shorts/VIDEO_ID",
  "viewCount": 410458,
  "likes": 512238,
  "commentsCount": 14,
  "channelName": "Channel Name",
  "channelUrl": "https://www.youtube.com/@channel",
  "numberOfSubscribers": 6930000,
  "duration": "00:00:26",
  "date": "2021-12-21",
  "text": "Description text...",
  "thumbnailUrl": "https://i.ytimg.com/...",
  "isMonetized": true,
  "commentsTurnedOff": false,
  "fromYTUrl": "https://www.youtube.com/results?search_query=keyword"
}
```

---

## 🏗️ Implementation Plan

### 1. Create New YouTube Search Scraper Class

**File:** `viraltracker/scrapers/youtube_search.py`

**Model after:** `viraltracker/scrapers/tiktok.py` (search functionality)

**Key Methods:**
```python
class YouTubeSearchScraper:
    def __init__(self, apify_token, supabase_client):
        self.apify_actor_id = "streamers/youtube-scraper"

    def scrape_search(
        self,
        search_terms: List[str],
        max_shorts: int = 100,
        max_videos: int = 0,
        max_streams: int = 0,
        days_back: Optional[int] = None,
        min_views: Optional[int] = None,
        sort_by: str = "views",
        project_slug: Optional[str] = None
    ) -> Tuple[int, int]:
        """
        Scrape YouTube by search terms

        Similar to TikTok's scrape_search() but for YouTube
        """
        pass
```

### 2. Key Differences from TikTok Pattern

| Aspect | TikTok | YouTube (New) |
|--------|--------|---------------|
| **Actor** | `clockworks/free-tiktok-scraper` | `streamers/youtube-scraper` |
| **Video Types** | All shorts | Separate counts for shorts/videos/streams |
| **Filters** | Absolute (views, days) | Date ranges + advanced filters |
| **Discovery** | Hashtag + keyword | Search term only |
| **User Scraping** | Yes (per-user outliers) | No (search results only) |

### 3. Integration Points

#### A. CLI Command
**File:** `viraltracker/cli/scrape.py` or new file `viraltracker/cli/youtube.py`

**Pattern:** Follow `viraltracker/cli/tiktok.py` structure

```bash
# Example commands
vt youtube search --terms "dog training,puppy tricks" --max-shorts 100 --project yakety-pack

vt youtube search --terms "viral dogs" --min-views 100000 --days-back 7 --project wonder-paws
```

#### B. Database Schema
**No changes needed!** Existing schema supports this:
- `platforms` table: `youtube_shorts` platform already exists
- `posts` table: Handles all video types
- `project_posts` table: Links videos to projects
- `import_source`: Set to `'search'` instead of `'scrape'`

#### C. Outlier Detection
**Two approaches possible:**

1. **Absolute Filters** (like TikTok):
   - Filter in Apify query (min views, date range)
   - All results treated as viral candidates
   - No statistical outlier detection needed

2. **Statistical Analysis** (like Instagram):
   - Scrape broad set of results
   - Calculate trimmed mean + SD
   - Flag statistical outliers
   - More sophisticated but requires more data

**Recommendation:** Start with **Absolute Filters** (simpler, faster)

---

## 📝 Step-by-Step Implementation

### Step 1: Create Search Scraper Class
```python
# viraltracker/scrapers/youtube_search.py

class YouTubeSearchScraper:
    """
    YouTube search scraper using streamers/youtube-scraper Apify actor

    Enables keyword/hashtag discovery for YouTube Shorts and videos.
    Follows TikTok search pattern with absolute filters.
    """

    def __init__(self, apify_token, supabase_client):
        self.apify_token = apify_token
        self.apify_actor_id = "streamers/youtube-scraper"
        self.supabase = supabase_client
        self.apify_client = ApifyClient(apify_token)

    def scrape_search(
        self,
        search_terms: List[str],
        max_shorts: int = 100,
        max_videos: int = 0,
        max_streams: int = 0,
        days_back: Optional[int] = None,
        min_views: Optional[int] = None,
        sort_by: str = "views",
        project_slug: Optional[str] = None
    ):
        """Scrape YouTube by search terms"""

        # 1. Build Apify input
        actor_input = {
            "searchQueries": search_terms,
            "maxResults": max_videos,
            "maxResultsShorts": max_shorts,
            "maxResultStreams": max_streams,
            "sortingOrder": sort_by  # "views", "date", "relevance", "rating"
        }

        # 2. Add date filter if specified
        if days_back:
            if days_back <= 1:
                actor_input["dateFilter"] = "today"
            elif days_back <= 7:
                actor_input["dateFilter"] = "week"
            elif days_back <= 30:
                actor_input["dateFilter"] = "month"
            else:
                actor_input["dateFilter"] = "year"

        # 3. Start Apify run (use .start() not .call())
        run = self.apify_client.actor(self.apify_actor_id).start(run_input=actor_input)

        # 4. Poll for completion
        result = self._poll_apify_run(run["id"], timeout=300)

        # 5. Fetch dataset
        items = self._fetch_dataset(result["datasetId"])

        # 6. Filter by min_views if specified
        if min_views:
            items = [item for item in items if item.get("viewCount", 0) >= min_views]

        # 7. Normalize data (convert to DataFrame)
        df = self._normalize_items(items)

        # 8. Upsert to database
        post_ids = self._upsert_posts(df, import_source="search")

        # 9. Link to project if specified
        if project_slug:
            project_id = self._get_project_id(project_slug)
            self._link_posts_to_project(post_ids, project_id)

        return (len(search_terms), len(post_ids))
```

### Step 2: Normalize Data
**Key differences from channel scraper:**
- May include regular videos AND shorts
- No channel metadata to extract (search results, not channel scraping)
- Need to handle `fromYTUrl` field (search query that found the video)

```python
def _normalize_items(self, items: List[Dict]) -> pd.DataFrame:
    """Normalize search results to DataFrame"""
    normalized = []

    for item in items:
        # Determine if it's a Short or regular video
        duration_sec = self._parse_duration(item.get("duration", "00:00:00"))
        is_short = duration_sec <= 60  # Shorts are ≤60 seconds

        post_data = {
            "channel": item.get("channelName", ""),
            "post_url": item.get("url", ""),
            "post_id": item.get("id", ""),
            "posted_at": item.get("date"),  # ISO format from Apify
            "views": item.get("viewCount", 0),
            "likes": item.get("likes", 0),
            "comments": item.get("commentsCount", 0),
            "caption": item.get("text", "")[:2200],
            "title": item.get("title", "")[:500],
            "length_sec": duration_sec,
            "is_short": is_short,
            "search_query": item.get("fromYTUrl", "")  # Track which query found it
        }

        normalized.append(post_data)

    return pd.DataFrame(normalized)
```

### Step 3: Add CLI Command
**File:** `viraltracker/cli/youtube.py` (new file)

```python
import click
from ..scrapers.youtube_search import YouTubeSearchScraper

@click.group()
def youtube_group():
    """YouTube-specific scraping commands."""
    pass

@youtube_group.command(name="search")
@click.option("--terms", required=True, help="Comma-separated search terms")
@click.option("--max-shorts", default=100, help="Max Shorts per term")
@click.option("--max-videos", default=0, help="Max regular videos per term")
@click.option("--days-back", type=int, help="Only videos from last N days")
@click.option("--min-views", type=int, help="Minimum view count filter")
@click.option("--sort-by", default="views", help="Sort by: views, date, relevance, rating")
@click.option("--project", help="Link results to project")
def youtube_search(terms, max_shorts, max_videos, days_back, min_views, sort_by, project):
    """
    Search YouTube for videos/shorts by keyword.

    Example:
        vt youtube search --terms "dog training,puppy tricks" --max-shorts 100 --min-views 100000
    """
    search_terms = [t.strip() for t in terms.split(",")]

    scraper = YouTubeSearchScraper(
        apify_token=Config.APIFY_TOKEN,
        supabase_client=get_supabase_client()
    )

    click.echo(f"🔍 Searching YouTube for: {', '.join(search_terms)}")

    terms_count, videos_count = scraper.scrape_search(
        search_terms=search_terms,
        max_shorts=max_shorts,
        max_videos=max_videos,
        days_back=days_back,
        min_views=min_views,
        sort_by=sort_by,
        project_slug=project
    )

    click.echo(f"✅ Scraped {videos_count} videos from {terms_count} search terms")

# Register with main CLI
youtube = youtube_group
```

### Step 4: Register Command in Main CLI
**File:** `viraltracker/cli/main.py`

```python
from .youtube import youtube

cli.add_command(youtube)
```

---

## 🧪 Testing Plan

### Test 1: Basic Search (Shorts Only)
```bash
vt youtube search \
  --terms "dog training" \
  --max-shorts 50 \
  --max-videos 0 \
  --sort-by views
```

**Expected:**
- Scrapes 50 top-viewed Shorts matching "dog training"
- Saves to database with `import_source='search'`
- No project linkage

### Test 2: Search with Filters
```bash
vt youtube search \
  --terms "viral dogs,funny puppies" \
  --max-shorts 100 \
  --days-back 7 \
  --min-views 100000 \
  --sort-by views
```

**Expected:**
- Scrapes up to 100 Shorts per term (200 total)
- Only Shorts from last 7 days
- Only Shorts with 100K+ views
- Sorted by view count

### Test 3: Search + Project Linkage
```bash
vt youtube search \
  --terms "golden retriever" \
  --max-shorts 50 \
  --min-views 500000 \
  --project wonder-paws-tiktok
```

**Expected:**
- Scrapes 50 Shorts with 500K+ views
- Links all results to "wonder-paws-tiktok" project
- Can run outlier detection on project later

### Test 4: Mixed Content (Shorts + Videos)
```bash
vt youtube search \
  --terms "dog training guide" \
  --max-shorts 20 \
  --max-videos 30 \
  --days-back 30
```

**Expected:**
- Scrapes 20 Shorts + 30 regular videos
- All from last 30 days
- Both types saved to database

---

## 📂 Files to Create/Modify

### New Files
1. **`viraltracker/scrapers/youtube_search.py`**
   - Main search scraper class
   - Model after `tiktok.py` structure

2. **`viraltracker/cli/youtube.py`**
   - YouTube-specific CLI commands
   - `youtube search` command

### Modified Files
1. **`viraltracker/cli/main.py`**
   - Register `youtube` command group

### Reference Files (DO NOT MODIFY)
1. **`viraltracker/scrapers/tiktok.py`**
   - Reference for search pattern
   - Reference for `scrape_search()` method

2. **`viraltracker/scrapers/youtube.py`**
   - Reference for YouTube-specific data normalization
   - Reference for Apify actor interaction patterns

---

## 🎓 Key Decisions & Rationale

### 1. Why Separate Class? (`youtube_search.py` vs extending `youtube.py`)
**Decision:** Create separate `YouTubeSearchScraper` class

**Rationale:**
- Different actor (`youtube-scraper` vs `youtube-shorts-scraper`)
- Different use case (discovery vs channel monitoring)
- Different data flow (search results vs channel posts)
- Keeps code clean and maintainable

### 2. Why Absolute Filters? (vs statistical outlier detection)
**Decision:** Use absolute filters (min_views, days_back) like TikTok

**Rationale:**
- Search results are already filtered by relevance/views
- No "baseline" to compare against (unlike per-channel)
- Faster and simpler implementation
- User can set their own viral thresholds

### 3. Why Support Regular Videos? (not just Shorts)
**Decision:** Support shorts, videos, and streams with separate limits

**Rationale:**
- Actor supports all three types
- Some channels have viral long-form content
- Flexibility for future use cases (e.g., tutorial videos)
- Easy to default to Shorts-only (set others to 0)

---

## 🚨 Important Notes

### Actor Differences
```
streamers/youtube-shorts-scraper (current):
- ✅ Scrapes specific channels
- ✅ Only returns Shorts
- ❌ No search functionality

streamers/youtube-scraper (new):
- ✅ Search by keyword/hashtag
- ✅ Shorts + videos + streams
- ✅ Advanced filters
- ⚠️  Different output format (similar but not identical)
```

### Database Considerations
- **No schema changes needed**
- Use existing `youtube_shorts` platform for Shorts
- May need to add `youtube` platform for regular videos (optional)
- Set `import_source='search'` to distinguish from channel scrapes

### Rate Limits
- Apify actor usage is metered
- Consider costs for large searches
- Recommend starting with small `max_shorts` values (50-100)

---

## 🔗 Reference Links

**Apify Actor:**
- Actor: `streamers/youtube-scraper`
- URL: https://apify.com/streamers/youtube-scraper

**Existing Code:**
- TikTok search: `viraltracker/scrapers/tiktok.py` (lines 200-400)
- YouTube channel: `viraltracker/scrapers/youtube.py`
- TikTok CLI: `viraltracker/cli/tiktok.py`

**Database:**
- Platforms table: `youtube_shorts` platform ID already exists
- Posts table: Accepts all video types
- project_posts: Links videos to projects

---

## ✅ Success Criteria

Implementation is complete when:
1. ✅ `vt youtube search` command works
2. ✅ Can scrape Shorts by keyword/hashtag
3. ✅ Can filter by views, date, etc.
4. ✅ Results save to database correctly
5. ✅ Can link results to projects
6. ✅ All 4 test cases pass

---

## 📋 Implementation Checklist

- [ ] Create `viraltracker/scrapers/youtube_search.py`
- [ ] Implement `YouTubeSearchScraper` class
- [ ] Implement `scrape_search()` method
- [ ] Implement `_normalize_items()` for search results
- [ ] Implement `_upsert_posts()` with `import_source='search'`
- [ ] Create `viraltracker/cli/youtube.py`
- [ ] Implement `youtube search` command
- [ ] Register command in `main.py`
- [ ] Test: Basic search (Shorts only)
- [ ] Test: Search with filters (views, date)
- [ ] Test: Search + project linkage
- [ ] Test: Mixed content (Shorts + videos)
- [ ] Document in README.md
- [ ] Create checkpoint document
- [ ] Commit to feature branch
- [ ] Merge to master

---

**Status:** 📋 Ready to implement in fresh context window
**Estimated Effort:** 2-3 hours
**Branch Strategy:** Create `feature/youtube-search` branch

