# Checkpoint: Model Upgrades and Workflow Logging

**Date:** 2025-11-28
**Status:** Complete

## Summary

Major upgrades to the ad creation workflow including model upgrades to Claude Opus 4.5, proper Gemini image model configuration, workflow logging, and a new Ad History UI page.

## Changes Made

### 1. Model Upgrades

#### Claude Opus 4.5 for Vision Analysis
- `analyze_reference_ad()` - Now uses Claude Opus 4.5 vision instead of Gemini flash
- `extract_template_angle()` - Now uses Claude Opus 4.5 vision instead of Gemini flash

#### Claude Opus 4.5 for Copy Generation
- `generate_benefit_variations()` - Now uses Claude Opus 4.5 for high-quality direct response copy
- Model: `claude-opus-4-5-20251101`

#### Gemini 3 Pro Image Preview for Image Generation
- Fixed: Was using `gemini-2.0-flash-exp` (text model) for image generation
- Now uses: `models/gemini-3-pro-image-preview` with `temperature=0.2`
- Temperature lowered for more consistent outputs

### 2. Brand Name & Banned Terms

#### New Product Fields
- `brand_name` - Correct brand name to use in ads (e.g., "Wonder Paws")
- `banned_terms` - List of competitor names that must never appear (e.g., ["Wuffes"])

#### Automatic Replacement
- Banned competitor names are automatically replaced with the brand name
- Case-insensitive replacement

#### Markdown Stripping
- Markdown formatting (`*bold*`, `**bold**`) is stripped from generated copy

### 3. Workflow Logging

#### New Database Columns (generated_ads)
- `model_requested` - Model we asked for
- `model_used` - Model that actually generated (may differ due to Gemini fallback)
- `generation_time_ms` - Time taken in milliseconds
- `generation_retries` - Number of retries needed

#### New Table: workflow_logs
- Step-by-step logging for debugging
- Tracks each workflow step with timing, status, errors
- Supports tracking model fallbacks

#### Gemini Metadata
- `generate_image()` now returns metadata dict with `return_metadata=True`
- Attempts to detect actual model used from Gemini response
- Logs model info to database for each generated ad

### 4. Ad History Page (New)

#### Features
- **Brand Filter** - Filter ad runs by brand
- **Summary View** - Product, Run ID, Date, approval count
- **Thumbnails** - Reference template and first generated ad
- **Expandable Rows** - Click to see all ads from a run
- **Download All** - Download all images from a run as ZIP

#### Per-Ad Display
- Full-size image
- Approval status badge
- Hook text used
- Claude & Gemini review scores
- Model info with fallback warning
- Generation time and retry count

### 5. Yakety Pack Hooks

Added 50 hooks for Yakety Pack product from customer reviews:
- Categories: skepticism_overcome, dramatic_transformation, professional_validation, etc.
- Sources tracked: Review 1-10, Persona - Jennifer/Sarah/Both
- Impact scores: 16-21

## Files Modified

### Agent & Services
- `viraltracker/agent/agents/ad_creation_agent.py` - Claude Opus vision, metadata tracking
- `viraltracker/services/gemini_service.py` - Correct image model, temperature, metadata return
- `viraltracker/services/ad_creation_service.py` - Store model metadata
- `viraltracker/services/models.py` - Added brand_name, banned_terms fields

### UI
- `viraltracker/ui/pages/6_📊_Ad_History.py` - New page for reviewing past ads

### SQL Migrations
- `sql/add_brand_name_banned_terms.sql` - Brand and banned terms columns
- `sql/add_workflow_logging.sql` - Model tracking and workflow_logs table
- `sql/insert_yakety_pack_hooks.sql` - 50 hooks for Yakety Pack

## Model Usage Summary

| Task | Model |
|------|-------|
| Reference ad analysis | Claude Opus 4.5 (vision) |
| Template angle extraction | Claude Opus 4.5 (vision) |
| Copy generation | Claude Opus 4.5 (text) |
| Image generation | Gemini 3 Pro Image Preview (temp=0.2) |
| Ad reviews | Claude Sonnet 4.5 + Gemini 2.0 Flash |

## Commits

- `9362dba` - feat: Add brand name and banned terms support
- `dec64a5` - fix: Use correct model for image generation (gemini-3-pro-image-preview)
- `ddd7c08` - feat: Use Claude Opus 4.5 for copy generation, set image temp to 0.2
- `1712982` - feat: Use Claude Opus 4.5 for vision analysis
- `dcc8512` - feat: Add Ad History page to review past ad runs
- `c664c3d` - feat: Add Download All button to Ad History page
- `b6e7870` - fix: Make download buttons more visible
- `1dfd9ca` - feat: Add 50 hooks for Yakety Pack product
- `d0b725d` - feat: Add workflow logging to track model usage

## SQL Migrations to Run

1. `sql/add_brand_name_banned_terms.sql` - Add brand_name and banned_terms columns
2. `sql/add_workflow_logging.sql` - Add model tracking and workflow_logs table
3. `sql/insert_yakety_pack_hooks.sql` - Insert 50 Yakety Pack hooks (if not already run)

## Testing Notes

- Test with Wonder Paws to verify banned terms replacement (Wuffes → Wonder Paws)
- Check Ad History page shows model info after running new ads
- Verify model fallback detection works when Gemini quota is exceeded
- Confirm markdown asterisks no longer appear in generated copy
