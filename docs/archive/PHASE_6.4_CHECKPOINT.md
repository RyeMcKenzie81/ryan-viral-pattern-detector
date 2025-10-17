# Phase 6.4 Checkpoint - Data Collection Progress

**Date:** October 9, 2025
**Location:** `/Users/ryemckenzie/projects/viraltracker/`
**Current Phase:** 6.4 - Expanded Correlation Analysis

---

## Current Status

### What's Complete ✅

1. **Fixed Gemini Model Configuration**
   - Updated default model from `models/gemini-1.5-flash-latest` → `models/gemini-flash-latest`
   - Files updated:
     - `viraltracker/cli/analyze.py` (line 29)
     - `viraltracker/analysis/video_analyzer.py` (line 50)

2. **Data Collection Progress**
   - **Total videos scored:** 19 (up from 14)
   - **New videos added:** 5
   - Successfully processed, analyzed with Gemini 2.5 Flash, and scored
   - New scores range: 67.5 to 88.0

3. **Files Created**
   - `wonder-paws-scores-n19.csv` - Export of all 19 scored videos
   - `/tmp/wonder-paws-urls.txt` - 50 TikTok URLs ready to import

### Current Analysis (n=19)

```
Sample Size: 19 videos

OVERALL SCORES
  Mean:     75.0 (was 73.3 at n=14)
  Median:   73.9
  Std Dev:  6.5
  Min:      61.2
  Max:      88.0

TOP SCORERS:
  1. 88.0 - @chh1986 (5.4M views)
  2. 86.5 - @evgnosiabartsota (1.5M views)
  3. 81.1 - @ovonir.hvcbi.wfq (415K views)
```

---

## Blocker: TikTok API Limitations

### What Works ✅
- **count=10**: Successfully returns results
- **Keywords**: "funny animals", "cute pets" (specific phrases work)

### What Fails ❌
- **count=50+**: Returns `search_nil_item: 'invalid_count'` error
- **Keywords**: "dogs", "puppy videos", "dog training" (popular keywords blocked)
- **API behavior**: Very restrictive, keyword-specific filtering

**Conclusion:** Can only scrape 10 videos at a time with specific keywords. TikTok API is heavily throttled.

---

## Next Steps: URL Import Strategy

### Ready to Execute

**File ready:** `/tmp/wonder-paws-urls.txt` contains 50 TikTok dog video URLs

**Command to run:**
```bash
/Users/ryemckenzie/projects/viraltracker/venv/bin/python -m viraltracker.cli.main tiktok analyze-urls /tmp/wonder-paws-urls.txt --project wonder-paws-tiktok
```

**Note:** Need to check `--help` for correct flags. The `analyze-urls` command exists but may not have `--save` flag.

### Full Pipeline After Import

1. **Import URLs** (50 videos)
   ```bash
   vt tiktok analyze-urls /tmp/wonder-paws-urls.txt --project wonder-paws-tiktok
   ```

2. **Process videos** (download from TikTok)
   ```bash
   vt process videos --project wonder-paws-tiktok
   ```

3. **Analyze with Gemini**
   ```bash
   vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-flash-latest
   ```

4. **Score all videos**
   ```bash
   vt score videos --project wonder-paws-tiktok
   ```

5. **Run correlation analysis** (expected n=69: 19 current + 50 new)
   ```bash
   vt score analyze --project wonder-paws-tiktok
   vt score export --project wonder-paws-tiktok --output wonder-paws-scores-n69.csv
   ```

---

## Additional URL Data Available

The user has **~120 additional TikTok URLs** in a CSV format with metadata (views, likes, comments, etc.) that can be imported if needed. The CSV includes fields like:
- `webVideoUrl`
- `playCount` (views)
- `diggCount` (likes)
- `commentCount`
- `shareCount`
- `text` (caption)
- `authorMeta.name` (username)

**Location:** User provided in chat, not yet saved to file.

---

## Key File Locations

### Data Files
- `wonder-paws-scores-n19.csv` - Current 19 video scores
- `/tmp/wonder-paws-urls.txt` - 50 URLs ready to import

### Code Files Modified
- `viraltracker/cli/analyze.py` - Fixed Gemini model default
- `viraltracker/analysis/video_analyzer.py` - Fixed Gemini model default

### Reference Documents
- `PHASE_6.3_ADDENDUM.md` - Correlation analysis from n=14
- `TOMORROW_DATA_COLLECTION_PLAN.md` - Original data collection plan
- `PHASE_6.3_COMPLETE.md` - Batch scoring implementation

---

## Database Status

**Supabase Connection:** Active
**Project:** wonder-paws-tiktok (ID: `6991a6fd-6b91-474e-8278-a24c5b71df04`)

**Tables with data:**
- `posts` - 19 posts
- `video_analysis` - 19 analyzed
- `video_scores` - 19 scored
- `video_processing_log` - 19 processed

---

## Python Environment

**Virtual Environment:** `/Users/ryemckenzie/projects/viraltracker/venv/`
**Working Directory:** `/Users/ryemckenzie/projects/viraltracker/`

**Shortcut command:**
```bash
vt() {
  /Users/ryemckenzie/projects/viraltracker/venv/bin/python -m viraltracker.cli.main "$@"
}
```

---

## Success Criteria (Original Goal)

- ✅ Fix Gemini model configuration
- 🔄 Collect 100-200 videos (currently at 19, have 50 URLs ready)
- ⏳ Run statistically robust correlation analysis (need n≥50-100)
- ⏳ Validate/invalidate negative correlations from n=14
- ⏳ Make weight adjustment decision for scorer v1.1.0

---

## Critical Commands Reference

### Import & Process Pipeline
```bash
# 1. Import URLs
vt tiktok analyze-urls /tmp/wonder-paws-urls.txt --project wonder-paws-tiktok

# 2. Process (download videos)
vt process videos --project wonder-paws-tiktok

# 3. Analyze with Gemini
vt analyze videos --project wonder-paws-tiktok

# 4. Score
vt score videos --project wonder-paws-tiktok

# 5. Analyze results
vt score analyze --project wonder-paws-tiktok
vt score export --project wonder-paws-tiktok --output scores.csv
```

### Alternative: Small Batch Search (if needed)
```bash
# Only works with count=10 and specific keywords
vt tiktok search "funny animals" --count 10 --project wonder-paws-tiktok --min-views 50000 --max-days 30 --save
```

---

## Background Process

⚠️ **Background process running:** Bash ID `6a2e6a`
Command: Analyze videos (from earlier, may be stale)
Check with: `BashOutput` tool with ID `6a2e6a` or kill with `KillShell`

---

## For Next Context Window

**Start here:**
1. Check if `analyze-urls` command works correctly (run with `--help`)
2. Import the 50 URLs from `/tmp/wonder-paws-urls.txt`
3. Process, analyze, and score the new batch
4. Target: Get to n≥69 total videos
5. Run correlation analysis to validate Phase 6.3 findings

**File to reference:** This file (`PHASE_6.4_CHECKPOINT.md`)
