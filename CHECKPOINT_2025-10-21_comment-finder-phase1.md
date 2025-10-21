# Checkpoint: Comment Finder V1 - Phase 1 (Foundation)

**Date:** October 21, 2025
**Branch:** `feature/comment-finder-v1`
**Status:** Foundation Complete - Ready for Phase 2 ✅

---

## Executive Summary

Started implementation of the Comment Opportunity Finder system - a CLI tool that scores fresh tweets, generates AI-powered reply suggestions, and exports opportunities to CSV for manual posting. This checkpoint covers Phase 1 (Foundation) completion.

**Progress:** ~20% complete (Phase 1 of 5)

---

## Original Plan Overview

### Three-Layer Architecture
1. **Ingest** — Collect and normalize raw data (already complete: Twitter scraping)
2. **Generate** — Create content based on ingested data (comment suggestions) ← Building this
3. **Gate/Filter** — Evaluate, score, and route data for quality and relevance ← Building this

### V1 Deliverables
1. **CLI Commands:**
   - `vt twitter generate-comments` — score, label, and generate reply suggestions
   - `vt twitter export-comments` — export top suggestions to CSV

2. **Scoring System:**
   - Velocity (engagement per minute / audience normalization)
   - Relevance (taxonomy matching via embeddings)
   - Openness (regex-based question/hedge detection)
   - Author Quality (whitelist/unknown/blacklist)
   - Labels: green/yellow/red based on total score

3. **AI Generation:**
   - 3 reply types per tweet: add_value, ask_question, mirror_reframe
   - Single Gemini API call per tweet (JSON response)
   - Voice/persona matching from config

4. **CSV Export:**
   - Columns: project, tweet_id, url, author, followers, tweeted_at, likes, replies, rts, score_total, label, topic, suggestion_type, comment, why

---

## What We've Completed (Phase 1)

### 1. ✅ Database Migrations
**File:** `migrations/2025-10-21_comment_finder.sql`

Created 4 tables:

**a) `generated_comments`** - Core handoff table
- Stores AI-generated suggestions with scoring
- Status lifecycle: pending → exported → posted/skipped
- Unique constraint on (project_id, tweet_id, suggestion_type)
- Includes: topic, why, rank, review_status for future UI

**b) `tweet_snapshot`** - Historical tweet data
- Captures tweet metrics at processing time
- Used for velocity calculation and author analysis
- Indexed by project, time, and author

**c) `author_stats`** - Author engagement metrics
- Tracks author reply patterns (for openness scoring in V1.1)
- Optional for V1, can populate incrementally

**d) `acceptance_log`** - Duplicate prevention
- Tracks processed tweets for 7-day lookback
- Prevents re-generating comments for same tweet
- Includes vector(768) column for semantic dedup in V1.1

**Key Design Decisions:**
- Used pgvector extension (for future semantic dedup)
- All tables have proper indexes for query performance
- Status enums enforced at DB level
- Comments include helpful metadata (topic, why, rank)

### 2. ✅ Embeddings Infrastructure
**File:** `viraltracker/core/embeddings.py`

Implemented complete embedding system:

**Core Components:**
- `Embedder` class - Gemini text-embedding-004 integration
- Batch processing (up to 100 texts per request)
- Retry logic with exponential backoff
- Rate limiting between batches

**Caching System:**
- JSON-based caching (no DB dependency for V1)
- Tweet embeddings by date: `cache/tweet_embeds_YYYYMMDD.json`
- Taxonomy embeddings by project: `cache/taxonomy_{project_id}.json`
- SHA256 hashing for cache keys

**Utilities:**
- `cosine_similarity()` - Vector similarity calculation
- `cache_get()` / `cache_set()` - JSON cache helpers
- Query vs document embedding modes

**Technical Specs:**
- Model: `models/text-embedding-004`
- Dimensions: 768
- Task types: RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY

### 3. ✅ Config Loader (Complete)
**File:** `viraltracker/core/config.py`

**Completed:**
- Added imports for yaml, dataclasses, typing
- Added `FinderConfig` dataclass
- Added `TaxonomyNode` dataclass
- Added `VoiceConfig` and `SourcesConfig` dataclasses
- Added `load_finder_config(project_slug)` function
- Added auto-generation of exemplars if missing
- Handles both GEMINI_API_KEY and GOOGLE_GEMINI_API_KEY

### 4. ✅ Phase 1 Testing (Complete)
**Files:** `test_phase1.py`, `projects/test-project/finder.yml`

**Test Results:**
- ✓ Config Loader: Successfully loads finder.yml configurations
- ✓ Embeddings: 768-dimension vectors, batch processing, cosine similarity
- ✓ Database: All 4 tables created and accessible in Supabase

**Dependencies Added:**
- PyYAML (for YAML config parsing)

---

## Configuration Spec (To Implement)

### finder.yml Structure
```yaml
taxonomy:
  - label: "facebook ads"
    description: "Paid acquisition on Meta: account structure, creatives, MER/CPA/ROAS"
    exemplars:  # optional, auto-generate if missing
      - "ASC is great until it isn't—split by audience freshness"
      - "Angles beat formats. Test 3 angles this week"

voice:
  persona: "direct, practical, contrarian-positive"
  constraints: ["no profanity", "avoid hype words"]
  examples:
    good:
      - "CPM isn't your bottleneck—creative fatigue is"
    bad:
      - "Wow amazing insight! 🔥🔥"

sources:
  whitelist_handles: ["mosseri", "shopify"]
  blacklist_keywords: ["giveaway", "airdrop", "link in bio"]

weights:
  velocity: 0.35
  relevance: 0.35
  openness: 0.20
  author_quality: 0.10

thresholds:
  green_min: 0.72
  yellow_min: 0.55

generation:
  temperature: 0.2
  max_tokens: 80
  model: "gemini-2.5-flash"
```

**Location:** `projects/{project_slug}/finder.yml`

### Taxonomy Exemplar Auto-Generation
If `exemplars` is empty or missing, generate 5 with Gemini:
```
Prompt: "Generate 5 tweet-length exemplars (15-25 words) that discuss: {description}.
Keep them specific, jargon-accurate, no emojis, no hashtags."
```

---

## File Structure Created

```
viraltracker/
├─ migrations/
│  └─ 2025-10-21_comment_finder.sql          ✅ COMPLETE
├─ viraltracker/
│  └─ core/
│     ├─ config.py                           ⏳ IN PROGRESS
│     └─ embeddings.py                       ✅ COMPLETE
└─ cache/                                     ✅ CREATED (gitignored)
```

---

## Still To Build (Phases 2-5)

### Phase 2: Scoring Logic
**Files to create:**
- `viraltracker/generation/comment_finder.py` - Core scoring logic

**Functions needed:**
- `compute_velocity(metrics, minutes_since, followers)` - Engagement/time ratio
- `relevance_from_taxonomy(embedding, taxo_vectors)` - Cosine + margin
- `openness_score(text, author_reply_rate=None)` - Regex-based
- `author_quality_score(handle, config)` - Whitelist/blacklist lookup
- `total_score(vel, rel, open, aq, weights)` - Weighted sum
- `label_from_score(total, thresholds)` - Green/yellow/red
- `gate(tweet, config, safety)` - Blacklist/safety/language filtering

### Phase 3: Generation Logic
**Files to create:**
- `viraltracker/generation/prompts/comments.json` - Prompt templates

**Functions needed:**
- `generate_comment_suggestions(tweet, config)` - Single Gemini call → 3 suggestions
- `validate_safety(suggestion)` - Check Gemini safety flags
- `save_suggestions_to_db(tweet_id, suggestions, scores)` - Write to generated_comments

**Gemini Integration:**
- Model: `gemini-2.5-flash`
- Temperature: 0.2
- Output: JSON with keys: add_value, ask_question, mirror_reframe
- One call per tweet (not 3 separate calls)

### Phase 4: CLI Commands
**Files to create:**
- `viraltracker/cli/twitter_comments.py` - CLI command definitions

**Commands:**
```bash
# Generate suggestions
vt twitter generate-comments \
  --project my-project \
  --hours-back 6 \
  --min-followers 1000 \
  --use-gate \
  --max-candidates 150

# Export to CSV
vt twitter export-comments \
  --project my-project \
  --out data/comment_opps.csv \
  --limit 200
```

### Phase 5: Testing & Validation
- Test scoring thresholds with real data
- Validate taxonomy matching accuracy
- Review sample generated comments
- Verify CSV format and content
- Test gate filtering effectiveness

---

## Key Implementation Details

### Scoring Algorithm
```python
# Velocity (0..1)
eng_per_min = (likes + 2*replies + 1.5*rts) / max(1, minutes_since)
aud_norm = log10(max(100, followers))
velocity = sigmoid(6.0 * eng_per_min / aud_norm)

# Relevance (0..1)
sims = [(label, cosine(tweet_vec, node_vec)) for label, node_vec in taxonomy]
best, second_best = top_2(sims)
relevance = 0.8*best + 0.2*max(0, best - second_best)

# Openness (0..1, regex-based for V1)
score = 0.0
if ends_with_question or starts_with_wh: score += 0.25
if has_hedge_words: score += 0.15
if author_reply_rate < 0.15: score += 0.10  # optional for V1
else: score += 0.05  # neutral default

# Author Quality
whitelist → 0.9, unknown → 0.6, blacklist → 0.0

# Total Score
total = 0.35*velocity + 0.35*relevance + 0.20*openness + 0.10*author_quality

# Labels
if total >= 0.72: green
elif total >= 0.55: yellow
else: red
```

### Generation Strategy
**One Call Per Tweet:**
```python
prompt = {
    "tweet": original_text,
    "topic": best_taxonomy_match,
    "voice": {
        "persona": config.voice.persona,
        "constraints": config.voice.constraints,
        "examples": config.voice.examples.good[:2]
    },
    "instruction": "Generate 3 replies. Output JSON: {add_value, ask_question, mirror_reframe}"
}

response = gemini.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    generation_config={"temperature": 0.2, "response_mime_type": "application/json"}
)

suggestions = json.loads(response.text)
```

### Duplicate Prevention
```python
# Check 7-day acceptance
SELECT 1 FROM acceptance_log
WHERE project_id = :pid
  AND source = 'twitter'
  AND foreign_id = :tweet_id
  AND accepted_at >= now() - interval '7 days'

# Check exact text match (last 100)
SELECT 1 FROM generated_comments
WHERE project_id = :pid
  AND comment_text = :candidate_text
ORDER BY created_at DESC
LIMIT 1
```

---

## Technical Decisions Made

### V1 Simplifications (Vs Full Plan)
**Deferred to V1.1:**
- ❌ Author reply rate (need more history) - use neutral default
- ❌ LLM-based openness check (expensive) - use regex only
- ❌ Quality validation + regeneration (adds latency) - trust Gemini defaults
- ❌ Semantic duplicate detection (need pgvector setup) - exact match only

**Kept in V1:**
- ✅ Velocity scoring
- ✅ Taxonomy relevance (embeddings)
- ✅ Regex-based openness
- ✅ Author quality (whitelist/blacklist)
- ✅ 3 reply types
- ✅ CSV export
- ✅ Gate filtering (blacklist/safety)
- ✅ Supabase persistence

### Cost Control Mechanisms
1. Process only green candidates (or top slice of yellow)
2. Require velocity threshold before generation
3. Cap per run (`--max-candidates`)
4. One LLM call per tweet (not 3)
5. Cache embeddings aggressively
6. Batch tweet embeddings (100 at a time)

**Estimated Daily Cost:**
- 200 candidates/day × $0.00001/token × 200 tokens = **~$0.40/day**
- Very affordable, can scale to 1000/day easily

---

## Next Session Tasks (Priority Order)

### Immediate (Config Loader - 30 min)
1. Finish `viraltracker/core/config.py`:
   - Add `FinderConfig` dataclass
   - Add `TaxonomyNode` dataclass
   - Add `load_finder_config(project_slug)` function
   - Add exemplar auto-generation logic

### Phase 2 (Scoring - 2-3 hours)
2. Create `viraltracker/generation/comment_finder.py`:
   - Implement velocity calculation
   - Implement taxonomy matching (with embeddings)
   - Implement openness scoring
   - Implement author quality lookup
   - Implement total scoring + labeling
   - Implement gate filtering

3. Create tweet fetcher:
   - Query posts table for recent tweets
   - Apply basic filters (hours-back, min-followers)
   - Return formatted data for scoring

### Phase 3 (Generation - 2 hours)
4. Create `viraltracker/generation/prompts/comments.json`:
   - System prompt
   - User prompt template with voice injection

5. Implement generation logic:
   - Format prompt with tweet + config
   - Call Gemini with JSON response type
   - Parse 3 suggestions
   - Check safety flags
   - Write to generated_comments table

### Phase 4 (CLI - 1-2 hours)
6. Create `viraltracker/cli/twitter_comments.py`:
   - `generate-comments` command with flags
   - `export-comments` command with flags
   - Wire into main CLI

7. Add CSV export:
   - Query generated_comments + tweet_snapshot
   - Format with exact column order
   - Write to specified path
   - Update status to 'exported'

### Phase 5 (Testing - 1-2 hours)
8. End-to-end testing:
   - Test with real project (ecom or yakety-pack)
   - Validate scoring makes sense
   - Review 10-20 generated comments
   - Adjust thresholds if needed

---

## Commands to Resume

```bash
# Check current branch
git status

# Continue from config.py
code viraltracker/core/config.py

# Or see what's pending
cat CHECKPOINT_2025-10-21_comment-finder-phase1.md
```

---

## Files Modified/Created (This Session)

### New Files
```
migrations/2025-10-21_comment_finder.sql    (4 tables)
viraltracker/core/embeddings.py              (complete embedding system)
CHECKPOINT_2025-10-21_comment-finder-phase1.md  (this file)
```

### Modified Files
```
viraltracker/core/config.py                  (added imports, needs dataclasses)
```

### Git Status
Branch: `feature/comment-finder-v1`
Uncommitted changes: Yes (checkpoint file + code)

---

## Context for Next Session

**Where we are:**
- Foundation complete (DB + embeddings)
- Config loader 50% done
- Ready to build scoring logic

**What to focus on:**
1. Finish config loader (30 min)
2. Build scoring system (2-3 hours)
3. Test scoring with real tweets before moving to generation

**Critical to remember:**
- Use Gemini `text-embedding-004` (768 dims)
- Use Gemini `gemini-2.5-flash` for generation
- One LLM call per tweet → JSON with 3 keys
- Cache everything (taxonomy, tweet embeddings)
- Project config at `projects/{slug}/finder.yml`

---

## Questions for Next Session

None - plan is clear and scoped well for V1.

---

**Status:** ✅ Phase 1 Complete (Foundation)
**Next:** Phase 2 (Scoring Logic)
**Est. Time to V1 Complete:** 6-8 hours remaining
