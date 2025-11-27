# Checkpoint: Content Source Selector & Real-Time Progress Tracking

**Date:** 2025-11-27
**Status:** Complete (with minor bug fixes)

## Summary

Added two major features to the Ad Creator:
1. **Content Source Selector** - Choose between "Hooks List" or "Recreate Template" modes
2. **Real-Time Progress Tracking** - Live updates during ad generation

## Features Implemented

### 1. Content Source Selector

Users can now choose how ad variations are generated:

- **Hooks List** (default): Uses persuasive hooks from the database
- **Recreate Template**: Extracts the template's angle and generates variations using product benefits/USPs

#### New Tools Added (`ad_creation_agent.py`)

1. `extract_template_angle()` - Uses Gemini Vision to analyze reference ad and extract:
   - Angle type (before_after, testimonial, benefit_statement, etc.)
   - Original text from the ad
   - Messaging template with `{placeholders}`
   - Tone (casual, professional, urgent, emotional)
   - Key structural elements
   - Adaptation guidance

2. `generate_benefit_variations()` - Applies template angle to product benefits:
   - Combines benefits, unique_selling_points, key_ingredients
   - Includes product's `current_offer` (enforced exactly)
   - Includes `social_proof` if available
   - Respects `prohibited_claims`
   - Returns hook-compatible format

### 2. Real-Time Progress Tracking

- Workflow runs in background thread
- UI polls database every second for:
  - Ad run status (analyzing → generating → complete)
  - Number of generated ads
- Progress bar updates with current stage and count

### 3. UI Improvements

- Button disabled during workflow ("⏳ Generating... Please wait")
- Slider and content source radio disabled during workflow
- Values persist in session state across reruns
- Prevents accidental multiple clicks

## Files Changed

| File | Changes |
|------|---------|
| `viraltracker/ui/pages/5_🎨_Ad_Creator.py` | Content source selector, progress tracking, disabled controls |
| `viraltracker/agent/agents/ad_creation_agent.py` | New tools, workflow branching, offer/claims enforcement |
| `viraltracker/api/models.py` | Added `content_source` field |
| `viraltracker/api/app.py` | Pass `content_source` to workflow |
| `viraltracker/services/ad_creation_service.py` | Made `hook_id` optional |
| `viraltracker/services/gemini_service.py` | Handle blocked/empty responses |

## Database Changes Required

```sql
-- Make hook_id nullable for benefit-based variations
ALTER TABLE generated_ads ALTER COLUMN hook_id DROP NOT NULL;
```

## Bug Fixes

1. **Foreign key violation** - Benefit variations generated synthetic UUIDs that didn't exist in hooks table. Fixed by passing `None` for `hook_id` in recreate_template mode.

2. **Incorrect offers** - AI was making up percentages (50% OFF) instead of using product's actual offer. Fixed by adding `current_offer`, `social_proof`, and `prohibited_claims` to the prompt with strict accuracy rules.

3. **whichOneof error** - Gemini API error when response is blocked. Fixed by checking `response.candidates` before accessing `.text`.

4. **Multiple workflow triggers** - Users could click button multiple times. Fixed by disabling form controls during workflow.

## Testing Results

- Successfully generated ads using "Recreate Template" mode
- Ads correctly show `hook_id = null` in database
- Progress bar updates in real-time
- Button properly disabled during generation

## Commits

```
aba9a57 fix: Remove variation count from generate button text
75220b7 fix: Disable form controls while workflow is running
d8e5d25 fix: Handle Gemini blocked/empty responses in analyze_image
242206c fix: Ensure benefit variations use product's actual offer and claims
af008a3 fix: Make hook_id nullable for benefit-based variations
1ce69c9 feat: Add content source selector and real-time progress tracking
```

## Next Steps

- [ ] Test with more reference ad templates
- [ ] Add more content source options (Headlines, Custom Angles)
- [ ] Implement pydantic-graph refactor for proper workflow orchestration
- [ ] Add hook usage tracking to reduce repetition
