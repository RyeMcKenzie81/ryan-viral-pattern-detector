# Start Phase 6: TikTok Scoring Engine Integration

## Quick Context

Building **ViralTracker** - a Python CLI tool for analyzing viral TikTok videos. Completed Phase 5d (enhanced output & simplified workflow). Starting Phase 6: deterministic scoring engine.

**Current Location:** `/Users/ryemckenzie/projects/viraltracker/`

**What Exists:**
- 120+ analyzed TikTok videos in Supabase
- Gemini AI analysis (hook, transcript, storyboard, overlays stored in `video_analysis` table)
- ScrapTik metadata (views, likes, comments, caption in `posts` table)
- Working CLI: `vt tiktok analyze-urls <file> --project <slug> --product <slug>`

**What We're Building:**
- TypeScript scoring engine (separate from Python)
- 9 deterministic subscores (hook, story, relatability, visuals, audio, watchtime, engagement, shareability, algo) + penalties
- Output: 0-100 overall score
- Python calls TypeScript via subprocess
- New `video_scores` table + CLI command `vt score videos`

---

## Architecture

```
Python → JSON → TypeScript Scorer → JSON → Python → Database
```

**TypeScript Scorer Location:** `scorer/` subdirectory
**Workflow:** Read stdin JSON → Calculate scores → Output stdout JSON

---

## Implementation Plan

**Full details:** `PHASE_6_SCORING_ENGINE_PLAN.md` (read this file first!)

**Phase 6.1:** Database & TypeScript Scorer (START HERE)
1. Create `sql/04_video_scores.sql` migration
2. Set up TypeScript project in `scorer/`
3. Implement Zod schemas + scoring formulas
4. Create CLI (stdin/stdout)
5. Write tests

**Phase 6.2:** Python Integration
1. Data adapter (`scoring/data_adapter.py`)
2. CLI command (`cli/score.py`)
3. Test integration

**Phase 6.3:** Batch Scoring
1. Score sample videos
2. Adjust formulas
3. Batch-score 120+ existing videos

---

## Data Flow Example

**Python prepares input (from database):**
```json
{
  "meta": {
    "video_id": "uuid",
    "followers": 50000,
    "length_sec": 45
  },
  "measures": {
    "hook": {
      "duration_sec": 4.5,
      "text": "dog parents listen carefully...",
      "type": "shock|curiosity|authority",
      "effectiveness_score": 9.5
    },
    "story": {
      "storyboard": [
        {"timestamp": 0, "duration": 9.9, "description": "..."}
      ],
      "beats_count": 7
    },
    "engagement": {
      "views": 573009,
      "likes": 45000,
      "comments": 1200
    }
  },
  "raw": {
    "transcript": [...],
    "storyboard": {...}
  }
}
```

**TypeScript scorer outputs:**
```json
{
  "version": "1.0.0",
  "subscores": {
    "hook": 85.5,
    "story": 78.2,
    "relatability": 82.0,
    "visuals": 75.5,
    "audio": 70.0,
    "watchtime": 68.5,
    "engagement": 88.0,
    "shareability": 72.0,
    "algo": 65.0
  },
  "penalties": 5.0,
  "overall": 76.8,
  "weights": {...}
}
```

---

## Key Files to Reference

**Read these first:**
1. `PHASE_6_SCORING_ENGINE_PLAN.md` - Complete implementation plan
2. `CHANGELOG.md` - Lines 269-409 (Phase 6 overview)

**Database schema:**
- `sql/01_initial_schema.sql` - Core tables
- `sql/02_add_video_analysis.sql` - Analysis table structure

**Current code:**
- `viraltracker/analysis/video_analyzer.py` - Gemini analysis (how we get hook, transcript, storyboard)
- `viraltracker/scrapers/tiktok.py` - ScrapTik integration (how we get views, likes, etc.)

---

## Database Tables We Use

**`posts` table:**
- `id`, `views`, `likes`, `comments`, `shares`, `caption`, `created_at`
- Linked to `accounts` (follower_count, username)

**`video_analysis` table (from Gemini):**
- `hook_transcript`, `hook_type`, `hook_timestamp`
- `transcript` (JSON: [{timestamp, speaker, text}])
- `storyboard` (JSON: {scenes: [{timestamp, duration, description}]})
- `text_overlays` (JSON: {overlays: [{timestamp, text, style}]})
- `key_moments` (JSON: {moments: [{timestamp, type, description}]})
- `viral_factors`, `viral_explanation`

---

## Starting Tasks

**Task 1: Database Migration**

Create `sql/04_video_scores.sql`:
- `video_scores` table (9 subscores + penalties + generated overall_score)
- Add `overall_score` column to `video_analysis`
- Trigger to sync overall_score between tables
- Indexes for performance

See PHASE_6_SCORING_ENGINE_PLAN.md lines 117-193 for exact schema.

**Task 2: TypeScript Project Setup**

Directory structure:
```
scorer/
├── package.json        # zod, typescript, vitest
├── tsconfig.json
├── src/
│   ├── schema.ts       # Zod schemas
│   ├── types.ts        # TS types
│   ├── formulas.ts     # 9 scoring functions
│   ├── scorer.ts       # Orchestrator
│   └── cli.ts          # stdin → stdout
└── tests/
    └── scorer.test.ts
```

**Task 3: Implement Scoring Formulas**

Example:
```typescript
export function scoreHook(m: Measures['hook']): number {
  let score = 50; // baseline

  // Duration: 3-5 sec ideal
  if (m.duration_sec >= 3 && m.duration_sec <= 5) score += 20;

  // Type quality
  if (m.type?.includes('shock')) score += 10;
  if (m.type?.includes('curiosity')) score += 10;

  // Effectiveness from Gemini
  if (m.effectiveness_score) {
    score += (m.effectiveness_score - 5) * 2;
  }

  return clamp(score, 0, 100);
}
```

---

## Questions to Answer

1. Should I build all 9 scoring formulas or start with 2-3 examples?
2. Do you want comprehensive tests or basic smoke tests?
3. Any specific scoring logic you want to emphasize?

---

## Success Criteria for Phase 6.1

- [ ] `video_scores` table exists in Supabase
- [ ] TypeScript project builds without errors
- [ ] Can run: `echo '{"meta":{...}, "measures":{...}}' | node scorer/dist/cli.js`
- [ ] Returns valid JSON with 9 subscores
- [ ] Tests pass
- [ ] Ready for Python integration (Phase 6.2)

---

## Context Window Status

**Starting fresh** - Full 200k tokens available
**Previous session:** Used 119k/200k (59.5%), completed Phase 5d successfully

**Files created in Phase 5d:**
- PHASE_5D_SUMMARY.md
- UPDATED_WORKFLOW.md
- export_wonder_paws_analysis.py
- test_product_integration.py
- Updated viraltracker/cli/tiktok.py

**Git status:** Committed (e7a6951) and pushed to GitHub ✅

---

## Recommended Approach

1. **Read** `PHASE_6_SCORING_ENGINE_PLAN.md` thoroughly
2. **Ask** clarifying questions before starting
3. **Start** with database migration (Task 1)
4. **Build** TypeScript project structure (Task 2)
5. **Implement** 2-3 scoring formulas as examples
6. **Test** with sample data
7. **Complete** remaining formulas
8. **Move** to Phase 6.2 (Python integration)

---

**Ready when you are! Let me know if you want to proceed or have questions.**
