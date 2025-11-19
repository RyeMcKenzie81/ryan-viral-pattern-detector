# CORRECTED Search Term Analysis Results - Yakety Pack Instagram Project

**Date**: October 23, 2025
**Project**: yakety-pack-instagram
**Status**: ⚠️ **ORIGINAL ANALYSIS INVALID - MAJOR BUG FOUND**

---

## Critical Issue Discovered

**The original batch analysis is completely invalid due to a major bug in the analyzer code.**

### The Bug

Located in `viraltracker/analysis/search_term_analyzer.py` lines 242-249:

```python
result = self.db.table('posts')\
    .select('...')\
    .eq('platform_id', platform_id)\
    .eq('project_posts.project_id', self.project_id)\  # ← Only filters by project!
    .gte('posted_at', cutoff_date.isoformat())\
    .order('posted_at', desc=True)\
    .limit(count)\  # ← Takes first 1000 tweets
    .execute()
```

**Problem**: After scraping tweets for a specific search term, the analyzer queries the database but:
1. Does NOT filter by search term
2. Just grabs the 1000 most recent tweets for the project
3. Result: **ALL 15 analyses used the EXACT SAME 1000 tweets**

### What Actually Happened

1. **Apify scraping**: Each search term scraped fresh tweets (varying counts: 21 to 1000)
2. **Database query**: Every analysis ignored the search term and pulled the same 1000 tweets
3. **Analysis**: All 15 JSON reports show identical score distributions because they analyzed identical tweets

**Database stats**:
- Total tweets in DB (last 7 days): 13,462
- Tweets analyzed per term: 1000 (the same 1000 each time)
- Unique tweets across all "15 analyses": **1000 total** (not 15,000!)

---

## Actual Apify Scrape Results

Based on Apify dashboard and batch log timestamps, here are the REAL scrape results:

| Rank | Search Term | Fresh Tweets | Daily Est. | Duration | Time Started |
|------|-------------|--------------|------------|----------|--------------|
| 1 | parenting tips | ~1000 | ~143/day | 1m 40s | 13:32 |
| 2 | kids technology | 1000 | 143/day | 1m 40s | 14:19 |
| 3 | mindful parenting | 1000 | 143/day | 1m 40s | 14:21 |
| 4 | tech boundaries | 165 | 24/day | 20s | 13:45 |
| 5 | screen time rules | 149 | 21/day | 17s | 14:06 |
| 6 | online safety kids | 121 | 17/day | 19s | 13:48 |
| 7 | family routines | 90 | 13/day | 12s | 13:57 |
| 8 | digital parenting | 76 | 11/day | 15s | 13:54 |
| 9 | device limits | 31 | 4/day | 7s | 14:21 |
| 10 | kids social media | 21 | 3/day | 7s | 13:51 |
| ? | digital wellness | ? | ? | ? | 13:37 |
| ? | screen time kids | ? | ? | ? | 13:27 |
| ? | kids screen time | ? | ? | ? | 13:42 |
| ? | parenting advice | ? | ? | ? | 13:47 |
| ? | toddler behavior | ? | ? | ? | 13:52 |

**Note**: 5 terms have unknown Apify results (likely 1000 or low volume based on timing patterns)

### Volume Tiers

**High Volume** (≥1000 tweets/week = ~143/day):
- parenting tips
- kids technology
- mindful parenting
- (possibly: digital wellness, screen time kids)

**Medium Volume** (100-200 tweets/week = 14-29/day):
- tech boundaries: 165 tweets (24/day)
- screen time rules: 149 tweets (21/day)
- online safety kids: 121 tweets (17/day)

**Low Volume** (<100 tweets/week = <14/day):
- family routines: 90 tweets (13/day)
- digital parenting: 76 tweets (11/day)
- device limits: 31 tweets (4/day)
- kids social media: 21 tweets (3/day)

---

## What This Means

### Original Report Claims (INVALID)
- ✗ "Analyzed 15,000 tweets total"
- ✗ "Each term analyzed 1000 tweets"
- ✗ "All 15 terms rated Poor (0.1-0.7% green)"
- ✗ "Score distribution varied by term"
- ✗ "Topic distribution varied by term"

### Actual Reality
- ✓ Analyzed **1000 unique tweets total** (same 1000, 15 times)
- ✓ Fresh scrapes ranged from 21 to 1000 tweets per term
- ✓ Only 3-5 terms found high volume (≥1000 tweets/week)
- ✓ 4 terms have very low volume (<100 tweets/week)
- ✓ Cannot determine actual score quality per search term
- ✓ Cannot determine actual topic distribution per search term

---

## Corrected Findings

### 1. Search Term Volume (VERIFIED via Apify)

**Conclusion**: There is HUGE variance in tweet volume by search term:
- Top terms: ~140 tweets/day (abundant)
- Bottom terms: ~3-4 tweets/day (scarce)

**Implication**:
- Use high-volume terms ("parenting tips", "kids technology") for regular sourcing
- Low-volume terms not viable for consistent daily comment generation

### 2. Score Quality (UNKNOWN - Needs Re-testing)

**We don't know**:
- Which search terms produce higher-scoring tweets
- Whether any terms reach ≥8% green threshold
- Topic distribution per search term

**Reason**: All analyses used the same 1000 tweets, so we can't compare terms

### 3. The One Valid Data Point

From the 1000 tweets that were analyzed (15 times):
- **0.31% green overall** (aggregated across all 15 identical analyses)
- These 1000 tweets came from the database's most recent tweets
- They represent a mix of all 15 search terms combined

**Interpretation**: The combined pool of recent tweets from all search terms has a 0.31% green rate. This suggests:
- Either the taxonomy is misaligned with Twitter content
- Or the 0.55 threshold is too strict
- Or both

---

## Next Steps - How to Fix This

### Immediate: Fix the Analyzer Bug

The `_scrape_tweets` method needs to:
1. Store search term metadata with tweets in the database
2. Filter database query by search term when fetching tweets
3. Or: Only return tweets from the fresh Apify scrape (don't pad with old tweets)

**Recommended fix**: Add search term tracking to the database schema and filter by it.

### Short-term: Re-run Valid Analysis

Once the bug is fixed:
1. **Test 3-5 high-volume terms only**:
   - parenting tips
   - kids technology
   - mindful parenting
   - digital wellness (if high volume)
   - screen time kids (if high volume)

2. **Use realistic counts**:
   - High-volume terms: 500-1000 tweets
   - Medium-volume terms: 100-200 tweets
   - Don't test low-volume terms (<100/week)

3. **Fresh tweets only**:
   - Clear database or add timestamp filter
   - Ensure each analysis uses only its own fresh scrape

### Medium-term: Taxonomy Investigation

Even with valid data, the 0.31% green rate suggests fundamental issues:

**Option A: Analyze the 1000 tweets we DO have**
- We know these 1000 tweets scored 0.31% green
- Manually review the ~3 green tweets to see what makes them score high
- Review samples of yellow tweets (86-92% of total)
- This can inform taxonomy improvements

**Option B: Lower the threshold**
- Test 0.50 or 0.45 instead of 0.55
- Re-score the existing 1000 tweets
- See if quality is acceptable at lower threshold

**Option C: Revise taxonomy**
- Based on manual review, rewrite the 3 topic descriptions
- Focus on matching how people actually talk on Twitter
- Re-test with high-volume search terms

---

## Recommended Focus Terms

Based on actual Apify volume data:

### Tier 1: Primary Terms (High Volume)
1. **parenting tips** - 1000 tweets/week, ~143/day
2. **kids technology** - 1000 tweets/week, ~143/day
3. **mindful parenting** - 1000 tweets/week, ~143/day

**Use these for**:
- Daily comment generation
- Regular content sourcing
- Primary taxonomy testing

### Tier 2: Secondary Terms (Medium Volume)
4. **tech boundaries** - 165 tweets/week, ~24/day
5. **screen time rules** - 149 tweets/week, ~21/day
6. **online safety kids** - 121 tweets/week, ~17/day

**Use these for**:
- Supplemental sourcing
- Topic diversity
- Weekly batches (not daily)

### Tier 3: Not Recommended (Low Volume)
- family routines - 13/day
- digital parenting - 11/day
- device limits - 4/day
- kids social media - 3/day

**Skip these**: Too low volume for consistent use

---

## Cost Analysis (Corrected)

**Actual cost**: $0.00
- Only embeddings were used (negligible cost)
- No comments generated (--skip-comments flag)

**If we had generated comments** (hypothetically):
- Based on faulty 15,000 tweet claim: ~$1.65
- Based on actual 1000 unique tweets: ~$0.11
- With 0.31% green rate: 3 green tweets with comments
- **Cost per green**: ~$0.037 (terrible efficiency)

This reinforces that we need better scoring before generating comments at scale.

---

## Technical Debt Created

### Files with Invalid Data
1. `~/Downloads/term_analysis/*_analysis.json` (15 files) - All invalid
2. `SEARCH_TERM_TEST_RESULTS.md` - Based on invalid data
3. `batch_log.txt` - Misleading "Scraped 1000 tweets" messages

### Code that Needs Fixing
1. `viraltracker/analysis/search_term_analyzer.py:242-249` - Add search term filter
2. Database schema - Consider adding `search_term` field to `posts` table
3. TwitterScraper - Should report actual vs. padded tweet counts

### Documentation Needed
1. How search term analysis actually works
2. Database query patterns
3. When tweets get padded from DB vs. fresh scrape

---

## Summary

### What We Learned (Despite the Bug)

1. **Volume varies dramatically**: 3/day to 143/day depending on search term
2. **High-volume terms exist**: 3-5 terms can support daily comment generation
3. **Low-volume terms not viable**: 4+ terms have <14 tweets/day
4. **Taxonomy/threshold issue**: Even mixed pool shows only 0.31% green
5. **Analyzer has major bug**: Doesn't actually compare search terms

### What We Still Don't Know

1. Which search terms produce highest-quality tweets
2. Whether any single term reaches ≥8% green
3. How topic distribution varies by search term
4. Whether fresh tweets score better than the database pool

### The Path Forward

1. **Fix the analyzer bug** (add search term filtering)
2. **Focus on 3-5 high-volume terms** (parenting tips, kids technology, mindful parenting)
3. **Investigate the taxonomy mismatch** (0.31% is way too low)
4. **Re-run with corrected analyzer** once fixed
5. **Consider alternative approaches** (lower threshold, revised taxonomy, different platforms)

---

**Analysis completed**: October 23, 2025, 15:00
**Analyst**: Claude Code
**Status**: Invalid - Major bug discovered
**Report location**: `/Users/ryemckenzie/projects/viraltracker/CORRECTED_SEARCH_TERM_RESULTS.md`
