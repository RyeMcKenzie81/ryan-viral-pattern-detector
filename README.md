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
