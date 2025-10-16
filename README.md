# ViralTracker

**Multi-platform viral content analysis system for TikTok, Instagram Reels, and YouTube Shorts**

Scrape, process, and analyze short-form video content to identify viral patterns using AI-powered Hook Intelligence analysis.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Quick Start

```bash
# 1. Scrape TikTok videos
./vt tiktok search "dog training" --count 100 --project my-project --save

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
- **YouTube Shorts** - Search and channel scraping

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
│   │   └── youtube.py         # YouTube Shorts
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
├── scorer/                    # Node.js scoring module
├── sql/                       # Database migrations
├── export_hook_analysis_csv.py  # Data export script
└── vt                         # Unified CLI tool
```

---

## Legacy Tools

The repository also includes older tools (retained for compatibility):

- **ryan-viral-pattern-detector/** - Original Instagram scraping tool
- **video-processor/** - Original video processing tool

These have been superseded by the unified `./vt` CLI but remain functional.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Changelog

### 2025-10-16
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
