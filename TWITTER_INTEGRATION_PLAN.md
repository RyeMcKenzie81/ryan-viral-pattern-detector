# Twitter Integration Implementation Plan

**Date:** 2025-10-16
**Actor:** `apidojo/tweet-scraper`
**Phase:** Phase 1 - Core Implementation

---

## 🎯 Objectives

Implement Twitter scraping with two modes:
1. **Search Mode** - Keyword/hashtag discovery for viral content
2. **Account Mode** - Per-account scraping with statistical outlier detection (3SD from trimmed mean)

Following the **TikTok pattern** for consistency with existing platform integrations.

---

## 📊 Requirements Summary

### Content Strategy
- ✅ **All content types**: Text, images, videos, quotes (no default filtering)
- ✅ **Platform name**: `twitter` (simple, recognizable)
- ✅ **Video type**: All tweets use `video_type: "post"` (Twitter doesn't have Shorts/long-form distinction)

### Implementation Modes
- ✅ **Search**: Keyword/hashtag discovery via Twitter queries
- ✅ **Account Scraping**: Per-account with outlier detection (TikTok pattern)
- ✅ **URL Import**: Direct tweet URL imports (completes feature set)

### CLI Design
- ✅ **Pattern**: Follow TikTok structure
  - `vt twitter search` - Keyword/hashtag search
  - `vt scrape --platform twitter` - Account scraping
  - `vt import url <tweet-url>` - Direct tweet import

### Query Handling
- ✅ **Simple mode**: Build Twitter queries automatically from user input
- ✅ **Advanced mode**: `--raw-query` flag for users who know Twitter query syntax
- ✅ **Batching**: Batch up to 5 queries per Apify run (actor limit)

### Date Chunking
- ✅ **Auto-chunking**: Monthly chunks by default for account scraping
- ✅ **Override**: `--chunk-by` flag (monthly/weekly/daily) for power users
- ✅ **Reason**: Actor returns ~800 tweets per query, chunking ensures complete history

### Filtering (Phase 1)
- ✅ **Inclusion filters only**: `--only-video`, `--only-image`, `--only-quote`, `--only-verified`, `--only-blue`
- ✅ **Single filter**: Only one `--only-X` flag allowed in Phase 1
- ⏳ **Phase 2**: Multi-filter support with OR logic (requires query merging)

### Rate Limiting & Safety
- ✅ **Minimum tweets**: Enforce 50-tweet minimum (hard requirement, prevents auto-ban)
- ✅ **Default count**: 100 tweets (safe default above minimum)
- ✅ **Concurrent runs**: Respect actor's 1 concurrent run limit
- ✅ **Batch size**: Max 5 queries per batch (actor limit)

---

## 🏗️ Technical Architecture

### Database Schema

#### Platform Entry
```sql
INSERT INTO platforms (name, slug, scraper_config) VALUES (
  'Twitter',
  'twitter',
  '{
    "actor_id": "apidojo/tweet-scraper",
    "default_post_type": "tweet",
    "supports_search": true,
    "supports_account_scraping": true
  }'::jsonb
);
```

#### Tweet Data Mapping
```python
# Actor output → Database mapping
{
  "id": "1728108619189874825",                    # → posts.platform_post_id
  "url": "https://x.com/elonmusk/status/...",     # → posts.post_url
  "text": "Tweet content...",                      # → posts.caption
  "retweetCount": 11311,                          # → posts.shares
  "replyCount": 6526,                             # → posts.comments
  "likeCount": 104121,                            # → posts.likes
  "quoteCount": 2915,                             # → Additional metadata
  "bookmarkCount": 702,                           # → Additional metadata
  "createdAt": "Fri Nov 24 17:49:36 +0000 2023", # → posts.posted_at
  "lang": "en",                                   # → Additional metadata
  "isReply": false,                               # → Additional metadata
  "isRetweet": false,                             # → Additional metadata
  "isQuote": true,                                # → Additional metadata
  "author": {
    "userName": "elonmusk",                       # → accounts.platform_username
    "name": "Elon Musk",                          # → accounts.display_name
    "followers": 172669889,                       # → accounts.follower_count
    "isVerified": true,                           # → accounts.is_verified
    "profilePicture": "...",                      # → accounts.profile_picture_url
    "description": "...",                         # → accounts.bio
    # ... more author fields
  }
}
```

#### New Fields for Twitter
```python
# posts.platform_specific_data (JSONB) will store:
{
  "retweetCount": int,
  "quoteCount": int,
  "bookmarkCount": int,
  "isReply": bool,
  "isRetweet": bool,
  "isQuote": bool,
  "lang": str,
  "source": str  # e.g., "Twitter for iPhone"
}
```

---

## 📁 File Structure

```
viraltracker/
├── scrapers/
│   └── twitter.py              # NEW - Twitter scraper (search + account)
├── importers/
│   └── twitter.py              # NEW - Twitter URL importer
├── cli/
│   ├── twitter.py              # NEW - Twitter CLI commands
│   └── scrape.py               # MODIFY - Add Twitter to platform options
└── core/
    └── models.py               # VERIFY - Ensure schema supports Twitter data
```

---

## 🔧 Implementation Details

### 1. Twitter Scraper Class (`viraltracker/scrapers/twitter.py`)

```python
class TwitterScraper:
    """
    Twitter scraper using apidojo/tweet-scraper Apify actor.

    Supports:
    - Keyword/hashtag search
    - Account scraping with outlier detection
    - Date range chunking for complete history
    - Batch query processing
    """

    def __init__(self, apify_token, supabase_client):
        self.apify_actor_id = "apidojo/tweet-scraper"
        # ... initialization

    # SEARCH MODE
    def scrape_search(
        self,
        search_terms: List[str],
        max_tweets: int = 100,
        min_likes: Optional[int] = None,
        min_retweets: Optional[int] = None,
        days_back: Optional[int] = None,
        only_video: bool = False,
        only_image: bool = False,
        only_quote: bool = False,
        only_verified: bool = False,
        only_blue: bool = False,
        raw_query: bool = False,
        project_slug: Optional[str] = None
    ) -> Tuple[int, int]:
        """
        Search Twitter by keywords/hashtags.

        If raw_query=False:
          - Builds Twitter query from search_terms + filters
          - Example: "dog training" + days_back=7 → "dog training since:2024-10-09"

        If raw_query=True:
          - Uses search_terms as-is (user provides full Twitter query)
          - Example: "from:NASA filter:video min_faves:10"

        Batches up to 5 queries per Apify run.
        """
        pass

    # ACCOUNT MODE
    def scrape_accounts(
        self,
        project_id: str,
        max_tweets_per_account: int = 500,
        days_back: Optional[int] = None,
        chunk_by: str = "monthly"  # monthly, weekly, daily
    ) -> Dict[str, int]:
        """
        Scrape accounts linked to project with outlier detection.

        Similar to TikTok pattern:
        1. Get accounts linked to project
        2. Chunk date ranges (monthly by default, ~800 tweets per chunk)
        3. Scrape all tweets for each account
        4. Calculate 3SD outliers per account
        5. Mark outliers in post_review table

        Args:
            chunk_by: How to chunk date ranges
              - "monthly": 1-month chunks (default, ~800 tweets/query)
              - "weekly": 1-week chunks (for high-volume accounts)
              - "daily": 1-day chunks (for extremely high-volume accounts)
        """
        pass

    # HELPER METHODS
    def _build_twitter_query(
        self,
        search_term: str,
        min_likes: Optional[int],
        min_retweets: Optional[int],
        days_back: Optional[int],
        only_video: bool,
        only_image: bool,
        only_quote: bool
    ) -> str:
        """
        Build Twitter query from parameters.

        Examples:
          "dog training" + days_back=7 + min_likes=1000
          → "dog training since:2024-10-09 min_faves:1000"

          "puppy" + only_video=True
          → "puppy filter:video"
        """
        pass

    def _chunk_date_ranges(
        self,
        start_date: datetime,
        end_date: datetime,
        chunk_by: str
    ) -> List[Tuple[datetime, datetime]]:
        """
        Chunk date range to respect 800-tweet limit per query.

        Example (monthly):
          2023-01-01 to 2023-12-31
          → [(2023-01-01, 2023-02-01), (2023-02-01, 2023-03-01), ...]
        """
        pass

    def _normalize_tweets(self, items: List[Dict]) -> pd.DataFrame:
        """Normalize Apify output to DataFrame for database insertion."""
        pass

    def _upsert_accounts(self, df: pd.DataFrame) -> None:
        """Upsert Twitter accounts to database."""
        pass

    def _upsert_posts(
        self,
        df: pd.DataFrame,
        import_source: str = "search"
    ) -> List[str]:
        """Upsert tweets to database."""
        pass

    def _calculate_outliers(
        self,
        account_id: str,
        threshold_sd: float = 3.0
    ) -> List[str]:
        """Calculate statistical outliers (3SD from trimmed mean)."""
        pass
```

---

### 2. Twitter URL Importer (`viraltracker/importers/twitter.py`)

```python
class TwitterURLImporter(BaseURLImporter):
    """
    Import individual tweets by URL.

    Supported formats:
    - https://twitter.com/username/status/1234567890
    - https://x.com/username/status/1234567890
    """

    def __init__(self, supabase_client):
        super().__init__(
            platform_slug="twitter",
            supabase_client=supabase_client
        )

    def validate_url(self, url: str) -> bool:
        """Validate Twitter/X tweet URL."""
        patterns = [
            r"^https?://(www\.)?(twitter|x)\.com/\w+/status/\d+",
        ]
        return any(re.match(p, url) for p in patterns)

    def extract_post_id(self, url: str) -> str:
        """Extract tweet ID from URL."""
        match = re.search(r"/status/(\d+)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract tweet ID from {url}")
```

---

### 3. Twitter CLI Commands (`viraltracker/cli/twitter.py`)

```python
@click.group(name="twitter")
def twitter_group():
    """Twitter scraping and analysis"""
    pass


@twitter_group.command(name="search")
@click.option('--terms', required=True, help='Comma-separated search terms')
@click.option('--count', default=100, type=int, help='Tweets per term (min: 50, default: 100)')
@click.option('--min-likes', type=int, help='Minimum like count')
@click.option('--min-retweets', type=int, help='Minimum retweet count')
@click.option('--days-back', type=int, help='Only tweets from last N days')
@click.option('--only-video', is_flag=True, help='Only tweets with video')
@click.option('--only-image', is_flag=True, help='Only tweets with images')
@click.option('--only-quote', is_flag=True, help='Only quote tweets')
@click.option('--only-verified', is_flag=True, help='Only verified users')
@click.option('--only-blue', is_flag=True, help='Only Twitter Blue users')
@click.option('--raw-query', is_flag=True, help='Use raw Twitter query syntax')
@click.option('--project', '-p', help='Project slug to link results')
def twitter_search(
    terms: str,
    count: int,
    min_likes: Optional[int],
    min_retweets: Optional[int],
    days_back: Optional[int],
    only_video: bool,
    only_image: bool,
    only_quote: bool,
    only_verified: bool,
    only_blue: bool,
    raw_query: bool,
    project: Optional[str]
):
    """
    Search Twitter by keywords/hashtags

    Examples:
        # Basic search
        vt twitter search --terms "dog training" --count 100

        # With filters
        vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7

        # Video only
        vt twitter search --terms "puppy videos" --count 150 --only-video

        # Advanced query (raw)
        vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query

        # Link to project
        vt twitter search --terms "golden retriever" --count 100 --project wonder-paws
    """
    # Validate minimum
    if count < 50:
        click.echo("❌ Error: Minimum 50 tweets required (actor limitation)", err=True)
        click.echo("💡 Tip: Use --count 50 or higher", err=True)
        raise click.Abort()

    # Validate single filter in Phase 1
    filters = [only_video, only_image, only_quote, only_verified, only_blue]
    if sum(filters) > 1:
        click.echo("❌ Error: Only one --only-* filter allowed in Phase 1", err=True)
        click.echo("💡 Coming in Phase 2: Multi-filter support", err=True)
        raise click.Abort()

    # Parse search terms
    search_terms = [t.strip() for t in terms.split(',')]

    # Display summary
    click.echo(f"\n{'='*60}")
    click.echo(f"🐦 Twitter Search")
    click.echo(f"{'='*60}\n")
    click.echo(f"Search terms: {', '.join(search_terms)}")
    click.echo(f"Tweets per term: {count}")

    # ... scraping logic
```

---

### 4. Update Scrape CLI (`viraltracker/cli/scrape.py`)

```python
# Extend existing scrape command to support Twitter

@scrape_command.command(name="scrape")
@click.option('--platform',
    type=click.Choice(['instagram', 'youtube_shorts', 'twitter']),  # Add twitter
    help='Platform to scrape')
@click.option('--chunk-by',
    type=click.Choice(['monthly', 'weekly', 'daily']),
    default='monthly',
    help='Date chunking for Twitter (default: monthly)')
# ... existing options
def scrape(platform, chunk_by, ...):
    """
    Scrape accounts linked to project with outlier detection

    Examples:
        # Twitter account scraping
        vt scrape --project my-twitter-project --platform twitter

        # With custom chunking
        vt scrape --project high-volume-accounts --platform twitter --chunk-by weekly
    """
    # ... handle Twitter case
```

---

## 🧪 Testing Plan

### Phase 1: Core Implementation Tests

#### Test 1: Basic Search
```bash
vt twitter search --terms "dog training" --count 100 --project test-twitter
```
**Expected:**
- Scrapes 100 tweets matching "dog training"
- Saves to database with `import_source='search'`
- Links to project

#### Test 2: Search with Filters
```bash
vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7 --only-video
```
**Expected:**
- Scrapes tweets from last 7 days
- Only tweets with 1000+ likes
- Only tweets with video
- Respects 200 tweet limit

#### Test 3: Raw Query
```bash
vt twitter search --terms "from:NASA filter:video min_faves:100" --count 500 --raw-query
```
**Expected:**
- Uses query as-is (no modification)
- Scrapes NASA's video tweets with 100+ likes

#### Test 4: Account Scraping
```bash
# First, add accounts to project via SQL or future CLI
vt scrape --project test-twitter --platform twitter
```
**Expected:**
- Scrapes all tweets for accounts linked to project
- Chunks date ranges automatically (monthly)
- Calculates 3SD outliers per account
- Marks outliers in post_review table

#### Test 5: URL Import
```bash
vt import url https://twitter.com/elonmusk/status/1728108619189874825 --project test-twitter
```
**Expected:**
- Saves tweet URL to database
- Links to project
- Ready for metadata population via scraper

#### Test 6: Batch Query
```bash
vt twitter search --terms "puppy,kitten,bunny" --count 100
```
**Expected:**
- Batches 3 queries into single Apify run
- Scrapes 100 tweets per term (300 total)

#### Test 7: Error Handling
```bash
# Test minimum enforcement
vt twitter search --terms "test" --count 25
```
**Expected:**
- ❌ Error message about 50-tweet minimum
- Aborts before calling Apify

#### Test 8: Date Chunking
```bash
# Account with lots of tweets
vt scrape --project high-volume-twitter --platform twitter --chunk-by weekly
```
**Expected:**
- Chunks into weekly date ranges
- Multiple queries per account
- Complete tweet history retrieved

---

## 📈 Success Criteria

### Phase 1 Complete When:
- ✅ `vt twitter search` works with all basic filters
- ✅ `vt scrape --platform twitter` works with outlier detection
- ✅ `vt import url` works for tweet URLs
- ✅ All 8 tests pass
- ✅ Data saves correctly to database
- ✅ Accounts and tweets properly linked
- ✅ 50-tweet minimum enforced
- ✅ Query batching works (5 queries max)
- ✅ Date chunking works for account scraping

### Phase 2 (Future):
- ⏳ Multi-filter support (OR logic)
- ⏳ Advanced filters (geotagging, mentions, replies, etc.)
- ⏳ CLI for adding Twitter accounts to projects
- ⏳ Better error messages for Apify rate limits
- ⏳ Support for Twitter Lists

---

## 🚨 Important Actor Limitations

### Rate Limiting (Critical)
- ✅ **Max 1 concurrent run** - Enforce in code
- ✅ **Max 5 queries batched** - Enforce in code
- ✅ **Couple minutes between runs** - Document, don't enforce (hard to track)
- ✅ **Min 50 tweets per query** - Enforce with hard minimum

### Forbidden Actions
- ❌ **Monitoring/real-time use** - Document clearly in CLI help
- ❌ **Single tweet fetching** - Allow via `import url` only (uses startUrls, not searchTerms)
- ❌ **Undeterministic queries** - Warn about using too-specific filters

### Cost Considerations
- **$0.30 per 1,000 tweets** on paid plans
- **Much higher** on free plans (demo mode)
- Users should be aware of costs before large scrapes

---

## 📝 Actor Input Mapping

### Search Mode
```python
actor_input = {
    "searchTerms": ["dog training", "puppy tricks"],  # Batch up to 5
    "maxItems": 100,                                  # Per search term
    "sort": "Latest",                                 # or "Top"
    "tweetLanguage": "en",                           # Optional

    # Filters (optional)
    "onlyVideo": True,                               # --only-video
    "onlyImage": True,                               # --only-image
    "onlyQuote": True,                               # --only-quote
    "onlyVerifiedUsers": True,                       # --only-verified
    "onlyTwitterBlue": True,                         # --only-blue
    "minimumFavorites": 1000,                        # --min-likes
    "minimumRetweets": 500,                          # --min-retweets
    "start": "2024-10-09",                          # Calculated from --days-back
    "end": "2024-10-16",                            # Today

    # Advanced (not in Phase 1)
    # "author": "NASA",
    # "geocode": "37.7749,-122.4194,10mi",
    # "geotaggedNear": "San Francisco",
    # etc.
}
```

### Account Mode (Date Chunking)
```python
# Example: Scrape @NASA tweets from 2023
search_queries = [
    "from:NASA since:2023-01-01 until:2023-02-01",  # Jan
    "from:NASA since:2023-02-01 until:2023-03-01",  # Feb
    "from:NASA since:2023-03-01 until:2023-04-01",  # Mar
    # ... etc
]

actor_input = {
    "searchTerms": search_queries[:5],  # Batch max 5
    "maxItems": 1000,                   # High limit (will get ~800/query)
    "sort": "Latest"
}
```

### URL Import Mode
```python
actor_input = {
    "startUrls": [
        "https://twitter.com/elonmusk/status/1728108619189874825"
    ]
}
```

---

## 🎨 CLI Help Examples

```bash
$ vt twitter search --help

Usage: vt twitter search [OPTIONS]

  Search Twitter by keywords/hashtags

Options:
  --terms TEXT            Comma-separated search terms [required]
  --count INTEGER         Tweets per term (min: 50, default: 100)
  --min-likes INTEGER     Minimum like count
  --min-retweets INTEGER  Minimum retweet count
  --days-back INTEGER     Only tweets from last N days
  --only-video            Only tweets with video
  --only-image            Only tweets with images
  --only-quote            Only quote tweets
  --only-verified         Only verified users
  --only-blue             Only Twitter Blue users
  --raw-query             Use raw Twitter query syntax
  --project, -p TEXT      Project slug to link results
  --help                  Show this message and exit

Examples:
  # Basic search
  vt twitter search --terms "dog training" --count 100

  # With filters
  vt twitter search --terms "viral dogs" --count 200 \\
    --min-likes 1000 --days-back 7 --only-video

  # Advanced query
  vt twitter search --terms "from:NASA filter:video" \\
    --count 500 --raw-query

Note: Phase 1 allows only ONE --only-* filter at a time.
      Multi-filter support coming in Phase 2.
```

---

## 📚 Twitter Query Reference

For `--raw-query` mode, users can use Twitter's advanced search syntax:

### Common Operators
```
from:USERNAME           # Tweets from specific user
to:USERNAME            # Replies to specific user
@USERNAME              # Mentions of user
#HASHTAG               # Hashtag search
"exact phrase"         # Exact phrase match
word1 OR word2         # Either word
word1 -word2           # Exclude word2
```

### Filters
```
filter:media           # Has media (image or video)
filter:images          # Has images
filter:video           # Has video
filter:links           # Has links
filter:retweets        # Only retweets
-filter:retweets       # Exclude retweets
filter:replies         # Only replies
-filter:replies        # Exclude replies
filter:verified        # Only verified users
```

### Engagement
```
min_faves:100          # Minimum likes
min_retweets:50        # Minimum retweets
min_replies:10         # Minimum replies
```

### Dates
```
since:2024-01-01       # After date
until:2024-12-31       # Before date
```

### Location
```
geocode:LAT,LONG,RADIUS   # Near location
place:PLACE_ID            # Tagged location
```

**Full reference**: https://github.com/igorbrigadir/twitter-advanced-search

---

## 🔄 Implementation Order

1. ✅ **Document plan** (this file)
2. **Create database migration** - Add Twitter platform
3. **Create `twitter.py` scraper** - Core functionality
4. **Create `twitter.py` importer** - URL imports
5. **Create `twitter.py` CLI** - Commands
6. **Update `scrape.py`** - Add Twitter platform option
7. **Test search mode** - Tests 1-3, 6-7
8. **Test account mode** - Tests 4, 8
9. **Test URL import** - Test 5
10. **Documentation** - Update README.md
11. **Commit & merge** - Complete Phase 1

---

## 💡 Future Enhancements (Phase 2)

### Advanced Filters
- Geotagging (`--near`, `--within-radius`, `--geocode`)
- User targeting (`--author`, `--in-reply-to`, `--mentioning`)
- Advanced engagement (`--min-replies`, `--min-quotes`)
- Place filtering (`--place`)

### Multi-Filter Support
```bash
# Phase 2: OR logic for multiple content types
vt twitter search --terms "pets" --only-video --only-image --count 200
# Would merge results from 2 queries: video tweets + image tweets
```

### Account Management
```bash
# CLI for adding Twitter accounts to projects
vt project add-accounts my-project --platform twitter --file accounts.txt
```

### Twitter Lists
```bash
# Scrape from Twitter Lists
vt twitter list https://twitter.com/i/lists/1234567890 --count 500
```

### Better Rate Limit Handling
- Track time between runs
- Warn if running too frequently
- Implement exponential backoff

---

## ✅ Ready to Implement

This plan provides:
- ✅ Clear technical specifications
- ✅ Actor integration details
- ✅ Database schema
- ✅ CLI design with examples
- ✅ Comprehensive testing plan
- ✅ Safety guardrails (rate limits, minimums)
- ✅ Phase 1/2 separation for iterative development

**Next Step**: Create feature branch and begin implementation!

```bash
git checkout -b feature/twitter-integration
```
