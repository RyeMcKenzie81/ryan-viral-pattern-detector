# Checkpoint: Ad Creator UI & Configurable Variations

**Date:** 2025-11-27
**Status:** Complete & Tested Successfully

## Summary

Implemented a Streamlit-based Ad Creator UI with configurable number of ad variations (1-15), hook shuffling for variety, and a success screen displaying generated ads.

## Changes Made

### 1. Configurable Number of Variations

**Files Modified:**
- `viraltracker/agent/agents/ad_creation_agent.py`
- `viraltracker/api/models.py`
- `viraltracker/api/app.py`
- `viraltracker/services/models.py`

**Changes:**
- Added `num_variations` parameter to `complete_ad_workflow()` (default: 5, max: 15)
- Updated `select_hooks()` to accept dynamic count
- Updated `AdCreationRequest` model with `num_variations` field (1-15)
- API endpoint passes `num_variations` to workflow
- Updated Pydantic model constraints from `le=5` to `le=15`

### 2. Hook Shuffling for Variety

**File:** `viraltracker/agent/agents/ad_creation_agent.py`

**Changes:**
- Added `import random` to `select_hooks()`
- Hooks are now shuffled before sending to Gemini:
  ```python
  shuffled_hooks = hooks.copy()
  random.shuffle(shuffled_hooks)
  ```
- This prevents the same hooks from being selected repeatedly across runs

### 3. New Streamlit Ad Creator UI

**File:** `viraltracker/ui/pages/5_🎨_Ad_Creator.py`

**Features:**
- **Product Selection:** Dropdown populated from database
- **Variations Slider:** Choose 1-15 ad variations
- **Reference Ad Source:**
  - Upload new image
  - Select from existing templates in storage
- **Progress Indicator:** Shows workflow status while running
- **Success Screen:**
  - Summary metrics (total, approved, rejected, flagged)
  - Grid display of generated ads (3 per row)
  - Status badges (✅ Approved, ❌ Rejected, 🚩 Flagged)
  - Ad images via signed URLs from Supabase storage
  - Expandable review details (Claude/Gemini reasoning)
- **Sidebar:** Recent ad runs with quick-load buttons

### 4. Database Constraint Update

**SQL Migration Required:**
```sql
ALTER TABLE generated_ads DROP CONSTRAINT IF EXISTS generated_ads_prompt_index_check;
ALTER TABLE generated_ads ADD CONSTRAINT generated_ads_prompt_index_check CHECK (prompt_index >= 1 AND prompt_index <= 15);
```

**Status:** ✅ Executed in Supabase dashboard

### 5. Previous Session Fixes (Same Day)

#### Railway API Deployment Fixes:
1. **Lazy initialization for ScrapingService** - APIFY_TOKEN no longer required at startup
2. **Direct workflow call** - Bypasses agent prompt to avoid 200K token limit with base64 images

**Files:**
- `viraltracker/services/scraping_service.py` - Lazy TwitterScraper init
- `viraltracker/api/app.py` - Direct `complete_ad_workflow()` call with RunContext

## Architecture Notes

### Current Pattern (Direct Function Call)
```python
# API endpoint calls workflow directly
ctx = RunContext(deps=deps, model=None, usage=RunUsage())
result = await complete_ad_workflow(ctx=ctx, ...)
```

### TODO: Refactor to pydantic-graph
The workflow should be refactored to use `pydantic-graph` for proper orchestration:
- See: https://ai.pydantic.dev/graph/
- 4 deterministic steps + 4 LLM steps = ideal for typed graph nodes
- Would enable better progress tracking, resumability, and step-level LLM logic

## Testing

### Railway API Test
```bash
VIRALTRACKER_API_KEY="your-key" python test_railway_ad_creation.py
```

### Local Streamlit Test
```bash
streamlit run viraltracker/ui/Home.py
# Navigate to "🎨 Ad Creator" page
```

## Git Commits

1. `b59c26b` - fix: Use lazy initialization for TwitterScraper in ScrapingService
2. `3a24199` - fix: Call ad creation workflow directly instead of via agent prompt
3. `ede30c1` - feat: Add configurable num_variations and Ad Creator UI
4. `6321474` - fix: Increase prompt_index limit from 5 to 15

## Known Issues

1. **Progress bar is static** - Shows "Analyzing reference ad..." but doesn't update in real-time
   - Enhancement: Poll database for ad_run status and generated_ads count

2. **Hook selection still has some repetition** - Shuffle helps but Gemini may still prefer certain hooks
   - Enhancement: Track recently used hooks and exclude from selection

## Files Changed

```
viraltracker/
├── agent/agents/ad_creation_agent.py  # num_variations, shuffle, prompt_index fix
├── api/
│   ├── app.py                          # Direct workflow call, pass num_variations
│   └── models.py                       # AdCreationRequest.num_variations
├── services/
│   ├── models.py                       # prompt_index le=15
│   └── scraping_service.py             # Lazy init
└── ui/pages/
    └── 5_🎨_Ad_Creator.py              # NEW - Full ad creation UI
```

## Test Results

### Successful Run (2025-11-27 07:48 UTC)
- **Run ID:** `0097066f...`
- **Variations:** 6
- **Results:** 6/6 approved
- **Time:** ~5 minutes total

All ads generated successfully with prompt_index values 1-6, confirming the constraint fix works.

## Data Updates

### Social Proof Update
```sql
UPDATE products
SET social_proof = '300,000+ Bottles Sold'
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';
```

## Next Steps

1. Add real-time progress tracking to UI (poll database)
2. Consider pydantic-graph refactor for workflow
3. Add hook usage tracking to improve variety
4. Add ability to regenerate individual failed ads
