# Phase 6.1: TikTok Scoring Engine - COMPLETE ✅

**Completed:** October 8, 2024
**Status:** Production-ready, tested, deployed to Supabase

---

## Summary

Built a deterministic TypeScript scoring engine that evaluates TikTok videos using 9 subscores (hook, story, relatability, visuals, audio, watchtime, engagement, shareability, algo) + penalties to produce a final 0-100 score.

**Key Achievement:** Fully functional scoring system ready for Python integration.

---

## What Was Built

### 1. Database Schema (`sql/04_video_scores.sql`)

**Tables:**
- `video_scores` - Stores 9 subscores + penalties + overall_score
  - Unique constraint: `(post_id, scorer_version)` for versioning
  - All subscores: `FLOAT NOT NULL CHECK (score >= 0 AND score <= 100)`
  - `overall_score` computed by TypeScript, stored as plain FLOAT (not generated column)
  - `score_details` JSONB for full scorer output (weights, diagnostics, flags)

**Indexes (8 total):**
- `idx_video_scores_post_id` - Fast lookups by post
- `idx_video_scores_overall` - Sorting by score (DESC)
- `idx_video_scores_scored_at` - Sorting by time (DESC)
- `idx_video_scores_version` - Filtering by scorer version
- `idx_video_scores_post_latest` - Unique partial index for version 1.0.0
- `idx_video_scores_details_gin` - JSONB filtering on flags/diagnostics
- Primary key + unique constraint indexes

**Trigger:**
- `sync_score_to_analysis` - Auto-syncs `overall_score` and `scored_at` from `video_scores` → `video_analysis`

**Views:**
- `video_scores_latest` - Latest score per post (newest scorer_version, then scored_at)
- `scored_videos_full` - Join posts + video_analysis + video_scores with all metadata

**RLS:**
- Enabled on `video_scores` table
- Read policy: Public (`USING (true)`)
- Write policy: Service role only (no policy = restricted)

**Migration Verification:**
```
✅ Table exists: 1
✅ Indexes count: 8
✅ Trigger exists: 1
✅ RLS enabled: true
✅ New columns in video_analysis: 2 (overall_score, scored_at)
```

---

### 2. TypeScript Scoring Engine (`scorer/`)

**Project Structure:**
```
scorer/
├── package.json          # Dependencies: zod, typescript, vitest, tsx
├── tsconfig.json         # TypeScript config (ES2022, strict mode)
├── vitest.config.ts      # Test configuration
├── sample.json           # Test fixture
├── .gitignore
├── README.md
├── src/
│   ├── schema.ts         # Zod validation schemas (input/output)
│   ├── types.ts          # TypeScript types + constants
│   ├── formulas.ts       # 9 scoring functions + penalties
│   ├── scorer.ts         # Orchestrator with diagnostics
│   └── cli.ts            # stdin/stdout CLI interface
└── tests/
    └── scorer.test.ts    # 16 tests (smoke + sample data)
```

**Scoring Weights (DEFAULT_WEIGHTS):**
```typescript
{
  hook: 0.18,        // 18% - First impression
  story: 0.10,       // 10% - Narrative structure
  relatability: 0.06, // 6%  - Audience connection
  visuals: 0.08,     // 8%  - Production quality
  audio: 0.06,       // 6%  - Sound/music
  watchtime: 0.25,   // 25% - Retention (highest weight!)
  engagement: 0.15,  // 15% - Social proof
  shareability: 0.07, // 7%  - Viral mechanics
  algo: 0.05         // 5%  - Platform optimization
}
// Total: 100%
```

**Scoring Formulas:**

1. **Hook (0-100):** Duration (3-5s ideal), type (shock/curiosity/authority), effectiveness score from Gemini
2. **Story (0-100):** Beat count (3+ ideal), story arc detected, pacing consistency
3. **Relatability (0-100):** Direct address ("you"/"your"), emotional triggers, common scenarios, account size
4. **Visuals (0-100):** Text overlays present, overlay count, edit rate per 10s
5. **Audio (0-100):** Trending sound used (+25), original sound created (+20), beat sync score
6. **Watchtime (0-100):** Length (15-45s ideal), avg watch %, completion rate
7. **Engagement (0-100):** Like rate (10%+ excellent), comment rate (1%+ excellent), share rate (1%+ viral)
8. **Shareability (0-100):** Caption length (100-150 chars ideal), has CTA, save-worthy signals
9. **Algo (0-100):** Hashtag count (3-5 optimal), niche/broad mix, caption length (50+ chars)
10. **Penalties (0+):** Spam indicators (10+ hashtags), low quality signals, excessive length (>2min), poor formatting

**Output Format:**
```json
{
  "version": "1.0.0",
  "subscores": {
    "hook": 100, "story": 85, "relatability": 58,
    "visuals": 85, "audio": 81.25, "watchtime": 100,
    "engagement": 70, "shareability": 96, "algo": 100
  },
  "penalties": 0,
  "overall": 89.3,
  "weights": { ... },
  "diagnostics": {
    "missing": [],
    "overall_confidence": 1.0
  },
  "flags": {
    "incomplete": false,
    "low_confidence": false
  }
}
```

**Testing:**
- 16 tests passing (100% success rate)
- Smoke tests: Bounds checking (0-100), schema validation
- Formula tests: Hook duration, story arc, engagement rates, watchtime optimization
- Sample data tests: High-quality (89.3/100), average (50-70), low-quality (<50), incomplete data
- Diagnostics: Missing field detection, confidence scoring

**Usage:**
```bash
# Development (tsx, no build)
npm run dev < sample.json

# Production (compiled)
npm run build
npm run cli < sample.json

# Testing
npm test
```

---

## Key Design Decisions

### 1. App-Computed Overall Score (Not DB-Generated)
**Decision:** Store `overall_score` as plain FLOAT, computed by TypeScript scorer.
**Rationale:**
- Allows per-row weights (future flexibility)
- Supports normalization (targetMean, targetStd)
- Enables version-specific scoring logic
- Avoids DB/app drift when weights change

### 2. Weights Prioritize Watchtime (25%)
**Decision:** Watchtime gets highest weight, hook second (18%).
**Rationale:**
- TikTok algorithm heavily favors retention
- Hook gets you the first 3 seconds, watchtime keeps them
- Engagement (15%) rewards social proof
- Lower weights for relatability/shareability (harder to measure deterministically)

### 3. Diagnostics for Missing Data
**Decision:** Don't fail scoring when data is missing - use fallbacks and report confidence.
**Rationale:**
- 120 existing videos may have incomplete Gemini analysis
- Better to score with warnings than fail
- `diagnostics.missing` array + `overall_confidence` (0-1) track data quality
- `flags.incomplete` when >3 critical fields missing

### 4. Normalization Layer (Optional)
**Decision:** Add post-hoc normalization to shift scores toward target distribution.
**Rationale:**
- Raw deterministic scores may cluster (e.g., all 60-80)
- Normalization spreads scores across 0-100 range
- Configurable: `enabled`, `targetMean` (70), `targetStd` (10)
- Preserves relative ordering

### 5. RLS with Public Read, Service Write
**Decision:** Enable RLS with wide-open read policy, no write policy.
**Rationale:**
- Scores are not sensitive (public TikTok data)
- Writes restricted to service role (Python CLI with service key)
- Future: Add user-based policies if needed

---

## Files Created

### Database
- `sql/04_video_scores.sql` - Complete migration (190 lines)
- `sql/04_video_scores_test.sql` - Test suite (126 lines)

### TypeScript Scorer
- `scorer/package.json`
- `scorer/tsconfig.json`
- `scorer/vitest.config.ts`
- `scorer/.gitignore`
- `scorer/README.md`
- `scorer/sample.json`
- `scorer/src/schema.ts` (180 lines)
- `scorer/src/types.ts` (75 lines)
- `scorer/src/formulas.ts` (380 lines)
- `scorer/src/scorer.ts` (120 lines)
- `scorer/src/cli.ts` (45 lines)
- `scorer/tests/scorer.test.ts` (380 lines)

### Documentation
- `PHASE_6.1_COMPLETE.md` (this file)

**Total:** 15 new files, ~1,400 lines of code

---

## Migration Issues Resolved

### Issue 1: UUID Function
**Error:** `uuid_generate_v4()` not available
**Fix:** Use `gen_random_uuid()` + `CREATE EXTENSION IF NOT EXISTS pgcrypto;`

### Issue 2: Weights Mismatch
**Error:** SQL generated column used old weights (0.20/0.15/0.12...)
**Fix:** Changed to app-computed `overall_score`, updated TypeScript weights to canvas spec

### Issue 3: View Column Errors
**Errors:**
- `column p.url does not exist`
- `column p.shares does not exist`
- `column a.username does not exist`

**Fix:** Simplified view to only include verified columns:
```sql
SELECT
  p.id as post_id,
  p.created_at as posted_at,
  va.hook_transcript,
  va.hook_type,
  va.overall_score,
  va.scored_at,
  vs.* (all subscores)
FROM posts p
JOIN video_analysis va ON p.id = va.post_id
LEFT JOIN video_scores_latest vs ON p.id = vs.post_id
```

---

## Testing Results

### Database Tests
```
✅ Table created: video_scores
✅ Indexes created: 8 total
✅ Trigger working: sync_score_to_analysis
✅ RLS enabled: true
✅ Columns added: overall_score, scored_at (video_analysis)
✅ Views accessible: video_scores_latest, scored_videos_full
```

### TypeScript Tests
```
 ✓ tests/scorer.test.ts (16 tests) 5ms

 Test Files  1 passed (1)
      Tests  16 passed (16)
```

### Sample Score Output
Input: Well-optimized TikTok video (4.5s hook, 35s length, trending audio, 573k views)
```json
{
  "version": "1.0.0",
  "overall": 89.3,
  "subscores": {
    "hook": 100.0,      // Perfect 4.5s duration + curiosity/authority
    "story": 85.0,      // 3 beats, arc detected
    "relatability": 58.0, // Some direct address
    "visuals": 85.0,    // 2 overlays, 2.5 edits/10s
    "audio": 81.25,     // Original sound + beat sync 7.5
    "watchtime": 100.0, // 35s = ideal range
    "engagement": 70.0, // 7.8% like rate (good)
    "shareability": 96.0, // 125 chars caption + CTA
    "algo": 100.0       // 4 hashtags, niche mix
  },
  "penalties": 0.0
}
```

---

## Next Steps: Phase 6.2

**Goal:** Python integration to call TypeScript scorer from CLI

**Tasks:**
1. Create `viraltracker/scoring/data_adapter.py` - Convert DB data → scorer input JSON
2. Create `viraltracker/cli/score.py` - CLI command `vt score videos --project <slug>`
3. Register command in `viraltracker/cli/main.py`
4. Test scoring on 1 video end-to-end
5. Batch score all 120+ existing videos

**Data Flow:**
```
Python CLI
  ↓ (fetch from DB)
video_analysis + posts data
  ↓ (data_adapter.py)
scorer input JSON
  ↓ (subprocess)
node scorer/dist/cli.js < input.json
  ↓ (stdout)
scorer output JSON
  ↓ (parse & save)
INSERT INTO video_scores (...)
  ↓ (trigger fires)
UPDATE video_analysis SET overall_score = ...
```

---

## Commands Reference

### TypeScript Scorer
```bash
# Install dependencies
cd scorer && npm install

# Build
npm run build

# Test
npm test

# Run scorer (dev)
npm run dev < sample.json

# Run scorer (prod)
npm run cli < sample.json
```

### Database
```bash
# Run migration
# Paste sql/04_video_scores.sql into Supabase SQL Editor

# Run tests
# Paste sql/04_video_scores_test.sql into Supabase SQL Editor

# Query scores
SELECT * FROM scored_videos_full ORDER BY overall_score DESC LIMIT 10;
```

---

## Version Info

- **Scorer Version:** 1.0.0
- **Database Schema:** 04_video_scores.sql
- **TypeScript:** 5.4.5
- **Node:** ES2022
- **Dependencies:** zod@3.23.8, vitest@1.5.0, tsx@4.7.2

---

**Phase 6.1 Status:** ✅ COMPLETE
**Ready for:** Phase 6.2 - Python Integration
