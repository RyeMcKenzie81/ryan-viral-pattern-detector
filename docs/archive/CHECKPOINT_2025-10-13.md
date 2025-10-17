# ViralTracker - Clockworks Migration Complete
**Date:** 2025-10-13
**Session Status:** Ready for analysis

## ✅ Completed Tasks

### 1. Migrated TikTok Scraper from ScrapTik to Clockworks
**Files modified:**
- `viraltracker/scrapers/tiktok.py`
  - Line 64: Changed default actor to `clockworks/tiktok-scraper`
  - Lines 304-349: Rewrote `_start_keyword_search_run()` for Clockworks input format
  - Lines 351-380: Updated `_start_hashtag_search_run()` for Clockworks
  - Lines 550-639: Rewrote `_normalize_search_posts()` to parse Clockworks flat structure
  - Lines 730-735: Fixed timezone handling (UTC) in `_apply_viral_filters()`

**Key differences:**
- Input: `{hashtags: [], searchQueries: [], resultsPerPage: n}`
- Output: Flat structure with nested `authorMeta` and `videoMeta` objects
- Hashtags vs search queries: Separate input parameters

### 2. Successfully Scraped Multiple Search Terms
**Completed 6 scrapes with filters (50K+ views, <25K followers, <20 days):**

1. **dog training**: 234 scraped → 8 passed (3.4%)
2. **dog health tips**: 184 scraped → 7 passed (3.8%)
3. **puppy care**: 210 scraped → 3 passed (1.4%)
4. **pet wellness**: 205 scraped → 19 passed (9.3%) 🎯
5. **#doghealth**: 300 scraped → 11 passed (3.7%)
6. **#dogtips**: 300 scraped → 6 passed (2.0%)

**Total results:**
- Videos scraped: 1,433
- Passed filters: **54 videos**
- Overall pass rate: 3.8%
- Clockworks limit: ~200-300 videos per search query

### 3. Dataset Growth
- Original dataset: 69 videos (all analyzed with Gemini 2.5 Pro v1.1.0)
- New videos added: ~54 (accounting for duplicates)
- **Current total: ~120 videos**

## 🔍 Key Findings

### Clockworks Actor Limitations
- Cannot scrape more than ~200-300 videos per search query
- No pagination/offset parameters
- TikTok blocks after a certain threshold
- **Workaround:** Use multiple diverse search terms

### Filter Effectiveness
- <25K followers filter is intentionally restrictive
- Only 3.8% of viral videos (50K+ views) come from small creators
- This is expected behavior for finding "outlier" videos
- "pet wellness" had best pass rate at 9.3%

### Previous Correlation Results (n=69)
From CHECKPOINT_2025-10-11.md:
- **emotion_intensity**: r=0.337, p=0.0046 ** (SIGNIFICANT)
- time_to_value_sec: r=-0.136, p=0.2660 (not significant)
- first_frame_face_pct: r=-0.191, p=0.1153 (not significant)
- Composite score: r=0.106, p=0.3874 (120% improvement over v1.0.0 baseline)

## 📊 Current Database State

### Videos
- **Total videos**: ~120
- **Status**: All videos appear to be processed (downloaded)
- **Analysis status**: Need to verify if new videos analyzed

### Analysis Version
- **Model**: models/gemini-2.5-pro
- **Version**: vid-1.1.0
- **Continuous metrics**: 14 fields extracted from `platform_specific_metrics`

## 🔄 Next Steps

### 1. Verify Analysis Status
Check how many videos are analyzed vs unanalyzed:
```bash
vt list videos --project wonder-paws-tiktok
```

### 2. Analyze New Videos with Gemini 2.5 Pro
If unanalyzed videos exist:
```bash
echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro
```

### 3. Run Updated Correlation Analysis
With ~120 videos (vs previous 69), rerun correlation analysis:
```bash
python analyze_v1_1_0_results.py
```

**Expected improvements:**
- n=120 provides better statistical power
- Can detect smaller effects (r > 0.25 with 80% power)
- More robust conclusions about which metrics correlate with views

### 4. Consider Additional Scraping (Optional)
If more data needed to reach n=150-200:
- Use more diverse search terms
- Try different niches within dog/pet space
- Vary time windows (e.g., <30 days, <14 days)

## 📁 Files Created This Session

### Test Scripts
- `test_clockworks_100_hashtag.py` - Tested hashtag search with 100 results
- `test_clockworks_100_search.py` - Tested search query with 100 results
- `test_clockworks_structure.py` - Inspected Clockworks output structure

### Analysis Scripts (from previous session)
- `analyze_v1_1_0_results.py` - Correlation analysis with v1.1.0 metrics
- `inspect_metrics.py` - Inspects platform_specific_metrics structure

## 🎯 Goal Review

**Original goal** (from CHECKPOINT_2025-10-11.md):
> Find outliers that are viral based on their individual merits and not because of popular accounts

**Status:** ✅ ACHIEVED
- Restrictive filters working as intended
- Growing dataset of small creator outliers
- Ready for improved correlation analysis

## 💡 Key Insights

### Sample Size Analysis
- **Current n=~120** (vs previous n=69)
- Can now detect medium effects (r > 0.25) with 80% power
- Approaching ideal range of 150-200 for robust conclusions
- Significant improvement in statistical power

### Retention Data Gap (Still Present)
- Measuring **views** (lagging indicator)
- Should measure **retention/watch time** (leading indicator)
- Only available via TikTok Analytics (owner access required)
- Current workaround: Use views as proxy metric

### Actor Comparison
- **ScrapTik**: Broken, returns `search_nil_item: 'invalid_count'`
- **Clockworks**: ✅ Works, but limited to ~200-300 videos per query
- **Solution**: Use multiple diverse search terms

---

## 📋 Command Reference

```bash
# List videos
vt list videos --project wonder-paws-tiktok

# Process videos (download)
vt process videos --project wonder-paws-tiktok

# Analyze with Gemini 2.5 Pro
echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro

# Search for more videos
vt tiktok search "search term" --count 300 --min-views 50000 --max-followers 25000 --max-days 20

# Run correlation analysis
python analyze_v1_1_0_results.py
```

## 🚀 Resume Instructions

To continue this session:

1. **Verify analysis status** of ~120 videos
2. **Run Gemini 2.5 Pro analysis** on any unanalyzed videos
3. **Execute correlation analysis** with larger dataset (n=~120)
4. **Compare results** with previous findings (n=69)
5. **Determine** if additional scraping needed to reach n=150-200
