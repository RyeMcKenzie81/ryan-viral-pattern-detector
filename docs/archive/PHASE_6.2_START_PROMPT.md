# Phase 6.2: Python Integration - START HERE

**Context:** Phase 6.1 complete ✅ (TypeScript scorer + database schema deployed)

**Current Location:** `/Users/ryemckenzie/projects/viraltracker/`

---

## Quick Status Check

Phase 6.1 delivered:
- ✅ TypeScript scoring engine in `scorer/` (9 subscores, stdin/stdout CLI)
- ✅ Database schema: `video_scores` table + trigger + views
- ✅ 16 tests passing, sample score: 89.3/100
- ✅ Committed (feb9d5b) and pushed to GitHub

**Scorer works:**
```bash
cd scorer
echo '{"meta":{...}, "measures":{...}}' | npm run cli
# Returns: {"version":"1.0.0","overall":89.3,"subscores":{...}}
```

**Database ready:**
- `video_scores` table exists (8 indexes, RLS enabled)
- `video_analysis.overall_score` column added
- Trigger syncs scores automatically

---

## What We're Building (Phase 6.2)

**Goal:** Connect Python CLI to TypeScript scorer so we can run:
```bash
vt score videos --project wonder-paws-tiktok
# Scores all analyzed videos in project, saves to video_scores table
```

**Architecture:**
```
Python CLI (vt score videos)
  ↓
Fetch video_analysis + posts data from Supabase
  ↓
data_adapter.py: Convert DB rows → scorer input JSON
  ↓
subprocess: node scorer/dist/cli.js < input.json
  ↓
Parse stdout JSON
  ↓
INSERT INTO video_scores (9 subscores + overall)
  ↓ (trigger fires)
UPDATE video_analysis SET overall_score = ...
```

---

## Implementation Plan (3 Files to Create)

### File 1: `viraltracker/scoring/__init__.py`
Empty file to make it a package.

### File 2: `viraltracker/scoring/data_adapter.py`
**Purpose:** Convert database data → scorer input JSON

**Key functions:**
- `prepare_scorer_input(post_id: str, supabase) -> Dict`
  - Fetch post + video_analysis from DB
  - Extract hook, story, visuals, audio, watchtime, engagement, shareability, algo measures
  - Format as scorer input JSON (see schema in `scorer/src/schema.ts`)

**Data sources:**
- `posts` table: `created_at`, `account_id`
- `accounts` table: `follower_count` (for relatability score)
- `video_analysis` table:
  - `hook_transcript`, `hook_type`, `hook_timestamp`
  - `transcript` (JSON: segments with speaker/text)
  - `storyboard` (JSON: scenes with timestamp/duration/description)
  - `text_overlays` (JSON: overlays with timestamp/text/style)
  - `key_moments` (JSON: moments with type/description)
- `video_processing_log` table: `video_duration_sec`

**Helper functions:**
- `_count_hashtags(caption: str) -> int`
- `_check_hashtag_mix(caption: str) -> bool`
- `_detect_cta(caption: str) -> bool`
- `_convert_storyboard(storyboard: Dict) -> List[Dict]`
- `_convert_overlays(text_overlays: Dict) -> List[Dict]`
- `_detect_story_arc(storyboard: Dict, key_moments: Dict) -> bool`

**Example output:**
```python
{
  "meta": {
    "video_id": "uuid",
    "post_time_iso": "2024-01-15T10:00:00Z",
    "followers": 50000,
    "length_sec": 35
  },
  "measures": {
    "hook": {
      "duration_sec": 4.5,
      "text": "dog parents listen carefully...",
      "type": "curiosity|authority",
      "effectiveness_score": 8.5
    },
    "story": {
      "storyboard": [...],
      "beats_count": 3,
      "arc_detected": True
    },
    # ... (8 more subscore measures)
  },
  "raw": {
    "transcript": [...],
    "hook_span": {"t_start": 0, "t_end": 4.5}
  }
}
```

### File 3: `viraltracker/cli/score.py`
**Purpose:** CLI command to score videos

**Command:**
```bash
vt score videos --project wonder-paws-tiktok [--limit 10] [--rescore]
```

**Flow:**
1. Get project by slug
2. Find analyzed videos in project (via `project_posts` join)
3. Filter out already-scored (unless `--rescore`)
4. For each video:
   - Call `prepare_scorer_input(post_id, supabase)`
   - Run `subprocess.run(["node", "scorer/dist/cli.js"], input=json.dumps(scorer_input), ...)`
   - Parse stdout JSON
   - `supabase.table("video_scores").upsert({...})`
5. Show summary (scored: X, failed: Y)

**Error handling:**
- Scorer returns non-zero: Log error, continue to next video
- Missing data: Scorer handles with diagnostics, still returns score
- Database errors: Retry once, then fail

### File 4: Update `viraltracker/cli/main.py`
**Purpose:** Register new `score` command group

```python
from .score import score_group

# In cli() function
cli.add_command(score_group)
```

---

## Reference Files to Read

**Before coding, read these:**

1. **Scorer input schema:**
   - `scorer/src/schema.ts` - Shows exact structure of `ScorerInputSchema`
   - `scorer/sample.json` - Example input with all fields

2. **Current database schema:**
   - `sql/01_migration_multi_brand.sql` - Posts, accounts, video_analysis structure
   - `sql/04_video_scores.sql` - New video_scores table

3. **Existing CLI patterns:**
   - `viraltracker/cli/tiktok.py` - How we do `--project` flag, progress bars, error handling
   - `viraltracker/analysis/video_analyzer.py` - How we fetch video_analysis data

4. **Data adapter reference:**
   - `PHASE_6_SCORING_ENGINE_PLAN.md` lines 256-442 - Full data adapter pseudocode

---

## Database Query Reference

**Get analyzed videos for a project:**
```python
# Get project
project = supabase.table("projects").select("id, name").eq("slug", project_slug).single().execute()

# Get analyzed posts in project
query = supabase.table("video_analysis").select(
  "post_id, posts!inner(id, created_at, account_id), accounts(follower_count)"
).in_("post_id",
  supabase.table("project_posts").select("post_id").eq("project_id", project.data['id']).execute().data
)

analyses = query.execute().data
```

**Get video duration:**
```python
duration_result = supabase.table("video_processing_log").select(
  "video_duration_sec"
).eq("post_id", post_id).single().execute()

length_sec = duration_result.data['video_duration_sec'] if duration_result.data else 0
```

**Get full video_analysis:**
```python
analysis = supabase.table("video_analysis").select("*").eq("post_id", post_id).single().execute()

# Parse JSON fields
storyboard = json.loads(analysis.data.get('storyboard', '{}')) if analysis.data.get('storyboard') else {}
text_overlays = json.loads(analysis.data.get('text_overlays', '{}')) if analysis.data.get('text_overlays') else {}
transcript = json.loads(analysis.data.get('transcript', '{}')) if analysis.data.get('transcript') else {}
```

---

## Subprocess Pattern

**Call TypeScript scorer:**
```python
import json
import subprocess
from pathlib import Path

SCORER_PATH = Path(__file__).parent.parent.parent / "scorer"

# Prepare input
scorer_input = prepare_scorer_input(post_id, supabase)

# Call scorer
result = subprocess.run(
    ["node", "dist/cli.js"],
    input=json.dumps(scorer_input),
    capture_output=True,
    text=True,
    cwd=SCORER_PATH
)

if result.returncode != 0:
    raise Exception(f"Scorer failed: {result.stderr}")

# Parse output
scores = json.loads(result.stdout)

# Save to DB
supabase.table("video_scores").upsert({
    "post_id": post_id,
    "scorer_version": scores["version"],
    "hook_score": scores["subscores"]["hook"],
    "story_score": scores["subscores"]["story"],
    # ... (7 more subscores)
    "penalties_score": scores["penalties"],
    "overall_score": scores["overall"],
    "score_details": scores  # Full JSON
}, on_conflict="post_id,scorer_version").execute()
```

---

## Success Criteria for Phase 6.2

- [ ] `viraltracker/scoring/data_adapter.py` created with `prepare_scorer_input()`
- [ ] `viraltracker/cli/score.py` created with `vt score videos` command
- [ ] Command registered in `main.py`
- [ ] Can run: `vt score videos --project wonder-paws-tiktok --limit 1`
- [ ] Score saved to `video_scores` table
- [ ] `video_analysis.overall_score` updated via trigger
- [ ] Query works: `SELECT * FROM scored_videos_full LIMIT 1;`
- [ ] Error handling works (missing data, scorer failure)

---

## Testing Plan

**Step 1: Test data adapter**
```python
# Create test script: test_data_adapter.py
from viraltracker.scoring.data_adapter import prepare_scorer_input
from viraltracker.core.database import get_supabase_client

supabase = get_supabase_client()
analysis = supabase.table("video_analysis").select("post_id").limit(1).execute()
post_id = analysis.data[0]['post_id']

scorer_input = prepare_scorer_input(post_id, supabase)
print(json.dumps(scorer_input, indent=2))

# Verify structure matches scorer/sample.json
```

**Step 2: Test subprocess call**
```bash
cd scorer && npm run build  # Ensure scorer is built
python test_data_adapter.py | node scorer/dist/cli.js
# Should output scores JSON
```

**Step 3: Test CLI command**
```bash
vt score videos --project wonder-paws-tiktok --limit 1
# Should score 1 video and save to DB
```

**Step 4: Verify database**
```sql
SELECT * FROM video_scores ORDER BY scored_at DESC LIMIT 1;
SELECT post_id, overall_score, scored_at FROM video_analysis WHERE overall_score IS NOT NULL LIMIT 1;
SELECT * FROM scored_videos_full LIMIT 1;
```

---

## Common Issues & Solutions

### Issue: "node: command not found"
**Solution:** Ensure Node.js is installed and in PATH. Use full path if needed.

### Issue: Scorer returns empty JSON
**Solution:** Check stderr for errors. Ensure scorer is built (`npm run build`).

### Issue: Missing video_duration_sec
**Solution:** Use fallback: `length_sec = 0` and set diagnostics flag.

### Issue: JSON parsing errors in storyboard/transcript
**Solution:** Wrap in try/except, use empty dict/list as fallback.

### Issue: "video_scores_pkey violation"
**Solution:** Use `upsert()` with `on_conflict="post_id,scorer_version"`.

---

## Files to Create (Checklist)

- [ ] `viraltracker/scoring/__init__.py`
- [ ] `viraltracker/scoring/data_adapter.py`
- [ ] `viraltracker/cli/score.py`
- [ ] Update `viraltracker/cli/main.py`
- [ ] Optional: `test_data_adapter.py` (for development)

---

## Next Steps After Phase 6.2

**Phase 6.3: Batch Scoring**
1. Score all 120+ analyzed videos
2. Export scores to CSV
3. Analyze score distribution
4. Adjust weights if needed (version bump to 1.1.0)

---

## Quick Start Commands

```bash
# 1. Ensure scorer is built
cd scorer && npm run build && cd ..

# 2. Create data adapter
# (Follow PHASE_6_SCORING_ENGINE_PLAN.md lines 256-442)

# 3. Create CLI command
# (Follow PHASE_6_SCORING_ENGINE_PLAN.md lines 593-748)

# 4. Test on one video
vt score videos --project wonder-paws-tiktok --limit 1

# 5. Batch score all
vt score videos --project wonder-paws-tiktok
```

---

## Key Context

- **Current working directory:** `/Users/ryemckenzie/projects/viraltracker/`
- **Scorer location:** `scorer/` (sibling to `viraltracker/`)
- **Scorer built:** `scorer/dist/cli.js` (run `npm run build` first)
- **Python package:** `viraltracker/` (where CLI lives)
- **Database:** Supabase (connection in `viraltracker/core/database.py`)
- **Existing videos:** 120+ analyzed TikTok videos in `video_analysis` table
- **Target project:** `wonder-paws-tiktok` (slug)

---

**Ready to code?** Start with `viraltracker/scoring/data_adapter.py` and reference `PHASE_6_SCORING_ENGINE_PLAN.md` for the full implementation details.

Good luck! 🚀
