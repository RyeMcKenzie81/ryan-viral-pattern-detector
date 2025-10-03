# ViralTracker Toolkit

A comprehensive toolkit for analyzing viral Instagram content and adapting strategies for content creators.

## Tools

### 1. Ryan's Viral Pattern Detector (`ryan-viral-pattern-detector/`)

**Purpose:** Scrape Instagram posts, analyze viral patterns, and export data for review

**Key Features:**
- Instagram scraping via Apify API
- Statistical outlier detection (trimmed mean/SD methodology)
- Multiple export formats (CSV for downloads, VA review, JSONL for AI)
- Review workflow for manual content decisions
- Supabase database integration
- Railway deployment ready

**Main Commands:**
```bash
python ryan_vpd.py scrape      # Scrape Instagram data
python ryan_vpd.py analyze     # Flag outliers using statistical analysis
python ryan_vpd.py export      # Export data in multiple formats
python ryan_vpd.py import-review   # Import VA review decisions
```

**Status:** ✅ Production Ready

---

### 2. Video Processor (`video-processor/`)

**Purpose:** Download viral videos, analyze with AI, and generate content adaptations

**Key Features:**

**Phase 1 - Video Processing (✅ Completed):**
- Downloads Instagram videos using yt-dlp
- Uploads to Supabase Storage
- Database tracking with processing logs
- 100% success rate (104 videos processed)

**Phase 2 - AI Analysis (✅ Completed):**
- Gemini AI-powered video analysis
- Hook analysis (first 3-5 seconds)
- Full transcription with timestamps
- Visual storyboard extraction
- Viral factors scoring
- Pattern matching

**Phase 3 - Yakety Pack Adaptation (✅ Completed):**
- Evaluates viral videos for product adaptation potential
- Generates production-ready video scripts
- Creates shot-by-shot storyboards with timestamps
- Scores videos on 4 criteria (hook relevance, audience match, transition ease, viral replicability)
- Outputs: `yakety_pack_evaluations.json` and `YAKETY_PACK_RECOMMENDATIONS.md`

**Main Commands:**
```bash
# Video Processing
python video_processor.py process --unprocessed-outliers
python video_processor.py status

# AI Analysis
python video_analyzer.py analyze

# Yakety Pack Adaptation
python yakety_pack_evaluator.py
python aggregate_analyzer.py
```

**Status:** ✅ Production Ready

---

## Workflow

1. **Scrape Instagram Data** → `ryan-viral-pattern-detector`
2. **Analyze & Flag Outliers** → `ryan-viral-pattern-detector`
3. **Download Videos** → `video-processor`
4. **AI Video Analysis** → `video-processor`
5. **Generate Adaptations** → `video-processor`
6. **Review & Select** → Manual review of recommendations
7. **Produce Content** → Film following generated scripts/storyboards

See `video-processor/WORKFLOW.md` for detailed workflow documentation.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Supabase account
- Apify account with API token
- Gemini API key

### Setup

1. **Clone and setup Ryan's Viral Pattern Detector:**
```bash
cd ryan-viral-pattern-detector
cp .env.example .env
# Edit .env with your credentials
pip install -r requirements.txt
```

2. **Setup Video Processor:**
```bash
cd video-processor
cp .env.example .env
# Edit .env with your credentials
pip install -r requirements.txt
```

3. **Run the complete pipeline:**
```bash
# 1. Scrape data
cd ryan-viral-pattern-detector
python ryan_vpd.py scrape --usernames usernames.csv --days 120

# 2. Analyze and export
python ryan_vpd.py analyze --sd-threshold 3.0
python ryan_vpd.py export

# 3. Process videos
cd ../video-processor
python video_processor.py process --unprocessed-outliers

# 4. Analyze with AI
python video_analyzer.py analyze

# 5. Generate adaptations
python yakety_pack_evaluator.py
```

---

## Project Structure

```
viraltracker/
├── ryan-viral-pattern-detector/    # Instagram scraping & outlier detection
│   ├── ryan_vpd.py                 # Main CLI tool
│   ├── sql/schema.sql              # Database schema
│   └── README.md                   # Full documentation
│
└── video-processor/                # Video download & AI analysis
    ├── video_processor.py          # Video download & upload
    ├── video_analyzer.py           # Gemini AI analysis
    ├── yakety_pack_evaluator.py    # Product adaptation evaluator
    ├── aggregate_analyzer.py       # Cross-video insights
    ├── WORKFLOW.md                 # Complete workflow guide
    └── README.md                   # Full documentation
```

---

## Success Metrics

### Ryan's Viral Pattern Detector
- 120 days of Instagram data scraped
- Account-level statistical analysis
- Outlier detection with configurable thresholds
- Multi-format export system

### Video Processor
- 104/104 videos successfully processed (100%)
- 103/104 AI analyses completed (99%)
- 64 high-potential adaptations identified (score ≥ 7.0)
- Complete production-ready scripts generated

---

## Changelog

### 2025-10-03
- **Removed:** viral-dashboard (non-functional)
- **Added:** This README documenting available tools

### 2025-10-01
- **Completed:** Yakety Pack adaptation evaluation system
- **Added:** Complete workflow documentation

### 2025-09-30
- **Completed:** Phase 1 & 2 of video processor
- **Added:** Gemini AI video analysis

### 2025-09-26
- **Initial Release:** Ryan's Viral Pattern Detector

---

## Documentation

- `ryan-viral-pattern-detector/README.md` - Complete VPD documentation
- `video-processor/README.md` - Complete video processor documentation
- `video-processor/WORKFLOW.md` - End-to-end workflow guide
- `video-processor/YAKETY_PACK_RECOMMENDATIONS.md` - Top 20 production-ready adaptations

---

## License

Internal use only. Ensure compliance with Instagram's Terms of Service and applicable data protection regulations.
