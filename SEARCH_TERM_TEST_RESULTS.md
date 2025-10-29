# Search Term Analysis Results - Yakety Pack Instagram Project

**Date**: October 23, 2025
**Project**: yakety-pack-instagram
**Analysis Type**: Batch search term testing (15 terms × 1000 tweets)
**Total Tweets Analyzed**: 15,000

---

## Executive Summary

**Critical Finding**: All 15 search terms tested rated **"Poor"** with an overall green tweet rate of only **0.31%**, far below the 8% threshold for "Good" performance.

**Key Metrics**:
- Best performing term: "kids technology" and "mindful parenting" (0.7% green)
- Worst performing terms: 10 terms with 0.1% green
- Average green percentage across all terms: 0.31%
- Total green tweets found: 46 out of 15,000 (0.31%)
- All terms show excellent freshness: 100% of tweets from last 48h (~500 conversations/day)

**Recommendation**: The current search term approach is **not viable** for finding high-quality, commentable content. See "Next Steps" section for recommended actions.

---

## Detailed Results by Term

### Performance Rankings (by Green %)

| Rank | Search Term | Tweets | Green | Yellow | Red | Green % | Fresh % | Conv/Day | Top Topic | Rating |
|------|-------------|--------|-------|--------|-----|---------|---------|----------|-----------|--------|
| 1 | kids technology | 1000 | 7 | 925 | 68 | 0.7% | 100% | 500 | digital wellness (82.5%) | Poor |
| 2 | mindful parenting | 1000 | 7 | 925 | 68 | 0.7% | 100% | 500 | digital wellness (82.6%) | Poor |
| 3 | online safety kids | 1000 | 6 | 924 | 70 | 0.6% | 100% | 500 | digital wellness (75.9%) | Poor |
| 4 | tech boundaries | 1000 | 6 | 914 | 80 | 0.6% | 100% | 500 | digital wellness (80.5%) | Poor |
| 5 | kids social media | 1000 | 5 | 921 | 74 | 0.5% | 100% | 500 | digital wellness (74.4%) | Poor |
| 6 | digital wellness | 1000 | 2 | 868 | 130 | 0.2% | 100% | 500 | digital wellness (69.3%) | Poor |
| 7 | kids screen time | 1000 | 2 | 868 | 130 | 0.2% | 100% | 500 | digital wellness (69.3%) | Poor |
| 8 | parenting advice | 1000 | 2 | 870 | 128 | 0.2% | 100% | 500 | digital wellness (66.3%) | Poor |
| 9 | parenting tips | 1000 | 2 | 869 | 129 | 0.2% | 100% | 500 | digital wellness (67.4%) | Poor |
| 10 | screen time kids | 1000 | 2 | 864 | 134 | 0.2% | 100% | 500 | digital wellness (73.4%) | Poor |
| 11 | device limits | 1000 | 1 | 869 | 130 | 0.1% | 100% | 500 | digital wellness (65.7%) | Poor |
| 12 | digital parenting | 1000 | 1 | 868 | 131 | 0.1% | 100% | 500 | digital wellness (65.0%) | Poor |
| 13 | family routines | 1000 | 1 | 868 | 131 | 0.1% | 100% | 500 | digital wellness (64.7%) | Poor |
| 14 | screen time rules | 1000 | 1 | 869 | 130 | 0.1% | 100% | 500 | digital wellness (65.8%) | Poor |
| 15 | toddler behavior | 1000 | 1 | 871 | 128 | 0.1% | 100% | 500 | digital wellness (65.3%) | Poor |

**Success Criteria Reminder**:
- Excellent: ≥15% green
- Good: ≥8% green
- Okay: ≥5% green
- Poor: <5% green

---

## Topic Distribution Analysis

All terms showed strong skew toward "digital wellness" as the top topic:

- **Digital wellness dominated**: 64.7% - 82.6% of tweets matched this topic
- **Parenting tips**: Appeared as secondary topic but rarely as top match
- **Screen time management**: Appeared least frequently across all terms

### Topic Distribution Breakdown

The taxonomy has 3 topics:
1. Digital wellness
2. Parenting tips
3. Screen time management

**Observation**: Even terms explicitly mentioning "parenting" (parenting tips, parenting advice, digital parenting, mindful parenting) primarily matched "digital wellness" rather than "parenting tips" topic.

This suggests:
- The "digital wellness" topic embedding may be too broad
- The other topic embeddings may be too narrow/specific
- Twitter content may naturally cluster around wellness language vs. tactical parenting advice

---

## Volume & Freshness Analysis

**Excellent News**: All terms show very high volume and freshness

- **100% freshness**: All 15,000 tweets were from the last 48 hours
- **Consistent volume**: ~500 conversations/day across all terms
- **No volume issues**: Every term successfully returned 1000 tweets

**Takeaway**: Twitter has abundant content in these categories. The problem is not volume - it's relevance/quality match to the project taxonomy.

---

## Cost Analysis

**Total Cost**: $0.00

- Analysis used embeddings only (no comment generation due to `--skip-comments` flag)
- Embedding costs via Google Generative AI were negligible
- Comment generation was skipped to reduce time from 5-6 hours to ~54 minutes

**If comments were generated**:
- Estimated cost: ~$1.65 ($0.11 per term)
- With 0.31% green rate, this would yield only ~46 green tweets with comments
- Cost per green tweet: ~$0.036 (very poor efficiency)

---

## Time Analysis

**Actual Time**: 54 minutes for 15 terms (3.6 min/term)

- Batch started: 13:29
- Batch completed: 14:21
- Includes 2-minute delays between searches for rate limiting

**Original Estimate (with comments)**: 5-6 hours (20-25 min/term)

**Time Savings**: ~85% reduction by using `--skip-comments` flag for exploratory analysis

---

## Key Insights

### 1. Scoring Threshold May Be Too Strict

The green threshold (0.55 similarity score) appears very difficult to meet:
- Only 46 out of 15,000 tweets (0.31%) scored ≥0.55
- 86-92% of tweets scored in yellow range (0.45-0.54)
- 6-13% of tweets scored red (<0.45)

**Implication**: Most tweets are "somewhat related" but not "highly related" to the taxonomy topics.

### 2. Taxonomy Topics May Need Adjustment

The project taxonomy topics might be:
- Too narrow/specific for Twitter content
- Not well-aligned with how people naturally discuss these topics
- Missing key themes that appear in the wild

**Example**: "Screen time kids" finds lots of tweets, but they don't strongly match any of the 3 topic embeddings.

### 3. Search Terms Are Not the Problem

The search terms themselves are working well:
- High volume (1000 tweets each, 100% fresh)
- Topically related to the project domain
- Diverse coverage of related concepts

The issue is the **scoring/taxonomy mismatch**, not the search strategy.

### 4. Volume vs. Quality Tradeoff

**Volume**: Excellent - 7,500 conversations/day across these terms
**Quality**: Poor - Only 0.31% meet the green threshold

---

## Comparison to Initial Test

**Previous Test** (from CHECKPOINT_SEARCH_TERM_ANALYZER.md):
- Term: "screen time kids"
- Sample: 50 tweets
- Result: 2% green (1 tweet)

**Current Batch Test**:
- Term: "screen time kids"
- Sample: 1000 tweets
- Result: 0.2% green (2 tweets)

**Observation**: The small sample actually over-represented the green rate. At scale, the rate dropped 10x.

---

## Next Steps & Recommendations

### Immediate Actions

1. **Investigate the 46 Green Tweets**
   - Manually review the green tweets to understand what makes them score ≥0.55
   - Look for patterns in language, topics, framing
   - Use insights to inform taxonomy adjustments

2. **Analyze Yellow Tweets**
   - Review a sample of yellow tweets (0.45-0.54 range)
   - Determine if they're actually relevant and useful for the project
   - Consider if the threshold should be lowered to 0.50 or 0.45

3. **Review Taxonomy Topics**
   - Re-examine the 3 topic definitions in `projects/yakety-pack-instagram/finder.yml`
   - Consider if topics need to be broader or differently framed
   - Test alternative topic wordings/descriptions

### Strategic Options

#### Option A: Lower the Threshold
**Action**: Change green threshold from 0.55 to 0.50 or 0.45
**Impact**: Would capture more tweets but potentially lower quality
**Next Step**: Re-score existing data with lower threshold to see new green %

#### Option B: Revise Taxonomy
**Action**: Rewrite the 3 topic definitions to better match Twitter language
**Impact**: Could significantly improve matching without changing threshold
**Next Step**: Analyze green/yellow tweets to inform new topic definitions

#### Option C: Add More Topics
**Action**: Expand from 3 topics to 5-7 topics to cover more nuances
**Impact**: Better coverage of the actual content landscape
**Next Step**: Identify common themes in yellow tweets and create new topics

#### Option D: Hybrid Scoring
**Action**: Use multiple criteria (topic match + engagement + freshness)
**Impact**: More sophisticated quality assessment
**Next Step**: Implement weighted scoring system

#### Option E: Different Content Source
**Action**: Test other platforms (Reddit, Quora, parenting forums)
**Impact**: May find more on-topic, long-form content
**Next Step**: Explore scraping options for alternative platforms

### Recommended Path Forward

**Phase 1 - Diagnostic** (1-2 hours):
1. Export the 46 green tweets to a spreadsheet
2. Manually review all 46 to understand what makes them green
3. Sample 100 yellow tweets and review for potential usefulness
4. Document patterns and insights

**Phase 2 - Taxonomy Adjustment** (2-3 hours):
1. Based on Phase 1 insights, rewrite taxonomy topics
2. Re-run analyzer on 1-2 test terms with new taxonomy
3. Compare results to baseline

**Phase 3 - Threshold Testing** (1 hour):
1. Re-score existing 15,000 tweets with thresholds of 0.50 and 0.45
2. Analyze how many tweets become green at each threshold
3. Manually review samples at each threshold to assess quality

**Phase 4 - Decision** (Based on results):
- If taxonomy changes improve to ≥5%: Proceed with new taxonomy
- If threshold changes provide good quality at ≥5%: Use new threshold
- If neither works: Consider Option E (different content source)

---

## Technical Notes

### Test Configuration

```bash
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "TERM" \
  --count 1000 \
  --min-likes 0 \
  --skip-comments \
  --report-file ~/Downloads/term_analysis/TERM_analysis.json
```

**Key Parameters**:
- `--count 1000`: Large sample for statistical significance
- `--min-likes 0`: No filtering, analyze full volume
- `--skip-comments`: Skip comment generation for speed
- Rate limiting: 2 minutes between searches

### Files Generated

- 15 JSON analysis reports: `~/Downloads/term_analysis/*_analysis.json`
- Batch execution log: `~/Downloads/term_analysis/batch_log.txt`
- Results extraction script: `extract_results.py`

### Taxonomy Reference

From `projects/yakety-pack-instagram/finder.yml`:

```yaml
topics:
  - id: digital_wellness
    name: "Digital wellness"
    description: "Content about managing technology use, digital detox, screen time limits, and healthy tech habits"

  - id: parenting_tips
    name: "Parenting tips"
    description: "Practical parenting advice, child development insights, behavior management strategies"

  - id: screen_time_management
    name: "Screen time management"
    description: "Specific strategies and tools for managing children's screen time and device usage"
```

---

## Conclusion

The batch analysis successfully tested 15 search terms across 15,000 tweets in under 1 hour. While the technical implementation worked flawlessly, **the results reveal a fundamental mismatch** between the current taxonomy/scoring system and the available Twitter content.

**The good news**: There's abundant, fresh content available (~7,500 conversations/day)

**The challenge**: Only 0.31% of that content scores as "highly relevant" (green) under the current system

**Next step**: Investigate the 46 green tweets and adjust the taxonomy/threshold to better capture the relevant content that exists in the wild.

---

**Analysis completed**: October 23, 2025, 14:30
**Analyst**: Claude Code
**Report location**: `/Users/ryemckenzie/projects/viraltracker/SEARCH_TERM_TEST_RESULTS.md`
