# Checkpoint: Phase 5 Complete - Deep Congruence Analysis

**Date:** 2026-02-04
**Branch:** `feat/veo-avatar-tool` (auto-deploys)
**Status:** Phases 1-5 complete and tested

---

## What Was Built

### CongruenceAnalyzer Service

Created `viraltracker/services/ad_intelligence/congruence_analyzer.py` that evaluates per-dimension alignment between:

1. **Video content** (from `ad_video_analysis`)
2. **Ad copy** (from classification)
3. **Landing page** (from `brand_landing_pages`)

### 5 Dimensions Evaluated

| Dimension | Comparison | Assessment Values |
|-----------|------------|-------------------|
| `awareness_alignment` | video ↔ copy ↔ LP awareness levels | aligned, weak, missing |
| `hook_headline` | video hook vs LP headline/subhead | aligned, weak, missing |
| `benefits_match` | video benefits vs LP benefits | aligned, weak, missing |
| `messaging_angle` | video angle vs LP messaging angle | aligned, weak, missing |
| `claims_consistency` | video claims vs LP claims | aligned, weak, missing |

### Output Format

Each dimension produces:
```json
{
  "dimension": "benefits_match",
  "assessment": "weak",
  "explanation": "Video emphasizes convenience, LP focuses on quality",
  "suggestion": "Add convenience messaging to LP hero section"
}
```

### Integration

- Integrated into `ClassifierService.classify_ad()`
- Runs automatically when both `video_analysis_id` and `lp_data` are available
- Results stored in `ad_creative_classifications.congruence_components` (JSONB)
- Computes weighted overall score from component assessments

---

## Files Created/Modified

### New Files
- `viraltracker/services/ad_intelligence/congruence_analyzer.py` (~350 lines)
  - `CongruenceAnalyzer` class
  - `CongruenceComponent` and `CongruenceResult` dataclasses
  - Gemini-based analysis for nuanced comparisons
  - Programmatic awareness gap calculation helper

- `scripts/test_congruence_analyzer.py` (~200 lines)
  - Standalone test with mock data
  - Integrated test with classifier
  - Database verification query

### Modified Files
- `viraltracker/services/ad_intelligence/classifier_service.py`
  - Added `congruence_analyzer` parameter to constructor
  - Added `_run_deep_congruence_analysis()` method
  - Integrated congruence analysis into classification flow
  - Updated LP data fetch to include more fields (benefits, features, etc.)

- `viraltracker/services/video_analysis_service.py`
  - Fixed `save_video_analysis()` to handle duplicate key errors gracefully
  - Returns existing analysis ID on duplicate instead of failing

---

## Test Results

### Wonder Paws Test (Ad: 120239089970340742)

```
Results:
  Source: gemini_video
  Video Analysis ID: 73f5c311-c604-4670-8f64-f978c89916b5
  Landing Page ID: 3dbec166-e77d-44a5-8e86-8b37d6f88d8f
  Awareness: solution_aware
  Congruence Components: 5

  Per-dimension assessments:

    awareness_alignment: aligned
      Both the video ad (solution_aware) and the LP are aligned...

    hook_headline: weak
      Video hook emphasizes "joint supplement" but LP headline is about "collagen"...
      Suggestion: Rephrase LP headline to match joint-focused messaging

    benefits_match: weak
      Video's joint-specific benefits don't fully match LP's collagen benefits...
      Suggestion: Update video or LP to align benefits messaging

    messaging_angle: weak
      Video's joint-specific angle differs from LP's broader collagen positioning...
      Suggestion: Adjust messaging to maintain consistent product focus

    claims_consistency: weak
      Video claim 'Triple-Lock Joint Protection' is missing from LP...
      Suggestion: Add key claims to LP to reinforce video promises
```

### Key Insights from Test

The analysis correctly identified that while awareness levels are aligned, there's a **messaging disconnect**:
- Video focuses on "joint supplement" positioning
- Landing page focuses on "collagen for dogs" positioning
- This creates friction in the customer journey

---

## Verification Query

```sql
-- Check per-dimension congruence for ads with matched LPs
SELECT
  c.meta_ad_id,
  c.congruence_components,
  c.congruence_score,
  c.video_analysis_id,
  c.landing_page_id,
  v.awareness_level,
  v.hook_transcript_spoken,
  v.benefits_shown
FROM ad_creative_classifications c
JOIN ad_video_analysis v ON v.id = c.video_analysis_id
WHERE c.landing_page_id IS NOT NULL
AND c.congruence_components IS NOT NULL
AND jsonb_array_length(c.congruence_components) > 0;
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   ClassifierService.classify_ad()                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Fetch ad data (thumbnail, copy, LP via destination URL)     │
│              ↓                                                   │
│  2. Run classification (video deep analysis or image+copy)       │
│              ↓                                                   │
│  3. Save video_analysis_id and landing_page_id                  │
│              ↓                                                   │
│  4. If BOTH video_analysis_id AND lp_data exist:                │
│     ┌──────────────────────────────────────────────────────┐    │
│     │         CongruenceAnalyzer.analyze_congruence()      │    │
│     │                                                       │    │
│     │  Inputs:                                              │    │
│     │  - video_data (from ad_video_analysis)               │    │
│     │  - copy_data (from classification)                   │    │
│     │  - lp_data (from brand_landing_pages)                │    │
│     │                                                       │    │
│     │  Gemini analyzes 5 dimensions:                       │    │
│     │  - awareness_alignment                               │    │
│     │  - hook_headline                                     │    │
│     │  - benefits_match                                    │    │
│     │  - messaging_angle                                   │    │
│     │  - claims_consistency                                │    │
│     │                                                       │    │
│     │  Returns: List[CongruenceComponent]                  │    │
│     └──────────────────────────────────────────────────────┘    │
│              ↓                                                   │
│  5. Store congruence_components in classification               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## What's Next: Phase 6 - Batch Re-analysis

1. Create script/job to re-analyze all existing video ads
2. Populate congruence data for ads with LPs
3. Build dashboard/reporting for congruence insights

---

## Test Brand

**Wonder Paws** (dog supplements)
- Brand ID: `bc8461a8-232d-4765-8775-c75eaafc5503`
- Org ID: `1fe982ec-1ff6-47d7-83df-caafc11381c8`
- Has video ads with deep analysis
- Has scraped landing pages
- Congruence analysis working

---

## Running Tests

```bash
source venv/bin/activate
python scripts/test_congruence_analyzer.py
```
