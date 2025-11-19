# Twitter Comment Finder V1.7 - Complete Workflow Documentation

**Date**: October 30, 2025
**Version**: V1.7.1 (with min-views filtering and export improvements)
**Status**: ✅ Production Ready

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Workflow Overview](#workflow-overview)
3. [Step 1: Scrape & Score](#step-1-scrape--score)
4. [Step 2: Generate Comments](#step-2-generate-comments)
5. [Step 3: Export to CSV](#step-3-export-to-csv)
6. [Database Schema](#database-schema)
7. [New Features in V1.7.1](#new-features-in-v171)
8. [Production Script](#production-script)
9. [Cost & Time Estimates](#cost--time-estimates)
10. [Troubleshooting](#troubleshooting)
11. [Status Lifecycle](#status-lifecycle)

---

## Executive Summary

V1.7 implements a **two-pass workflow** that separates tweet scoring from comment generation:

**Traditional Workflow** (Before V1.7):
- Fetch tweets → Score ALL tweets → Generate comments for greens
- Problem: Re-scoring wastes time and can produce inconsistent results

**V1.7 Two-Pass Workflow**:
1. **Pass 1 (Scrape & Score)**: Fetch + score ALL tweets, save scores to database (no comments)
2. **Pass 2 (Generate)**: Query saved greens from DB, generate comments (no re-scoring)
3. **Export**: Export greens with comments to CSV

**Key Benefits**:
- ✅ Faster: No re-scoring when generating comments
- ✅ Consistent: Same scores used throughout workflow
- ✅ Cost-effective: Score 10,000 tweets for $0, only pay for comment generation
- ✅ Flexible: Generate comments on-demand for saved greens

**Latest Updates (V1.7.1)**:
- ✅ Min-views filtering to focus on high-reach tweets
- ✅ Improved export filename format with timestamps
- ✅ Status lifecycle management (pending → exported → posted)

---

## Workflow Overview

```
┌──────────────────────────────────────────────────────────────┐
│ STEP 1: Scrape & Score (45-60 min, $0)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                              │
│ 19 keywords × 500 tweets = 9,500 tweets                     │
│                                                              │
│ ▸ Scrape tweets via Apify Twitter Actor                     │
│ ▸ Score ALL with 5-topic taxonomy                           │
│ ▸ Save scores to database (comment_text = '')               │
│ ▸ Label as green/yellow/red                                 │
│ ▸ Generate JSON reports per keyword                         │
│                                                              │
│ Output: ~200-400 greens saved to database                   │
└──────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│ STEP 2: Generate Comments (10-15 min, ~$0.50-1.00)          │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                              │
│ Query: greens with comment_text = '' AND views >= 50        │
│                                                              │
│ ▸ Load saved scores from database                           │
│ ▸ NO re-scoring (uses saved labels)                         │
│ ▸ Filter by min-views (default: 50)                         │
│ ▸ Generate 3-5 comment suggestions per green                │
│ ▸ Batch mode: 5 concurrent API requests                     │
│ ▸ Update database with comments                             │
│                                                              │
│ Output: ~150-250 greens with comments (filtered by views)   │
└──────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│ STEP 3: Export to CSV (<1 min, $0)                          │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                              │
│ ▸ Query greens with comments from last 24h                  │
│ ▸ Status: pending (not yet posted)                          │
│ ▸ Sort by balanced metric: score × (views + likes)          │
│ ▸ Export to timestamped CSV                                 │
│ ▸ Auto-update status to 'exported'                          │
│                                                              │
│ Output: yakety-pack-instagram-24h-2025-10-30.csv            │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 1: Scrape & Score

### Purpose
Scrape recent tweets matching configured keywords and score them using the 5-topic taxonomy. Save all scores to database without generating expensive comment suggestions.

### Command (CLI)

```bash
python -m viraltracker.cli.main twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "kids social media" \
  --count 500 \
  --days-back 1 \
  --min-likes 0 \
  --skip-comments \
  --report-file ~/Downloads/keyword_analysis_24h/kids_social_media_report.json
```

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `--project` | `yakety-pack-instagram` | Project slug in database |
| `--term` | `"kids social media"` | Search keyword |
| `--count` | `500` | Max tweets to scrape per keyword |
| `--days-back` | `1` | Only tweets from last N days |
| `--min-likes` | `0` | Minimum likes filter (0 = no filter) |
| `--skip-comments` | flag | **V1.7**: Skip comment generation, save scores only |
| `--report-file` | path | JSON report output path |

### What Happens

1. **Scrape Tweets**: Calls Apify Twitter Actor API to search for tweets
2. **Save to Database**:
   - Upsert accounts to `accounts` table
   - Insert tweets to `posts` table
   - Link tweets to project in `project_posts` table
   - Create analysis run record in `analysis_runs` table
3. **Score Each Tweet**:
   - Velocity score: engagement rate (likes + retweets + replies) / views
   - Relevance score: semantic similarity to 5 taxonomy topics
   - Openness score: receptivity to comments (based on language patterns)
   - Author quality score: follower count + verification
   - Total score: weighted combination
4. **Label Tweets**:
   - Green: score ≥ 0.50
   - Yellow: 0.40 ≤ score < 0.50
   - Red: score < 0.40
5. **Save Scores to Database**:
   - Table: `generated_comments`
   - `label`: green/yellow/red
   - `tweet_score`, `velocity_score`, `relevance_score`, `openness_score`, `author_quality_score`
   - `best_topic_name`, `best_topic_similarity`
   - **`comment_text`: `''`** (empty, marking as score-only)
   - `suggestion_type`: 'score_only'
6. **Generate Report**: JSON file with metrics and recommendations

### Output

**Database Records**:
```
Tweets scraped: 500
Tweets scored: 500
Greens saved: ~10-20 (2-4% typical)
Yellows saved: ~450-475 (90-95% typical)
Reds saved: ~15-25 (3-5% typical)
```

**Files**:
- JSON report: `~/Downloads/keyword_analysis_24h/{keyword}_report.json`

**Time**: 2-3 minutes per keyword

**Cost**: $0 (no API calls for comment generation)

### Example Report (kids_social_media_report.json)

```json
{
  "project": "yakety-pack-instagram",
  "search_term": "kids social media",
  "analyzed_at": "2025-10-30T12:58:19.869889",
  "tweets_analyzed": 500,
  "metrics": {
    "score_distribution": {
      "green": {
        "count": 16,
        "percentage": 3.2,
        "avg_score": 0.525
      },
      "yellow": {
        "count": 465,
        "percentage": 93.0,
        "avg_score": 0.442
      },
      "red": {
        "count": 19,
        "percentage": 3.8,
        "avg_score": 0.389
      }
    },
    "topic_distribution": {
      "digital wellness": 343,
      "parent-child connection": 102,
      "family gaming": 41,
      "screen time management": 13,
      "parenting tips": 1
    }
  },
  "recommendation": {
    "rating": "Poor",
    "confidence": "High",
    "reasoning": "Only 3.2% green (target: 8%+). Consider other terms."
  }
}
```

---

## Step 2: Generate Comments

### Purpose
Generate comment suggestions ONLY for tweets already scored as green, without re-scoring. Uses saved scores from database.

### Command (CLI)

```bash
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --max-candidates 10000 \
  --min-views 50 \
  --batch-size 5
```

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `--project` | `yakety-pack-instagram` | Project slug |
| `--hours-back` | `24` | Look back N hours for saved scores |
| `--use-saved-scores` | flag | **V1.7**: Use saved scores from DB, skip re-scoring |
| `--max-candidates` | `10000` | Max tweets to process (set high to get all) |
| `--min-views` | `50` | **V1.7.1**: Minimum tweet views (filters low-reach tweets) |
| `--batch-size` | `5` | Concurrent API requests (V1.2 batch mode) |

### What Happens

#### 1. Query Database for Saved Greens

```sql
SELECT
  gc.*,
  p.post_id,
  p.caption,
  p.posted_at,
  p.likes,
  p.comments,
  p.shares,
  p.views,
  a.platform_username,
  a.follower_count
FROM generated_comments gc
JOIN posts p ON gc.tweet_id = p.post_id
JOIN accounts a ON p.account_id = a.id
WHERE gc.label = 'green'
  AND gc.comment_text = ''
  AND gc.created_at >= NOW() - INTERVAL '24 hours'
  AND p.views >= 50
ORDER BY gc.tweet_score DESC
LIMIT 10000;
```

#### 2. Load Saved Scores

Convert database records to `TweetMetrics` and `ScoringResult` objects:
- Uses saved `tweet_score`, `velocity_score`, `relevance_score`, etc.
- NO re-scoring occurs
- Preserves original labels (green/yellow/red)

#### 3. Filter by Min-Views

**NEW in V1.7.1**: Filters tweets with fewer than specified views
- Default: 50 views minimum
- Rationale: Tweets with <50 views won't get meaningful impressions when we comment
- Filtering happens at two levels:
  - Database query (if using regular workflow)
  - Post-query filtering (if using saved-scores workflow)

#### 4. Generate Comment Suggestions

For each green tweet:
1. Call Gemini API with tweet text and context
2. Request 5 suggestion types:
   - `add_value`: Share helpful insights or resources
   - `ask_question`: Ask engaging follow-up questions
   - `funny`: Light-hearted humor or relatable anecdotes
   - `debate`: Respectfully challenge or offer alternative perspective
   - `relate`: Share personal experience or empathy
3. Filter suggestions:
   - Reject if >280 characters
   - Reject if too generic
   - Typically 3-5 pass filters per tweet
4. Rank by quality

#### 5. Save to Database

Update `generated_comments` table:
- Set `comment_text` to actual comment
- Set `suggestion_type` to type (add_value, ask_question, etc.)
- Set `rank` to quality ranking (1 = best)
- Update `api_cost_usd` with actual cost

#### 6. Batch Processing

**V1.2 Batch Mode**:
- Processes 5 tweets concurrently
- 15 requests/minute rate limit
- 5× faster than sequential
- Progress bar shows real-time status

### Output

```
Found 66 saved green scores

🔍 Filtering candidates...
   ⚠️  Filtered out 12 tweets with <50 views
   ✅ 54 tweets remaining

💬 Generating comment suggestions (batch mode: 5 concurrent)...

Progress: [████████████████████] 54/54 (100%)

✅ Generated 243 comment suggestions
   - 54 tweets × 4.5 avg suggestions/tweet

💰 Cost: $0.005418 USD (~$0.0001 per tweet)
⏱️  Time: ~3 minutes
```

### Cost & Time Estimates

| Greens | Filtered (50+ views) | Suggestions | Cost (est.) | Time (est.) |
|--------|---------------------|-------------|-------------|-------------|
| 50 | ~40 | ~180 | $0.004 | ~3 min |
| 100 | ~75 | ~340 | $0.008 | ~5 min |
| 200 | ~150 | ~675 | $0.015 | ~10 min |
| 300 | ~225 | ~1,010 | $0.023 | ~15 min |

**Note**: Cost is ~$0.0001 per tweet. Batch mode is 5× faster than sequential.

---

## Step 3: Export to CSV

### Purpose
Export all greens with comments from the time range to a timestamped CSV file for review and posting.

### Command (CLI)

```bash
# Generate timestamped filename
export_date=$(date +%Y-%m-%d)
export_file=~/Downloads/yakety-pack-instagram-24h-${export_date}.csv

python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out $export_file \
  --hours-back 24 \
  --status pending \
  --label green \
  --sort-by balanced
```

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `--project` | `yakety-pack-instagram` | Project slug |
| `--out` | `~/Downloads/yakety-pack-instagram-24h-2025-10-30.csv` | **V1.7.1**: Timestamped output path |
| `--hours-back` | `24` | **V1.7**: Filter by time range |
| `--status` | `pending` | Only pending (not yet posted) |
| `--label` | `green` | Only greens |
| `--sort-by` | `balanced` | Sort by score × (views + likes) |
| `--limit` | (omit) | **V1.7**: No limit, export all |

### Export Filename Format

**NEW in V1.7.1**: Improved filename format for better organization

**Format**: `{project}-{timeframe}-{date}.csv`

**Examples**:
- `yakety-pack-instagram-24h-2025-10-30.csv` (24 hour window)
- `yakety-pack-instagram-7d-2025-10-30.csv` (7 day window)

**Benefits**:
- Easy to identify project
- Clear time window
- Export date for version tracking
- Prevents overwriting previous exports

### What Happens

#### 1. Query Database

```sql
SELECT
  p.post_id as tweet_id,
  p.caption as tweet_text,
  p.posted_at,
  p.likes,
  p.shares as retweets,
  p.comments as replies,
  p.views,
  a.platform_username as author_handle,
  a.follower_count as author_followers,
  gc.label,
  gc.tweet_score,
  gc.velocity_score,
  gc.relevance_score,
  gc.openness_score,
  gc.author_quality_score,
  gc.best_topic_name,
  gc.comment_text,
  gc.suggestion_type,
  gc.rank,
  gc.created_at,
  gc.status
FROM generated_comments gc
JOIN posts p ON gc.tweet_id = p.post_id
JOIN accounts a ON p.account_id = a.id
WHERE gc.label = 'green'
  AND gc.comment_text != ''
  AND gc.status = 'pending'
  AND gc.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY (gc.tweet_score * (p.views + p.likes)) DESC;
```

#### 2. Sort by Balanced Metric

**Balanced sort**: `score × (views + likes)`

**Why this works**:
- Prioritizes high-quality tweets (high score)
- Weights by reach (views) and engagement (likes)
- Balances quality and opportunity

#### 3. Export to CSV

**CSV Columns**:
```
tweet_id, tweet_url, tweet_text, author_handle, author_followers,
likes, retweets, replies, views, score, velocity_score, relevance_score,
openness_score, author_quality_score, topic, suggestion_type, comment_text,
rank, posted_at, created_at, status
```

#### 4. Update Status to 'exported'

**NEW in V1.7.1**: Automatically updates status after export

```sql
UPDATE generated_comments
SET status = 'exported'
WHERE id IN (exported_comment_ids);
```

**Why**:
- Prevents duplicate exports
- Tracks what's been exported vs. posted
- Enables workflow progression tracking

### Output

```
📊 Exporting comments for yakety-pack-instagram...

Filters:
- Label: green
- Status: pending
- Hours back: 24

Found 54 tweets with 243 suggestions

🔄 Updating status to 'exported'...
✅ Updated 243 suggestions to 'exported'

✅ Exported to: ~/Downloads/yakety-pack-instagram-24h-2025-10-30.csv

Summary:
- 54 tweets
- 243 suggestions (~4.5 per tweet)
- Top tweet: 12,456 views, 234 likes, score 0.68
```

### CSV Example

```csv
tweet_id,tweet_url,tweet_text,author_handle,author_followers,likes,retweets,replies,views,score,suggestion_type,comment_text,rank,topic
1850123456789,https://twitter.com/user/status/1850123456789,"My 8yo asked if she could have TikTok. I said no. She cried. Did I do the right thing?",parentingmom,12456,234,45,67,12456,0.68,relate,"I went through the same thing last year! We compromised with Zigazoo (kid-safe version). Still says no to TikTok until 13. Trust your instincts!",1,digital wellness
```

---

## Database Schema

### Table: `generated_comments`

Primary table for storing scores and comments.

#### Score-Only Records (After Step 1)

Records with `comment_text = ''` are score-only (no comments yet).

**Example Query**:
```sql
SELECT * FROM generated_comments
WHERE label = 'green'
  AND comment_text = ''
  AND created_at >= NOW() - INTERVAL '24 hours'
LIMIT 5;
```

**Schema**:

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | `a1b2c3...` | Primary key |
| `tweet_id` | VARCHAR | `1850123456789` | Twitter post ID |
| `project_id` | UUID | `d4e5f6...` | Foreign key to projects |
| `label` | VARCHAR | `green` | green/yellow/red |
| `tweet_score` | FLOAT | `0.68` | Total composite score |
| `velocity_score` | FLOAT | `0.75` | Engagement rate score |
| `relevance_score` | FLOAT | `0.82` | Topic relevance score |
| `openness_score` | FLOAT | `0.65` | Receptivity score |
| `author_quality_score` | FLOAT | `0.58` | Author quality score |
| `best_topic_name` | VARCHAR | `digital wellness` | Top matching topic |
| `best_topic_similarity` | FLOAT | `0.88` | Topic match confidence |
| `comment_text` | TEXT | `''` | **EMPTY** (score-only) |
| `suggestion_type` | VARCHAR | `score_only` | Placeholder |
| `rank` | INT | NULL | Not ranked yet |
| `api_cost_usd` | FLOAT | `0.0` | No API cost yet |
| `status` | VARCHAR | `pending` | pending/exported/posted |
| `created_at` | TIMESTAMP | `2025-10-30 12:58:19` | When scored |
| `updated_at` | TIMESTAMP | `2025-10-30 12:58:19` | Last update |

#### With Comments (After Step 2)

Records with `comment_text != ''` have generated comments.

**Example Query**:
```sql
SELECT * FROM generated_comments
WHERE label = 'green'
  AND comment_text != ''
  AND status = 'pending'
LIMIT 5;
```

**Updated Fields**:

| Field | Example | Description |
|-------|---------|-------------|
| `comment_text` | `"I went through the same thing..."` | Generated comment |
| `suggestion_type` | `relate` | add_value/ask_question/funny/debate/relate |
| `rank` | `1` | Quality ranking (1 = best) |
| `api_cost_usd` | `0.000103` | API cost for this suggestion |

### Related Tables

#### `posts` (Tweets)

Stores tweet data scraped from Twitter.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `post_id` | VARCHAR | Twitter post ID (unique) |
| `platform_id` | UUID | Foreign key to platforms (Twitter) |
| `account_id` | UUID | Foreign key to accounts |
| `caption` | TEXT | Tweet text |
| `posted_at` | TIMESTAMP | When tweet was posted |
| `likes` | INT | Like count |
| `comments` | INT | Reply count |
| `shares` | INT | Retweet count |
| `views` | INT | View count |

#### `accounts` (Twitter Users)

Stores Twitter account data.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `platform_id` | UUID | Foreign key to platforms (Twitter) |
| `platform_username` | VARCHAR | Twitter handle |
| `follower_count` | INT | Follower count |
| `is_verified` | BOOLEAN | Verification status |

---

## New Features in V1.7.1

### 1. Min-Views Filtering

**Feature**: `--min-views` parameter for filtering low-reach tweets

**Why**: Tweets with very few views won't generate meaningful impressions when we comment. Default threshold of 50 views filters out the long tail.

**Implementation**:
- Added to `generate-comments` command
- Default: 0 (no filtering)
- Recommended: 50 views
- Filters at two levels:
  - Database query (regular workflow)
  - Post-query filtering (saved-scores workflow)

**Files Modified**:
- `viraltracker/cli/twitter.py:394-406` - Added CLI option
- `viraltracker/cli/twitter.py:569-575` - Added post-query filtering
- `viraltracker/generation/tweet_fetcher.py:19-27` - Added parameter
- `viraltracker/generation/tweet_fetcher.py:81-89` - Added DB filtering
- `scrape_all_keywords_24h.sh:170` - Added to production script

**Usage**:
```bash
# Generate comments only for tweets with 50+ views
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --min-views 50 \
  --batch-size 5
```

**Output**:
```
Found 66 saved green scores

🔍 Filtering candidates...
   ⚠️  Filtered out 12 tweets with <50 views
   ✅ 54 tweets remaining
```

### 2. Export Filename Format

**Feature**: Timestamped export filenames with project-timeframe-date format

**Old Format**: `keyword_greens_24h.csv` (generic, gets overwritten)

**New Format**: `{project}-{timeframe}-{date}.csv`
- Example: `yakety-pack-instagram-24h-2025-10-30.csv`

**Why**:
- Prevents overwriting previous exports
- Easy to identify project and time window
- Date stamped for version tracking
- Better file organization

**Implementation**:
- `scrape_all_keywords_24h.sh:178-179` - Dynamic filename generation

**Code**:
```bash
export_date=$(date +%Y-%m-%d)
export_file=~/Downloads/yakety-pack-instagram-24h-${export_date}.csv
```

### 3. Status Lifecycle Management

**Feature**: Automatic status updates during workflow

**Status Values**:
1. `pending` - Newly generated, not yet exported
2. `exported` - Exported to CSV, ready for review
3. `posted` - Actually posted to Twitter

**Why**:
- Prevents duplicate exports
- Tracks workflow progress
- Enables filtering by status

**Workflow**:
```
Step 2 (Generate) → status = 'pending'
Step 3 (Export)   → status = 'exported'
Manual Posting    → status = 'posted'
```

**Implementation**:
- `viraltracker/cli/twitter.py:1025-1046` - Auto-update on export

**Re-exporting**:
```bash
# Export again (already exported records)
python -m viraltracker.cli.main twitter export-comments \
  --status exported \
  --out ~/Downloads/re-export.csv
```

---

## Production Script

### Master Script: `scrape_all_keywords_24h.sh`

Complete 3-step workflow script for production use.

**Location**: `/Users/ryemckenzie/projects/viraltracker/scrape_all_keywords_24h.sh`

**Configuration**:
- **19 keywords**: device limits, digital parenting, digital wellness, etc.
- **500 tweets per keyword**
- **Last 24 hours**
- **Green threshold**: 0.50
- **Min views**: 50 (for comment generation)
- **Batch size**: 5 concurrent requests

### Script Structure

```bash
#!/bin/bash

# Configuration
terms=(
  "device limits"
  "digital parenting"
  "digital wellness"
  # ... 16 more keywords
)

# Step 1: Scrape & Score (45-60 min, $0)
for term in "${terms[@]}"; do
  python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 500 \
    --days-back 1 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/keyword_analysis_24h/${filename}_report.json

  # Rate limiting: 2 min between keywords
  sleep 120
done

# Step 2: Generate Comments (10-15 min, ~$0.50-1.00)
source venv/bin/activate && python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --use-saved-scores \
  --max-candidates 10000 \
  --min-views 50 \
  --batch-size 5

# Step 3: Export to CSV (<1 min, $0)
export_date=$(date +%Y-%m-%d)
export_file=~/Downloads/yakety-pack-instagram-24h-${export_date}.csv

source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out $export_file \
  --hours-back 24 \
  --status pending \
  --label green \
  --sort-by balanced

echo "✅ Complete! Greens exported to: $export_file"
```

### Running the Script

```bash
# Make executable
chmod +x scrape_all_keywords_24h.sh

# Run with logging
./scrape_all_keywords_24h.sh 2>&1 | tee ~/Downloads/scrape_24h_$(date +%Y%m%d).log

# Run in background
nohup ./scrape_all_keywords_24h.sh > ~/Downloads/scrape_24h.log 2>&1 &
```

### Expected Output

```
========================================
Scraping All Keywords (24 Hours)
========================================
Total keywords: 19
Tweets per keyword: 500
Time window: 24 hours (1 day)
Green threshold: 0.50
Min likes: 0
Skip comments: Yes (saves scores for later generation)
Taxonomy: 5 topics (V1.6)
========================================

[1/19] Scraping: device limits
...
✅ Completed: device limits

[2/19] Scraping: digital parenting
...
✅ Completed: digital parenting

...

========================================
Step 2: Generate comments for all greens from last 24 hours
========================================

Found 66 saved green scores
   ⚠️  Filtered out 12 tweets with <50 views
   ✅ 54 tweets remaining

💬 Generating comment suggestions...
✅ Generated 243 comment suggestions

========================================
Step 3: Export greens to CSV
========================================

✅ Exported 54 tweets with 243 suggestions

✅ Complete! Greens exported to: ~/Downloads/yakety-pack-instagram-24h-2025-10-30.csv
```

---

## Cost & Time Estimates

### Per Run (Daily)

| Step | Description | Time | Cost | Notes |
|------|-------------|------|------|-------|
| 1 | Scrape & Score | 45-60 min | $0 | 19 keywords × 500 tweets |
| 2 | Generate Comments | 10-15 min | $0.50-1.00 | ~150-250 greens after filtering |
| 3 | Export CSV | <1 min | $0 | Database query only |
| **Total** | **Complete Workflow** | **~60-75 min** | **~$0.50-1.00** | Fully automated |

### Monthly (22 working days)

| Item | Calculation | Cost |
|------|-------------|------|
| Comment Generation API | 200 greens × 22 days × $0.003 | ~$13/month |
| Apify Twitter Scraper | 10k tweets/day × 22 days | ~$5/month |
| Railway (Web + Cron) | Platform hosting | ~$5/month |
| **Total** | | **~$23/month** |

### Cost Breakdown by Component

**Step 1 (Scraping)**:
- Apify API: ~$0.20/day (~10k tweets)
- Scoring computation: $0 (local)

**Step 2 (Comments)**:
- Gemini API: ~$0.0001 per tweet
- 200 greens × $0.0001 = ~$0.02
- BUT: 5 suggestions per tweet = ~$0.10
- Batch processing overhead = ~$0.40
- **Total: ~$0.50-1.00/day**

**Step 3 (Export)**:
- Database query: $0
- CSV generation: $0

---

## Troubleshooting

### Issue 1: No saved scores found

**Error**:
```
⚠️  No saved green scores found in last 24 hours
```

**Causes**:
1. Step 1 hasn't run yet (no scores in database)
2. Time window too narrow (increase `--hours-back`)
3. All greens already have comments (`comment_text != ''`)

**Solutions**:
```bash
# Increase time window
--hours-back 48

# Check database
python -c "
from viraltracker.core.database import get_supabase_client
db = get_supabase_client()
result = db.table('generated_comments')\
  .select('count')\
  .eq('label', 'green')\
  .eq('comment_text', '')\
  .execute()
print(f'Score-only greens: {result.data}')
"
```

### Issue 2: Export finds no results

**Error**:
```
No suggestions found matching criteria
```

**Causes**:
1. Status is `exported` (already exported once)
2. No comments generated yet (`comment_text = ''`)
3. Time window too narrow

**Solutions**:
```bash
# Export already-exported records
--status exported

# Check all statuses
--status all

# Increase time window
--hours-back 48
```

### Issue 3: Low green count

**Symptom**: Only finding 5-10 greens per 500 tweets (1-2%)

**Expected**: 2-5% green rate (10-25 greens per 500)

**Causes**:
1. Poor keyword selection (not relevant to brand)
2. Low-quality tweets in results
3. Scoring threshold too high (0.50)

**Solutions**:
1. Analyze keyword reports to find best-performing terms
2. Lower green threshold to 0.45 (requires code change)
3. Increase `--count` to 1000 tweets per keyword

### Issue 4: High API costs

**Symptom**: Step 2 costing >$2.00

**Expected**: ~$0.50-1.00 for 150-250 greens

**Causes**:
1. Too many greens (not filtering by min-views)
2. Batch mode not enabled
3. API pricing changed

**Solutions**:
```bash
# Add min-views filtering
--min-views 50

# Enable batch mode
--batch-size 5

# Check cost per tweet
grep "api_cost_usd" ~/Downloads/*.log
```

### Issue 5: Apify rate limits

**Error**:
```
Rate limit exceeded (429 Too Many Requests)
```

**Causes**:
1. Running too many scrapes concurrently
2. Not waiting between keywords
3. Apify account limits hit

**Solutions**:
```bash
# Increase wait time between keywords (in script)
sleep 180  # 3 minutes instead of 2

# Reduce scrape count
--count 300

# Check Apify dashboard for rate limits
```

### Issue 6: Database connection errors

**Error**:
```
Could not connect to Supabase
```

**Causes**:
1. Missing `.env` file
2. Invalid `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY`
3. Network issues

**Solutions**:
```bash
# Check .env file exists
cat .env | grep SUPABASE

# Test connection
python -c "
from viraltracker.core.database import get_supabase_client
db = get_supabase_client()
print('✅ Connected to Supabase')
"
```

---

## Status Lifecycle

### State Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   COMMENT LIFECYCLE                     │
└─────────────────────────────────────────────────────────┘

    ┌──────────┐
    │ Step 1:  │
    │  Score   │
    └────┬─────┘
         │
         ▼
    ┌──────────────────┐
    │ status = pending │  ← Score-only record (comment_text = '')
    │ comment_text = ''│
    └────┬─────────────┘
         │
         │  Step 2: Generate Comments
         ▼
    ┌──────────────────┐
    │ status = pending │  ← Has comments, not exported yet
    │ comment_text ≠ ''│
    └────┬─────────────┘
         │
         │  Step 3: Export to CSV
         ▼
    ┌────────────────────┐
    │ status = exported  │  ← Exported to CSV, ready for review
    │ comment_text ≠ ''  │
    └────┬───────────────┘
         │
         │  Manual: Post to Twitter
         ▼
    ┌───────────────────┐
    │ status = posted   │  ← Actually posted on Twitter
    │ comment_text ≠ '' │
    └───────────────────┘
```

### Status Filters

**Pending (newly generated)**:
```bash
--status pending  # Default for exports
```

**Exported (already in CSV)**:
```bash
--status exported  # Re-export already exported
```

**Posted (live on Twitter)**:
```bash
--status posted  # See what's been posted
```

**All statuses**:
```bash
--status all  # Everything
```

### Status Queries

**Count by status**:
```sql
SELECT status, COUNT(*) as count
FROM generated_comments
WHERE label = 'green'
  AND comment_text != ''
GROUP BY status;
```

**Recently exported**:
```sql
SELECT * FROM generated_comments
WHERE status = 'exported'
  AND updated_at >= NOW() - INTERVAL '24 hours'
ORDER BY updated_at DESC;
```

**Pending exports**:
```sql
SELECT COUNT(*) FROM generated_comments
WHERE status = 'pending'
  AND comment_text != ''
  AND label = 'green';
```

---

## Related Documentation

- `WORKFLOW_SAVED_SCORES_V17.md` - Original V1.7 documentation
- `CHECKPOINT_V17_COMPLETE_WORKFLOW.md` - V1.7 testing checkpoint
- `CHECKPOINT_2025-10-29_SCORE_SAVING_FIX.md` - Score-saving bug fix
- `WORKFLOW_FIX_SCORE_SAVING.md` - Technical details of score-saving

---

## Version History

### V1.7.1 (October 30, 2025)
- ✅ Added `--min-views` parameter (default: 0, recommended: 50)
- ✅ Improved export filename format: `{project}-{timeframe}-{date}.csv`
- ✅ Documented status lifecycle (pending → exported → posted)
- ✅ Updated production script with new features
- ✅ Multi-level view filtering (DB query + post-query)

### V1.7 (October 29, 2025)
- ✅ Two-pass workflow (scrape & score → generate comments)
- ✅ `--use-saved-scores` flag for querying pre-scored greens
- ✅ `--hours-back` time filtering for exports
- ✅ Score-only records with empty `comment_text`
- ✅ No export limit (removed 200 limit)

### V1.6 (October 2025)
- ✅ 5-topic taxonomy for relevance scoring
- ✅ Batch comment generation (5 concurrent)
- ✅ Cost tracking per suggestion

### V1.5 (October 2025)
- ✅ Multi-brand, multi-platform support
- ✅ Supabase database integration
- ✅ Project-based organization

---

**Created**: October 30, 2025
**Author**: Claude Code
**Version**: V1.7.1
**Status**: ✅ Production Ready
