# Checkpoint: AI-Enhanced Template Approval

**Date**: 2025-12-04
**Status**: Implementation Complete - Ready for Testing
**Context Window**: Updated after implementation

## Feature Overview

Adding AI-powered analysis to the template approval workflow with a two-step approval process:
1. User clicks "Approve" → AI analyzes and suggests metadata
2. User reviews AI suggestions → Confirms/edits → Finalizes

## Architecture Decision

**Using Direct Service Calls (NOT pydantic-graph)** because:
- User-driven, interactive workflow
- Short, synchronous operations
- UI controls the flow

## Completed Steps

### 1. Database Migration ✅
**File**: `/sql/2025-12-04_template_ai_analysis_fields.sql`

New columns on `scraped_templates`:
- `source_brand` (TEXT)
- `source_landing_page` (TEXT)
- `industry_niche` (TEXT)
- `target_sex` (TEXT) - male/female/unisex
- `awareness_level` (INTEGER 1-5)
- `awareness_level_name` (TEXT)
- `sales_event` (TEXT)
- `ai_suggested_name` (TEXT)
- `ai_suggested_description` (TEXT)
- `ai_analysis_raw` (JSONB)

Updated `template_queue`:
- Added `pending_details` to status enum
- Added `ai_suggestions` (JSONB) column

### 2. Awareness Levels Reference Doc ✅
**File**: `/docs/reference/consumer_awareness_levels.md`

Eugene Schwartz 5 levels documented for RAG/reference.

### 3. Template Queue Service - COMPLETE
**File**: `/viraltracker/services/template_queue_service.py`

Added:
- Import `json`, `base64`
- `TEMPLATE_ANALYSIS_PROMPT` constant with full prompt
- `analyze_template_for_approval()` method - downloads image, calls Gemini, parses JSON
- `start_approval()` method - sets status to pending_details, runs AI, stores suggestions
- `finalize_approval()` method - creates template with all user-confirmed metadata
- `get_pending_details_item()` method - gets item awaiting confirmation
- `cancel_approval()` method - returns item to pending status

### 4. Template Queue UI - COMPLETE
**File**: `/viraltracker/ui/pages/16_📋_Template_Queue.py`

Changes made:
- Added session state: `reviewing_item_id`, `ai_suggestions`
- Added action functions: `start_ai_approval()`, `finalize_ai_approval()`, `cancel_ai_approval()`
- Added helper functions: `get_industry_options()`, `get_sales_event_options()`, `get_awareness_level_options()`
- Added `render_details_review()` function for AI suggestions review form
- Modified `render_pending_queue()` to use two-step flow with AI analysis

### 5. Architecture Docs - COMPLETE
**File**: `/docs/architecture.md`

Added section "Pydantic-Graph vs Direct Service Calls" with:
- Comparison table
- Criteria for choosing each pattern
- Example using template approval workflow

## Remaining Steps

### 6. Run Database Migration
Need to run the SQL migration on the Supabase database.

### 7. Test with Pending Templates

## Key Files

| File | Status | Purpose |
|------|--------|---------|
| `sql/2025-12-04_template_ai_analysis_fields.sql` | ✅ Created | DB migration |
| `docs/reference/consumer_awareness_levels.md` | ✅ Created | Awareness levels reference |
| `viraltracker/services/template_queue_service.py` | ✅ Complete | AI analysis methods |
| `viraltracker/ui/pages/16_📋_Template_Queue.py` | ✅ Complete | Two-step UI |
| `docs/architecture.md` | ✅ Complete | Add pydantic-graph guidance |

## AI Analysis Prompt

The prompt is defined in `template_queue_service.py` as `TEMPLATE_ANALYSIS_PROMPT`. It:
- Takes page_name and link_url as context
- Returns JSON with: suggested_name, suggested_description, format_type, industry_niche, target_sex, awareness_level (1-5), awareness_level_reasoning, sales_event, visual_notes
- Includes awareness level guide in the prompt

## Model Choice

Using Gemini Flash (default `gemini-2.0-flash-exp` in GeminiService) for fast, cost-effective analysis.

## Todo List State

1. ✅ Create database migration for new columns
2. ✅ Add awareness levels document to Knowledge Base
3. ✅ Add AI analysis method to template_queue_service.py
4. ✅ Update Template Queue UI for two-step approval
5. ✅ Update architecture.md with pydantic-graph guidance
6. ⏳ Run database migration
7. ⏳ Test with existing pending templates

## Industry/Niche Options
supplements, pets, skincare, fitness, fashion, tech, food_beverage, home_garden, finance, health_wellness, beauty, automotive, travel, education, other

## Sales Event Options
None, black_friday, cyber_monday, mothers_day, fathers_day, valentines_day, christmas, new_year, summer_sale, labor_day, memorial_day, other

## Awareness Levels
1. Unaware - Doesn't know they have a problem
2. Problem Aware - Knows problem, not solutions
3. Solution Aware - Knows solutions exist, not your product
4. Product Aware - Knows your product, not convinced
5. Most Aware - Ready to buy, needs offer
