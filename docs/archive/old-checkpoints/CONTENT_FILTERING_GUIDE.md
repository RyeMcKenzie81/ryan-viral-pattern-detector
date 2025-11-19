# Content Filtering Guide

**Last Updated**: October 28, 2025

## Overview

The Comment Finder has a multi-layer filtering system to avoid unwanted content **at the scoring/relevance level**, before tweets even reach the export stage.

## How Filtering Works

### Layer 1: Gate Filtering (Pre-Scoring)

The **gate filter** blocks tweets before they're scored. Tweets are rejected if they match:

1. **Language check** - Only English tweets pass (configurable)
2. **Blacklist keywords** - Tweets containing blocked keywords
3. **Blacklist handles** - Tweets from blocked authors

**Location**: `viraltracker/generation/comment_finder.py` - `gate_tweet()` function (lines 300-344)

### Layer 2: Relevance Scoring

After gate filtering, tweets are scored against your **3 taxonomy topics**:
- screen time management
- parenting tips
- digital wellness

Tweets that don't semantically match these topics score low and get labeled "red" (< 0.50).

**Location**: `cache/taxonomy_yakety-pack-instagram.json`

### Layer 3: Score Thresholds

- **Green** (≥ 0.50) - Matches taxonomy, passes gate, high engagement
- **Yellow** (≥ 0.40) - Moderate match
- **Red** (< 0.40) - Poor match or fails criteria

## Current Blacklist Configuration

**File**: `projects/yakety-pack-instagram/finder.yml`

```yaml
sources:
  whitelist_handles: []
  blacklist_keywords:
  - giveaway
  - sponsored
  - affiliate
  - crypto
```

Any tweet containing these keywords is **immediately rejected** at the gate level.

## Adding Blacklist Keywords

To filter out specific content types, add keywords to the blacklist in your project's `finder.yml`:

### Example: Filter Out Political & Controversial Content

```yaml
sources:
  whitelist_handles: []
  blacklist_keywords:
  # Existing filters
  - giveaway
  - sponsored
  - affiliate
  - crypto

  # Political content
  - trump
  - biden
  - election
  - republican
  - democrat
  - political

  # Controversial topics (if you want to avoid)
  - abortion
  - gun control
  - climate change denial

  # Low-quality engagement bait
  - click here
  - follow for follow
  - dm me
  - check bio
  - link in bio
```

### Example: Filter Out Specific Parenting Topics

```yaml
sources:
  blacklist_keywords:
  - giveaway
  - sponsored
  - affiliate
  - crypto

  # Topics to avoid
  - homeschool  # If not your audience
  - formula feeding  # Avoid feeding debates
  - sleep training  # Controversial topic
  - gentle parenting  # Specific philosophy
  - attachment parenting

  # Divisive content
  - bad parent
  - terrible mother
  - worst dad
```

### Example: Filter Out Memes & Low-Value Content

```yaml
sources:
  blacklist_keywords:
  - giveaway
  - sponsored
  - affiliate
  - crypto

  # Meme indicators
  - "😂😂😂"  # Multiple laugh emojis
  - lmao
  - lmfao
  - bruh
  - fr fr

  # Engagement bait
  - tag someone
  - share if you agree
  - retweet if
  - like if
```

## Advanced: Blacklist Handles

You can also block specific Twitter accounts:

```yaml
sources:
  whitelist_handles: []
  blacklist_keywords:
  - giveaway
  - sponsored
  - affiliate
  - crypto

  blacklist_handles:
  - spammy_account
  - competitor_brand
  - controversial_influencer
```

**Note**: Handle matching is case-insensitive and strips @ symbol automatically.

## Testing Your Blacklist

After adding keywords, test with a small scrape:

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --max-candidates 100 \
  --greens-only
```

Check the output for blocked tweets:

```
✓ Scored 95 tweets
- Passed gate: 75
- Blocked: 20   # <-- Tweets filtered by blacklist
```

Then export and review:

```bash
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/test_blacklist.csv \
  --limit 20 \
  --greens-only
```

Review the CSV to ensure no unwanted content passed through.

## Keyword Matching Behavior

**Case-insensitive**: "GIVEAWAY", "giveaway", "GiVeAwAy" all match

**Substring matching**: "giveaway" blocks:
- "HUGE GIVEAWAY!"
- "join our giveaway"
- "giveawaycontest"

**Exact word matching is NOT used**, so be careful with short keywords:

❌ **Bad**: `- free` (blocks "free time", "sugar-free", "feel free")
✅ **Better**: `- free shipping`, `- free trial`, `- get free`

## Wildcards & Regex

The current system does **not support** regex or wildcards. All keywords are literal substring matches.

If you need advanced pattern matching, you'd need to modify:
`viraltracker/generation/comment_finder.py` - `gate_tweet()` function

## Recommended Blacklist Templates

### Conservative (Brand Safety)

```yaml
blacklist_keywords:
- giveaway
- sponsored
- affiliate
- crypto
- nft
- onlyfans
- adult content
- porn
- drugs
- violence
- suicide
- self harm
- trump
- biden
- political
```

### Quality-Focused (High-Value Content Only)

```yaml
blacklist_keywords:
- giveaway
- sponsored
- affiliate
- crypto
- tag someone
- follow for follow
- dm me
- link in bio
- click here
- lmao
- bruh
```

### Niche-Specific (Yakety Pack Example)

```yaml
blacklist_keywords:
- giveaway
- sponsored
- affiliate
- crypto

# Avoid divisive parenting debates
- formula feeding
- breastfeeding wars
- sleep training debate
- cry it out
- attachment parenting drama

# Avoid mom-shaming content
- bad mom
- worst parent
- terrible mother
- lazy parenting
```

## Performance Impact

- **Minimal** - Gate filtering is fast (simple string matching)
- Runs **before** expensive embedding/LLM calls
- Actually **saves money** by filtering out junk before API calls

## Monitoring Filtered Content

To see what's being filtered, check the generation logs:

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 48 \
  --greens-only 2>&1 | tee ~/Downloads/generation_log.txt
```

Look for lines like:

```
✓ Scored 500 tweets
- Passed gate: 420
- Blocked: 80   # <-- 80 tweets filtered by blacklist
```

## When to Use Export Filtering vs Blacklist

**Use Blacklist (Pre-Scoring)**:
- Content you NEVER want to engage with
- Spam, promotional content, controversial topics
- Saves API costs by filtering before LLM calls

**Use Export Filtering** (`--label green`):
- Prioritizing high-quality over moderate-quality
- Sorting by score vs views vs balanced
- Already paid for scoring, just selecting best

## Configuration File Location

```
/Users/ryemckenzie/projects/viraltracker/projects/yakety-pack-instagram/finder.yml
```

Changes to this file take effect immediately on the next run.

## Related Documentation

- `PRIORITIZATION_V1.4.md` - Export prioritization and sorting
- `viraltracker/generation/comment_finder.py` - Scoring implementation
- `viraltracker/core/config.py` - Configuration loading
