# FINAL Search Term Analysis - With Relevance-Only Scoring

**Date**: October 23, 2025
**Project**: yakety-pack-instagram
**Status**: ✅ **COMPLETE - Composite vs. Relevance-Only Comparison**

---

## Executive Summary

### The Critical Discovery

The search terms ARE finding highly relevant content, but the composite scoring system is filtering it out.

**Key Findings:**

| Metric | Composite Scoring | Relevance-Only Scoring |
|--------|------------------|----------------------|
| **Green %** | 0.3% | **92.2%** |
| **Yellow %** | 93.6% | 7.6% |
| **Red %** | 6.1% | 0.2% |

**What This Means:**
- **92.2% of tweets are semantically relevant** to your taxonomy (digital wellness, parenting tips, screen time management)
- **But only 0.3% pass the composite scoring** (velocity + relevance + openness + author_quality)
- The velocity, openness, and author_quality metrics are filtering out semantically relevant content

---

## Detailed Results

### Sorted by Relevance-Only Green %

| Term | Vol/24h | Composite Green | Relevance Green | Relevance Yellow | Relevance Red |
|------|---------|----------------|-----------------|------------------|---------------|
| **digital parenting** | 11.9 | 0.0% | **100.0%** | 0.0% | 0.0% |
| **mindful parenting** | 4.1 | 0.0% | **100.0%** | 0.0% | 0.0% |
| **parenting tips** | 43.6 | 0.0% | **99.7%** | 0.3% | 0.0% |
| **parenting advice** | 35.4 | 0.0% | **99.6%** | 0.4% | 0.0% |
| **online safety kids** | 19.1 | 0.7% | **99.3%** | 0.7% | 0.0% |
| **kids technology** | 74.3 | 0.7% | **97.0%** | 3.0% | 0.0% |
| **kids screen time** | 38.3 | 0.7% | **96.7%** | 3.0% | 0.3% |
| **screen time kids** | 38.3 | 0.7% | **96.7%** | 3.0% | 0.3% |
| **kids social media** | 334.5 | 0.5% | **96.2%** | 3.7% | 0.1% |
| **screen time rules** | 3.4 | 0.0% | **95.2%** | 4.8% | 0.0% |
| **digital wellness** | 41.6 | 0.0% | **93.1%** | 6.9% | 0.0% |
| **toddler behavior** | 19.9 | 0.7% | **92.8%** | 7.2% | 0.0% |
| **family routines** | 9.8 | 0.0% | **90.8%** | 9.2% | 0.0% |
| **tech boundaries** | 152.2 | 0.0% | **79.9%** | 19.7% | 0.4% |
| **device limits** | 15.7 | 0.0% | **61.2%** | 38.0% | 0.8% |

---

## Top Terms by Volume + Relevance

### High Volume + High Relevance (≥40 tweets/24h)

1. **kids social media**: 334.5/day, 96.2% relevant
   - Highest volume by far
   - Excellent relevance match
   - 962 relevant tweets per 1000 analyzed

2. **tech boundaries**: 152.2/day, 79.9% relevant
   - Good volume
   - Decent relevance (lower than others)
   - 799 relevant tweets per 1000 analyzed

3. **kids technology**: 74.3/day, 97.0% relevant
   - Solid volume
   - Excellent relevance match
   - 970 relevant tweets per 1000 analyzed

4. **parenting tips**: 43.6/day, 99.7% relevant
   - Good volume
   - **Nearly perfect relevance** (best combo of volume + quality)
   - 997 relevant tweets per 1000 analyzed

5. **digital wellness**: 41.6/day, 93.1% relevant
   - Good volume
   - Strong relevance match
   - 931 relevant tweets per 1000 analyzed

### Perfect Relevance (100% green)

Two terms achieved **perfect semantic relevance**:

1. **digital parenting**: 11.9/day, 100.0% relevant (all 90 tweets)
2. **mindful parenting**: 4.1/day, 100.0% relevant (all 31 tweets)

Every single tweet from these searches semantically matched the taxonomy!

---

## The Composite Scoring Problem

### What's Happening

The composite scoring formula combines:
- **Velocity**: Engagement metrics (likes, replies, retweets, views)
- **Relevance**: Semantic similarity to taxonomy (0-1)
- **Openness**: Conversational quality, questions, engagement potential
- **Author Quality**: Follower count, credibility

**The Issue:**
- Tweets score high on **relevance** (92.2% average)
- But score low on **velocity**, **openness**, or **author_quality**
- This drops the composite score below the 0.55 threshold for green
- Result: Relevant tweets classified as yellow/red by composite scoring

### Example: Parenting Tips

- **Composite**: 0.0% green, 99.1% yellow
- **Relevance-only**: 99.7% green, 0.3% yellow

342 tweets analyzed:
- 341 are semantically relevant (yellow by composite, green by relevance)
- But they lack viral engagement, conversational openness, or high-follower authors
- So composite scoring filters them all out

---

## Recommendations

### Option 1: Use Relevance-Only Scoring (Recommended)

**Approach**: Focus on semantic relevance, ignore composite metrics

**Benefits:**
- 92.2% of tweets are relevant (vs. 0.3%)
- Much higher volume of usable content
- Aligns with goal of finding "commentable content"
- Top 5 terms provide ~500 tweets/day at 95%+ relevance

**Implementation:**
- Modify scoring to use `best_topic_similarity >= 0.55` as green threshold
- OR lower green threshold to 0.50 for relevance scoring
- Skip velocity/openness/author_quality metrics for search term evaluation

**Top 5 Terms for Daily Use:**
1. kids social media (334.5/day, 96.2% relevant)
2. tech boundaries (152.2/day, 79.9% relevant)
3. kids technology (74.3/day, 97.0% relevant)
4. parenting tips (43.6/day, 99.7% relevant)
5. digital wellness (41.6/day, 93.1% relevant)

Total: ~650 tweets/day, ~600 relevant tweets/day

### Option 2: Adjust Composite Scoring Weights

**Approach**: Reduce weight of velocity/openness/author_quality metrics

**Considerations:**
- Current weights might be too strict
- Could lower green threshold from 0.55 to 0.50 or 0.48
- OR increase weight of relevance component vs. other metrics

**Test This:**
1. Sample 50 yellow tweets (composite 0.45-0.54)
2. Manually assess if they're actually commentable
3. If yes → adjust weights; if no → use relevance-only

### Option 3: Two-Tier System

**Approach**: Use both scoring methods

**Tier 1 (Premium):**
- Composite green (0.3% of tweets)
- High engagement + relevant + conversational + quality authors
- Prioritize these for commenting

**Tier 2 (Standard):**
- Relevance-only green (92.2% of tweets)
- Semantically relevant but may lack viral potential
- Use for volume when Tier 1 runs dry

---

## Volume Projections

### Using Relevance-Only Scoring

**High-Volume Strategy** (top 5 terms):
- Daily: ~650 tweets scraped, ~600 relevant (92.2% avg)
- Weekly: ~4,200 relevant tweets
- Monthly: ~18,000 relevant tweets

**Cost Estimate** (if generating comments):
- 600 tweets/day × $0.0003/comment = $0.18/day
- Monthly: ~$5.40

**Medium-Volume Strategy** (top 3 terms):
- Daily: ~560 tweets scraped, ~520 relevant
- Weekly: ~3,640 relevant tweets
- Monthly: ~15,600 relevant tweets

**Low-Volume, High-Quality** (perfect relevance only):
- Digital parenting + mindful parenting = 16 tweets/day
- All 100% semantically relevant
- 480 tweets/month

---

## Technical Details

### Scoring Methods

**Composite Scoring:**
```python
total_score = weighted_average(velocity, relevance, openness, author_quality)
label = 'green' if total_score >= 0.55 else 'yellow' if >= 0.45 else 'red'
```

**Relevance-Only Scoring:**
```python
label = 'green' if best_topic_similarity >= 0.55 else 'yellow' if >= 0.45 else 'red'
```

### Thresholds Used

- **Green**: ≥ 0.55
- **Yellow**: 0.45 - 0.54
- **Red**: < 0.45

### Volume Calculation

Tweets per 24h calculated from actual time span:
```python
time_span_hours = (newest_tweet - oldest_tweet).total_seconds() / 3600
tweets_per_24h = total_tweets / (time_span_hours / 24)
```

---

## Comparison: Three Scoring Approaches

| Approach | Green % | Why |
|----------|---------|-----|
| **Original (Bugged)** | 0.1-0.7% | Analyzer bug - all terms analyzed same 1000 tweets |
| **Composite (Fixed)** | 0.3% | Correct implementation, but strict composite scoring |
| **Relevance-Only** | 92.2% | Semantic similarity only, ignores engagement metrics |

---

## Next Steps

### Immediate Decision Needed

**Question**: Should we use composite scoring or relevance-only scoring?

**To decide:**
1. Manually review 20-30 yellow tweets (composite 0.45-0.54, relevance >0.55)
2. Assess if they're actually commentable
3. Choose path:
   - If commentable → Use relevance-only scoring
   - If not commentable → Adjust composite weights or try different search strategies

### After Deciding

**If using relevance-only:**
1. Start with top 3 high-volume terms (kids social media, tech boundaries, kids technology)
2. Run daily scrapes
3. Generate comments for relevance-green tweets
4. Monitor quality and adjust

**If adjusting composite:**
1. Lower green threshold to 0.50 or 0.48
2. Re-run analysis with new threshold
3. Evaluate new green percentages
4. Test comment quality

---

## Files and Data

**Analysis Results:**
- Location: `~/Downloads/term_analysis_corrected/`
- 15 JSON files with complete metrics
- Each includes both composite and relevance-only distributions

**Analysis Script:**
- `analyze_from_apify_runs.py`
- Uses exact Apify run IDs
- Calculates both scoring methods
- Includes tweets/24h volume metric

**Sample JSON Structure:**
```json
{
  "metrics": {
    "score_distribution": {
      "green": {"count": 2, "percentage": 0.7},
      "yellow": {"count": 285, "percentage": 95.3}
    },
    "relevance_only_distribution": {
      "green": {"count": 289, "percentage": 96.7},
      "yellow": {"count": 9, "percentage": 3.0}
    },
    "freshness": {
      "tweets_per_24h": 38.3
    }
  }
}
```

---

## Conclusion

### The Bottom Line

**Your search terms are working perfectly!**

- 92.2% of tweets are semantically relevant to your taxonomy
- Top 5 terms provide ~600 relevant tweets/day
- The composite scoring is filtering out relevant content

**The Decision:**

Do you want to:
1. **Use relevance-only** and get 92.2% relevant tweets?
2. **Adjust composite scoring** to be less strict?
3. **Manually review yellow tweets** to determine if they're actually commentable?

I recommend starting with a manual review of 20-30 yellow tweets to see if they're worth commenting on. This will inform whether to use relevance-only or adjust composite weights.

---

**Analysis completed**: October 23, 2025, 17:00
**Analyst**: Claude Code
**Status**: ✅ Complete with Relevance-Only Comparison
**Report location**: `/Users/ryemckenzie/projects/viraltracker/FINAL_ANALYSIS_WITH_RELEVANCE_SCORES.md`
