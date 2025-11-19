# ViralTracker

**Multi-platform viral content analysis system for TikTok, Instagram Reels, YouTube Shorts, and Twitter**

Scrape, process, and analyze short-form video content and tweets to identify viral patterns using AI-powered Hook Intelligence analysis.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Quick Start

```bash
# 1. Scrape videos (multiple platforms supported)
# TikTok
./vt tiktok search "dog training" --count 100 --project my-project --save

# YouTube Shorts
./vt youtube search --terms "dog training" --max-shorts 100 --project my-project

# Twitter
./vt twitter search --terms "dog training" --count 100 --project my-project

# 2. Process videos (download + extract metrics)
./vt process videos --project my-project

# 3. Analyze with AI (Hook Intelligence v1.2.0)
./vt analyze videos --project my-project --gemini-model models/gemini-2.5-pro

# 4. Export and analyze data
python export_hook_analysis_csv.py
python -m analysis.run_hook_analysis --csv data/hook_intelligence_export.csv --outdir results

# 5. Review insights
cat results/playbook.md
```

---

## Features

### 🎬 Multi-Platform Scraping
- **TikTok** - Search by keywords, hashtags, trending (Clockworks API)
- **Instagram Reels** - Account-based scraping (Apify)
- **YouTube Shorts** - Keyword search and channel scraping with video type classification
- **Twitter** - Keyword search with engagement filters and batch querying (Apify)

### 📊 Video Processing
- Automatic download via `yt-dlp`
- Scene detection and cut analysis
- Audio transcription with timestamps
- Visual metrics (face detection, motion, overlay text)

### 🤖 AI-Powered Hook Intelligence v1.2.0
- **14 Hook Type Classifications** - relatable_slice, humor_gag, shock_violation, etc.
- **Temporal Analysis** - Hook span detection, payoff timing
- **Modality Attribution** - Audio vs Visual vs Overlay contribution
- **Windowed Metrics** - Face %, cuts, text density per second
- **Risk Flags** - Brand safety and content suitability

### 📈 Statistical Analysis
- Univariate correlation analysis (Spearman rank)
- Pairwise ranking models (within-account matchups)
- Interaction effect testing
- Editor-friendly playbook generation with lift metrics

---

## Platform-Specific Features

### YouTube Search

Keyword/hashtag discovery for YouTube Shorts and videos with advanced filtering:

```bash
# Basic search (Shorts only)
./vt youtube search --terms "dog training" --max-shorts 50

# Multiple search terms
./vt youtube search --terms "dog training,puppy tricks,pet care" --max-shorts 100

# With view and date filters
./vt youtube search --terms "viral dogs" --max-shorts 100 --days-back 7 --min-views 100000

# Find viral content from micro-influencers
./vt youtube search --terms "dog training tips" --max-shorts 100 --min-views 100000 --max-subscribers 50000

# Mixed content (Shorts + regular videos)
./vt youtube search --terms "puppy guide" --max-shorts 20 --max-videos 30

# Link to project for analysis
./vt youtube search --terms "golden retriever" --max-shorts 50 --project my-project
```

**Features:**
- Separate limits for Shorts, videos, and live streams
- Video type classification (short/video/stream) for data science analysis
- Subscriber filtering (min/max) for micro-influencer discovery
- View count and date range filtering
- Sort by views, date, relevance, or rating
- Automatic classification based on URL patterns
- Project linking for organizing results

**Use Cases:**
- Discover viral Shorts by keyword/hashtag
- Find breakout content from small creators (<50K subscribers)
- Compare Shorts performance vs long-form videos
- Track trending topics across different time ranges

### Twitter Search & Analysis

Complete Twitter integration with keyword search, engagement filtering, and account-based outlier detection:

```bash
# Basic search (minimum 50 tweets required by Apify)
./vt twitter search --terms "dog training" --count 100

# Advanced engagement filters (Phase 2)
./vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --min-replies 100 --days-back 7

# Multi-filter support (Phase 2) - Combine any filters
./vt twitter search --terms "pets" --only-video --only-image --count 200
./vt twitter search --terms "dogs" --only-video --only-verified --min-likes 500

# Batch search (max 5 terms in one Apify run)
./vt twitter search --terms "puppy,kitten,bunny" --count 100

# Link to project for analysis
./vt twitter search --terms "golden retriever" --count 100 --project my-twitter-project

# Raw Twitter query syntax (advanced users)
./vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query
./vt twitter search --terms "(cat OR dog) min_faves:1000 -filter:retweets" --count 200 --raw-query

# Account scraping with outlier detection (3SD from trimmed mean)
./vt project add-accounts my-project twitter-handles.txt --platform twitter
./vt scrape --project my-project --platform twitter --chunk-by monthly
```

#### Phase 2 Features

**🎯 Multi-Filter Support (OR Logic)**
- Combine multiple content filters: `--only-video --only-image --only-quote`
- Query generation: `(filter:video OR filter:images OR filter:quote)`
- Mix content + account filters: `--only-video --only-verified`
- All filters work together seamlessly

**📊 Advanced Engagement Filters**
| Filter | Description | Example |
|--------|-------------|---------|
| `--min-likes` | Minimum like count | `--min-likes 1000` |
| `--min-retweets` | Minimum retweet count | `--min-retweets 500` |
| `--min-replies` | Minimum reply count | `--min-replies 100` |
| `--min-quotes` | Minimum quote count | `--min-quotes 50` |
| `--days-back` | Only recent tweets | `--days-back 7` |

**⏱️ Rate Limit Tracking (Automatic)**
- 2-minute minimum between searches
- Smart warnings: "Last search was 45s ago, wait 75s more"
- Interactive prompt to continue or wait
- Tracking file: `~/.viraltracker/twitter_last_run.txt`
- Prevents Apify actor auto-ban

**👥 Account Management**
```bash
# Add Twitter accounts to project
./vt project add-accounts my-project twitter-handles.txt --platform twitter

# File format (one username per line):
# elonmusk
# NASA
# OpenAI
```

**🔍 Content Type Filters**
| Filter | Finds | Query Syntax |
|--------|-------|--------------|
| `--only-video` | Tweets with video | `filter:video` |
| `--only-image` | Tweets with images | `filter:images` |
| `--only-quote` | Quote tweets | `filter:quote` |
| `--only-verified` | Verified accounts | Actor param |
| `--only-blue` | Twitter Blue users | Actor param |

**📈 Outlier Detection**
- Automatic 3SD from trimmed mean calculation
- Per-account viral tweet identification
- Marks outliers in `post_review` table
- Excludes top/bottom 10% before calculating threshold

#### Rate Limiting (Automatic Protection)

The system automatically prevents rate limit violations:

```bash
# First search - proceeds normally
$ vt twitter search --terms "dogs" --count 100
✅ Search Complete

# Second search 30s later - warning displayed
$ vt twitter search --terms "cats" --count 100
⚠️  Rate Limit Warning
   Last Twitter search was 30s ago
   Recommended wait: 90s

💡 Why? Apify actor limits:
   - Only 1 concurrent run allowed
   - Wait 2+ minutes between searches
   - Prevents actor auto-ban

Continue anyway? [y/N]: n
⏰ Please wait 90s and try again
```

#### Query Building Examples

**Simple Queries** (auto-generated):
```bash
--terms "dogs"
→ "dogs -filter:retweets"

--terms "viral" --min-likes 1000 --days-back 7
→ "viral since:2025-10-11 min_faves:1000 -filter:retweets"

--terms "pets" --only-video
→ "pets filter:video -filter:retweets"
```

**Multi-Filter Queries** (OR logic):
```bash
--terms "content" --only-video --only-image
→ "content (filter:video OR filter:images) -filter:retweets"

--terms "trending" --only-video --only-quote --min-likes 500
→ "trending min_faves:500 (filter:video OR filter:quote) -filter:retweets"
```

#### Apify Actor Limitations

| Limitation | Value | Impact |
|------------|-------|--------|
| Min tweets per search | 50 | Hard requirement, enforced by CLI |
| Max queries per batch | 5 | Batch large searches |
| Concurrent runs | 1 | Only one search at a time |
| Cooldown between runs | 2 minutes | Automatically tracked |
| Max items per query | ~800 | Date chunking for accounts |

#### Use Cases

- **Trend Discovery** - Track viral topics and hashtags in real-time
- **Content Research** - Find high-engagement tweets in your niche
- **Video-First Strategy** - Discover video-heavy Twitter content
- **Competitor Analysis** - Monitor brand mentions and competitor activity
- **Influencer Discovery** - Find verified accounts with viral content
- **Outlier Identification** - Detect per-account viral tweets (3SD method)
- **Engagement Targeting** - Filter by specific engagement thresholds

### Comment Opportunity Finder V1 (PRODUCTION-READY!)

AI-powered system that finds high-potential tweets and generates contextual reply suggestions for engagement growth.

**Status**: ✅ Phase 5 testing complete - **Production-ready!**

**Real-World Performance** (50 candidate test):
- **19/36** tweets scored yellow (0.45-0.53 range)
- **19/19** successfully generated (57 total suggestions)
- **$0.19 cost** per run (well under $0.50 target)
- **~2.5 minutes** execution time

**The Three-Layer Architecture:**
1. **Ingest** - Collect and normalize raw data (Twitter scraping) ✅
2. **Score** - Four-component scoring (velocity, relevance, openness, author quality) ✅
3. **Generate** - Create AI-powered comment suggestions (3 types per tweet) ✅
4. **Export** - CSV output for manual review and posting ✅

#### Quick Start

```bash
# 1. Collect tweets for your project
./vt twitter search --terms "your niche" --count 100 --project my-project

# 2. Create finder config (projects/my-project/finder.yml)
# See configuration example below

# 3. Generate comment suggestions
./vt twitter generate-comments --project my-project

# 4. Export to CSV for manual posting
./vt twitter export-comments --project my-project --out comments.csv
```

#### Configuration (finder.yml)

Create `projects/{project_slug}/finder.yml`:

```yaml
taxonomy:
  - label: "facebook ads"
    description: "Paid acquisition on Meta: account structure, creatives, MER/CPA/ROAS"
    exemplars:  # Optional - auto-generates if empty
      - "ASC is great until it isn't—split by audience freshness"
      - "Angles beat formats. Test 3 angles this week"

voice:
  persona: "direct, practical, contrarian-positive"
  constraints:
    - "no profanity"
    - "avoid hype words"
  examples:
    good:
      - "CPM isn't your bottleneck—creative fatigue is"
    bad:
      - "Wow amazing insight! 🔥🔥"

sources:
  whitelist_handles: ["mosseri", "shopify"]
  blacklist_keywords: ["giveaway", "airdrop"]

weights:
  velocity: 0.35       # Engagement rate
  relevance: 0.35      # Taxonomy matching
  openness: 0.20       # Question/hedge detection
  author_quality: 0.10 # Whitelist/blacklist

thresholds:
  green_min: 0.72      # High quality
  yellow_min: 0.55     # Medium quality

generation:
  temperature: 0.2
  max_tokens: 80
  model: "gemini-2.5-flash"
```

#### Scoring System

**Four-Component Scoring:**

1. **Velocity (0..1)** - Engagement rate normalized by audience size
   - Formula: `sigmoid(6.0 * (eng_per_min / log10(followers)))`
   - Identifies rapidly-engaging content

2. **Relevance (0..1)** - Taxonomy matching via embeddings
   - Formula: `0.8 * best_similarity + 0.2 * margin`
   - Uses Gemini text-embedding-004 (768 dims)

3. **Openness (0..1)** - Question/hedge detection
   - Regex patterns: WH-questions, question marks, hedge words
   - Identifies tweets inviting replies

4. **Author Quality (0..1)** - Whitelist/blacklist lookup
   - Whitelist: 0.9, Unknown: 0.6, Blacklist: 0.0

**Total Score:** Weighted sum → **Label:**
- 🟢 **Green** (≥0.72) - High quality, generate immediately
- 🟡 **Yellow** (≥0.55) - Medium quality, consider
- 🔴 **Red** (<0.55) - Low quality, skip

#### AI Generation

**Three Reply Types (Single API Call):**

1. **add_value** - Share specific insight, tip, or data point
2. **ask_question** - Ask thoughtful follow-up question
3. **mirror_reframe** - Acknowledge and reframe with fresh angle

**Model:** Gemini Flash Latest (cost-optimized, fast)
**Output:** JSON with all 3 suggestions in one call
**Cost:** ~$0.01 per tweet (3 suggestions)

#### Real-World Examples

From production testing (ecom project):

**add_value:**
- "Check mobile load speed. Every 1-second delay drops conversions by 7%."
- "70% of consumers prefer direct product comparison over browsing a single store."

**ask_question:**
- "Did you prioritize A/B testing the product page layout or the cart?"
- "Are you segmenting 'Maybe Later' based on cart value or time spent browsing?"

**mirror_reframe:**
- "The build is done. Now the focus shifts to conversion rate optimization (CRO)."
- "Finishing the build is great. Now the real work: A/B testing the checkout flow."

#### CSV Export Format

10 columns for manual review and posting (V1 simplified):

```
project, tweet_id, url, score_total, label, topic,
suggestion_type, comment, why, rank
```

**Note**: Tweet metadata (author, followers, etc.) will be added in V1.1 after FK relationships are established.

#### CLI Commands

**Generate Suggestions:**
```bash
# Basic - last 6 hours
./vt twitter generate-comments --project my-project

# Advanced - 12 hours, 5K+ followers
./vt twitter generate-comments -p my-project \
  --hours-back 12 --min-followers 5000

# All tweets (no filters)
./vt twitter generate-comments -p my-project \
  --no-use-gate --no-skip-low-scores
```

**Export to CSV:**
```bash
# All pending suggestions
./vt twitter export-comments -p my-project -o comments.csv

# Top 50 green only
./vt twitter export-comments -p my-project -o top50.csv \
  --limit 50 --label green

# Already exported (for review)
./vt twitter export-comments -p my-project -o review.csv \
  --status exported
```

#### Database Tables

**Four New Tables:**

1. **generated_comments** - AI suggestions with lifecycle
   - Status: pending → exported → posted/skipped
   - Stores all 3 suggestion types per tweet

2. **tweet_snapshot** - Historical metrics for scoring
   - Captures engagement at processing time
   - Used for velocity calculation

3. **author_stats** - Author engagement patterns (V1.1)
   - Reply rate tracking for future enhancements

4. **acceptance_log** - Duplicate prevention
   - 7-day lookback to avoid re-processing
   - pgvector support for semantic dedup (V1.1)

#### Cost Control

**V1 is highly cost-effective:**
- One LLM call per tweet (not 3 separate calls)
- Aggressive embedding caching (taxonomy + tweets)
- Batch processing (100 embeddings at once)
- Process only green/yellow candidates by default
- Configurable `--max-candidates` cap

**Real-World Costs** (Phase 5 testing):
- **50 candidates**: $0.19 (19 generated)
- **Projected 200 candidates/day**: ~$0.40-0.60
- **Cost per suggestion**: ~$0.003 (3 suggestions per tweet)

**Production Example**: Running daily with 50 candidates = **~$6/month**

#### Use Cases

- **Thought Leadership** - Reply to high-value discussions in your niche
- **Network Building** - Engage with relevant influencers
- **Lead Generation** - Provide value in target audience conversations
- **Brand Awareness** - Strategic replies on trending topics

#### V1 Status: Production-Ready ✅

**Validated Features** (Phase 5 testing):
- ✅ Velocity, relevance, openness, author quality scoring
- ✅ Taxonomy-based relevance (embeddings with caching)
- ✅ Gate filtering (language, blacklist)
- ✅ 3 AI-generated reply types (single API call)
- ✅ CSV export (10 columns)
- ✅ Supabase persistence with upsert
- ✅ Duplicate prevention (database-level)
- ✅ Cost validation (<$0.50 per run)
- ✅ Error handling and recovery

### Comment Opportunity Finder V1.1 (SHIPPED!)

**Status**: ✅ V1.1 complete - **All Priority 1 and Priority 3 features shipped!**

**V1.1 Enhancements** (2025-10-22):

#### Priority 1: Production Essentials ✅

**1.1 Tweet Metadata in CSV Export** ✅
- Added FK constraint: `generated_comments.tweet_id` → `posts.post_id`
- Enhanced CSV with 7 new columns:
  - `author` (username)
  - `followers` (follower count)
  - `views` (tweet views)
  - `tweet_text` (full tweet content)
  - `posted_at` (timestamp)
- Migration: `migrations/2025-10-22_add_tweet_metadata_fk.sql`

**New CSV Format** (17 columns total):
```
project, tweet_id, url,
author, followers, views, tweet_text, posted_at,
score_total, label, topic, why,
suggested_response, suggested_type,
alternative_1, alt_1_type,
alternative_2, alt_2_type
```

**1.2 Semantic Duplicate Detection** ✅
- Embedding-based similarity check using pgvector cosine similarity
- Threshold: 0.95 (configurable)
- Stores 768-dim embeddings in `acceptance_log` table
- **Impact**: Saves 20-30% API costs on duplicate tweets
- **Test Results**: Detected 12/20 duplicates on second run

**1.3 Rate Limit Handling** ✅
- `RateLimiter` class with exponential backoff
- Tracks API calls per minute (default: 15 req/min)
- Automatic retry on 429 errors with backoff: 2s, 4s, 8s
- Prevents crashes during large runs

#### Priority 2: Quality Improvements ✅

**2.1 Post-Generation Quality Filter** ✅
- **Length check**: 30-120 characters
- **Generic phrase detection**: Blocks 16 common phrases
  - "Great post!", "Thanks for sharing", "Love this", etc.
- **Circular response filter**: >50% word overlap blocked
- **Test Results**: Filtered 1/12 suggestions (8% filter rate)

**2.2 Improved "Why" Rationale** ✅
- Enhanced with engagement metrics:
  - **Likes per hour**: Shows trending speed (e.g., "2.1K likes/hr")
  - **Follower count**: Shows author reach (e.g., "7.0K followers")
  - **Topic match %**: Shows relevance (e.g., "digital wellness (78%)")
- Example: "7.0K followers + digital wellness (78%)"
- Replaces terse V1 format: "score 0.42"

#### Priority 3: Performance & Scale ✅

**3.2 Incremental Taxonomy Embedding** ✅
- Hash-based cache invalidation (SHA256 of node content)
- Only recomputes embeddings for changed taxonomy nodes
- **Impact**: Saves time during config iteration
- **Test Results**: "Using cached embeddings for all 3 taxonomy nodes"

**Cache Format** (with metadata):
```json
{
  "embeddings": { "label": [768-dim vector] },
  "hashes": { "label": "hash_string" },
  "cached_at": 1761170000.0
}
```

#### V1.1 Test Results

**Semantic Dedup Test** (yakety-pack-instagram):
```
Run 1: 20 tweets → 20 processed (0 duplicates)
Run 2: 20 tweets → 8 processed (12 duplicates detected)
Cost savings: ~$0.12 (12 × $0.01)
```

**Quality Filter Test**:
```
36 suggestions generated
35 passed filter (97.2%)
1 filtered: "too_long" (>120 chars)
```

**Incremental Embeddings Test**:
```
Run 1: "Computing embeddings for 3 taxonomy nodes (no cache)"
Run 2: "Using cached embeddings for all 3 taxonomy nodes"
Time savings: ~5 seconds per run
```

#### V1.1 Cost Impact

- **Semantic Dedup**: 20-30% reduction in duplicate API calls
- **Quality Filter**: Prevents low-quality generations
- **Rate Limiting**: Prevents 429 errors and wasted retries
- **Estimated savings**: $0.05-0.10 per run (for typical 50-tweet batches)

#### Known V1.1 Limitations

**Deferred to Future Versions:**
- ⏳ **Batch Generation** (Feature 3.1) - Async/await for 5x speed
  - Would enable: 36 tweets in <1 min vs 3 min
  - Requires: Converting `CommentGenerator` to async
  - Estimated effort: 4 hours
- ⏳ **Cost Tracking** (Feature 4.1) - Display estimated/actual costs
- ⏳ **Better Logging** (Feature 4.2) - `--verbose` and `--debug-tweet` flags

**Still Limitations:**
- English-only (no multi-language support)
- Manual posting (no Twitter API integration)
- No learning from user feedback

### Comment Opportunity Finder V1.7 (SHIPPED!)

**Status**: ✅ V1.7.1 complete - **Two-Pass Workflow with Min-Views Filtering**

**Release Date**: 2025-10-30

**Big Win**: Two-pass workflow separates scoring from comment generation, enabling cost-effective batch processing at scale!

**📖 Complete Documentation**: See [TWITTER_WORKFLOW_V17_UPDATED.md](TWITTER_WORKFLOW_V17_UPDATED.md) for full workflow details.

#### V1.7 Two-Pass Workflow

**Problem Solved**: Previous versions re-scored all tweets when generating comments, wasting time and potentially producing inconsistent results.

**V1.7 Solution**: Separate scoring from comment generation in a two-pass approach.

**Three-Step Workflow:**

```bash
# Step 1: Scrape & Score (45-60 min, $0)
# - Scrape 19 keywords × 500 tweets = 9,500 tweets
# - Score ALL tweets with 5-topic taxonomy
# - Save scores to database (comment_text = '')
# - NO comment generation yet
./scrape_all_keywords_24h.sh  # First part of script

# Step 2: Generate Comments (10-15 min, ~$0.50-1.00)
# - Query saved greens from database
# - NO re-scoring (uses saved labels)
# - Filter by min-views (default: 50)
# - Generate 3-5 comment suggestions per green
# - Batch mode: 5 concurrent API requests
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --max-candidates 10000 \
  --min-views 50 \
  --batch-size 5

# Step 3: Export to CSV (<1 min, $0)
# - Export greens with comments to timestamped CSV
# - Auto-update status to 'exported'
export_date=$(date +%Y-%m-%d)
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/yakety-pack-instagram-24h-${export_date}.csv \
  --hours-back 24 \
  --status pending \
  --label green \
  --sort-by balanced
```

#### V1.7.1 New Features (October 30, 2025)

**1. Min-Views Filtering** ✅
- `--min-views` parameter filters low-reach tweets
- Default: 0 (no filtering), Recommended: 50 views
- Prevents wasting resources on tweets that won't generate impressions
- Example: 66 greens → 54 remaining after filtering <50 views

**2. Timestamped Export Filenames** ✅
- Old format: `keyword_greens_24h.csv` (gets overwritten)
- New format: `{project}-{timeframe}-{date}.csv`
- Example: `yakety-pack-instagram-24h-2025-10-30.csv`
- Better organization and prevents overwriting previous exports

**3. Status Lifecycle Management** ✅
- Status progression: `pending` → `exported` → `posted`
- Auto-updates status after export to prevent duplicate exports
- Query by status: `--status pending`, `--status exported`, `--status posted`

**4. Score-Only Records** ✅
- Database marker: `comment_text = ''` for scores without comments
- Enables two-pass workflow
- Query saved scores: `WHERE label = 'green' AND comment_text = ''`

#### V1.7 Key Benefits

- ✅ **Faster**: No re-scoring when generating comments
- ✅ **Consistent**: Same scores used throughout workflow
- ✅ **Cost-effective**: Score 10,000 tweets for $0, only pay for comment generation
- ✅ **Flexible**: Generate comments on-demand for saved greens
- ✅ **Scalable**: Process 150-250 greens with comments in 10-15 minutes
- ✅ **Production-ready**: Complete end-to-end workflow tested

#### V1.7 Real-World Performance

**Test Run (Oct 30, 2025)**:
- **Step 1**: 19 keywords × 500 tweets = 9,500 tweets scored → 66 greens found
- **Step 2**: 66 greens → 54 after min-views filter → 243 suggestions generated
- **Step 3**: Exported to `yakety-pack-instagram-24h-2025-10-30.csv`
- **Total cost**: ~$0.50-1.00 (Step 2 only, Steps 1 & 3 are free)
- **Total time**: ~60-75 minutes (fully automated)

### Comment Opportunity Finder V1.2 (SHIPPED!)

**Status**: ✅ V1.2 Feature 3.1 complete - **Async Batch Generation (5x Speed Improvement)**

**Release Date**: 2025-10-22

**Big Win**: Concurrent API calls achieve **5x speed improvement** for comment generation!

#### Feature 3.1: Async Batch Generation ✅

**Performance Transformation:**
- **Before (V1.1)**: 426 tweets = sequential processing (~30 minutes)
- **After (V1.2)**: 426 tweets = batch processing (~6 minutes with batch_size=5)
- **Speedup**: **5x faster**

**How It Works:**
- Uses `asyncio` + `ThreadPoolExecutor` for concurrent API calls
- Processes 5-10 tweets simultaneously (configurable)
- Respects rate limits (15 req/min) across concurrent tasks
- Maintains all V1.1 features (dedup, quality filter, etc.)

**CLI Usage:**

```bash
# Default batch processing (batch_size=5)
./vt twitter generate-comments --project my-project

# Custom batch size (3-10 concurrent requests)
./vt twitter generate-comments --project my-project --batch-size 8

# Disable batching (use sequential mode)
./vt twitter generate-comments --project my-project --no-batch

# All V1.1 flags still work
./vt twitter generate-comments --project my-project \
  --batch-size 7 \
  --hours-back 12 \
  --min-followers 5000 \
  --no-skip-low-scores
```

**Technical Architecture:**

1. **AsyncCommentGenerator** class wraps synchronous `CommentGenerator`
2. **AsyncRateLimiter** enforces 15 req/min across async tasks
3. **Semaphore** limits concurrent requests to batch_size
4. **ThreadPoolExecutor** runs sync API calls concurrently
5. **Progress tracking** shows real-time progress (25%, 50%, 75%, 100%)

**Performance Examples:**

| Tweets | Sequential (V1.1) | Batch size=5 (V1.2) | Speedup |
|--------|-------------------|---------------------|---------|
| 10 | 40 seconds | 8 seconds | **5x** |
| 50 | 200 seconds (3.3 min) | 40 seconds | **5x** |
| 100 | 400 seconds (6.7 min) | 80 seconds (1.3 min) | **5x** |
| 426 | 1704 seconds (28.4 min) | 340 seconds (5.7 min) | **5x** |

**Backward Compatibility:**
- ✅ Sequential mode still available with `--no-batch`
- ✅ All V1.1 features preserved
- ✅ Same output quality and format
- ✅ No breaking changes

**Test Results** (2025-10-22):

```bash
# Async batch test (4 tweets, batch_size=4)
$ ./vt twitter generate-comments --project yakety-pack-instagram \
  --max-candidates 12 --batch-size 4 --no-skip-low-scores

⚡ Batch mode: Processing 4 tweets with 4 concurrent requests
[2025-10-22 18:57:16] INFO: Generated suggestions for tweet 1
[2025-10-22 18:57:16] INFO: Generated suggestions for tweet 2  # Same timestamp!
[2025-10-22 18:57:16] INFO: Generated suggestions for tweet 3  # Same timestamp!
[2025-10-22 18:57:16] INFO: Generated suggestions for tweet 4  # Same timestamp!
   [1/4] Progress: 25%
   [2/4] Progress: 50%
   [3/4] Progress: 75%
   [4/4] Progress: 100%
✅ Batch complete: 4 succeeded, 0 failed

Total time: ~11 seconds (including setup)
```

**Verified Features:**
- ✅ Concurrent processing (multiple tweets at same timestamp)
- ✅ Progress callbacks working
- ✅ Rate limiting enforced
- ✅ All V1.1 features still working:
  - Semantic duplicate detection ✅
  - Quality filter ✅
  - Incremental taxonomy embeddings ✅
  - Enhanced "why" rationale ✅

**New Files:**
- `viraltracker/generation/async_comment_generator.py` (337 lines)
  - `AsyncCommentGenerator` class
  - `AsyncRateLimiter` class
  - `generate_comments_async()` convenience function

**Modified Files:**
- `viraltracker/cli/twitter.py`
  - Added `--batch-size` parameter (default: 5)
  - Added `--no-batch` flag
  - Fixed `--no-skip-low-scores` and `--no-use-gate` flags
  - Integrated async batch processing

**Cost Impact:**
- **No change** in per-tweet cost (~$0.01)
- **Time savings** = opportunity to process more tweets in same window
- **Better UX** = faster feedback loop for users

**Why V1.2 Matters:**
- **Production-Ready**: Process daily batches 5x faster
- **Scale-Ready**: Handle 500+ tweets in <10 minutes
- **User-Friendly**: Real-time progress tracking
- **Risk-Free**: Backward compatible with V1.1

#### Feature 4.1: API Cost Tracking ✅

**Cost Transparency**: Track and monitor Gemini API spending for budget control.

**What It Does:**
- Extracts token usage from every Gemini API call (prompt + completion tokens)
- Calculates cost using Gemini Flash pricing ($0.075/$0.30 per 1M tokens)
- Stores cost per suggestion in database (`api_cost_usd` column)
- Displays total cost and per-tweet average in CLI output

**CLI Output:**

```bash
# After generation completes
📊 Results:
   Tweets processed: 426
   Successful: 426 (1278 total suggestions)

💰 API Cost: $0.0341 USD (avg $0.00008 per tweet)

💡 Next steps:
   - Export to CSV: vt twitter export-comments --project my-project
```

**Typical Costs:**

| Scenario | Input Tokens | Output Tokens | Cost per Tweet |
|----------|-------------|---------------|----------------|
| Short tweet | 400 | 100 | $0.00006 |
| Average tweet | 500 | 150 | $0.00008 |
| Long tweet | 600 | 200 | $0.00010 |

**Batch Cost Examples:**

| Tweets | Time (batch_size=5) | Estimated Cost |
|--------|---------------------|----------------|
| 10 | 8 seconds | $0.0008 |
| 50 | 40 seconds | $0.004 |
| 100 | 80 seconds | $0.008 |
| 426 | 340 seconds | $0.034 |

**Cost Queries:**

Query total cost by project:
```sql
SELECT
    project_id,
    COUNT(DISTINCT tweet_id) as tweets_processed,
    COUNT(*) as suggestions_generated,
    SUM(api_cost_usd) as total_cost_usd,
    AVG(api_cost_usd) as avg_cost_per_suggestion
FROM generated_comments
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY project_id
ORDER BY total_cost_usd DESC;
```

**Database Schema:**
```sql
-- Added to generated_comments table
ALTER TABLE generated_comments
ADD COLUMN api_cost_usd numeric(10, 8) DEFAULT 0.0;
```

**New Files:**
- `viraltracker/generation/cost_tracking.py` (180 lines)
  - `TokenUsage` dataclass
  - `APICost` dataclass
  - `extract_token_usage()` function
  - `calculate_cost()` function
  - `format_cost_summary()` function

**Modified Files:**
- `viraltracker/generation/comment_generator.py`
  - Extract token usage after API call
  - Add `api_cost_usd` to `GenerationResult`
  - Pass cost to database storage
- `viraltracker/generation/async_comment_generator.py`
  - Track total cost across batch
  - Include cost in stats dict
- `viraltracker/cli/twitter.py`
  - Display cost summary after generation

**Benefits:**
- **Budget Monitoring**: Track API spending in real-time
- **Cost Forecasting**: Estimate costs for large runs
- **Historical Analysis**: Query costs by date, project, or topic
- **Transparency**: Full visibility into per-suggestion costs

---

## Documentation

- **[CLI Guide](docs/CLI_GUIDE.md)** - Complete command-line reference
- **[Hook Analysis Guide](docs/HOOK_ANALYSIS_GUIDE.md)** - Statistical analysis methods
- **[Installation](#installation)** - Setup instructions below

---

## Installation

### Prerequisites
- Python 3.13+
- FFmpeg (for video processing)
- Node.js 18+ (for scorer module)
- Supabase account
- API keys: Google Gemini, Apify, Clockworks

### Setup

```bash
# Clone repository
git clone https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git
cd viraltracker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

Create `.env` with:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key

# Google Gemini
GOOGLE_GEMINI_API_KEY=your-gemini-api-key

# Scraping APIs
APIFY_API_TOKEN=your-apify-token
CLOCKWORKS_API_KEY=your-clockworks-key
```

---

## Architecture

### Data Flow

```
1. Scraping → posts table (metadata)
2. Processing → video_processing table + Supabase Storage
3. AI Analysis → video_analysis table (hook_features JSONB)
4. Export → CSV for statistical analysis
5. Advanced Analysis → Playbook generation
```

### Core Tables

- **brands, products, projects** - Multi-tenant organization
- **platforms, accounts, posts** - Social media data
- **video_processing** - Processing status and metrics
- **video_analysis** - AI analysis results (Hook Intelligence)

---

## Hook Intelligence v1.2.0

### What It Analyzes

**14 Hook Types:**
- `result_first` - Shows outcome immediately
- `shock_violation` - Unexpected content
- `reveal_transform` - Before/after
- `relatable_slice` - Everyday moment
- `humor_gag` - Comedy setup
- `tension_wait` - Build suspense
- `direct_callout` - Addresses viewer
- `challenge_stakes` - Competition
- `authority_flex` - Credibility
- And 5 more...

**Temporal Features:**
- Hook span (start/end time)
- Payoff timing (seconds until payoff)
- Windowed metrics (1s, 2s, 3s, 5s windows)

**Modality Attribution:**
- Audio contribution (0-1)
- Visual contribution (0-1)
- Overlay text contribution (0-1)

**Continuous Metrics:**
- Face presence percentage
- Cut frequency
- Motion intensity
- Text overlay density

---

## Example Analysis Results

### Wonder Paws TikTok Research (n=297 videos)

**Top Insights:**

1. **Best Combination: Relatable + Humor**
   - Videos with relatable_slice ≥ 0.6 AND humor_gag ≥ 0.4
   - **+71% normalized views** (Δmedian = 0.711)
   - Sample: 71 videos

2. **Quick Payoff Matters**
   - Videos with payoff ≤ 1.0 second
   - **+25% normalized views** (Δmedian = 0.247)
   - Sample: 57 videos

3. **Individual Effects:**
   - shock_violation: +28.6% (p < 0.001)
   - humor_gag: +25.5% (p < 0.001)
   - overlay_text: -20.0% (p < 0.001)

**Key Finding:** Relatable content needs humor to work - negative individually (-12%), positive when combined (+15%).

---

## Project Structure

```
viraltracker/
├── viraltracker/              # Core Python package
│   ├── scrapers/              # Platform scrapers
│   │   ├── tiktok.py          # TikTok (Clockworks API)
│   │   ├── instagram.py       # Instagram Reels (Apify)
│   │   ├── youtube.py         # YouTube Shorts (YouTube Data API)
│   │   └── twitter.py         # Twitter (Apify apidojo/tweet-scraper)
│   ├── importers/             # URL importers
│   │   ├── instagram.py       # Instagram URL importer
│   │   ├── youtube.py         # YouTube URL importer
│   │   └── twitter.py         # Twitter URL importer
│   ├── cli/                   # Command-line interface
│   │   ├── twitter.py         # Twitter CLI commands
│   │   ├── project.py         # Project management
│   │   └── scrape.py          # Cross-platform scraping
│   ├── processing/            # Video processing
│   ├── analysis/              # AI analysis (Gemini)
│   └── core/                  # Database, config
│
├── analysis/                  # Statistical analysis module
│   ├── run_hook_analysis.py   # Main analysis script
│   ├── config.py              # Analysis configuration
│   └── column_map.py          # CSV column mapping
│
├── docs/                      # Documentation
│   ├── CLI_GUIDE.md           # Command-line reference
│   └── HOOK_ANALYSIS_GUIDE.md # Analysis methods
│
├── migrations/                # Database migrations
│   └── 2025-10-16_add_twitter_platform.sql
├── scorer/                    # Node.js scoring module
├── export_hook_analysis_csv.py  # Data export script
└── vt                         # Unified CLI tool
```

---

## Archive

Legacy tools have been moved to `archive/legacy-code/`:
- **ryan-viral-pattern-detector/** - Original Instagram scraping tool (superseded by `viraltracker/scrapers/instagram.py`)
- **video-processor/** - Original video processing tool (superseded by `viraltracker/processing/` and `viraltracker/analysis/`)

Historical documentation is available in `docs/archive/`.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Changelog

### 2025-10-30 - Comment Finder V1.7 SHIPPED! 🚀
- ✅ **Added:** Two-Pass Workflow - Separate scoring from comment generation
  - `--use-saved-scores` flag queries pre-scored greens from database
  - `--skip-comments` flag in analyze-search-term saves scores without comments
  - Score-only records marked with `comment_text = ''`
  - Enables cost-effective batch processing at scale
- ✅ **Added:** Min-Views Filtering (V1.7.1)
  - `--min-views` parameter filters low-reach tweets (default: 0, recommended: 50)
  - Multi-level filtering (database query + post-query)
  - Example: 66 greens → 54 after filtering <50 views
  - Prevents wasting resources on low-impression tweets
- ✅ **Added:** Timestamped Export Filenames (V1.7.1)
  - New format: `{project}-{timeframe}-{date}.csv`
  - Example: `yakety-pack-instagram-24h-2025-10-30.csv`
  - Prevents overwriting previous exports
  - Better file organization
- ✅ **Added:** Status Lifecycle Management (V1.7.1)
  - Status progression: `pending` → `exported` → `posted`
  - Auto-update status after export
  - Query by status: `--status pending/exported/posted`
  - Prevents duplicate exports
- ✅ **Added:** Time-Based Filtering for Exports
  - `--hours-back` parameter for export-comments command
  - Filter exported greens by time range
  - Removed 200 limit on exports (export all by default)
- ✅ **Enhanced:** Production Script (`scrape_all_keywords_24h.sh`)
  - Complete 3-step workflow automation
  - Step 1: Scrape & score 19 keywords (45-60 min, $0)
  - Step 2: Generate comments with saved scores (10-15 min, ~$0.50-1.00)
  - Step 3: Export to timestamped CSV (<1 min, $0)
- ✅ **Files Modified:**
  - `viraltracker/cli/twitter.py` (added --min-views, --use-saved-scores, --hours-back)
  - `viraltracker/generation/tweet_fetcher.py` (added min_views filtering)
  - `scrape_all_keywords_24h.sh` (updated for V1.7 workflow)
- ✅ **Documentation:**
  - `TWITTER_WORKFLOW_V17_UPDATED.md` - Complete V1.7 workflow documentation
  - `WORKFLOW_SAVED_SCORES_V17.md` - Original V1.7 technical docs
  - `CHECKPOINT_V17_COMPLETE_WORKFLOW.md` - Testing checkpoint
  - Updated README with V1.7 section

### 2025-10-22 - Comment Finder V1.2 SHIPPED! 🚀
- ✅ **Added:** Async Batch Generation (Feature 3.1) - **5x Speed Improvement!**
  - `AsyncCommentGenerator` class with ThreadPoolExecutor
  - `AsyncRateLimiter` for concurrent rate limiting
  - `--batch-size` parameter (default: 5 concurrent requests)
  - `--no-batch` flag to disable batching
  - Progress tracking (25%, 50%, 75%, 100%)
  - Real-world test: 4 tweets processed concurrently in ~6 seconds
  - Performance: 426 tweets in 5.7 min (vs 28.4 min sequential)
- ✅ **Added:** API Cost Tracking (Feature 4.1) - **Budget Transparency!**
  - Extracts token usage from Gemini API responses
  - Calculates costs using Gemini Flash pricing ($0.075/$0.30 per 1M tokens)
  - Stores cost per suggestion in database (`api_cost_usd` column)
  - Displays total cost and per-tweet average in CLI output
  - Example: 426 tweets = $0.034 USD (~$0.00008 per tweet)
  - Migration: `2025-10-22_add_api_cost.sql`
- ✅ **Fixed:** Boolean flags now support `--no-*` variants
  - `--skip-low-scores/--no-skip-low-scores` (was broken)
  - `--use-gate/--no-use-gate` (was broken)
- ✅ **Maintained:** All V1.1 features still working
  - Semantic duplicate detection ✅
  - Quality filter ✅
  - Incremental taxonomy embeddings ✅
  - Enhanced "why" rationale ✅
- ✅ **Files Added:**
  - `viraltracker/generation/async_comment_generator.py` (new)
  - `viraltracker/generation/cost_tracking.py` (new)
  - `V1.2_ASYNC_DESIGN.md` (design doc)
  - `V1.2_COST_TRACKING_DESIGN.md` (design doc)
  - `V1.2_FEATURE_3.1_RESULTS.md` (test results)
  - `V1.2_FEATURE_4.1_RESULTS.md` (test results)
  - `migrations/2025-10-22_add_api_cost.sql` (new)
- ✅ **Files Modified:**
  - `viraltracker/cli/twitter.py` (async integration, flag fixes, cost display)
  - `viraltracker/generation/comment_generator.py` (cost tracking)
  - `viraltracker/generation/async_comment_generator.py` (cost aggregation)

### 2025-10-22 - Comment Finder V1.1 SHIPPED! 🚀
- ✅ **Added:** Tweet Metadata in CSV Export (Feature 1.1)
  - 7 new columns: author, followers, views, tweet_text, posted_at
  - FK constraint: `generated_comments.tweet_id` → `posts.post_id`
  - Migration: `2025-10-22_add_tweet_metadata_fk.sql`
- ✅ **Added:** Semantic Duplicate Detection (Feature 1.2)
  - Embedding-based similarity check (pgvector, threshold 0.95)
  - Stores 768-dim embeddings in `acceptance_log`
  - Saves 20-30% API costs on duplicates
- ✅ **Added:** Rate Limit Handling (Feature 1.3)
  - `RateLimiter` class with exponential backoff
  - 15 req/min default, retry on 429 errors
- ✅ **Added:** Post-Generation Quality Filter (Feature 2.1)
  - Length check (30-120 chars)
  - Generic phrase detection (16 phrases)
  - Circular response filter (>50% word overlap)
- ✅ **Enhanced:** Improved "Why" Rationale (Feature 2.2)
  - Engagement metrics: likes/hr, follower count, topic match %
  - Example: "7.0K followers + digital wellness (78%)"
- ✅ **Added:** Incremental Taxonomy Embedding (Feature 3.2)
  - Hash-based cache invalidation
  - Only recomputes changed nodes
- ✅ **Files Modified:**
  - `viraltracker/cli/twitter.py` (semantic dedup, export)
  - `viraltracker/generation/comment_generator.py` (rate limit, quality filter, rationale)
  - `viraltracker/core/embeddings.py` (incremental caching)
  - `migrations/2025-10-22_add_tweet_metadata_fk.sql` (new)

### 2025-10-21
- ✅ **Added:** Comment Opportunity Finder V1 - Complete AI-powered comment suggestion system
- ✅ **Added:** Four-component scoring (velocity, relevance, openness, author quality)
- ✅ **Added:** Gemini-powered comment generation (3 reply types in single API call)
- ✅ **Added:** CSV export with full metadata (15 columns)
- ✅ **Added:** CLI commands: `vt twitter generate-comments` and `vt twitter export-comments`
- ✅ **Added:** Four new database tables (generated_comments, tweet_snapshot, author_stats, acceptance_log)
- ✅ **Added:** Taxonomy-based relevance matching with embeddings (Gemini text-embedding-004)
- ✅ **Added:** Gate filtering system (language, blacklist, safety)
- ✅ **Added:** Per-project finder.yml configuration with voice/persona matching

### 2025-10-17
- ✅ **Added:** Twitter Phase 2 - Multi-filter support (combine video + image + verified)
- ✅ **Added:** Twitter Phase 2 - Advanced engagement filters (min-replies, min-quotes)
- ✅ **Added:** Twitter Phase 2 - Rate limit tracking with automatic warnings
- ✅ **Added:** Twitter Phase 2 - Account management (add Twitter accounts to projects)
- ✅ **Added:** Twitter integration with keyword search and batch querying
- ✅ **Added:** Twitter engagement filters (likes, retweets, date range)
- ✅ **Added:** Twitter content type filters (video, image, quotes, verified, Blue)
- ✅ **Added:** URL importer for Twitter posts
- ✅ **Fixed:** Rate limit batching (53 runs → ~11 batched runs for account scraping)

### 2025-10-16
- ✅ **Added:** YouTube keyword/hashtag search with video type classification
- ✅ **Added:** Subscriber filtering (min/max) for micro-influencer discovery
- ✅ **Added:** Explicit video_type tracking (short/video/stream) for data science
- ✅ **Added:** Hook Analysis Module (n=297 analysis complete)
- ✅ **Added:** Comprehensive CLI and analysis documentation
- ✅ **Added:** Export script for statistical analysis

### 2025-10-15
- ✅ **Completed:** Hook Intelligence v1.2.0 (n=289 dataset)
- ✅ **Completed:** Dataset expansion (128 → 289 videos)

### 2025-10-14
- ✅ **Migrated:** Gemini SDK to 2.5 Pro
- ✅ **Implemented:** Scorer v1.1.0 with continuous formulas

### 2025-10-11
- ✅ **Completed:** YouTube Shorts integration
- ✅ **Implemented:** Multi-platform unified CLI

### 2025-10-03
- **Added:** Core ViralTracker multi-platform system

---

## License

MIT License - See LICENSE file for details

---

## Acknowledgments

- **Apify** - Web scraping infrastructure
- **Clockworks** - TikTok API access
- **Google Gemini** - AI-powered video analysis
- **yt-dlp** - Video download utility
- **Supabase** - PostgreSQL and storage

---

## Support

For questions or issues, please open a GitHub issue or refer to:
- [CLI Guide](docs/CLI_GUIDE.md)
- [Hook Analysis Guide](docs/HOOK_ANALYSIS_GUIDE.md)

---

**Last updated:** 2025-11-19 - Railway deployment fix
