# Phase 5: End-to-End Testing - Continuation Prompt

## Context

Comment Finder V1 is **100% complete** with all code written, unit tests passing, and documentation finalized. This continuation focuses on **Phase 5: End-to-End Testing** with real data to validate the entire system works in production.

**Branch**: `feature/comment-finder-v1`
**Status**: All commits pushed to GitHub (7 commits total)
**Last Checkpoint**: `CHECKPOINT_2025-10-21_comment-finder-v1-complete.md`

## What Comment Finder V1 Does

Finds high-potential tweets for engagement by:
1. **Scoring** fresh tweets (velocity, relevance, openness, author quality)
2. **Generating** 3 AI-powered reply suggestions per tweet using Gemini
3. **Exporting** opportunities to CSV for manual review/posting

## Phase 5 Objectives

Test the **complete pipeline** with real Twitter data:

```bash
# 1. Generate comment suggestions (scoring + AI generation)
./vt twitter generate-comments --project ecom --hours-back 6

# 2. Export to CSV for review
./vt twitter export-comments --project ecom --out opportunities.csv
```

Validate that:
- Scoring correctly identifies high-potential tweets
- AI suggestions are contextual, on-brand, and diverse
- CSV export contains actionable opportunities
- Cost stays under $0.50/run
- No duplicate suggestions generated

## Prerequisites

### 1. Database Setup
All 4 tables should exist in Supabase:
- `generated_comments`
- `tweet_snapshot`
- `author_stats`
- `acceptance_log`

**Verify**: Run `\d generated_comments` in Supabase SQL editor

### 2. Environment Variables
Required in `.env`:
```
SUPABASE_URL=...
SUPABASE_KEY=...
GEMINI_API_KEY=...  # or GOOGLE_GEMINI_API_KEY
```

### 3. Project Configuration
Must have `projects/ecom/finder.yml` (or another project)

**Check**: `ls projects/ecom/finder.yml`

If missing, reference the example in `CHECKPOINT_2025-10-21_comment-finder-v1-complete.md` Section 3.1

### 4. Twitter Data
Need recent tweets ingested (within last 6-24 hours)

**Check**:
```bash
# Count recent tweets
./vt twitter stats --project ecom
```

If no recent data, run:
```bash
./vt twitter search --terms "ecom,shopify" --count 500 --days-back 1 --project ecom
```

## Testing Plan

### Step 1: Validate Database Schema

```bash
# Connect to Supabase and verify tables exist
# Check that generated_comments table has correct columns
```

**Expected**: 4 tables present with correct schemas

### Step 2: Validate Project Configuration

```bash
# Read projects/ecom/finder.yml
# Verify taxonomy, voice, weights, thresholds, generation settings
```

**Expected**: Valid YAML with all required sections

### Step 3: Run Comment Generation

```bash
source venv/bin/activate
./vt twitter generate-comments \
  --project ecom \
  --hours-back 6 \
  --min-followers 1000 \
  --max-candidates 50 \
  --use-gate
```

**Monitor for**:
- Fetches ~50 candidates from database
- Computes embeddings (should use cache after first run)
- Scores each tweet (velocity, relevance, openness, author quality)
- Generates AI suggestions for high-scoring tweets (green/yellow only)
- Saves to `generated_comments` table
- No errors or crashes

**Success Criteria**:
- 5-15 tweets pass scoring gate (depends on data)
- Each passing tweet gets 3 suggestions (add_value, ask_question, mirror_reframe)
- Total cost < $0.50 (check Gemini API usage)
- No duplicate tweet_ids in generated_comments for same project

### Step 4: Review Scoring Quality

**Check `generated_comments` table**:

```sql
SELECT
  tweet_id,
  score_total,
  label,
  topic,
  why
FROM generated_comments
WHERE project_id = (SELECT id FROM projects WHERE slug = 'ecom')
ORDER BY score_total DESC
LIMIT 10;
```

**Validate**:
- Scores range 0.0-1.0
- Labels: 'green' (≥0.6), 'yellow' (0.4-0.6), or 'red' (<0.4)
- Topics match taxonomy from finder.yml
- "why" rationale makes sense (e.g., "high velocity + topic facebook ads (0.85)")

**Manual Check** (pick 2-3 tweets):
- Does velocity make sense? (high engagement relative to audience)
- Does relevance make sense? (tweet about the taxonomy topic)
- Does openness make sense? (tweet asks question or is exploratory)
- Does author quality make sense? (based on whitelist/blacklist)

### Step 5: Review AI Suggestion Quality

**Check suggestions**:

```sql
SELECT
  tweet_id,
  suggestion_type,
  comment_text,
  rank
FROM generated_comments
WHERE project_id = (SELECT id FROM projects WHERE slug = 'ecom')
  AND label IN ('green', 'yellow')
ORDER BY score_total DESC, tweet_id, rank
LIMIT 15;
```

**Validate Each Suggestion Type**:

1. **add_value**: Should share insights, data, or tips
   - Does it add genuine value?
   - Is it specific and actionable?
   - Does it match the persona from finder.yml?

2. **ask_question**: Should ask thoughtful follow-ups
   - Is the question relevant to the tweet?
   - Does it invite discussion?
   - Avoids generic "great point!" style

3. **mirror_reframe**: Should acknowledge and reframe
   - Does it show understanding of original tweet?
   - Does it add a fresh angle?
   - Feels conversational?

**Voice Matching**:
- Check 3-5 suggestions against voice.persona in finder.yml
- Verify they follow voice.constraints (e.g., "no profanity")
- Compare to voice.examples.good vs voice.examples.bad

### Step 6: Test CSV Export

```bash
./vt twitter export-comments \
  --project ecom \
  --out opportunities.csv \
  --limit 50 \
  --label green
```

**Validate CSV**:
- Opens in spreadsheet app
- Has 15 columns: project, tweet_id, url, author_handle, author_followers, score_total, label, topic, why, suggestion_type, comment_text, rank, tweeted_at, review_status, status
- tweet_url is clickable and correct
- Sorted by score_total DESC
- Contains only 'green' label tweets
- No duplicates

**Manual Review**:
- Pick top 5 opportunities
- Click tweet URLs - do they open correctly?
- Read suggestions - would you actually post these?
- Check if any are too old (>24h)

### Step 7: Test Duplicate Prevention

```bash
# Run generate-comments again with same parameters
./vt twitter generate-comments \
  --project ecom \
  --hours-back 6 \
  --min-followers 1000 \
  --max-candidates 50 \
  --use-gate
```

**Expected**:
- Should skip tweets already in `generated_comments`
- No duplicate (project_id, tweet_id, suggestion_type) combinations
- "Skipped N duplicates" message in output

### Step 8: Test Different Time Windows

```bash
# Try different time windows
./vt twitter generate-comments --project ecom --hours-back 12
./vt twitter generate-comments --project ecom --hours-back 24
```

**Validate**:
- More candidates with longer time window
- Velocity scores decrease for older tweets (expected)
- Still finds some green tweets even at 24h

### Step 9: Cost Validation

**Check Gemini API usage** (https://aistudio.google.com):

- Embedding calls: ~1-2 per run (cached after first)
- Generation calls: 1 per green/yellow tweet
- Total cost should be < $0.50 for 50 candidates

**If costs too high**:
- Reduce --max-candidates
- Increase score gates in finder.yml thresholds
- Check cache is working (cache/tweet_embeds_*.json)

### Step 10: Edge Case Testing

Test error handling:

```bash
# Missing config
./vt twitter generate-comments --project nonexistent

# No API key
GEMINI_API_KEY="" ./vt twitter generate-comments --project ecom

# No recent tweets
./vt twitter generate-comments --project ecom --hours-back 0.1

# Invalid parameters
./vt twitter generate-comments --project ecom --max-candidates -1
```

**Expected**: Clear error messages, no crashes

## Success Criteria

Phase 5 is complete when:

- [ ] All 4 database tables exist and have correct schemas
- [ ] finder.yml loads without errors
- [ ] generate-comments runs end-to-end with real data
- [ ] 5-15 tweets pass scoring gate (for 50 candidates)
- [ ] Scoring looks reasonable (velocity, relevance, openness, author quality)
- [ ] All 3 suggestion types generate correctly
- [ ] AI suggestions match voice/persona from config
- [ ] CSV export contains actionable opportunities
- [ ] Duplicate prevention works (no re-processing same tweets)
- [ ] Total cost < $0.50 per run
- [ ] No crashes or unhandled errors

## Known Limitations (V1)

These are **expected** and documented:

1. **No semantic duplicate detection** - only exact tweet_id matching
2. **No rate limit handling** - assumes Gemini free tier limits
3. **No batch generation** - processes tweets serially
4. **Fixed English-only** - no multi-language support
5. **Manual posting** - no auto-reply (by design)

These will be addressed in V1.1+ if needed.

## Troubleshooting

### Scoring Issues

**Problem**: All tweets score red (< 0.4)

**Debug**:
```python
# In Python shell
from viraltracker.generation.comment_finder import TweetMetrics, compute_total_score
from viraltracker.core.config import load_finder_config

config = load_finder_config("ecom")
print(config.weights)  # Should be velocity:0.35, relevance:0.35, etc.
print(config.thresholds)  # Should be green:0.6, yellow:0.4
```

**Fixes**:
- Lower thresholds in finder.yml (green: 0.5, yellow: 0.3)
- Adjust weights (increase openness if tweets are questions)
- Check taxonomy topics match tweet content

### Generation Issues

**Problem**: Gemini safety filters block all suggestions

**Debug**:
```python
# Check tweets in generated_comments
# Look for safety_blocked errors in logs
```

**Fixes**:
- Use less controversial tweets for testing
- Adjust prompt in viraltracker/generation/prompts/comments.json
- Skip blocked tweets (expected behavior)

### Cost Issues

**Problem**: Costs > $0.50/run

**Debug**:
- Check cache/tweet_embeds_*.json exists
- Count generation calls (should be ~10-20 for 50 candidates)

**Fixes**:
- Reduce --max-candidates to 30
- Increase green threshold to 0.65 (fewer generations)
- Verify caching works

## Files to Review

Key files for understanding system:

1. `CHECKPOINT_2025-10-21_comment-finder-v1-complete.md` - Full context
2. `README.md` - Comment Finder section (Quick Start)
3. `projects/ecom/finder.yml` - Configuration example
4. `viraltracker/generation/comment_finder.py` - Scoring logic
5. `viraltracker/generation/comment_generator.py` - AI generation
6. `viraltracker/cli/twitter.py` - CLI commands (lines 500-900)
7. `migrations/2025-10-21_comment_finder.sql` - Database schema

## Git Commits (For Reference)

All 7 commits on `feature/comment-finder-v1`:

1. `eb0b311` - Archive legacy code and outdated documentation
2. `2669ac7` - Add YouTube keyword/hashtag search
3. `e3de2c9` - Add query batching
4. `e2c9c94` - Fix scorer v1.2.0 compatibility
5. `382dc42` - Add Hook Analysis Module
6. `7c8a4f1` - Complete Comment Finder V1 core implementation (Phases 1-4)
7. `7e9cf88` - Complete Comment Finder V1 documentation

## After Testing

Once Phase 5 is complete:

1. **Document results** in new checkpoint file
2. **Create PR** if all tests pass:
   ```bash
   gh pr create --title "Comment Finder V1 - AI-Powered Reply Finder" \
     --body "..." # Include test results
   ```
3. **Decide on V1.1** features based on real usage

## Questions to Answer

As you test, answer these:

1. Does scoring accurately identify high-potential tweets?
2. Are AI suggestions contextual and on-brand?
3. Would you actually post these replies?
4. Are there any edge cases that break the system?
5. Should any thresholds/weights be adjusted?
6. Is the CSV export format useful?
7. Are costs acceptable for daily usage?

---

## Ready to Start

You should now have everything needed to run Phase 5 end-to-end testing. Start with Step 1 (validate database) and work through systematically.

**Good luck!** This is the final validation before Comment Finder V1 ships.
