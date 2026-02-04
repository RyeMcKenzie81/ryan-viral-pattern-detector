# Deep Video Analysis - Checkpoint 01: Phase 1+2 Complete

**Date:** 2026-02-03
**Status:** Phase 1+2 Complete, Enhancement Identified

---

## What Was Implemented

### Phase 1: Database Schema

#### New Tables

**`ad_video_analysis`** - Stores comprehensive video analysis results
```sql
-- Key columns:
- id, organization_id, brand_id, meta_ad_id
- input_hash, prompt_version (versioning)
- status ('ok', 'validation_failed', 'error'), validation_errors, error_message
- full_transcript, transcript_segments JSONB
- text_overlays JSONB, text_overlay_confidence
- hook_transcript_spoken, hook_transcript_overlay, hook_fingerprint, hook_type
- hook_effectiveness_signals JSONB
- storyboard JSONB
- benefits_shown[], features_demonstrated[], pain_points_addressed[]
- angles_used[], jobs_to_be_done[], claims_made JSONB
- awareness_level, awareness_confidence, target_persona JSONB
- video_duration_sec, production_quality, format_type
- raw_response JSONB, model_used, analyzed_at
```

**`meta_ad_destinations`** - Stores ad landing page URLs for congruence matching
```sql
- id, organization_id, brand_id, meta_ad_id
- destination_url (original), canonical_url (normalized)
- fetched_at, updated_at
```

#### Schema Updates

**`ad_creative_classifications`** - Added columns:
- `video_analysis_id` UUID FK → links to deep analysis
- `congruence_components` JSONB → per-dimension evaluation results

**`brand_landing_pages`** - Added column:
- `canonical_url` TEXT → for URL matching

### Phase 2: Services

**`viraltracker/services/video_analysis_service.py`** (~600 lines)
- `compute_input_hash(storage_path, etag, updated_at)` - deterministic versioning
- `compute_hook_fingerprint(spoken, overlay)` - normalized SHA256
- `validate_analysis_timestamps(data)` - validates transcript/overlay/storyboard structure
- `VideoAnalysisService` class:
  - `get_video_asset()` - fetch from meta_ad_assets
  - `download_from_storage()` - download from Supabase
  - `check_existing_analysis()` - idempotency check
  - `deep_analyze_video()` - full Gemini Files API analysis
  - `save_video_analysis()` - persist to database
  - `get_latest_analysis()` - fetch by ad/brand

**`viraltracker/services/url_canonicalizer.py`** (~100 lines)
- `canonicalize_url(url)` - normalizes URLs for matching
- Drops: UTMs, fbclid, gclid, Shopify variant, tracking params
- Normalizes: lowercase host, remove www, remove trailing slash

### Phase 2: Classifier Integration (Minimal Wiring)

**`viraltracker/services/ad_intelligence/classifier_service.py`**
- Added `video_analysis_service` constructor parameter
- Added `video_analysis_id` and `congruence_components` to classification records
- Updated `_row_to_model()` and `_dict_to_model()` for new fields

**`viraltracker/services/ad_intelligence/models.py`**
- Added `video_analysis_id: Optional[UUID]` to `CreativeClassification`
- Added `congruence_components: List[Dict[str, Any]]` to `CreativeClassification`

---

## Test Results

Ran `scripts/test_video_analysis.py` on Wonder Paws video:

```
meta_ad_id: 120239089970340742
status: ok
awareness_level: solution_aware
hook_type: claim
hook_transcript_spoken: "Let's see."
hook_transcript_overlay: "This isn't your average dog joint supplement."
video_duration_sec: 35
benefit_count: 6

Storyboard (first 3 scenes):
  0.0s: A woman is unboxing a package while a dog watches intently...
  2.9s: The woman holds the Wonder Paws bottle, and the dog sniffs it...
  5.0s: Close-up on the Wonder Paws bottle, dropper is used...
```

**Idempotency:** ✅ Repeat calls skip Gemini (same input_hash)

---

## Gap Identified: Visual Hook Context Missing

### The Problem

Current hook data is incomplete:
| Field | Value |
|-------|-------|
| `hook_transcript_spoken` | "Let's see." |
| `hook_transcript_overlay` | "This isn't your average dog joint supplement." |
| `hook_type` | "claim" |

Without knowing what's happening visually, this data is hard to interpret.

The storyboard has this context:
> "A woman is unboxing a package while a dog watches intently"

But it's **not linked to the hook fields**.

### What's Needed

Add a **visual hook description** that captures:
1. What's visually happening in the first 3-5 seconds
2. Key visual elements (person, dog, product, text overlay appearance)
3. The visual hook "type" (unboxing, transformation, demonstration, testimonial)

This creates a complete hook fingerprint:
- **Spoken:** What they say
- **Overlay:** What text appears
- **Visual:** What you see

---

## Files Created/Modified

| File | Status | Lines |
|------|--------|-------|
| `migrations/2026-02-03_ad_video_analysis.sql` | Created | 97 |
| `migrations/2026-02-03_meta_ad_destinations.sql` | Created | 45 |
| `migrations/2026-02-03_classification_video_analysis_link.sql` | Created | 20 |
| `viraltracker/services/video_analysis_service.py` | Created | ~600 |
| `viraltracker/services/url_canonicalizer.py` | Created | ~100 |
| `viraltracker/services/ad_intelligence/classifier_service.py` | Modified | +20 |
| `viraltracker/services/ad_intelligence/models.py` | Modified | +5 |
| `scripts/test_video_analysis.py` | Created | 170 |

---

## Next Steps

1. **Enhancement:** Add visual hook fields (see plan update)
2. **Phase 3:** LP URL fetching from Meta API
3. **Phase 4:** Full classifier integration
4. **Phase 5:** Deep congruence evaluation
5. **Phase 6:** Batch re-analysis job
6. **Phase 7:** Hook performance queries
