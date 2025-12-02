# Checkpoint: Ad Workflow Improvements

**Date:** 2025-11-28
**Status:** Complete

## Summary

Major improvements to the ad creation workflow focused on copy quality, validation, and error resilience.

## Changes Made

### 1. Founders Support
- Added `founders` column to products table
- Updated Product model in `services/models.py` to include founders field
- `analyze_reference_ad()` now detects two types of founder elements:
  - **Founder Signatures**: Sign-offs at end (e.g., "Love, The Smith Family")
  - **Founder Mentions**: References in body text (e.g., "We created this...")
- `generate_nano_banana_prompt()` includes founders section when detected
- Emphasis on using ALL founder names (counts them, warns against truncation)

### 2. Workflow Resilience
- Wrapped generation step in try/except - continues with other variations if one fails
- Wrapped Claude and Gemini reviews in try/except - handles review failures gracefully
- Added `generation_failed` and `review_failed` statuses
- If one reviewer fails, uses the other's decision instead of crashing
- Workflow completes even if some variations fail

### 3. Gemini Error Handling
- Added content validation checks to prevent "whichOneof" errors
- Checks for `candidate.content` and `candidate.content.parts` before accessing `response.text`
- Specific error handling for blocked content with user-friendly message

### 4. Copy Quality Improvements

#### Direct Response Copywriter Persona
```
You are a world-class direct response copywriter - the kind who has generated millions in sales through Facebook ads. Your copy is:
- Crystal clear: The reader knows EXACTLY what this is and who it's for within 2 seconds
- Emotionally resonant: You tap into real pain points and desires
- Punchy and concise: Every word earns its place, no fluff
- Action-oriented: The reader feels compelled to learn more
- Authentic: It sounds like a real person, not a corporation
```

#### Headline Clarity Rules
- Must be immediately clear about WHO this is for
- No vague pronouns ("their", "them") without establishing context
- Must say "your child", "your kids" explicitly for parent products
- Reader should understand within 2 seconds

#### Word Count Matching
- Shows original headline word count and character count
- Headlines must match original length (±8 words max)
- "DO NOT write paragraphs - write PUNCHY headlines"
- "Shorter is better"

#### Technical Specs Filtering
- Separated emotional benefits from technical specs
- USPs containing "cards", "pages", "included", "app", "guide", etc. filtered out
- Technical specs excluded from headline generation

### 5. Copy Validation (Reject & Regenerate)

Added validation step BEFORE image generation that checks for:
- **Hallucinated free gifts** - If "free gift/bonus" in copy but not in actual offer
- **Invented scarcity numbers** - "50 owners", "100 customers", etc.
- **Fake time limits** - "this weekend", "until midnight", "24 hours"
- **Made-up dollar amounts** - Dollar figures not in product offer
- **Word count violations** - More than ±8 words from original

If validation fails:
1. Logs which variations failed and why
2. Appends specific feedback to the prompt
3. Retries (up to 3 attempts total)
4. Only passes validated copy to image generation

### 6. Offer Rules Strengthened
- Prominent display of product's ACTUAL offer
- "DO NOT copy offers from the reference template (it's for a different product!)"
- Explicit list of things NOT to invent: free gifts, bonus items, limited quantities, time limits, dollar amounts
- Concrete examples of what not to do

## Files Modified

- `viraltracker/agent/agents/ad_creation_agent.py` - Main workflow improvements
- `viraltracker/services/models.py` - Added founders field to Product model
- `viraltracker/services/gemini_service.py` - Error handling improvements
- `sql/add_founders_column.sql` - Database migration for founders

## Commits

- `8ef1064` - fix: Add founders field to Product model for ad creation
- `57b0b15` - fix: Add content validation checks to prevent whichOneof errors
- `f873c36` - fix: Make ad workflow resilient to individual generation/review failures
- `7336f2f` - fix: Improve ad headline clarity and filter out technical specs
- `cf96e24` - fix: Emphasize that ALL founder names must be included in signature
- `bd2e480` - feat: Add word count matching to keep headlines punchy like originals
- `21df486` - fix: Strengthen offer rules to prevent hallucination from template
- `3cafc6e` - feat: Add copy validation with reject & regenerate + DR copywriter persona

## Testing Notes

- Test with products that have founders configured (Yakety Pack)
- Test with products that have specific offers (Wonder Paws: "Up to 35% off")
- Verify validation catches hallucinated offers, scarcity, time limits
- Verify workflow completes even when some variations fail review
