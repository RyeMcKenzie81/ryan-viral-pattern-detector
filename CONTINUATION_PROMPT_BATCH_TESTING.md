# Continuation Prompt - Search Term Batch Testing

**Copy this entire prompt into a new Claude Code session to continue**

---

## Context

I'm working on the viraltracker project, specifically testing the newly implemented Search Term Analyzer tool to find optimal Twitter search terms for the yakety-pack-instagram project.

### What Was Done Previously

✅ **Implemented Search Term Analyzer** (V1 Complete)
- Created `viraltracker/analysis/search_term_analyzer.py` with full analysis pipeline
- Added `analyze-search-term` CLI command to `viraltracker/cli/twitter.py`
- Successfully tested with 50 tweets for "screen time kids" (result: 2% green - Poor)
- Tool calculates 5 metrics: score distribution, freshness, virality, topic distribution, cost efficiency
- Provides recommendations: Excellent (≥15% green), Good (≥8%), Okay (≥5%), Poor (<5%)

### Current Status

- Location: `/Users/ryemckenzie/projects/viraltracker`
- Branch: `feature/comment-finder-v1`
- Python venv: `venv/`
- Database: Supabase (connected via env var)

**Important**: The analyzer is project-specific and taxonomy-driven. It scores tweets based on semantic similarity to the project's taxonomy topics (screen time management, parenting tips, digital wellness).

---

## Your Task

Run a comprehensive batch analysis to test 10-15 different search terms with 1000 tweets each to find the best terms for the yakety-pack-instagram project.

### Search Terms to Test

Please analyze these 15 search terms in order of priority:

**High Priority** (test first):
1. "screen time kids"
2. "parenting tips"
3. "digital wellness"
4. "kids screen time"
5. "parenting advice"

**Medium Priority**:
6. "toddler behavior"
7. "device limits"
8. "screen time rules"
9. "family routines"
10. "digital parenting"

**Lower Priority** (if time permits):
11. "kids social media"
12. "online safety kids"
13. "tech boundaries"
14. "kids technology"
15. "mindful parenting"

### Analysis Parameters

For each search term, run:

```bash
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "SEARCH_TERM_HERE" \
  --count 1000 \
  --min-likes 20 \
  --report-file ~/Downloads/TERM_NAME_analysis.json
```

**Settings**:
- Count: 1000 tweets per term
- Min likes: 20 (higher quality threshold)
- Days back: 7 (default)
- Batch size: 10 (default for async generation)

**Expected Time**: ~20-25 minutes per term
**Expected Cost**: ~$0.11 per term (~$1.65 total for 15 terms)

---

## Important Notes

### Rate Limiting
- **Twitter scraping**: Wait 2 minutes between searches (automatically tracked by tool)
- **Gemini API**: 15 requests/minute (automatically handled)
- If you hit rate limits, the tool will wait automatically

### What to Look For

**Success Criteria** (from plan):
- **Excellent**: ≥15% green + ≥30% freshness
- **Good**: ≥8% green + ≥20% freshness
- **Okay**: ≥5% green (but lower volume)
- **Poor**: <5% green

**Goal**: Find 3-5 terms rated "Good" or "Excellent"

### Expected Results

Based on the small test:
- "screen time kids" scored 2% green (Poor)
- Most tweets matched "digital wellness" and "parenting tips" topics
- Expect more specific terms to perform better
- Terms with "parenting" may score higher due to taxonomy match

---

## Execution Strategy

### Option 1: Manual Sequential Testing (Recommended)

Run each term one at a time, review results, and decide whether to continue:

```bash
# Start with high-priority terms
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "parenting tips" \
  --count 1000 \
  --min-likes 20 \
  --report-file ~/Downloads/parenting_tips_analysis.json

# Review results, then continue with next term
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "digital wellness" \
  --count 1000 \
  --min-likes 20 \
  --report-file ~/Downloads/digital_wellness_analysis.json

# Repeat for each term...
```

**Advantages**:
- Can stop if you find enough good terms
- Can adjust strategy based on early results
- Lower risk of wasting API costs

### Option 2: Automated Batch Testing (Run Overnight)

Create a shell script to run all terms automatically:

```bash
#!/bin/bash

# Create output directory
mkdir -p ~/Downloads/term_analysis

# Define search terms
terms=(
  "screen time kids"
  "parenting tips"
  "digital wellness"
  "kids screen time"
  "parenting advice"
  "toddler behavior"
  "device limits"
  "screen time rules"
  "family routines"
  "digital parenting"
  "kids social media"
  "online safety kids"
  "tech boundaries"
  "kids technology"
  "mindful parenting"
)

# Analyze each term
for term in "${terms[@]}"; do
  echo "========================================"
  echo "Analyzing: $term"
  echo "========================================"

  # Convert term to filename (replace spaces with underscores)
  filename=$(echo "$term" | tr ' ' '_')

  ./vt twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 1000 \
    --min-likes 20 \
    --report-file ~/Downloads/term_analysis/${filename}_analysis.json

  echo ""
  echo "Completed: $term"
  echo ""

  # Wait 2 minutes between searches (rate limiting)
  echo "Waiting 2 minutes before next search..."
  sleep 120
done

echo "========================================"
echo "Batch analysis complete!"
echo "Results saved to: ~/Downloads/term_analysis/"
echo "========================================"
```

Save this as `batch_analyze.sh`, make it executable, and run it:

```bash
chmod +x batch_analyze.sh
./batch_analyze.sh
```

**Advantages**:
- Fully automated (can run overnight)
- Tests all terms systematically
- Complete comparison data

**Disadvantages**:
- Higher API costs if many terms are poor
- Takes 5-6 hours total
- Can't adjust strategy mid-way

---

## After Testing

### 1. Review Results

For each term, check:
- Green ratio (target: ≥8%)
- Freshness percentage
- Topic distribution
- Recommendation rating

### 2. Create Summary Report

Document your findings in a new file: `SEARCH_TERM_TEST_RESULTS.md`

Include:
- Table of all terms with key metrics
- Top 3-5 recommended terms
- Insights on topic distribution
- Cost analysis
- Recommendations for regular use

### 3. Optional: Implement Batch Analysis Command (V2)

If you have time, implement the batch analysis command from `SEARCH_TERM_ANALYZER_V2_FEATURES.md` to automate this process for future testing.

---

## Success Criteria

By end of session, you should have:

- [x] Tested at least 10 search terms with 1000 tweets each
- [x] Generated JSON reports for each term
- [x] Identified 3-5 "Good" or "Excellent" terms
- [x] Created summary document with findings
- [x] Provided recommendations for which terms to use regularly

**Optional**:
- [ ] Implemented batch analysis command (V2 feature)
- [ ] Created comparison visualization

---

## Files to Reference

Read these files in the repo for context:

1. `CHECKPOINT_SEARCH_TERM_ANALYZER.md` - Previous session summary
2. `SEARCH_TERM_ANALYZER_IMPLEMENTATION.md` - Tool documentation
3. `SEARCH_TERM_ANALYZER_PLAN.md` - Original plan
4. `projects/yakety-pack-instagram/finder.yml` - Project taxonomy
5. `viraltracker/analysis/search_term_analyzer.py` - Analyzer code (if debugging needed)

---

## Expected Output Format

For each term tested, you'll see output like:

```
============================================================
📊 Analysis Results
============================================================

Tweets analyzed: 1000

Score Distribution:
  🟢 Green:    150 ( 15.0%) - avg score: 0.618
  🟡 Yellow:   720 ( 72.0%) - avg score: 0.476
  🔴 Red:      130 ( 13.0%) - avg score: 0.382

Freshness:
  Last 48h: 450 tweets (45.0%)
  ~225 tweets/day

Topic Distribution:
  - parenting tips: 520 (52.0%)
  - digital wellness: 350 (35.0%)
  - screen time management: 130 (13.0%)

Cost Efficiency:
  Total cost:        $0.110
  Cost per green:    $0.00073
  Greens per dollar: 1364

============================================================
💡 Recommendation: Excellent (High confidence)
============================================================
15.0% green (target: 15%+). High volume (45.0% in 48h). Use this term regularly.
```

---

## Questions?

If anything is unclear:
1. Check `SEARCH_TERM_ANALYZER_IMPLEMENTATION.md` for tool docs
2. Check `CHECKPOINT_SEARCH_TERM_ANALYZER.md` for session history
3. Run `./vt twitter analyze-search-term --help` for command options

---

**Ready?** Start with the high-priority terms and work your way through the list! 🚀

Good luck finding those optimal search terms! 🎯
