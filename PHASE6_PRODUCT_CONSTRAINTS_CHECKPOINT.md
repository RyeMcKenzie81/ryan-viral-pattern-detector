# Phase 6: Product Constraints & Offer Controls - COMPLETED

**Date:** 2025-11-26
**Session:** Ad Creation Enhancement - Preventing Hallucinated Claims

## Overview

User identified **critical issue**: AI is hallucinating discount claims (e.g., "50% off") when actual offer is "up to 35% off subscription vs one-time purchase". This violates advertising regulations and could cause legal issues.

**Root Causes Identified:**
1. **Missing offer data structure** - Only generic `price_range` field exists
2. **No prohibited claims list** - AI can make medical/FDA claims
3. **Poor benefit matching** - Only uses first benefit as subheadline, doesn't match hook theme

---

## Problem Analysis

### Issue #1: Hallucinated Discount Claims
- **Current:** `price_range: "$30-43"` is vague
- **Actual offer:** "Up to 35% off with subscription 3-pack vs single purchase"
- **AI generated:** "Up to 50%" (WRONG - legal violation!)

### Issue #2: Generic Benefits Not Matched to Hooks
- **Location:** `viraltracker/agent/agents/ad_creation_agent.py:812, 834`
- **Current behavior:**
  ```python
  # Line 812: Always uses FIRST benefit (wrong!)
  "subheadline": product.get('benefits', [])[0] if product.get('benefits') else "",

  # Line 834: Dumps ALL benefits generically
  - Benefits: {', '.join(product.get('benefits', []))}
  ```
- **Problem:** If hook is about "joint pain" but first benefit is "shiny coat", ad doesn't make sense

### Issue #3: No Compliance Controls
- No way to prevent prohibited claims ("cure", "FDA approved", "treat disease")
- No required disclaimers field
- No brand voice guidelines

---

## Solution Design

### New Database Fields (5 columns)

**Positive Constraints (what TO say):**
- `current_offer TEXT` - Explicit offer text to prevent hallucination
- `unique_selling_points TEXT[]` - Key differentiators vs competitors

**Negative Constraints (what NOT to say):**
- `prohibited_claims TEXT[]` - Array of forbidden words/phrases
- `required_disclaimers TEXT` - Legal text that must appear

**Brand Voice:**
- `brand_voice_notes TEXT` - Tone and style guidelines

---

## Implementation Status

### ✅ Completed

1. **Database Schema Designed**
   - 5 new columns for products table
   - Comments documenting field usage
   - Example data for Wonder Paws product

2. **SQL Migration Created**
   - File: `sql/migration_product_constraints.sql`
   - Ready to apply via Supabase dashboard

### 🚧 In Progress

3. **Run SQL Migration** - Need to apply via Supabase dashboard

### ⏳ Remaining Work

4. **Update Product Pydantic Model**
   - Add 5 new Optional fields to Product class
   - Update field validators
   - Location: `viraltracker/services/models.py:723-739`

5. **Implement Hook-to-Benefit Matching**
   - Create algorithm to select most relevant benefit for each hook
   - Match hook theme/category to benefit keywords
   - Location: New function in `ad_creation_agent.py`

6. **Update Prompt Generation**
   - Use matched benefits instead of first benefit
   - Add prohibited claims as negative examples
   - Include offer data prominently
   - Include required disclaimers
   - Location: `ad_creation_agent.py:generate_nano_banana_prompt()`

7. **Populate Wonder Paws Data**
   - Run UPDATE query with real offer and constraints
   - Product ID: `83166c93-632f-47ef-a929-922230e05f82`

8. **Test End-to-End Workflow**
   - Run integration test with new fields
   - Verify ads use correct offer
   - Verify benefits match hooks
   - Verify no prohibited claims appear

9. **Document & Commit**
   - Create final checkpoint
   - Commit all changes
   - Push to GitHub

---

## SQL Migration (Ready to Apply)

```sql
-- Add new columns to products table
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS current_offer TEXT,
  ADD COLUMN IF NOT EXISTS prohibited_claims TEXT[],
  ADD COLUMN IF NOT EXISTS required_disclaimers TEXT,
  ADD COLUMN IF NOT EXISTS brand_voice_notes TEXT,
  ADD COLUMN IF NOT EXISTS unique_selling_points TEXT[];
```

**Apply this via Supabase Dashboard → SQL Editor**

---

## Example Wonder Paws Data (After Migration)

```sql
UPDATE products
SET
  current_offer = 'Up to 35% off with subscription 3-pack vs single purchase',
  prohibited_claims = ARRAY['cure', 'FDA approved', 'treat', 'prevent disease', 'medical grade', 'veterinarian prescribed'],
  required_disclaimers = '*These statements have not been evaluated by the FDA. This product is not intended to diagnose, treat, cure, or prevent any disease.',
  brand_voice_notes = 'Warm, caring, and pet-owner friendly. Focus on quality of life improvements, not medical claims.',
  unique_selling_points = ARRAY['Triple-action collagen formula', 'Supports joints, coat, and skin', 'Easy liquid drops', 'Made with natural ingredients']
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';
```

---

## Hook-to-Benefit Matching Algorithm (Design)

**Concept:** Match hook theme to most relevant product benefit

```python
def match_benefit_to_hook(hook: SelectedHook, benefits: List[str]) -> str:
    """
    Select the most relevant benefit for a given hook.

    Strategy:
    1. Extract keywords from hook text and category
    2. Score each benefit by keyword overlap
    3. Return highest scoring benefit
    4. Fallback to first benefit if no match
    """
    # Example:
    # Hook: "My dog went from limping to running in 2 weeks!" (category: before_after)
    # Keywords: ["limping", "running", "mobility", "movement"]
    # Benefits:
    #   - "Supports hip & joint mobility" → HIGH SCORE (mobility match)
    #   - "Promotes shiny coat" → LOW SCORE (no match)
    # Result: "Supports hip & joint mobility"
```

---

## Next Steps

1. **User:** Apply SQL migration via Supabase dashboard
2. **Continue implementation:**
   - Update Product model
   - Implement hook matching
   - Update prompt generation
   - Populate data
   - Test

---

## Files Modified (So Far)

### Created
- `sql/migration_product_constraints.sql` - Database migration

### To Be Modified
- `viraltracker/services/models.py` - Add fields to Product class
- `viraltracker/agent/agents/ad_creation_agent.py` - Hook matching + prompt updates

---

## Current Git Status

**Branch:** `feature/ad-creation-api`

**Previous work (already committed):**
- All 19 bugs fixed (Phase 5)
- End-to-end workflow passing
- Pushed to GitHub

**This session (not yet committed):**
- SQL migration file created
- Checkpoint document created

---

## Key Insights

**Legal Compliance Risk:**
- Hallucinated claims could violate FTC/FDA regulations
- Need explicit control over all ad copy claims
- Especially important for health/supplement products

**Benefit Matching Importance:**
- Generic "first benefit" approach produces irrelevant ads
- Hook theme should drive benefit selection
- Improves ad quality and conversion rates

**User Quote:**
> "I noticed the example we tested with came back stating the product was up to 50% off. I believe on collagen its up to 35% off (single one time purchase vs subscription 3 packs)"

---

## Completion Summary

### ✅ All Tasks Completed

1. **Database Schema** - 5 new columns added to `products` table
2. **SQL Migration** - Applied successfully via Supabase dashboard
3. **Product Model** - Updated with 5 new Optional fields and validators
4. **Hook-to-Benefit Matching** - 73-line algorithm implemented (viraltracker/agent/agents/ad_creation_agent.py:733-806)
5. **Prompt Generation** - Updated to use matched benefits and all constraint fields
6. **Wonder Paws Data** - Populated with refined product constraints
7. **Bug #20 Fixed** - Added retry logic for Gemini JSON parsing errors
8. **Integration Test** - End-to-end workflow passed successfully (3 minutes 45 seconds)

### Test Results

```
1 passed, 23 warnings in 225.90s (0:03:45)
```

All Phase 6 features working correctly:
- Exact offer wording used ("Up to 35% off" not hallucinated "50% off")
- Hook-to-benefit matching selects relevant benefits
- Brand voice and unique selling points included in prompts
- No legal compliance violations

### Final State

**Branch:** `feature/ad-creation-api`

**Files Modified:**
- `viraltracker/agent/agents/ad_creation_agent.py` - Added hook matching + retry logic
- `viraltracker/services/models.py` - Added 5 Phase 6 fields to Product class
- `sql/migration_product_constraints.sql` - Database migration (applied)
- `update_wonder_paws_product.py` - Data population script (created)
- `PHASE6_PRODUCT_CONSTRAINTS_CHECKPOINT.md` - This documentation

**Ready for commit and push to GitHub.**
