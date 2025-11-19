# Workflow Documentation: Two-Pass Comment Generation (V1.7)

**Date**: October 30, 2025
**Version**: V1.7
**Status**: ✅ Tested and working

---

## Problem Solved

Previously, the `generate-comments` command would re-score all tweets from scratch, which:
- ❌ Wasted time re-scoring tweets already scored
- ❌ Could produce inconsistent results if scoring changed
- ❌ Made the score-saving feature pointless

**V1.7 Solution**: Added `--use-saved-scores` flag that queries database for pre-scored greens and generates comments without re-scoring.

---

## Complete Two-Pass Workflow

### Overview

```
┌─────────────────────────────────────────────────────────┐
│ STEP 1: Scrape & Score (45-60 min, $0)                 │
│ - Scrapes tweets from keywords                          │
│ - Scores ALL tweets with 5-topic taxonomy               │
│ - Saves scores to database (empty comment_text)         │
│ - Skips expensive comment generation                    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 2: Generate Comments (15 min, ~$1-5)              │
│ - Queries database for saved greens                     │
│ - NO re-scoring (uses saved labels)                     │
│ - Generates 3-5 comment suggestions per green           │
│ - Updates database with comments                        │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 3: Export to CSV                                   │
│ - Exports all greens with comments from time range      │
│ - Ready for review and posting                          │
└─────────────────────────────────────────────────────────┘
```

---

## Step 1: Scrape & Score

**Purpose**: Scrape recent tweets and score them, saving scores to database without generating comments.

### Command (Using Keyword Analyzer)

```bash
python -m viraltracker.analysis.search_term_analyzer \
  --project yakety-pack-instagram \
  --hours 24 \
  --skip-comments \
  --out ~/Downloads/keyword_analysis_24h
```

### What Happens

1. **Scrapes tweets** from configured keywords (500 per keyword)
2. **Scores each tweet** using 5-topic taxonomy:
   - Velocity score (engagement rate)
   - Relevance score (topic match)
   - Openness score (receptivity)
   - Author quality score
   - Total score → Green/Yellow/Red label
3. **Saves scores to database**:
   - Table: `generated_comments`
   - Label: `green`, `yellow`, or `red`
   - `comment_text`: `''` (empty, marking it as score-only)
4. **Exports report files**: JSON files per keyword in output directory

### Output

- **Database**: Scores saved in `generated_comments` table
- **Files**: `~/Downloads/keyword_analysis_24h/*.json` (19 files)
- **Time**: 45-60 minutes
- **Cost**: $0 (no API calls for comment generation)

### Expected Results

```
Keywords analyzed: 19
Tweets scraped: ~9,500 (500 × 19)
Tweets scored: ~9,500
Greens found: ~200-400 (typical)
Saved to DB: All scores (greens, yellows, reds)
```

---

## Step 2: Generate Comments (Using Saved Scores)

**Purpose**: Generate comment suggestions ONLY for tweets already scored as green, without re-scoring.

### Command

```bash
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --max-candidates 10000 \
  --batch-size 5
```

### Parameters Explained

| Parameter | Value | Description |
|-----------|-------|-------------|
| `--project` | `yakety-pack-instagram` | Project slug in database |
| `--hours-back` | `24` | Look back N hours for saved scores |
| `--use-saved-scores` | flag | **NEW V1.7**: Use saved scores from DB, skip re-scoring |
| `--max-candidates` | `10000` | Max tweets to process (set high to get all) |
| `--batch-size` | `5` | Concurrent API requests (V1.2 batch mode) |

### What Happens

1. **Queries database** for:
   - `label = 'green'`
   - `comment_text = ''` (score-only records)
   - `created_at >= (now - hours_back)`
2. **Loads saved scores** into memory (no re-scoring)
3. **Generates comments** for each green:
   - 5 suggestion types: add_value, ask_question, funny, debate, relate
   - Filters out too-long suggestions
   - Typically 3-5 pass filters
4. **Saves to database**:
   - Updates `comment_text` field
   - Saves all suggestions with rankings
5. **Batch processing**: 5 concurrent requests, 15 req/min rate limit

### Output

```
Found 21 saved green scores
Generated 78 comment suggestions (21 tweets × ~3.7 avg)
Cost: $0.002173 USD (~$0.00008 per tweet)
Time: ~2 minutes (21 tweets with batch mode)
```

### Cost Estimates

| Greens | Suggestions | Cost (est.) | Time (est.) |
|--------|-------------|-------------|-------------|
| 50 | ~180 | $0.005 | ~5 min |
| 100 | ~360 | $0.010 | ~8 min |
| 200 | ~720 | $0.020 | ~15 min |
| 300 | ~1,080 | $0.030 | ~20 min |

**Note**: Batch mode (V1.2) is 5× faster than sequential. Cost is ~$0.0001 per tweet.

---

## Step 3: Export to CSV

**Purpose**: Export all greens with comments from the time range to a CSV file for review.

### Command

```bash
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/greens_24h.csv \
  --hours-back 24 \
  --label green \
  --status pending \
  --sort-by balanced
```

### Parameters Explained

| Parameter | Value | Description |
|-----------|-------|-------------|
| `--project` | `yakety-pack-instagram` | Project slug |
| `--out` | `~/Downloads/greens_24h.csv` | Output CSV file path |
| `--hours-back` | `24` | **NEW V1.7**: Filter by time range |
| `--label` | `green` | Only greens |
| `--status` | `pending` | Not yet posted |
| `--sort-by` | `balanced` | Sort by score + engagement |
| `--limit` | (omit) | **NEW V1.7**: No limit, export all |

### What Happens

1. **Queries database** for:
   - `label = 'green'`
   - `comment_text != ''` (has comments)
   - `created_at >= (now - hours_back)`
   - `status = 'pending'`
2. **Sorts by balanced metric**: score × (views + likes)
3. **Exports to CSV** with columns:
   - tweet_id, tweet_url, text, author, followers
   - likes, retweets, views, score
   - suggestion_type, comment_text, topic
   - posted_at, created_at

### Output

```
Exported: 21 tweets with 78 suggestions
File: ~/Downloads/greens_24h.csv
Ready for review and posting
```

---

## Database Schema

### Score-Only Records (After Step 1)

```sql
SELECT * FROM generated_comments
WHERE label = 'green'
AND comment_text = ''
LIMIT 5;
```

| Field | Value |
|-------|-------|
| `label` | `green` |
| `tweet_score` | 0.75 |
| `velocity_score` | 0.8 |
| `relevance_score` | 0.85 |
| `openness_score` | 0.7 |
| `author_quality_score` | 0.65 |
| `best_topic_name` | "Parenting Stress" |
| `best_topic_similarity` | 0.88 |
| `comment_text` | `''` **(empty)** |

### With Comments (After Step 2)

```sql
SELECT * FROM generated_comments
WHERE label = 'green'
AND comment_text != ''
LIMIT 5;
```

Same fields as above, plus:

| Field | Value |
|-------|-------|
| `comment_text` | "I completely agree! We found..." |
| `suggestion_type` | "relate" |
| `rank` | 1 |
| `api_cost_usd` | 0.000103 |

---

## Files Modified in V1.7

### 1. viraltracker/cli/twitter.py

**Lines 403-417**: Added `--use-saved-scores` flag

**Lines 487-568**: Implemented saved-scores workflow:
- Query database for score-only greens
- Convert to `TweetMetrics` and `ScoringResult` objects
- Parse `posted_at` string to datetime
- Skip all fetching/scoring logic

**Lines 680-685**: Handle empty embedding map for saved-scores

**Lines 711-852**: Modified `export-comments` command:
- Added `--hours-back` parameter for time filtering
- Changed `--limit` default from 200 to None

---

## Key Implementation Details

### Why Empty `comment_text`?

Score-only records use `comment_text = ''` as a marker because:
- Database has NOT NULL constraint on `comment_text`
- Easy to query: `WHERE comment_text = ''` = scores only
- Easy to query: `WHERE comment_text != ''` = has comments
- No schema changes needed

### Why Empty Embedding Map?

Saved-scores workflow creates empty `tweet_embedding_map = {}` because:
- Embeddings are only used for semantic deduplication
- We don't have embeddings (skipped scoring step)
- Code checks `if tweet_emb:` before storing, so it safely skips

### Datetime Parsing

Database returns `posted_at` as ISO string:
```python
posted_at = post_data['posted_at']  # "2025-10-28T14:30:00Z"
if isinstance(posted_at, str):
    posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
```

---

## Testing Results

### Test Configuration
- Project: `yakety-pack-instagram`
- Time range: Last 48 hours
- Max candidates: 250
- Batch size: 5

### Results
```
✅ Found 21 saved green scores from database
✅ Generated 78 comment suggestions (21 tweets × ~3.7 avg)
✅ All saved successfully to database
✅ Cost: $0.002173 USD (~$0.00008 per tweet)
✅ Time: ~2 minutes
✅ No errors
```

---

## Troubleshooting

### Issue: No saved scores found

**Error**:
```
⚠️  No saved green scores found in last 24 hours
```

**Solutions**:
1. Increase `--hours-back` (try 48 or 72)
2. Check if Step 1 (scraping) completed successfully
3. Verify scores in database:
   ```sql
   SELECT COUNT(*) FROM generated_comments
   WHERE label = 'green' AND comment_text = '';
   ```

### Issue: "tweet_id" already exists error

**Error**:
```
duplicate key value violates unique constraint "generated_comments_pkey"
```

**Cause**: Trying to save comments for tweets that already have comments.

**Solution**: This is expected behavior. The database uses `on_conflict` to update existing records. No action needed.

### Issue: "str object has no attribute 'timestamp'"

**Error**:
```
AttributeError: 'str' object has no attribute 'timestamp'
```

**Cause**: Fixed in V1.7. The `posted_at` field needs datetime parsing.

**Solution**: Update to V1.7 (lines 531-535 in twitter.py).

---

## Production Workflow (Railway Cron)

### Daily Scrape Script

```bash
#!/bin/bash
# File: run_daily_scrape_with_logging.py

# Step 1: Scrape & Score (45-60 min, $0)
python -m viraltracker.analysis.search_term_analyzer \
  --project yakety-pack-instagram \
  --hours 24 \
  --skip-comments \
  --out /tmp/keyword_analysis_24h

# Step 2: Generate Comments (15 min, ~$1)
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --max-candidates 10000 \
  --batch-size 5

# Step 3: Export CSV
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out /tmp/greens_24h.csv \
  --hours-back 24 \
  --label green \
  --status pending \
  --sort-by balanced
```

### Railway Schedule

```toml
# railway.toml
[[services]]
name = "cron"

[[services.cron.crons]]
schedule = "0 11 * * 1-5"  # Mon-Fri 6 AM EST (11:00 UTC)
command = "python run_daily_scrape_with_logging.py"
```

---

## Cost Summary

### Per Run (Daily)
- **Step 1**: $0 (scraping + scoring)
- **Step 2**: ~$0.90 (300 greens × $0.003)
- **Step 3**: $0 (database query + CSV export)
- **Total**: ~$0.90/day

### Monthly (22 working days)
- **API costs**: ~$20/month (300 greens × 22 days × $0.003)
- **Railway costs**: ~$5/month (web + cron)
- **Total**: ~$25/month

---

## Next Steps

1. ✅ V1.7 implementation complete
2. ✅ Testing complete (21 greens, 78 suggestions)
3. ⏳ Railway cron service setup (pending)
4. ⏳ First production run (pending)
5. ⏳ Monitor and optimize

---

## Related Documentation

- `CHECKPOINT_2025-10-29_SCORE_SAVING_FIX.md` - Original score-saving bug fix
- `CHECKPOINT_2025-10-29_RAILWAY_DEPLOYED.md` - Railway deployment
- `WORKFLOW_FIX_SCORE_SAVING.md` - Technical details of score-saving

---

**Created**: October 30, 2025
**Author**: Claude Code
**Version**: V1.7 (Two-pass workflow with saved scores)
**Status**: ✅ Tested and documented
