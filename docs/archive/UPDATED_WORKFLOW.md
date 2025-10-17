# ✅ Updated TikTok URL Analysis Workflow

## Changes Made

Added optional `--product` flag to both URL analysis commands:
- `vt tiktok analyze-url`
- `vt tiktok analyze-urls`

## New Workflow Examples

### Without Product Adaptations (Just Analysis)
```bash
# Analyze videos to understand viral patterns
vt tiktok analyze-urls urls.txt --project wonder-paws-tiktok
```

This will:
- ✅ Fetch metadata from TikTok
- ✅ Link to project (Wonder Paws TikTok Research)
- ✅ Link to brand (Wonder Paws)
- ✅ Download videos
- ✅ Analyze with Gemini AI
- ✅ Show detailed analysis (hook, transcript, storyboard, viral factors)
- ❌ NO product adaptations generated

### With Product Adaptations
```bash
# Analyze AND generate product-specific adaptations
vt tiktok analyze-urls urls.txt \
  --project wonder-paws-tiktok \
  --product collagen-3x-drops
```

This will do everything above PLUS:
- ✅ Generate adapted hooks for your product
- ✅ Generate adapted scripts
- ✅ Provide adaptation scores (hook relevance, audience match, etc.)

## Single URL Examples

```bash
# Just analysis
vt tiktok analyze-url "https://www.tiktok.com/@user/video/123" \
  --project wonder-paws-tiktok

# Analysis + product adaptations
vt tiktok analyze-url "https://www.tiktok.com/@user/video/123" \
  --project wonder-paws-tiktok \
  --product collagen-3x-drops
```

## When to Use Each

### Use WITHOUT `--product` when:
- Researching competitor strategies
- Analyzing viral patterns without adaptation
- Studying viral mechanics for learning
- Don't have a specific product to adapt for

### Use WITH `--product` when:
- Need to adapt competitor videos for your product
- Want scripting ideas for your product
- Need hook variations for your campaigns
- Building a content strategy around your product

## Code Changes Summary

**Files Modified:**
- `viraltracker/cli/tiktok.py`
  - Line 530: Added `--product` option to `analyze-url` command
  - Line 565-574: Added product lookup logic
  - Line 643-644: Added product adaptation messaging
  - Line 729: Added `--product` option to `analyze-urls` command
  - Line 764-773: Added product lookup logic for batch command

**Key Implementation:**
- Product parameter is optional (defaults to None)
- If provided, validates product exists in database
- Passes product_id to VideoAnalyzer for adaptation generation
- Maintains backward compatibility (existing calls without --product still work)

## Next Steps

Now that the workflow is simplified, you can proceed with:
1. Building the TypeScript scoring engine
2. Integrating Gemini Flash 2.5 Video for perceptual features
3. Adding the 9-subscore evaluation system
