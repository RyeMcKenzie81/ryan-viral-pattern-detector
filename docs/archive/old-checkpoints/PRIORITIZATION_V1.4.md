# Comment Finder V1.4: Export Prioritization

**Release Date**: October 28, 2025
**Feature**: Intelligent tweet prioritization for CSV exports

## Overview

Added configurable prioritization to the `export-comments` CLI command to help optimize which tweets to engage with first. The system supports three different sorting strategies based on different engagement goals.

## What Changed

### New CLI Parameter: `--sort-by`

```bash
--sort-by [score|views|balanced]  # Default: balanced
```

**Three Sorting Options**:

1. **`score`** - Quality/relevance focus
   - Prioritizes tweets with highest relevance scores
   - Best for: Brand alignment, topic relevance
   - Priority formula: `score_total`

2. **`views`** - Maximum reach focus
   - Prioritizes tweets with most views
   - Best for: Pure visibility, viral opportunities
   - Priority formula: `views`

3. **`balanced`** - Quality × Reach (DEFAULT)
   - Balances relevance and reach for best ROI
   - Best for: Most use cases, efficient time investment
   - Priority formula: `score_total × √views`

### New CSV Columns

Two new columns added to all exports:

- **`rank`**: Sequential ranking (1, 2, 3, etc.)
- **`priority_score`**: Calculated priority value based on sort method

### Updated CSV Structure

```csv
rank,priority_score,project,tweet_id,url,author,followers,views,tweet_text,posted_at,score_total,label,topic,why,suggested_response,suggested_type,alternative_1,alt_1_type,alternative_2,alt_2_type,alternative_3,alt_3_type,alternative_4,alt_4_type
1,447.2,yakety-pack-instagram,1980618893837365632,...
2,231.02,yakety-pack-instagram,1981859951971868758,...
```

## Usage Examples

### Default: Balanced (Recommended)

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/prioritized_comments.csv \
  --status pending \
  --greens-only
```

### Quality Focus

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/quality_comments.csv \
  --status pending \
  --sort-by score \
  --greens-only
```

### Maximum Reach Focus

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/viral_comments.csv \
  --status pending \
  --sort-by views \
  --greens-only
```

## Why Balanced (Default)?

Analysis of 58 tweets from the 48-hour keyword scrape showed:

### Score-Only Approach Issues
- Missed high-reach opportunities
- Some high-scoring tweets had <10 views
- Limited potential impact

### Views-Only Approach Issues
- Could include off-brand content
- Lower relevance scores (some as low as 0.50)
- Risk of inconsistent messaging

### Balanced Approach Benefits
✅ All top 10 had both good scores (0.51-0.59) AND reach (5K-150K views)
✅ Best ROI: Quality engagement with meaningful reach
✅ Optimal time investment

**Top 3 from Balanced Sort**:
1. @bradleywhitford - Priority: 217.43 (0.59 score × 887 √views)
2. @cmoncheeeeks - Priority: 194.44 (0.58 score × 459 √views)
3. @enhaclerc - Priority: 160.20 (0.55 score × 399 √views)

## Implementation Details

### Code Location
`viraltracker/cli/twitter.py` - Lines 717, 807-899

### Sorting Algorithm

```python
import math

if sort_by == 'balanced':
    # Score × √views
    priority_score = score_total * math.sqrt(views)
elif sort_by == 'views':
    priority_score = views
else:  # score
    priority_score = score_total
```

### Why Square Root of Views?

The square root function prevents extremely viral tweets from completely dominating the list while still giving proper weight to reach. This creates a more balanced distribution.

**Example**:
- Tweet A: score=0.55, views=100,000 → √100,000 = 316 → priority = 173.8
- Tweet B: score=0.60, views=10,000 → √10,000 = 100 → priority = 60.0

Without square root, Tweet A would have 10x the priority (55,000 vs 6,000), which would crowd out smaller but highly relevant tweets.

## Integration with Batch Workflow

The prioritization works seamlessly with the existing keyword scraping workflow:

```bash
# Step 1: Scrape all 19 keywords (last 48 hours)
./scrape_all_keywords.sh

# Step 2: Generate comments (greens only)
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 48 \
  --greens-only

# Step 3: Export with balanced prioritization (default)
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/daily_comments.csv \
  --status pending \
  --greens-only
```

## Keyword Performance (48-Hour Scrape)

**Best Performers** (Green Rate):
- "kids" - 5.4%
- "parenting advice" - 4.4%
- "kids social media" - 4.2%

**Lowest Performers**:
- "device limits" - 1.2%
- "digital parenting" - 1.4%
- "digital wellness" - 1.8%

**Overall**: 301 greens from 9,500 tweets (3.17%)

## Files Modified

- `/Users/ryemckenzie/projects/viraltracker/viraltracker/cli/twitter.py`
  - Added `--sort-by` parameter
  - Added sorting logic for all three strategies
  - Added rank and priority_score columns to CSV output
  - Updated fieldnames list

## Testing

**Test Command**:
```bash
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/test_balanced_export.csv \
  --limit 10 \
  --status pending \
  --sort-by balanced
```

**Verified Output**:
- ✅ Rank column properly numbered (1-10)
- ✅ Priority scores calculated correctly
- ✅ Tweets sorted by balanced formula
- ✅ CSV structure maintained with all 24 columns

## Next Steps

Consider adding:
- `--hours-back` parameter to export-comments for time-based filtering
- Custom priority formulas via config file
- Weighted scoring by topic or label
