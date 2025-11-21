# ViralTracker Changelog

## 2025-11-20 - Agent Tool Selection Bug Fix

### Fixed: Agent Re-Scraping Instead of Analyzing Existing Data

**Problem:**
When users scraped tweets and then asked to "find viral outliers from them", the agent incorrectly triggered a second scrape operation instead of analyzing the existing database data.

**Root Cause:**
- Ambiguous system prompt caused agent to misinterpret "find viral outliers" as "find tweets about [keyword]"
- Agent selected `search_twitter_tool` (which scrapes new tweets) instead of `find_outliers_tool` (which analyzes existing data)

**Solution:**
Enhanced agent system prompt with:
1. **Explicit tool descriptions** - Clear labels indicating which tools scrape vs analyze
2. **Conversation context awareness** - Better handling of follow-up queries referencing recent scrapes
3. **Clarification guidance** - Agent now asks for clarification when intent is ambiguous instead of guessing
4. **Concrete examples** - Added exact scenario (scrape → analyze workflow) to prompt

**Code Changes:**
- `viraltracker/agent/agent.py` (lines 235-392):
  - Updated `find_outliers_tool` description with "ANALYZES EXISTING DATABASE DATA - DOES NOT SCRAPE NEW TWEETS"
  - Updated `search_twitter_tool` description with "SCRAPES NEW TWEETS FROM TWITTER API - USE ONLY FOR NEW KEYWORD SEARCHES"
  - Enhanced conversation context section with explicit scrape-then-analyze workflow guidance
  - Added clarification guidelines: "When in doubt, ask for clarification instead of guessing"
  - Added concrete examples showing correct tool selection for multi-turn conversations

**Impact:**
- Prevents duplicate Apify scraping operations
- Reduces API costs and execution time
- Improves agent reliability for multi-turn conversations
- Agent now asks clarifying questions when intent is ambiguous

## 2025-10-08 - Enhanced Output & Simplified Workflow

### Phase 5d: Output Formatting & Workflow Improvements (COMPLETED ✅)

**BREAKING CHANGE:** URL analysis commands now use `--project` instead of `--brand`

**What Changed:**
1. **Enhanced Output Formatting**
   - Added detailed analysis display in terminal (matches export script quality)
   - Shows hook, transcript, storyboard, viral factors, improvements
   - Displays product adaptations when requested
   - No more minimal output - full breakdown on every analysis

2. **Simplified Workflow**
   - Changed from `--brand` to `--project` flag (breaking change)
   - Added optional `--product` flag for adaptations
   - Auto-links posts to both `brand_posts` AND `project_posts` tables
   - No more manual linking required between brands and projects

**New Commands:**
```bash
# Without product adaptations
vt tiktok analyze-url <URL> --project wonder-paws-tiktok

# With product adaptations
vt tiktok analyze-url <URL> --project wonder-paws-tiktok --product collagen-3x-drops

# Batch processing
vt tiktok analyze-urls urls.txt --project wonder-paws-tiktok [--product <slug>]
```

**Migration from 5c:**
```bash
# OLD (Phase 5c - no longer works)
vt tiktok analyze-url <URL> --brand wonder-paws

# NEW (Phase 5d - required)
vt tiktok analyze-url <URL> --project wonder-paws-tiktok
```

**Code Changes:**
- `viraltracker/cli/tiktok.py` (+341 lines):
  - Added `display_analysis_results()` helper function (lines 28-168)
  - Updated `analyze-url` to use `--project` + optional `--product` (lines 527-694)
  - Updated `analyze-urls` to use `--project` + optional `--product` (lines 726-889)
  - Auto-links to both `brand_posts` and `project_posts` tables

**New Files:**
- `PHASE_5D_SUMMARY.md` - Complete phase documentation
- `UPDATED_WORKFLOW.md` - Usage examples and workflow guide
- `export_wonder_paws_analysis.py` - Export script for analysis results
- `test_product_integration.py` - Integration tests (all passing ✅)

**Issues Resolved:**
- ✅ Output formatting now matches search command quality
- ✅ Brand/project workflow simplified (no manual linking)
- ✅ Product adaptations are now optional (only when `--product` specified)

**Commit:** e7a6951
**Files Changed:** 5 files, +908 lines, -39 lines

---

## 2025-10-07 - TikTok URL Analysis Feature

### Phase 5c: TikTok URL Import & Analysis (COMPLETED ✅)

**New Feature: Direct URL Analysis**
Added ability to analyze TikTok videos from URLs (complementing existing search/hashtag/user scraping).

**New CLI Commands:**
```bash
vt tiktok analyze-url <URL> --brand <brand-slug> [--download]
vt tiktok analyze-urls <file> --brand <brand-slug> [--download]
```

**Key Implementation Details:**
- Uses ScrapTik's `post_awemeId` endpoint (extracts aweme_id from URL)
- Links videos to brands via `brand_posts` table (not just projects)
- Supports all TikTok URL formats: standard, vt.tiktok.com, vm.tiktok.com
- Optional `--download` flag for end-to-end processing

**Code Changes:**
- `viraltracker/cli/tiktok.py`: Added `analyze-url` and `analyze-urls` commands
- `viraltracker/scrapers/tiktok.py`: New methods:
  - `fetch_video_by_url()` - Fetch single video metadata
  - `_start_post_fetch_run()` - Apify run with aweme_id
  - `_normalize_single_post()` - Parse `{aweme_detail: {...}}` response
  - `_link_posts_to_brand()` - Link to brands table
- Updated `save_posts_to_db()` to accept `brand_id` parameter

**Production Test:**
- Brand: Wonder Paws (Collagen 3X Drops)
- Imported: 10 TikTok URLs from file
- Total views: 3.6M (avg 363K per video)
- All downloaded: 121MB total
- All analyzed: Gemini 2.0 Flash with product adaptations

**Viral Patterns Identified:**
- Problem-based hooks (dog health issues)
- Natural alternatives to vet treatments
- Emotional storytelling (suffering → relief)
- Specific claims (80% improvement, 3 weeks)
- Personal testimonials with before/after

**Files Created:**
- `test_tiktok_urls.txt` - Example URL input
- `tiktok_wonder_paws_urls.csv` - Metadata export
- `tiktok_analysis_results.csv` - Full analysis with adaptations

**Known Issues:**
1. ⚠️ Gemini model name in CLI: uses deprecated `models/gemini-1.5-flash-latest`
   - Workaround: Use `--gemini-model models/gemini-2.0-flash-exp`
   - TODO: Update default in `video_analyzer.py`

2. ⚠️ Output formatting inconsistent with search command
   - URL commands need better progress indicators
   - TODO: Match search command output format

3. ⚠️ Brand vs Project workflow confusing
   - URL import links to brands
   - Process/analyze commands require projects
   - Had to manually link posts to project for processing
   - TODO: Unify brand/project handling

**Successful Workflow Pattern:**
```bash
# 1. Import URLs to brand
vt tiktok analyze-urls urls.txt --brand wonder-paws --no-download

# 2. Link to project (manual Python)
# [Script to link brand_posts to project_posts]

# 3. Download videos
vt process videos --project wonder-paws-tiktok

# 4. Analyze with Gemini
vt analyze videos --project wonder-paws-tiktok \
  --product collagen-3x-drops \
  --gemini-model models/gemini-2.0-flash-exp
```

---

## 2025-01-07 - TikTok Integration Complete

### Phase 5b: TikTok Integration

**Completed Features:**
- ✅ ScrapTik API integration (Apify actor: scraptik~tiktok-api)
- ✅ Three discovery modes: keyword search, hashtag tracking, user scraping
- ✅ Outlier detection strategies documented and implemented
- ✅ Platform-aware Gemini video analysis (auto-detects TikTok vs Instagram)
- ✅ TikTok CLI commands with rich filtering options
- ✅ End-to-end workflow tested with real brand (Wonder Paws)

**Key Components Built:**

1. **Database Configuration** (`sql/03_update_tiktok_scraper.sql`)
   - Configured TikTok platform with ScrapTik actor details
   - Cost per request: $0.002
   - Endpoints: searchPosts, challengePosts, userPosts, get-post

2. **TikTok Scraper Service** (`viraltracker/scrapers/tiktok.py` - 718 lines)
   - `search_by_keyword()`: Search with viral filters
   - `search_by_hashtag()`: Track hashtag performance
   - `scrape_user()`: User posts with statistical outlier detection
   - `_apply_viral_filters()`: 100K+ views, <10 days old, <50K followers
   - `save_posts_to_db()`: Upsert accounts and posts with project linking

3. **TikTok CLI Commands** (`viraltracker/cli/tiktok.py` - 435 lines)
   - `vt tiktok search <keyword>`: Keyword search with filters
   - `vt tiktok hashtag <hashtag>`: Hashtag tracking
   - `vt tiktok user <username>`: User scraping with optional outlier detection
   - Options: `--count`, `--min-views`, `--max-days`, `--max-followers`, `--project`, `--save`, `--analyze-outliers`

4. **Platform-Aware Analysis** (`viraltracker/analysis/video_analyzer.py`)
   - Auto-detects platform from database (Instagram/TikTok/YouTube Shorts)
   - Adapts Gemini prompts dynamically based on platform
   - Critical fix: Use `models/gemini-flash-latest` (proxy to latest version)

5. **Documentation**
   - `viraltracker/docs/outlier_detection_strategies.md`: Four strategies documented
   - `TIKTOK_INTEGRATION.md`: Complete integration guide
   - `TIKTOK_TEST_RESULTS.md`: Test results with Wonder Paws
   - `WONDER_PAWS_FULL_DETAILED_ANALYSIS.md`: Full analysis export with timestamps

**Production Test Results:**

Brand: Wonder Paws
Product: Collagen 3X Drops
Keywords Searched: "dog collagen", "dog pain", "dog joints"

- ✅ 4 viral videos found (1.9M total views)
- ✅ All videos downloaded (41.77 MB)
- ✅ All videos analyzed with detailed breakdowns:
  - Full transcripts with timestamps and speakers
  - Text overlays with timestamps and styles
  - Scene-by-scene visual storyboards with durations
  - Key moments breakdown
  - Viral factors analysis
  - Product adaptations for Collagen 3X Drops

**Cost Analysis:**
- Scraping: $0.006 (3 searches × $0.002)
- AI Analysis: ~$0.02 (4 videos with Gemini)
- Total: $0.026 per complete viral analysis workflow

**Critical Technical Decisions:**

1. **Gemini Model**: Use `models/gemini-flash-latest` (NOT version-specific like `gemini-2.0-flash-exp`)
   - Latest version proxy ensures detailed breakdowns (transcripts, storyboards, timestamps)
   - Version-specific models returned incomplete data

2. **Outlier Detection**: Two approaches
   - Keyword/Hashtag: Filtered criteria (100K+ views, <10 days, <50K followers)
   - User Tracking: Statistical (3 SD from trimmed mean)

3. **Data Normalization**: ScrapTik returns nested structure
   - `search_item_list` > `aweme_info` extraction required
   - Field names use snake_case (`play_count`, not `playCount`)

**Files Modified:**
- `sql/03_update_tiktok_scraper.sql`
- `viraltracker/scrapers/tiktok.py` (NEW - 718 lines)
- `viraltracker/cli/tiktok.py` (NEW - 435 lines)
- `viraltracker/cli/main.py` (registered TikTok commands)
- `viraltracker/analysis/video_analyzer.py` (platform detection)

**Test Files Created:**
- `export_complete_analysis.py`: Export full analysis with timestamps
- `check_raw_data.py`: Verify Gemini response structure
- `delete_and_reanalyze.py`: Re-analyze with correct model
- `check_instagram_data.py`: Platform data comparison

---

## Previous Updates

### Phase 5a: Script Management (Completed)
- Script versioning and approval workflow
- Script templates and generation

### Phase 4d: Instagram Testing (Completed)
- End-to-end Instagram workflow tested
- Yakety Pack brand analysis complete

### Phase 4c: Product Adaptation Engine (Completed)
- Gemini-powered script adaptation
- Multi-product support

### Phase 4b: Gemini Video Analysis (Completed)
- Hook analysis, transcripts, storyboards
- Viral factor detection

### Phase 4a: Instagram Integration (Completed)
- Apify Instagram scraper integration
- URL import functionality

### Phases 1-3: Foundation (Completed)
- Database schema (Supabase)
- Core models and services
- CLI framework

---

## 2025-10-08 - Scoring Engine Integration (UPCOMING)

### Phase 6: Deterministic TikTok Scoring System (IN PROGRESS 🚧)

**Goal:** Replace subjective "viral factors" with deterministic 0-100 scoring using 9 subscores + penalties.

**Architecture:**
- TypeScript scoring engine in `scorer/` subdirectory
- Python calls scorer via subprocess (JSON in/out)
- New `video_scores` database table
- New CLI command: `vt score videos --project <project>`

**9 Subscores (0-100 each):**
1. **Hook** (20% weight) - First 3-5 seconds effectiveness
2. **Story** (15% weight) - Narrative structure, beats, arc
3. **Relatability** (12% weight) - Audience connection, emotion
4. **Visuals** (10% weight) - Production quality, editing, overlays
5. **Audio** (8% weight) - Sound quality, music, trending sounds
6. **Watchtime** (12% weight) - Retention signals, completion rate
7. **Engagement** (10% weight) - Likes, comments, shares relative to views
8. **Shareability** (8% weight) - Caption, CTA, viral mechanics
9. **Algo** (5% weight) - Platform optimization (hashtags, length, etc.)

**Penalties:** Subtracted from total (clickbait, poor audio, etc.)

**Overall Score:** Weighted average of subscores minus penalties (0-100)

**Implementation Phases:**

**Phase 6.1: Database & TypeScript Scorer**
- [ ] Create `sql/04_video_scores.sql` migration
- [ ] Add `video_scores` table (9 subscores + penalties + overall)
- [ ] Add `overall_score` column to `video_analysis`
- [ ] Set up TypeScript project in `scorer/`
- [ ] Implement Zod schemas with our data extensions
- [ ] Implement 9 scoring formulas + penalties
- [ ] Create CLI that reads JSON from stdin
- [ ] Write unit tests

**Phase 6.2: Python Integration**
- [ ] Create `viraltracker/scoring/data_adapter.py`
- [ ] Build Python → TypeScript bridge (subprocess)
- [ ] Create `viraltracker/cli/score.py` command
- [ ] Test on sample videos

**Phase 6.3: Batch Scoring & Testing**
- [ ] Score 10 sample videos
- [ ] Verify scores make intuitive sense
- [ ] Adjust formulas based on results
- [ ] Batch-score all 120+ existing analyzed videos
- [ ] Create visualization/export scripts

**Phase 6.4: Model Upgrade (Optional)**
- [ ] Update default Gemini model to `models/gemini-2.5-pro`
- [ ] Add `--gemini-model` option to analyze commands
- [ ] Test differences between models
- [ ] Document model selection guidance

**Data Sources:**
- ScrapTik metadata (views, likes, comments, caption, hashtags)
- Gemini analysis (hook, transcript, storyboard, overlays, key moments)
- Derived metrics (engagement rate, hashtag mix, story beats)

**Example Output:**
```json
{
  "version": "1.0.0",
  "subscores": {
    "hook": 85.5,
    "story": 78.2,
    "relatability": 82.0,
    "visuals": 75.5,
    "audio": 70.0,
    "watchtime": 68.5,
    "engagement": 88.0,
    "shareability": 72.0,
    "algo": 65.0
  },
  "penalties": 5.0,
  "overall": 76.8
}
```

**New CLI Commands:**
```bash
# Score unscored videos in a project
vt score videos --project wonder-paws-tiktok

# Re-score all videos (even if already scored)
vt score videos --project wonder-paws-tiktok --rescore

# Score with limit for testing
vt score videos --project wonder-paws-tiktok --limit 10
```

**Database Schema:**
```sql
CREATE TABLE video_scores (
  id UUID PRIMARY KEY,
  post_id UUID NOT NULL REFERENCES posts(id),
  scorer_version TEXT NOT NULL,
  scored_at TIMESTAMP DEFAULT NOW(),

  -- 9 subscores
  hook_score FLOAT NOT NULL CHECK (0-100),
  story_score FLOAT NOT NULL CHECK (0-100),
  relatability_score FLOAT NOT NULL CHECK (0-100),
  visuals_score FLOAT NOT NULL CHECK (0-100),
  audio_score FLOAT NOT NULL CHECK (0-100),
  watchtime_score FLOAT NOT NULL CHECK (0-100),
  engagement_score FLOAT NOT NULL CHECK (0-100),
  shareability_score FLOAT NOT NULL CHECK (0-100),
  algo_score FLOAT NOT NULL CHECK (0-100),

  -- Penalties & Overall
  penalties_score FLOAT NOT NULL DEFAULT 0,
  overall_score FLOAT GENERATED (weighted formula),

  score_details JSONB
);
```

**Benefits:**
- Objective, reproducible scores
- Compare videos across time/creators
- Identify specific weaknesses (e.g., poor hook but great story)
- Track score improvements with content iterations
- Build dashboards and analytics
- Replace subjective viral factors with metrics

**Documentation:**
- Full plan: `PHASE_6_SCORING_ENGINE_PLAN.md`
- TypeScript schemas: `scorer/src/schema.ts`
- Scoring formulas: `scorer/src/formulas.ts`
- Data mapping: Phase 6 plan, lines 195-347

**Status:** Planning complete, ready for implementation
**Estimated Time:** 4-6 hours total
**Dependencies:** Phase 5d complete ✅

---
