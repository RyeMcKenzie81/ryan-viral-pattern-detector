# Content Filter Update V1.5

**Date**: October 28, 2025
**Features**: Enhanced blacklist + Link spam detection

## Changes Made

### 1. Updated Blacklist Keywords

**File**: `projects/yakety-pack-instagram/finder.yml`

Added three categories of filters:

#### Political Content
- trump
- donald trump
- maga
- make america great

#### Racism & Hate Speech
- racist
- racism
- white supremacy
- hate crime
- racial slur
- bigot
- xenophob

#### Low-Quality Link Spam
- click here
- link in bio
- check out my
- visit my website
- read more here
- swipe up

### 2. Smart Link Spam Detection

**File**: `viraltracker/generation/comment_finder.py`

Added intelligent filtering for link spam tweets:

**Logic**:
```
IF tweet has a link (http://, https://, or t.co/)
  AND meaningful text < 50 characters (excluding URLs, mentions, hashtags)
  AND no replies/comments
THEN block as "link spam"
```

**Example Blocked**:
```
"Check this out! https://spammy-link.com"
→ Only 14 chars of actual text + link + 0 replies = BLOCKED
```

**Example Allowed**:
```
"This article about screen time rules really changed my perspective.
Worth a read: https://article.com"
→ 70+ chars of text = ALLOWED (even with 0 replies)

"Great resource! https://link.com"
→ Only 15 chars BUT has 5 replies = ALLOWED (shows engagement)
```

## How It Works

### Three-Layer Filtering

**Layer 1: Language Check**
- Only English tweets pass

**Layer 2: Blacklist Keywords**
- 18 total keywords (promotional, political, hate speech, link spam patterns)
- Case-insensitive substring matching
- Blocks before scoring (saves API costs)

**Layer 3: Smart Link Spam Detection** (NEW)
- Analyzes text-to-link ratio
- Considers engagement (replies) as quality signal
- Blocks low-effort promotional tweets

### Performance Impact

- **Zero slowdown** - All filtering is regex/string operations
- **Cost savings** - Blocks spam before expensive LLM calls
- **Smarter filtering** - Context-aware, not just keyword matching

## Testing

Test the new filters:

```bash
source venv/bin/activate && python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --max-candidates 100 \
  --greens-only
```

Look for output like:

```
✓ Scored 95 tweets
- Passed gate: 60
- Blocked: 35   # <-- Should be higher now

Blocked reasons:
- blacklist keyword: trump (8)
- blacklist keyword: racist (2)
- link spam: short text (15 chars) + link + no engagement (12)
- blacklist keyword: link in bio (13)
```

## Configuration

All configuration is in:
```
projects/yakety-pack-instagram/finder.yml
```

**Changes take effect immediately** - no restart needed.

## Adding More Keywords

To add more blacklist keywords, edit `finder.yml`:

```yaml
sources:
  blacklist_keywords:
  # Existing filters
  - trump
  - racist
  - link in bio

  # Add new ones:
  - your_keyword_here
  - another_keyword
```

## Adjusting Link Spam Threshold

The link spam detector uses a 50-character threshold. To adjust:

Edit `viraltracker/generation/comment_finder.py` line 361:

```python
# Current: Block if < 50 chars + link + no replies
if text_length < 50 and replies == 0:

# More aggressive (blocks more):
if text_length < 100 and replies < 5:

# More lenient (blocks less):
if text_length < 30 and replies == 0:
```

## Current Full Blacklist

```yaml
blacklist_keywords:
# Promotional/spam content (4)
- giveaway
- sponsored
- affiliate
- crypto

# Political content (4)
- trump
- donald trump
- maga
- make america great

# Racism and hate speech (7)
- racist
- racism
- white supremacy
- hate crime
- racial slur
- bigot
- xenophob

# Low-quality link spam (6)
- click here
- link in bio
- check out my
- visit my website
- read more here
- swipe up
```

**Total**: 21 blacklist keywords + smart link detection

## Code Changes Summary

### Modified Files

1. **projects/yakety-pack-instagram/finder.yml**
   - Added 17 new blacklist keywords (political, hate speech, link spam)

2. **viraltracker/generation/comment_finder.py**
   - Updated `gate_tweet()` function signature (line 300)
   - Added `replies` parameter
   - Added link spam detection logic (lines 346-362)
   - Updated function call in `score_tweet()` (line 409)

### Lines Changed
- `comment_finder.py:300-364` - Enhanced gate_tweet function
- `comment_finder.py:409` - Updated function call
- `finder.yml:34-62` - Expanded blacklist

## Related Documentation

- `CONTENT_FILTERING_GUIDE.md` - Complete filtering system guide
- `PRIORITIZATION_V1.4.md` - Export prioritization feature

## Version History

- **V1.5** (Oct 28, 2025) - Smart link spam detection + expanded blacklist
- **V1.4** (Oct 28, 2025) - Export prioritization (balanced scoring)
- **V1.0-V1.3** - Initial comment finder releases
