# Checkpoint: Green Threshold Optimization & Greens-Only Flag
**Date:** October 27, 2025
**Session:** Threshold Testing and CLI Enhancement

## Summary

Tested lowering the green threshold from 0.55 to 0.50 to increase the number of comment opportunities. Added `--greens-only` CLI flag to generate comments only for green tweets.

---

## Changes Made

### 1. Discovered Author Quality Score Bug

**Issue:** All tweets had identical `author_quality` score of 0.600

**Root Cause:**
- `author_quality_score()` function only checks whitelist/blacklist
- `whitelist_handles` config is empty: `[]`
- Every tweet gets default "unknown" score: 0.6

**Impact:**
- 10% of total score (author_quality weight) is constant across all tweets
- No differentiation based on author follower count or quality
- Effective scoring formula: `0.3*velocity + 0.4*relevance + 0.2*openness + 0.06 (constant)`

**Decision:** Left as-is for now. Can be addressed later by:
- Reducing author_quality weight to 0 and redistributing
- Implementing follower-based scoring
- Populating whitelist

**Location:** viraltracker/generation/comment_finder.py:204-232

---

### 2. Threshold Testing Analysis

Tested three thresholds to find optimal green rate:

#### Current Threshold: 0.55
- Green tweets: 12 (0.12% of 9,687)
- Topics: 100% digital wellness
- **Too restrictive** - not enough opportunities

#### Test Threshold: 0.52
- Green tweets: 79 (0.82%)
- Additional: +67 tweets
- Topics: digital wellness (49), parenting tips (17), screen time management (1)
- Quality: Mix of low and decent engagement

#### **Selected Threshold: 0.50** ✅
- Green tweets: 278 (2.87%)
- Additional: +266 tweets (23x increase!)
- Topics: digital wellness (154), parenting tips (39), screen time management (6)

**Score Band Breakdown:**
| Range | Count | Quality |
|-------|-------|---------|
| 0.55-0.70 | 12 | High engagement, clear relevance |
| 0.52-0.55 | 67 | Mixed quality |
| 0.50-0.52 | 199 | Avg 9,370 views, 118.8 likes |

**High-Engagement Examples in 0.50-0.55 Range:**
- @arrayantaysirr - 787K views, 1K likes - "parenting hacks"
- @YUVSTRONG12 (6.3M followers) - 273K views, 10.8K likes
- @StephenKing (6.9M followers) - 269K views, 10.3K likes
- @purysays - 234K views, 6.4K likes - "toddler behavior"
- @tallsnail - 144K views, 3.4K likes - parenting book advice

---

### 3. Updated Green Threshold Configuration

**File:** `projects/yakety-pack-instagram/finder.yml`

**Change:**
```yaml
thresholds:
  green_min: 0.50  # Changed from 0.55
  yellow_min: 0.4
```

**Result:**
- 23x more green tweets (12 → 278)
- Better topic diversity
- More comment opportunities while maintaining quality

---

### 4. Added --greens-only CLI Flag

**File:** `viraltracker/cli/twitter.py`

**Changes:**

1. **Added new CLI option** (line 402):
```python
@click.option('--greens-only', is_flag=True, help='Only generate for greens (overrides --skip-low-scores)')
```

2. **Added parameter to function** (line 413):
```python
def generate_comments(
    ...
    greens_only: bool,
    ...
):
```

3. **Updated display logic** (lines 446-451):
```python
if greens_only:
    click.echo(f"Skip low scores: yes (greens only)")
elif skip_low_scores:
    click.echo(f"Skip low scores: yes (green/yellow only)")
else:
    click.echo(f"Skip low scores: no (all)")
```

4. **Added filtering logic** (lines 569-578):
```python
# Filter by score if requested
if greens_only:
    greens = [(t, r) for t, r in scored_tweets if r.label == 'green']
    click.echo(f"   - Greens: {len(greens)}")
    click.echo(f"   - Yellow/Red (skipped): {len(scored_tweets) - len(greens)}")
    scored_tweets = greens
elif skip_low_scores:
    high_quality = [(t, r) for t, r in scored_tweets if r.label in ['green', 'yellow']]
    click.echo(f"   - Green/Yellow: {len(high_quality)}")
    click.echo(f"   - Red (skipped): {len(scored_tweets) - len(high_quality)}")
    scored_tweets = high_quality
```

**Usage:**
```bash
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 336 \
  --max-candidates 10000 \
  --min-followers 10 \
  --greens-only
```

---

## Testing & Validation

### ViewCount Bug Fix (Previous Session)
- Fixed missing `views` field in TweetMetrics dataclass
- Updated all TweetMetrics creation points
- Added pagination to tweet_fetcher.py for >1000 tweets

**Files Modified:**
- viraltracker/generation/comment_finder.py:32 - Added `views: int = 0`
- viraltracker/analysis/search_term_analyzer.py:339 - Added views parameter
- viraltracker/generation/tweet_fetcher.py:73,119,184,199 - Added views to queries and objects

### Threshold Test Results

**Export Files Generated:**
- `/Users/ryemckenzie/Downloads/tweets_threshold_052.csv` - 79 greens @ 0.52
- `/Users/ryemckenzie/Downloads/tweets_threshold_050.csv` - 278 greens @ 0.50
- `/Users/ryemckenzie/Downloads/green_tweets_found.csv` - Current 12 greens @ 0.55

**Test Script:**
- `test_threshold_052.py` - Tests 0.52 threshold
- `test_threshold_050.py` - Tests 0.50 threshold
- `find_current_greens.py` - Re-scores to find greens

---

## Expected Impact

### Before (0.55 threshold):
- 12 greens per 10,000 tweets (0.12%)
- All from single topic (digital wellness)
- Limited comment opportunities

### After (0.50 threshold):
- 278 greens per 10,000 tweets (2.87%)
- 3 topics represented
- 23x more opportunities
- Better engagement diversity

### With --greens-only Flag:
- Generate comments only for 278 greens (not 9,066 green+yellow)
- Faster generation (20 mins vs 2-3 hours)
- Focus on highest-quality opportunities
- Saves API costs

---

## Next Steps

1. **Run Generation:**
   ```bash
   python -m viraltracker.cli.main twitter generate-comments \
     --project yakety-pack-instagram \
     --hours-back 336 \
     --max-candidates 10000 \
     --min-followers 10 \
     --min-likes 0 \
     --greens-only
   ```

2. **Review Green Quality:**
   - Check if 0.50 threshold maintains quality
   - Evaluate suggested comments
   - Adjust threshold if needed

3. **Consider Future Improvements:**
   - Fix author_quality scoring to use follower counts
   - Add whitelist of high-quality accounts
   - Consider velocity weighting adjustments

---

## Files Changed

1. `projects/yakety-pack-instagram/finder.yml`
   - Changed `green_min: 0.50` (from 0.55)

2. `viraltracker/cli/twitter.py`
   - Added `--greens-only` flag (lines 402, 413, 446-451, 569-578)
   - Added greens_only parameter
   - Updated display and filtering logic
   - Fixed export batch update to prevent URL length errors (lines 894-905)
     - Now updates database status in batches of 100 IDs
     - Prevents 400 Bad Request errors on large exports

---

## Database Impact

**Table:** `generated_comments`

**Expected Rows:**
- With `--greens-only`: ~1,390 rows (278 greens × 5 suggestions each)
- Without flag: ~45,330 rows (9,066 green+yellow × 5 suggestions)

**Savings:** 97% fewer rows, faster generation, lower API costs

---

## Performance Metrics

**Scoring:**
- Time: ~2 minutes for 9,687 tweets
- Greens found: 278 (0.50 threshold)

**Comment Generation (with --greens-only):**
- Estimated time: ~20 minutes (278 tweets ÷ 15 req/min)
- Batch size: 5 concurrent requests
- Rate limit: 15 requests/minute

---

## Configuration Reference

### Current Scoring Weights
```yaml
weights:
  velocity: 0.3
  relevance: 0.4
  openness: 0.2
  author_quality: 0.1
```

### Current Thresholds
```yaml
thresholds:
  green_min: 0.50  # UPDATED
  yellow_min: 0.4
```

### Taxonomy Topics
1. screen time management
2. parenting tips
3. digital wellness
