# TikTok Video Scorer

Deterministic scoring engine for TikTok videos. Evaluates videos using 9 subscores to produce a final 0-100 score.

## Overview

This TypeScript scorer reads video analysis data from stdin (JSON) and outputs scoring results to stdout (JSON).

**Subscores:**
1. **Hook** (20%) - First 3-5 seconds quality
2. **Story** (15%) - Narrative structure
3. **Relatability** (12%) - Audience connection
4. **Visuals** (10%) - Production quality
5. **Audio** (8%) - Sound/music
6. **Watchtime** (12%) - Video length optimization
7. **Engagement** (10%) - Like/comment/share rates
8. **Shareability** (8%) - Viral potential
9. **Algo** (5%) - Platform optimization

**Penalties** are subtracted from the weighted total.

## Installation

```bash
npm install
# or
pnpm install
```

## Usage

### Development (with tsx)

```bash
npm run dev < sample.json
```

### Production (compiled)

```bash
npm run build
npm run cli < sample.json
```

### Testing

```bash
npm test
```

## Input Format

```json
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
      "arc_detected": true
    },
    "visuals": {
      "text_overlay_present": true,
      "overlays": [...],
      "edit_rate_per_10s": 2.5
    },
    "audio": {
      "trending_sound_used": true
    },
    "watchtime": {
      "length_sec": 35,
      "avg_watch_pct": 75
    },
    "engagement": {
      "views": 500000,
      "likes": 45000,
      "comments": 1200,
      "shares": 800
    },
    "shareability": {
      "caption_length_chars": 125,
      "has_cta": true
    },
    "algo": {
      "caption_length_chars": 125,
      "hashtag_count": 4,
      "hashtag_niche_mix_ok": true
    }
  }
}
```

## Output Format

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
  "weights": {...},
  "diagnostics": {
    "missing": ["audio.beat_sync_score"],
    "overall_confidence": 0.9
  },
  "flags": {
    "incomplete": false,
    "low_confidence": false
  }
}
```

## Integration

Called from Python via subprocess:

```python
import json
import subprocess

result = subprocess.run(
    ["node", "scorer/dist/cli.js"],
    input=json.dumps(scorer_input),
    capture_output=True,
    text=True
)

scores = json.loads(result.stdout)
```

## Architecture

```
scorer/
├── src/
│   ├── schema.ts      # Zod validation schemas
│   ├── types.ts       # TypeScript type definitions
│   ├── formulas.ts    # 9 scoring functions + penalties
│   ├── scorer.ts      # Orchestrator with normalization
│   └── cli.ts         # stdin/stdout interface
├── tests/
│   └── scorer.test.ts # Smoke + sample data tests
└── package.json
```

## Version History

- **1.0.0** - Initial deterministic scoring engine
