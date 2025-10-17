# Phase 6: TikTok Scoring Engine Integration

**Status:** 📋 Ready to Implement
**Dependencies:** Phase 5d complete ✅

---

## Executive Summary

Integrate a TypeScript-based deterministic scoring engine that evaluates TikTok videos using 9 subscores (hook, story, relatability, visuals, audio, watchtime, engagement, shareability, algo) + penalties to produce a final 0-100 score.

**Key Differences from Current System:**
- **Current:** Gemini AI generates subjective "viral factors" and explanations
- **New:** Deterministic scoring formulas using ScrapTik metadata + Gemini features
- **Integration:** TypeScript scorer runs separately, called from Python CLI

---

## Architecture Decisions ✅

1. **TypeScript scorer as separate project** - Python calls via subprocess
2. **Two tables** - `video_scores` for details, `overall_score` in `video_analysis` for convenience
3. **Gemini models:**
   - Current analysis: `models/gemini-flash-latest` (auto-upgrades to 2.5)
   - New scoring features: `models/gemini-2.5-pro` for enhanced video analysis
4. **Manual scoring command** - `vt score videos --project <project>`
5. **Batch scoring command** - Re-score 120 existing analyses with `--rescore` flag
6. **Scorer location** - Same repo in `scorer/` subdirectory (keeps everything together)
7. **Missing metrics** - Use defaults initially, add watch time/velocity in Phase 6.1

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    VIRALTRACKER (Python)                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Fetch Video         2. Analyze w/ Gemini                 │
│     (ScrapTik)              (gemini-flash-latest)            │
│         │                   video_analysis table             │
│         │                          │                         │
│         └──────────┬───────────────┘                         │
│                    │                                         │
│                    ▼                                         │
│         3. Call TypeScript Scorer                            │
│            (subprocess to scorer/)                           │
│                    │                                         │
│                    ▼                                         │
│         4. Save Scores to DB                                 │
│            (video_scores table)                              │
│            (overall_score → video_analysis)                  │
└─────────────────────────────────────────────────────────────┘
                       │
                       │ JSON via stdin/stdout
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              TIKTOK-EVALUATOR (TypeScript)                   │
│              Location: viraltracker/scorer/                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Input:  { meta, measures, raw }                             │
│          - meta: video_id, post_time, followers, etc.        │
│          - measures: hook, story, visuals, audio, etc.       │
│          - raw: transcript, storyboard, overlays             │
│                                                               │
│  Process: Deterministic formulas                             │
│          - 9 subscores (0-100 each)                          │
│          - 1 penalties score                                 │
│          - Weighted overall (0-100)                          │
│                                                               │
│  Output: { subscores, penalties, overall, weights }          │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema Changes

### New Table: `video_scores`

```sql
-- sql/04_video_scores.sql
CREATE TABLE video_scores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,

  -- Metadata
  scorer_version TEXT NOT NULL,
  scored_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

  -- 9 Subscores (0-100 each)
  hook_score FLOAT NOT NULL CHECK (hook_score >= 0 AND hook_score <= 100),
  story_score FLOAT NOT NULL CHECK (story_score >= 0 AND story_score <= 100),
  relatability_score FLOAT NOT NULL CHECK (relatability_score >= 0 AND relatability_score <= 100),
  visuals_score FLOAT NOT NULL CHECK (visuals_score >= 0 AND visuals_score <= 100),
  audio_score FLOAT NOT NULL CHECK (audio_score >= 0 AND audio_score <= 100),
  watchtime_score FLOAT NOT NULL CHECK (watchtime_score >= 0 AND watchtime_score <= 100),
  engagement_score FLOAT NOT NULL CHECK (engagement_score >= 0 AND engagement_score <= 100),
  shareability_score FLOAT NOT NULL CHECK (shareability_score >= 0 AND shareability_score <= 100),
  algo_score FLOAT NOT NULL CHECK (algo_score >= 0 AND algo_score <= 100),

  -- Penalties
  penalties_score FLOAT NOT NULL DEFAULT 0,

  -- Overall (computed with default weights)
  overall_score FLOAT GENERATED ALWAYS AS (
    GREATEST(0, LEAST(100,
      (hook_score * 0.20) +
      (story_score * 0.15) +
      (relatability_score * 0.12) +
      (visuals_score * 0.10) +
      (audio_score * 0.08) +
      (watchtime_score * 0.12) +
      (engagement_score * 0.10) +
      (shareability_score * 0.08) +
      (algo_score * 0.05) -
      penalties_score
    ))
  ) STORED,

  -- Full scoring details (JSON with weights used, feature flags, etc.)
  score_details JSONB,

  -- Constraints
  UNIQUE(post_id, scorer_version),
  FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE INDEX idx_video_scores_post_id ON video_scores(post_id);
CREATE INDEX idx_video_scores_overall ON video_scores(overall_score DESC);
CREATE INDEX idx_video_scores_scored_at ON video_scores(scored_at DESC);

COMMENT ON TABLE video_scores IS 'Deterministic scoring results from TypeScript evaluator';
COMMENT ON COLUMN video_scores.overall_score IS 'Weighted average of subscores minus penalties (0-100)';
```

### Update `video_analysis` Table

Add convenience columns for quick queries:

```sql
-- Add to existing video_analysis table
ALTER TABLE video_analysis
  ADD COLUMN overall_score FLOAT,
  ADD COLUMN scored_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX idx_video_analysis_overall_score ON video_analysis(overall_score DESC);

-- Trigger to sync from video_scores
CREATE OR REPLACE FUNCTION sync_overall_score()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE video_analysis
  SET overall_score = NEW.overall_score,
      scored_at = NEW.scored_at
  WHERE post_id = NEW.post_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_score_to_analysis
AFTER INSERT OR UPDATE ON video_scores
FOR EACH ROW
EXECUTE FUNCTION sync_overall_score();

COMMENT ON COLUMN video_analysis.overall_score IS 'Denormalized from video_scores for quick filtering';
```

---

## Data Mapping: ViralTracker → Scorer

### Input Data Structure

```typescript
interface ScorerInput {
  meta: {
    video_id: string;
    post_time_iso: string;
    followers: number;
    length_sec: number;
  };
  measures: {
    hook: {
      duration_sec: number;
      text: string;
      type: string;  // e.g., "shock|curiosity|authority"
      visual_description?: string;
      effectiveness_score?: number;
    };
    story: {
      storyboard?: Array<{
        timestamp: number;
        duration: number;
        description: string;
      }>;
      beats_count?: number;
      arc_detected?: boolean;
    };
    visuals: {
      overlays?: Array<{
        timestamp: number;
        text: string;
        style?: string;
      }>;
      edit_rate_per_10s?: number;
      text_overlay_present?: boolean;
    };
    audio: {
      trending_sound_used?: boolean;
      original_sound_created?: boolean;
    };
    watchtime: {
      length_sec: number;
      avg_watch_pct?: number;  // Future
      completion_rate?: number;  // Future
    };
    engagement: {
      views: number;
      likes: number;
      comments: number;
      shares: number;
      saves?: number;
    };
    shareability: {
      caption_length_chars: number;
      has_cta?: boolean;
    };
    algo: {
      caption_length_chars: number;
      hashtag_count: number;
      hashtag_niche_mix_ok: boolean;
    };
  };
  raw?: {
    transcript?: Array<{
      timestamp: number;
      speaker: string;
      text: string;
    }>;
    hook_span?: {
      t_start: number;
      t_end: number;
    };
    storyboard?: any;  // Full JSON from video_analysis
    overlays?: any;    // Full JSON from video_analysis
  };
}
```

### Python Data Adapter

**File:** `viraltracker/scoring/data_adapter.py`

```python
"""Adapter to convert ViralTracker data to scorer input format."""

import json
from typing import Dict, Optional
import re

def prepare_scorer_input(post_id: str, supabase) -> Dict:
    """
    Gather all data from posts + video_analysis tables
    and format for TypeScript scorer.
    """
    # Fetch post with account and video processing info
    post_result = supabase.table("posts").select(
        "*, accounts(follower_count), video_processing_log(video_duration_sec)"
    ).eq("id", post_id).single().execute()

    if not post_result.data:
        raise ValueError(f"Post not found: {post_id}")

    post = post_result.data

    # Fetch analysis
    analysis_result = supabase.table("video_analysis").select("*").eq(
        "post_id", post_id
    ).single().execute()

    if not analysis_result.data:
        raise ValueError(f"No analysis found for post: {post_id}")

    analysis = analysis_result.data

    # Parse JSON fields
    storyboard = json.loads(analysis.get('storyboard', '{}')) if analysis.get('storyboard') else {}
    text_overlays = json.loads(analysis.get('text_overlays', '{}')) if analysis.get('text_overlays') else {}
    transcript = json.loads(analysis.get('transcript', '{}')) if analysis.get('transcript') else {}
    key_moments = json.loads(analysis.get('key_moments', '{}')) if analysis.get('key_moments') else {}

    # Build scorer input
    return {
        "meta": {
            "video_id": post_id,
            "post_time_iso": post['created_at'],
            "followers": post['accounts']['follower_count'] if post.get('accounts') else 0,
            "length_sec": post['video_processing_log'][0]['video_duration_sec'] if post.get('video_processing_log') else 0
        },
        "measures": {
            "hook": {
                "duration_sec": analysis.get('hook_timestamp', 0) or 0,
                "text": analysis.get('hook_transcript', ''),
                "type": analysis.get('hook_type', ''),
                "visual_description": _extract_hook_visual(analysis),
                "effectiveness_score": _extract_hook_effectiveness(analysis)
            },
            "story": {
                "storyboard": _convert_storyboard(storyboard),
                "beats_count": len(storyboard.get('scenes', [])),
                "arc_detected": _detect_story_arc(storyboard, key_moments)
            },
            "visuals": {
                "overlays": _convert_overlays(text_overlays),
                "text_overlay_present": bool(text_overlays.get('overlays')),
            },
            "audio": {
                # TODO: Add from posts music metadata when available
                "trending_sound_used": False,
                "original_sound_created": False
            },
            "watchtime": {
                "length_sec": post['video_processing_log'][0]['video_duration_sec'] if post.get('video_processing_log') else 0,
                # Future: avg_watch_pct, completion_rate
            },
            "engagement": {
                "views": post.get('views', 0),
                "likes": post.get('likes', 0),
                "comments": post.get('comments', 0),
                "shares": post.get('shares', 0),
                "saves": post.get('saves', 0) if post.get('saves') else 0
            },
            "shareability": {
                "caption_length_chars": len(post.get('caption', '')),
                "has_cta": _detect_cta(post.get('caption', ''))
            },
            "algo": {
                "caption_length_chars": len(post.get('caption', '')),
                "hashtag_count": _count_hashtags(post.get('caption', '')),
                "hashtag_niche_mix_ok": _check_hashtag_mix(post.get('caption', ''))
            }
        },
        "raw": {
            "transcript": _convert_transcript(transcript),
            "hook_span": {
                "t_start": 0,
                "t_end": analysis.get('hook_timestamp', 0) or 0
            },
            "storyboard": storyboard,
            "overlays": text_overlays
        }
    }

def _extract_hook_visual(analysis: Dict) -> Optional[str]:
    """Extract visual description from hook_visual_storyboard JSON."""
    try:
        hook_visual = json.loads(analysis.get('hook_visual_storyboard', '{}'))
        return hook_visual.get('visual_description')
    except:
        return None

def _extract_hook_effectiveness(analysis: Dict) -> Optional[float]:
    """Extract effectiveness score from hook_visual_storyboard JSON."""
    try:
        hook_visual = json.loads(analysis.get('hook_visual_storyboard', '{}'))
        return hook_visual.get('effectiveness_score')
    except:
        return None

def _convert_storyboard(storyboard: Dict) -> list:
    """Convert our storyboard format to scorer format."""
    scenes = storyboard.get('scenes', [])
    return [
        {
            "timestamp": scene.get('timestamp', 0),
            "duration": scene.get('duration', 0),
            "description": scene.get('description', '')
        }
        for scene in scenes
    ]

def _convert_overlays(text_overlays: Dict) -> list:
    """Convert our text overlays format to scorer format."""
    overlays = text_overlays.get('overlays', [])
    return [
        {
            "timestamp": overlay.get('timestamp', 0),
            "text": overlay.get('text', ''),
            "style": overlay.get('style', 'normal')
        }
        for overlay in overlays
    ]

def _convert_transcript(transcript: Dict) -> list:
    """Convert our transcript format to scorer format."""
    segments = transcript.get('segments', [])
    return [
        {
            "timestamp": seg.get('timestamp', 0),
            "speaker": seg.get('speaker', 'unknown'),
            "text": seg.get('text', '')
        }
        for seg in segments
    ]

def _detect_story_arc(storyboard: Dict, key_moments: Dict) -> bool:
    """Heuristic: has setup, build, payoff structure."""
    scenes = storyboard.get('scenes', [])
    moments = key_moments.get('moments', [])

    # Simple heuristic: at least 3 scenes and has climax moment
    has_climax = any(m.get('type', '').lower() == 'climax' for m in moments)
    return len(scenes) >= 3 and has_climax

def _count_hashtags(caption: str) -> int:
    """Count hashtags in caption."""
    return len(re.findall(r'#\w+', caption))

def _check_hashtag_mix(caption: str) -> bool:
    """Check for broad + niche hashtag mix (simple heuristic)."""
    hashtags = re.findall(r'#\w+', caption)
    if len(hashtags) < 3:
        return False

    # Heuristic: mix of short (broad) and long (niche) hashtags
    short = sum(1 for h in hashtags if len(h) <= 10)
    long = sum(1 for h in hashtags if len(h) > 10)
    return short > 0 and long > 0

def _detect_cta(caption: str) -> bool:
    """Detect call-to-action in caption."""
    cta_patterns = [
        r'\bfollow\b', r'\blike\b', r'\bcomment\b', r'\bshare\b',
        r'\bclick\b', r'\blink in bio\b', r'\btap\b', r'\btry\b'
    ]
    caption_lower = caption.lower()
    return any(re.search(pattern, caption_lower) for pattern in cta_patterns)
```

---

## TypeScript Scorer Structure

**Location:** `viraltracker/scorer/`

```
scorer/
├── package.json
├── tsconfig.json
├── src/
│   ├── schema.ts          # Zod schemas with our extensions
│   ├── types.ts           # TypeScript types
│   ├── formulas.ts        # 9 scoring functions + penalties
│   ├── scorer.ts          # Main scoring orchestrator
│   └── cli.ts             # CLI entry point (reads stdin, outputs stdout)
├── tests/
│   └── scorer.test.ts
└── README.md
```

### Key Files Content

**package.json:**
```json
{
  "name": "@viraltracker/scorer",
  "version": "1.0.0",
  "type": "module",
  "main": "dist/cli.js",
  "scripts": {
    "build": "tsc",
    "test": "vitest",
    "cli": "node dist/cli.js"
  },
  "dependencies": {
    "zod": "^3.22.0"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "vitest": "^1.0.0",
    "@types/node": "^20.0.0"
  }
}
```

**src/cli.ts:**
```typescript
#!/usr/bin/env node
import { stdin } from 'process';
import { scoreVideo } from './scorer.js';

// Read JSON from stdin
let inputData = '';
stdin.on('data', (chunk) => {
  inputData += chunk;
});

stdin.on('end', () => {
  try {
    const input = JSON.parse(inputData);
    const result = scoreVideo(input);
    console.log(JSON.stringify(result, null, 2));
    process.exit(0);
  } catch (error) {
    console.error(JSON.stringify({
      error: error instanceof Error ? error.message : 'Unknown error',
      stack: error instanceof Error ? error.stack : undefined
    }));
    process.exit(1);
  }
});
```

**src/formulas.ts** (simplified examples):
```typescript
export function scoreHook(m: Measures['hook']): number {
  let score = 50; // baseline

  // Duration: 3-5 sec ideal
  if (m.duration_sec >= 3 && m.duration_sec <= 5) {
    score += 20;
  } else if (m.duration_sec < 2) {
    score -= 10; // too short
  } else if (m.duration_sec > 7) {
    score -= 10; // too long
  }

  // Type quality (from Gemini analysis)
  const types = m.type?.toLowerCase().split('|') || [];
  if (types.includes('shock')) score += 10;
  if (types.includes('curiosity')) score += 10;
  if (types.includes('authority')) score += 5;

  // Effectiveness score from Gemini (if available)
  if (m.effectiveness_score) {
    score += (m.effectiveness_score - 5) * 2; // Scale 0-10 to -10 to +10
  }

  return clamp(score, 0, 100);
}

export function scoreStory(m: Measures['story']): number {
  let score = 50;

  // Has storyboard beats
  if (m.beats_count && m.beats_count >= 3) {
    score += 15;
  }

  // Story arc detected
  if (m.arc_detected) {
    score += 15;
  }

  // Consistent pacing (using storyboard timestamps)
  if (m.storyboard && m.storyboard.length >= 3) {
    const durations = m.storyboard.map(b => b.duration);
    const avgDuration = durations.reduce((a,b) => a+b, 0) / durations.length;
    const variance = durations.reduce((a,b) => a + Math.pow(b - avgDuration, 2), 0) / durations.length;
    const stdDev = Math.sqrt(variance);

    // Reward consistent pacing (low variance)
    if (stdDev < 2) score += 10;
  }

  return clamp(score, 0, 100);
}

// Similar functions for:
// - scoreRelatability
// - scoreVisuals
// - scoreAudio
// - scoreWatchtime
// - scoreEngagement
// - scoreShareability
// - scoreAlgo
// - scorePenalties

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}
```

---

## Python CLI Integration

**New File:** `viraltracker/cli/score.py`

```python
"""Scoring CLI commands."""

import logging
from typing import Optional
import json
import subprocess
from pathlib import Path

import click

from ..core.database import get_supabase_client
from ..scoring.data_adapter import prepare_scorer_input

logger = logging.getLogger(__name__)

# Find scorer directory
SCORER_PATH = Path(__file__).parent.parent.parent / "scorer"

@click.group(name="score")
def score_group():
    """Score videos with deterministic formulas"""
    pass


@score_group.command(name="videos")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--limit', type=int, help='Max videos to score')
@click.option('--rescore', is_flag=True, help='Re-score already scored videos')
def score_videos(project: str, limit: Optional[int], rescore: bool):
    """
    Score analyzed videos using deterministic formulas.

    Examples:
        vt score videos --project wonder-paws-tiktok
        vt score videos --project wonder-paws-tiktok --limit 10
        vt score videos --project wonder-paws-tiktok --rescore
    """
    try:
        click.echo(f"\n{'='*60}")
        click.echo(f"📊 Video Scoring Engine")
        click.echo(f"{'='*60}\n")

        supabase = get_supabase_client()

        # Get project
        project_result = supabase.table("projects").select("id, name").eq("slug", project).execute()
        if not project_result.data:
            click.echo(f"❌ Project '{project}' not found", err=True)
            raise click.Abort()

        project_id = project_result.data[0]['id']
        project_name = project_result.data[0]['name']

        click.echo(f"Project: {project_name}")
        click.echo()

        # Get analyzed videos
        query = supabase.table("video_analysis").select(
            "post_id, posts!inner(id)"
        ).in_("post_id",
            supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute().data
        )

        if not rescore:
            # Exclude already scored
            scored_ids = [r['post_id'] for r in supabase.table("video_scores").select("post_id").execute().data]
            # Filter client-side (Supabase doesn't have NOT IN easily)
            analyses = [a for a in query.execute().data if a['post_id'] not in scored_ids]
        else:
            analyses = query.execute().data

        if limit:
            analyses = analyses[:limit]

        if not analyses:
            click.echo("✅ No videos to score")
            return

        click.echo(f"Videos to score: {len(analyses)}")
        click.echo()

        # Confirm
        if not click.confirm(f"Score {len(analyses)} videos?"):
            click.echo("Cancelled")
            return

        click.echo()

        # Score each video
        scored = 0
        failed = 0

        for i, analysis in enumerate(analyses, 1):
            post_id = analysis['post_id']
            try:
                click.echo(f"[{i}/{len(analyses)}] Scoring video {post_id[:8]}...")

                # Prepare input
                scorer_input = prepare_scorer_input(post_id, supabase)

                # Call TypeScript scorer
                result = subprocess.run(
                    ["node", "dist/cli.js"],
                    input=json.dumps(scorer_input),
                    capture_output=True,
                    text=True,
                    cwd=SCORER_PATH
                )

                if result.returncode != 0:
                    click.echo(f"   ❌ Scorer failed: {result.stderr}")
                    failed += 1
                    continue

                scores = json.loads(result.stdout)

                # Save to database
                supabase.table("video_scores").upsert({
                    "post_id": post_id,
                    "scorer_version": scores.get("version", "1.0.0"),
                    "hook_score": scores["subscores"]["hook"],
                    "story_score": scores["subscores"]["story"],
                    "relatability_score": scores["subscores"]["relatability"],
                    "visuals_score": scores["subscores"]["visuals"],
                    "audio_score": scores["subscores"]["audio"],
                    "watchtime_score": scores["subscores"]["watchtime"],
                    "engagement_score": scores["subscores"]["engagement"],
                    "shareability_score": scores["subscores"]["shareability"],
                    "algo_score": scores["subscores"]["algo"],
                    "penalties_score": scores["penalties"],
                    "score_details": scores
                }, on_conflict="post_id,scorer_version").execute()

                click.echo(f"   ✅ Overall: {scores['overall']:.1f}/100")
                scored += 1

            except Exception as e:
                click.echo(f"   ❌ Error: {e}")
                logger.exception(e)
                failed += 1

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Scoring Complete")
        click.echo(f"{'='*60}\n")
        click.echo(f"📊 Summary:")
        click.echo(f"   Scored: {scored}")
        click.echo(f"   Failed: {failed}")
        click.echo()

    except Exception as e:
        click.echo(f"\n❌ Scoring failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()
```

**Register in main.py:**
```python
from .score import score_group

# In cli() function
cli.add_command(score_group)
```

---

## Implementation Phases

### Phase 6.1: Database & TypeScript Scorer (2-3 hours)

**Tasks:**
1. Create `sql/04_video_scores.sql` migration
2. Run migration on Supabase
3. Set up TypeScript project in `scorer/`
4. Implement Zod schemas with our extensions
5. Implement 9 scoring formulas + penalties
6. Create CLI that reads JSON from stdin
7. Test with sample data

**Files to Create:**
- `sql/04_video_scores.sql`
- `scorer/package.json`
- `scorer/tsconfig.json`
- `scorer/src/schema.ts`
- `scorer/src/types.ts`
- `scorer/src/formulas.ts`
- `scorer/src/scorer.ts`
- `scorer/src/cli.ts`
- `scorer/tests/scorer.test.ts`

### Phase 6.2: Python Integration (1-2 hours)

**Tasks:**
1. Create data adapter (`scoring/data_adapter.py`)
2. Create CLI command (`cli/score.py`)
3. Test on sample videos
4. Fix any data mapping issues

**Files to Create:**
- `viraltracker/scoring/__init__.py`
- `viraltracker/scoring/data_adapter.py`
- `viraltracker/cli/score.py`
- Update `viraltracker/cli/main.py`

### Phase 6.3: Batch Scoring & Testing (1 hour)

**Tasks:**
1. Score 10 sample videos
2. Verify scores make sense
3. Adjust formulas if needed
4. Batch-score all 120 existing videos
5. Create visualization/export script

**Files to Create:**
- `export_video_scores.py`
- `viraltracker/docs/scoring_system.md`

### Phase 6.4: Model Upgrade (Optional, 30 min)

**Tasks:**
1. Update default Gemini model to `models/gemini-2.5-pro`
2. Add `--gemini-model` option to analyze commands
3. Test with new model
4. Document differences

---

## Testing Plan

### Unit Tests (TypeScript)

```typescript
// scorer/tests/scorer.test.ts
import { describe, it, expect } from 'vitest';
import { scoreHook, scoreStory } from '../src/formulas';

describe('Hook Scoring', () => {
  it('rewards ideal duration (3-5 sec)', () => {
    const score = scoreHook({ duration_sec: 4, text: 'test', type: '' });
    expect(score).toBeGreaterThan(50);
  });

  it('penalizes too short hooks', () => {
    const score = scoreHook({ duration_sec: 1, text: 'test', type: '' });
    expect(score).toBeLessThan(50);
  });
});

describe('Story Scoring', () => {
  it('rewards multiple beats', () => {
    const score = scoreStory({ beats_count: 5, arc_detected: true });
    expect(score).toBeGreaterThan(70);
  });
});
```

### Integration Tests (Python)

```python
# test_scoring_integration.py
from viraltracker.scoring.data_adapter import prepare_scorer_input
from viraltracker.core.database import get_supabase_client

def test_data_adapter():
    """Test that we can prepare scorer input from database."""
    supabase = get_supabase_client()

    # Get a sample analyzed video
    analysis = supabase.table("video_analysis").select("post_id").limit(1).execute()
    post_id = analysis.data[0]['post_id']

    # Prepare input
    scorer_input = prepare_scorer_input(post_id, supabase)

    # Verify structure
    assert 'meta' in scorer_input
    assert 'measures' in scorer_input
    assert 'video_id' in scorer_input['meta']
    assert 'hook' in scorer_input['measures']

    print("✅ Data adapter test passed")

if __name__ == "__main__":
    test_data_adapter()
```

---

## Success Criteria

- [ ] TypeScript scorer accepts JSON input and outputs scores
- [ ] All 9 subscores calculated correctly (0-100 range)
- [ ] Overall score matches weighted formula
- [ ] Python CLI command `vt score videos` works
- [ ] Scores saved to `video_scores` table
- [ ] Overall score synced to `video_analysis` table
- [ ] Can batch-score 120 existing videos
- [ ] Scores make intuitive sense (manual spot checks)
- [ ] Documentation complete

---

## Next Steps

**Ready to start? Here's the prompt for a new context window:**

```
I need to implement Phase 6 of ViralTracker: TikTok Scoring Engine Integration.

Context:
- We have a Python-based TikTok analysis tool (ViralTracker)
- 120 videos already analyzed with Gemini AI (hook, transcript, storyboard, overlays stored in video_analysis table)
- Need to add deterministic scoring using TypeScript evaluator
- Scorer will read JSON from stdin, output scores to stdout
- Python will call scorer via subprocess and save results to video_scores table

Implementation plan is in: PHASE_6_SCORING_ENGINE_PLAN.md

Start with Phase 6.1: Database & TypeScript Scorer
1. Create sql/04_video_scores.sql migration
2. Set up TypeScript project in scorer/ directory
3. Implement scoring formulas

Files to reference:
- viraltracker/analysis/video_analyzer.py (current Gemini analysis)
- viraltracker/scrapers/tiktok.py (ScrapTik metadata)
- Database schema in sql/ directory

Let me know when you're ready and I'll provide the current database schema.
```

---

## Appendix: Default Weights

```typescript
export const DEFAULT_WEIGHTS = {
  hook: 0.20,        // 20% - First impression critical
  story: 0.15,       // 15% - Narrative structure
  relatability: 0.12, // 12% - Audience connection
  visuals: 0.10,     // 10% - Production quality
  audio: 0.08,       // 8%  - Sound/music
  watchtime: 0.12,   // 12% - Retention signals
  engagement: 0.10,  // 10% - Social proof
  shareability: 0.08, // 8%  - Viral mechanics
  algo: 0.05         // 5%  - Platform optimization
  // penalties subtracted from total
};
```

These weights are configurable in the scorer and can be adjusted based on testing results.

