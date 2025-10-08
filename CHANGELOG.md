# ViralTracker Changelog

## 2025-10-07 - TikTok URL Analysis Feature

### Phase 5c: TikTok URL Import & Analysis

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
