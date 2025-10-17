# Phase 6.3 Addendum: Correlation Analysis & Next Steps

**Date:** October 8, 2025
**Status:** Exploratory analysis complete, more data needed
**Sample Size:** 14 videos (below statistical minimum)

---

## Executive Summary

Performed exploratory correlation analysis to determine which subscores actually predict viral performance (views/likes). Found **concerning negative correlations** and **one strong positive correlation**, suggesting the scorer may be measuring wrong factors or using incorrect weights.

**Key Finding:** Algorithm optimization, shareability, and relatability scores are **negatively correlated with views** - the opposite of what we'd expect. However, **hook scores strongly predict likes** (r=0.737).

**Limitation:** n=14 is below statistical minimum (need n≥30 for reliable conclusions). Results are exploratory only.

**Next Step:** Collect 100-200 more videos tomorrow to confirm patterns and adjust scorer weights accordingly.

---

## Correlation Analysis Results

### Sample Characteristics

- **Sample size:** 14 videos
- **Score range:** 61.2 - 81.1
- **View range:** 86,139 - 846,088
- **Engagement ratio:** 0.33% - 2.52% (mean: 0.79%)

### Correlations with VIEWS

| Subscore | r | Strength | Direction | Interpretation |
|----------|---|----------|-----------|----------------|
| **Story** | **0.523** | **Moderate** | ✅ Positive | Better story → more views |
| Engagement | 0.332 | Weak | ✅ Positive | Higher engagement → more views |
| Visuals | 0.318 | Weak | ✅ Positive | Better visuals → more views |
| Hook | 0.281 | Weak | ✅ Positive | Better hook → more views |
| Overall | 0.108 | Very weak | ✅ Positive | Barely any correlation |
| Watchtime | -0.033 | Very weak | ⚠️ Negative | No clear pattern |
| Relatability | -0.221 | Weak | ⚠️ Negative | Higher relatability → FEWER views! |
| Shareability | -0.315 | Weak | ⚠️ Negative | Higher shareability → FEWER views! |
| **Algorithm** | **-0.390** | **Weak** | **⚠️ Negative** | **Better algo optimization → FEWER views!** |
| Audio | nan | - | - | All scores identical (47.5) |

### Correlations with LIKES

| Subscore | r | Strength | Direction | Interpretation |
|----------|---|----------|-----------|----------------|
| **Engagement** | **0.875** | **Very Strong** | ✅ Positive | Engagement uses likes in calculation |
| **Hook** | **0.737** | **Strong** | ✅ Positive | **Better hooks → more likes!** |
| Story | 0.394 | Weak | ✅ Positive | Better story → more likes |
| Overall | 0.348 | Weak | ✅ Positive | Higher score → more likes |
| Visuals | 0.305 | Weak | ✅ Positive | Better visuals → more likes |
| Shareability | 0.167 | Very weak | ✅ Positive | Weak correlation |
| Relatability | 0.086 | Very weak | ✅ Positive | Almost no correlation |
| Watchtime | 0.004 | Very weak | ✅ Positive | No correlation |
| Algorithm | -0.258 | Weak | ⚠️ Negative | Better algo → FEWER likes! |
| Audio | nan | - | - | All scores identical |

---

## Key Findings

### ✅ What Actually Works

1. **Hook Score strongly predicts likes (r=0.737)**
   - This is a REAL signal!
   - Videos with better hooks get significantly more likes
   - Validates our hook scoring methodology

2. **Story Score moderately predicts views (r=0.523)**
   - Better story structure → more views
   - Narrative arc matters for view count
   - Story scoring is on the right track

3. **Engagement Score strongly predicts likes (r=0.875)**
   - Expected (engagement score uses like count in calculation)
   - Confirms our engagement calculation is working

### ⚠️ What Doesn't Work (MAJOR ISSUES)

1. **Algorithm Score negatively correlates with views (r=-0.390)**
   - **This is backwards!**
   - Our "algorithm optimization" (hashtags, caption length, posting time) predicts FEWER views
   - Possible explanations:
     - We're measuring the wrong algo factors
     - Optimal hashtag count (3-6) might be wrong for TikTok
     - Posting time analysis is flawed
     - Over-optimized content looks spammy

2. **Shareability Score negatively correlates with views (r=-0.315)**
   - **Also backwards!**
   - Videos we score as "shareable" get fewer views
   - Possible explanations:
     - Our shareability signals are wrong (caption length, CTA detection)
     - Save-worthy estimation is flawed
     - What we think is shareable isn't what users actually share

3. **Relatability Score weak/negative correlation**
   - r=-0.221 for views, r=0.086 for likes
   - Follower count (our main relatability signal) doesn't predict virality
   - Small accounts can go just as viral as big accounts

4. **Audio Score has no variance (all 47.5)**
   - Can't measure correlation because all videos have same score
   - Confirms we need actual audio analysis (trending sounds, beat sync)

5. **Overall Score barely predicts views (r=0.108)**
   - Our composite score doesn't predict viral performance
   - Suggests our weights are significantly off

---

## Statistical Limitations

### Sample Size Issues

**Current:** n=14
**Recommended minimum:** n≥30 for reliable correlations
**Ideal:** n≥100 for detecting moderate effects

**Statistical Power:**
- **Can detect:** r > 0.7 (strong correlations only)
- **Cannot reliably detect:** r = 0.3-0.6 (moderate correlations)
- **Will miss:** r < 0.3 (weak correlations)

**What this means:**
- The r=0.737 (hook→likes) is likely real (strong enough to detect)
- The r=0.523 (story→views) is promising but needs more data to confirm
- The negative correlations (algo, shareability) are concerning but need verification
- Weak correlations (<0.3) might exist but we can't see them

### Interpretation Caveats

⚠️ **These results are EXPLORATORY, not conclusive**

With n=14:
- False positives are possible
- True effects might be missed
- Effect sizes could be over/underestimated
- Patterns may not hold with more data

**Required for confident conclusions:**
- **Moderate effects (r=0.4-0.6):** Need n≥30
- **Weak effects (r=0.3-0.4):** Need n≥85
- **Very weak effects (r=0.2-0.3):** Need n≥200

---

## Implications for Scorer

### If Patterns Hold with More Data...

**1. Algorithm Score needs major rework**
- Current: Hashtag count (3-6), caption length, posting time
- Problem: Negatively correlates with views
- Fix options:
  - Remove from scorer entirely
  - Investigate what TikTok actually rewards
  - Add trending hashtag detection
  - Add soundtracking analysis

**2. Shareability Score needs rework**
- Current: Caption length, CTA detection, save estimation
- Problem: Negatively correlates with views
- Fix options:
  - Reverse scoring logic
  - Find what actually makes videos shareable
  - Look at emotional triggers, not just CTAs

**3. Relatability Score needs adjustment**
- Current: Heavily based on follower count
- Problem: Follower count doesn't predict virality
- Fix options:
  - Reduce weight significantly (0.10 → 0.05)
  - Focus on content relatability, not creator size
  - Add niche targeting analysis

**4. Hook Score is working!**
- Current: Duration, text, type, effectiveness
- Status: Strong predictor of likes ✅
- Action: Keep methodology, maybe increase weight

**5. Story Score is working!**
- Current: Storyboard, beats, arc detection
- Status: Moderate predictor of views ✅
- Action: Keep methodology, validate with more data

**6. Audio Score needs implementation**
- Current: All videos score 47.5 (defaults)
- Problem: Can't measure impact because no variance
- Fix options:
  - Integrate TikTok API for sound metadata
  - Add trending sound detection
  - Implement beat sync analysis

### Proposed Weight Adjustments (if patterns hold)

**Current (v1.0.0):**
```typescript
hook: 0.20
story: 0.15
relatability: 0.10
visuals: 0.10
audio: 0.10
watchtime: 0.15
engagement: 0.10
shareability: 0.05
algo: 0.05
```

**Proposed (v1.1.0) - PENDING MORE DATA:**
```typescript
hook: 0.25        // ↑ Increase (strong predictor)
story: 0.20       // ↑ Increase (moderate predictor)
relatability: 0.05 // ↓ Reduce (weak/negative)
visuals: 0.10     // = Keep (weak positive)
audio: 0.15       // ↑ Increase (need real data first)
watchtime: 0.10   // ↓ Reduce (no correlation)
engagement: 0.10  // = Keep (but already uses likes)
shareability: 0.02 // ↓ Reduce (negative correlation!)
algo: 0.03        // ↓ Reduce (negative correlation!)
```

**Rationale:**
- Boost hook/story (proven predictors)
- Drastically reduce algo/shareability (negative correlations)
- Reduce relatability (no predictive power)
- Maintain audio for future implementation
- Reduce watchtime (no current correlation)

---

## Why the Negative Correlations?

### Hypothesis 1: Over-Optimization is Spammy
**Theory:** Videos that are "too optimized" look like spam to TikTok's algorithm.

**Evidence:**
- Algo score (hashtags, captions) negatively correlates with views
- Shareability score (CTAs) negatively correlates with views
- Authentic, less-optimized content might perform better

**Test:** Compare high-algo-score videos vs. low-algo-score videos manually

### Hypothesis 2: We're Measuring the Wrong Factors
**Theory:** Our assumptions about what TikTok rewards are incorrect.

**Evidence:**
- Industry advice says "use 3-6 hashtags" but that might be outdated
- Posting time analysis assumes EST, but TikTok is global
- CTA detection might penalize videos instead of helping

**Test:** Research actual TikTok algorithm preferences in 2025

### Hypothesis 3: Small Sample Bias
**Theory:** The 14 videos aren't representative; patterns will disappear with more data.

**Evidence:**
- n=14 is very small
- Correlations could be driven by 1-2 outliers
- Need n≥30 to rule out random noise

**Test:** Collect 100+ videos and re-run analysis

### Hypothesis 4: Survivorship Bias
**Theory:** We're only analyzing videos that already went viral (100K+ views).

**Evidence:**
- All 14 videos have 100K+ views (scraped with min_views filter)
- Missing low-performing videos for comparison
- Can't see what separates viral from non-viral

**Test:** Scrape videos without view filters (get full range)

---

## Data Collection Issues

### Apify TikTok Scraper Status

**Problem:** As of October 8, 2025, keyword search returns empty results.

**Evidence:**
```
search_item_list: null
search_nil_info: { search_nil_item: 'invalid_count' }
```

**Attempted searches (all failed):**
- "dog supplements" (count: 100)
- "dog health" (count: 50)
- "dogs" (count: 100)

**Timeline:**
- **October 7:** Scraper working (14 videos scraped successfully)
- **October 8:** Scraper broken (all searches return null)

**Possible causes:**
1. TikTok API changes (likely)
2. Apify actor needs update
3. Rate limiting (temporary)
4. Account quota exceeded

**Resolution:**
- Wait 24 hours and retry
- Contact Apify support if persists
- Consider alternative scraping methods

---

## Next Steps

### Tomorrow (October 9, 2025)

**1. Retry TikTok Scraping**

Test if Apify scraper is working again:
```bash
vt tiktok search "dogs" --count 10 --project wonder-paws-tiktok --save
```

If successful, proceed to step 2. If failed, wait another day or contact Apify.

**2. Collect 100-200 Videos**

Target search terms (dog wellness niche):
```bash
# Broad terms (50 each)
vt tiktok search "dogs" --count 50 --project wonder-paws-tiktok
vt tiktok search "dog health" --count 50 --project wonder-paws-tiktok

# Specific terms (25 each)
vt tiktok search "dog supplements" --count 25 --project wonder-paws-tiktok
vt tiktok search "pet wellness" --count 25 --project wonder-paws-tiktok
vt tiktok search "dog nutrition" --count 25 --project wonder-paws-tiktok
vt tiktok search "holistic dog care" --count 25 --project wonder-paws-tiktok
```

**Filters:**
- Min views: 50K (lower than 100K to get more variety)
- Max days: 30 (more recent content)
- Max followers: 500K (include mid-tier creators)

**3. Remove View Filters for Some Searches**

To test Hypothesis 4 (survivorship bias), collect some low-view videos:
```bash
vt tiktok search "dogs" --count 25 --min-views 1000 --max-days 7
```

**4. Process Videos**
```bash
# Download videos
vt process videos --project wonder-paws-tiktok

# Analyze with Gemini
vt analyze videos --project wonder-paws-tiktok

# Score all videos
vt score videos --project wonder-paws-tiktok
```

**5. Re-run Correlation Analysis**

With 114-214 total videos:
- Re-run correlation analysis
- Compare to n=14 results
- Look for pattern changes
- Identify which correlations were real vs. noise

**6. Adjust Scorer Weights**

If negative correlations persist:
- Implement v1.1.0 weights
- Re-score all videos with new weights
- Compare v1.0.0 vs v1.1.0 predictions

---

## Expected Timeline

### Phase 6.4: Expanded Correlation Analysis

**Day 1 (Tomorrow):**
- Test scraper (5 min)
- Collect 100-200 videos (30 min)
- Process videos (1 hour)
- Analyze with Gemini (3-5 hours)
- Score all videos (5 min)

**Day 2:**
- Run expanded correlation analysis
- Generate insights report
- Propose weight adjustments
- Document findings

**Day 3:**
- Implement v1.1.0 weights
- Re-score all videos
- Compare performance
- Finalize recommendations

---

## Questions to Answer

### With Expanded Dataset

1. **Do negative correlations persist?**
   - If yes → Major scorer redesign needed
   - If no → n=14 was just noise/outliers

2. **Does hook score remain strong predictor?**
   - If yes → Validate hook methodology
   - If no → Re-examine hook scoring

3. **Does story score strengthen?**
   - If yes (r>0.6) → Increase story weight
   - If weakens (r<0.3) → Re-examine story scoring

4. **What actually predicts views?**
   - Look for new patterns
   - Identify missing factors
   - Consider external variables (trending sounds, challenges)

5. **Does view count range affect correlations?**
   - Compare high-view vs. low-view videos
   - Check for non-linear relationships
   - Look for threshold effects

---

## Success Criteria for Phase 6.4

- [ ] Collect 100+ additional videos
- [ ] Process and analyze all videos
- [ ] Score all videos with v1.0.0
- [ ] Re-run correlation analysis (n≥100)
- [ ] Identify statistically significant patterns
- [ ] Propose evidence-based weight adjustments
- [ ] Implement v1.1.0 if warranted
- [ ] Document findings and recommendations

---

## Files Reference

**Data Export:**
- `wonder-paws-scores.csv` - Current 14 video scores

**Analysis Scripts:**
- Run correlation: See PHASE_6.3_COMPLETE.md for code

**Related Documentation:**
- PHASE_6.1_COMPLETE.md - Scorer implementation
- PHASE_6.2_COMPLETE.md - Python integration
- PHASE_6.3_COMPLETE.md - Batch scoring & analysis

---

## Appendix: Full Correlation Data

### Views Correlations (Sorted by |r|)

1. story_score: r=0.523 (moderate, positive)
2. algo_score: r=-0.390 (weak, negative) ⚠️
3. engagement_score: r=0.332 (weak, positive)
4. visuals_score: r=0.318 (weak, positive)
5. shareability_score: r=-0.315 (weak, negative) ⚠️
6. hook_score: r=0.281 (weak, positive)
7. relatability_score: r=-0.221 (weak, negative) ⚠️
8. overall_score: r=0.108 (very weak, positive)
9. watchtime_score: r=-0.033 (very weak, negative)
10. audio_score: nan (no variance)

### Likes Correlations (Sorted by |r|)

1. engagement_score: r=0.875 (very strong, positive)
2. hook_score: r=0.737 (strong, positive) ⭐
3. story_score: r=0.394 (weak, positive)
4. overall_score: r=0.348 (weak, positive)
5. visuals_score: r=0.305 (weak, positive)
6. algo_score: r=-0.258 (weak, negative) ⚠️
7. shareability_score: r=0.167 (very weak, positive)
8. relatability_score: r=0.086 (very weak, positive)
9. watchtime_score: r=0.004 (very weak, positive)
10. audio_score: nan (no variance)

---

**Status:** Analysis complete, awaiting more data
**Next Action:** Retry scraping tomorrow (October 9, 2025)
**Goal:** Collect 100-200 videos for robust correlation analysis

---

**Phase 6.3 Addendum: COMPLETE ✅**
**Phase 6.4: PENDING DATA COLLECTION**
