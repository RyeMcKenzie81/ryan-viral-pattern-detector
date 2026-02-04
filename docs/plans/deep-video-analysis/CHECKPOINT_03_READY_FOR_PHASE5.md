# Checkpoint: Ready for Phase 5 - Deep Congruence

**Date:** 2026-02-04
**Branch:** `feat/veo-avatar-tool` (auto-deploys)
**Status:** Phases 1-4.5 complete, Phase 5 ready to start

---

## Quick Context

We're building a **Deep Video Analysis** system for ad intelligence. The goal is to extract rich data from video ads (transcripts, hooks, benefits, etc.) and compare them to landing pages for congruence analysis.

### What's Complete

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Database schema (ad_video_analysis, meta_ad_destinations) | ✅ |
| 2 | VideoAnalysisService - deep video analysis with Gemini | ✅ |
| 2.5 | Visual hook extraction (hook_visual_description, etc.) | ✅ |
| 3 | LP URL fetching from Meta API + matching | ✅ |
| 4 | Classifier integration (VideoAnalysisService + LP lookup) | ✅ |
| 4.5 | LP auto-scrape with FireCrawl (`scrape_missing_lp` param) | ✅ |

### What's Next: Phase 5 - Deep Congruence

Create a `CongruenceAnalyzer` that evaluates **per-dimension** alignment between video, copy, and landing page.

**Dimensions to evaluate:**

| Dimension | Comparison |
|-----------|------------|
| Awareness alignment | video awareness ↔ copy awareness ↔ LP awareness |
| Hook ↔ headline | video hook (spoken+overlay+visual) ↔ LP headline/subhead |
| Benefits match | benefits shown in video ↔ benefits emphasized on LP |
| Messaging angle | video framing/angle ↔ LP framing/angle |
| Claims consistency | video claims ↔ LP claims (no promise drop-off) |

**Per-dimension output format:**
```json
{
  "dimension": "benefits_match",
  "assessment": "weak",  // aligned | weak | missing
  "explanation": "Video emphasizes convenience, LP focuses on quality",
  "suggestion": "Add convenience messaging to LP hero section"
}
```

**Store in:** `ad_creative_classifications.congruence_components` (JSONB column, already exists)

---

## Key Files

### Services
- `viraltracker/services/video_analysis_service.py` - Deep video analysis
- `viraltracker/services/ad_intelligence/classifier_service.py` - Classification + LP lookup
- `viraltracker/services/meta_ads_service.py` - Destination URL sync
- `viraltracker/services/url_canonicalizer.py` - URL normalization

### Test Scripts
- `scripts/test_video_analysis.py` - Phase 2 tests
- `scripts/test_ad_destinations.py` - Phase 3 tests
- `scripts/test_classifier_video_integration.py` - Phase 4/4.5 tests

### Database Tables
- `ad_video_analysis` - Deep video analysis results
- `meta_ad_destinations` - Ad destination URLs (canonical)
- `ad_creative_classifications` - Classifications with `video_analysis_id`, `landing_page_id`, `congruence_components`
- `brand_landing_pages` - Scraped LP data

### Plan Files
- Main plan: `/Users/ryemckenzie/.claude/plans/squishy-tinkering-snowflake.md`
- Checkpoint: `docs/plans/deep-video-analysis/CHECKPOINT_02_PHASE4.md`

---

## Test Brand

**Wonder Paws** (dog supplements)
- Brand ID: `bc8461a8-232d-4765-8775-c75eaafc5503`
- Org ID: `1fe982ec-1ff6-47d7-83df-caafc11381c8`
- Has video ads, landing pages, and destination URLs synced

---

## Phase 5 Implementation Plan

From the main plan file:

### Phase 5: Deep Congruence ✓ Checkpoint
1. Create `CongruenceAnalyzer` for **per-dimension evaluation**
2. Store results in `congruence_components` JSONB column
3. Optional: Compute weighted overall score from components
4. Handle missing/low-quality data gracefully:
   - No LP match → mark all LP-dependent dimensions as "unevaluated"
   - No transcript → mark transcript-dependent dimensions as "unevaluated"
5. Support re-evaluation when missing data becomes available
6. **TEST**: Run congruence on ads with matched LPs, verify per-dimension output

### Suggested File Structure
```
viraltracker/services/ad_intelligence/
├── classifier_service.py      # Existing - calls congruence after classification
├── congruence_analyzer.py     # NEW - per-dimension congruence evaluation
└── models.py                  # Add CongruenceComponent model
```

---

## Environment Notes

- FireCrawl API key is set in `.env`
- Migrations are applied
- Branch auto-deploys on push to GitHub
- Test with: `source venv/bin/activate && python scripts/test_*.py`

---

## Verification Query (After Phase 5)

```sql
-- Check per-dimension congruence for ads with matched LPs
SELECT
  c.meta_ad_id,
  c.congruence_components,
  c.congruence_score,
  v.hook_type,
  v.hook_transcript_spoken,
  v.hook_visual_description
FROM ad_creative_classifications c
JOIN ad_video_analysis v ON v.id = c.video_analysis_id
WHERE c.landing_page_id IS NOT NULL
AND c.congruence_components IS NOT NULL;
```
