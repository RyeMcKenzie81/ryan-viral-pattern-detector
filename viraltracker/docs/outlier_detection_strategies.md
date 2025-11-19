# Outlier Detection Strategies

## Overview

ViralTracker uses different outlier detection strategies depending on the data source and analysis goal.

## User/Creator Tracking (Instagram & TikTok)

**Use Case:** Analyzing posts from a single creator's account

**Method:** Statistical outlier detection using trimmed mean

**Algorithm:**
1. Fetch posts from user in specified time frame (e.g., last 30 days or last 50 posts)
2. Calculate **trimmed mean** for key metrics (views, likes, comments, shares)
   - Remove top/bottom 10% to eliminate statistical noise
3. Calculate **standard deviation** (SD)
4. Identify outliers: Posts with metrics **3 SD above trimmed mean**

**Rationale:**
- Each creator has different baseline engagement based on follower count
- Relative performance matters more than absolute numbers
- Finds content that **overperformed for that specific creator**
- Reveals what resonated more than their typical content

**Example:**
- Creator A (10K followers): Average 500 likes/post → 2K likes = outlier
- Creator B (1M followers): Average 50K likes/post → 2K likes = poor performance

---

## Keyword/Hashtag Search - Multiple Options

**Use Case:** Searching for viral content across multiple creators

### Option 1: Absolute Ranking
**Method:** Sort by raw metrics (views, likes, shares, comments)

**Pros:**
- Simple to implement
- Finds biggest viral hits

**Cons:**
- Biases toward large creators
- Misses high-quality content from smaller accounts

---

### Option 2: Engagement Rate Analysis (Statistical)
**Method:** Calculate engagement rates and use statistical outlier detection

**Algorithm:**
1. Calculate engagement rates: `likes/views`, `comments/views`, `shares/views`
2. Calculate trimmed mean of engagement rates across all search results
3. Find posts with engagement rates **3 SD above trimmed mean**

**Pros:**
- Normalizes for creator size
- Finds high-quality engagement regardless of follower count
- Statistical rigor

**Cons:**
- Small creators with low views can have high percentages
- May miss content with massive reach but "normal" engagement rate

---

### Option 3: Hybrid Score
**Method:** Combine absolute engagement + engagement rate

**Formula Example:**
```
score = (views * 0.3) + (engagement_rate * 0.7)
```

**Pros:**
- Balances reach and quality
- Customizable weights

**Cons:**
- More complex
- Weight tuning required

---

### Option 4: Tiered Filtering (Multi-Stage)
**Method:** Apply sequential filters

**Algorithm:**
1. **Filter 1:** Minimum view threshold (e.g., 10K+ views)
2. **Filter 2:** High engagement rate (top 10% of results)
3. Optional: Additional filters (recency, creator size)

**Pros:**
- Ensures minimum reach AND quality
- Highly customizable

**Cons:**
- May miss emerging viral content
- Filter thresholds need tuning per platform

---

## Current Implementation

### TikTok Keyword/Hashtag Search (Implemented)

**Strategy:** Custom filtering criteria to find micro-influencer viral content

**Filters:**
1. **Views:** Must have over 100,000 views (proven viral reach)
2. **Recency:** Must be less than 10 days old (current trends)
3. **Creator Size:** Account must have less than 50,000 followers (micro-influencer)

**Rationale:**
- Targets content that went viral from **smaller creators**
- More achievable/replicable for typical users
- Fresh, trending content
- Filters out mega-influencer content (different dynamics)

**Use Case:** Find what works for creators similar to your size/reach

---

### Instagram User Tracking (Implemented)

**Strategy:** Statistical outlier detection (3 SD from trimmed mean)

**Implementation:** See `viraltracker/services/outlier_detector.py`

---

## Future Considerations

### Platform-Specific Adjustments

**TikTok vs Instagram:**
- TikTok algorithm favors recency more heavily → shorter time windows
- TikTok has explicit "shares" metric → may be strong signal
- Instagram Reels: "saves" metric may indicate high-value content

### Multi-Metric Scoring

Could combine multiple signals:
```python
viral_score = (
    views_zscore * 0.3 +
    likes_zscore * 0.25 +
    comments_zscore * 0.2 +
    shares_zscore * 0.15 +
    engagement_rate_zscore * 0.1
)
```

### Machine Learning Approach

Future enhancement: Train classifier on historical viral content to predict viral potential

---

## References

- Z-score (standard score): `(x - mean) / std_dev`
- Trimmed mean: Mean after removing outliers (top/bottom 10%)
- 3-sigma rule: ~99.7% of data falls within 3 SD in normal distribution
