# Checkpoint: Copy Scaffolds & Template Evaluation

**Date:** 2025-12-15
**Branch:** `feature/copy-scaffolds-template-eval`
**Status:** Core implementation complete, pending copy generation testing

---

## What Was Built

### 1. Database Schema (Migration Run)
- `copy_scaffolds` table - tokenized headline/primary text templates
- `angle_copy_sets` table - generated copy per angle
- `template_evaluations` table - D1-D6 rubric scores
- Added evaluation columns to `scraped_templates` and `ad_brief_templates`

### 2. Services Created

**TemplateEvaluationService** (`viraltracker/services/template_evaluation_service.py`)
- AI-driven D1-D6 rubric evaluation using Gemini vision
- Batch evaluation for all templates
- Phase eligibility scoring (D6 pass, total >= 12, D2 >= 2)
- Stores all 6 dimension scores in `phase_tags`

**CopyScaffoldService** (`viraltracker/services/copy_scaffold_service.py`)
- Token filling (`{SYMPTOM_1}`, `{ANGLE_CLAIM}`, etc.)
- 40-character headline validation
- Guardrails checking (no discounts, medical claims for Phase 1-2)
- Copy set generation per angle

### 3. UI Pages

**Template Evaluation Admin** (`34_🔍_Template_Evaluation.py`)
- View all templates with evaluation status
- Run individual or batch AI evaluation
- Filter by eligibility, source, phase
- Shows D1-D6 breakdown with color coding

**Ad Planning Wizard Updates** (`32_📋_Ad_Planning.py`)
- Changed from 8 steps to 9 steps
- Step 7: Template selection with eligibility filtering
- Step 8: Copy scaffold selection & generation (NEW)
- Step 9: Review with copy preview

### 4. Seed Data
- 12 headline scaffolds (H1-H4 variations)
- 4 primary text scaffolds (P1-P4)
- SQL in `sql/seed_copy_scaffolds.sql`

### 5. Phase 1-2 Creative Templates
Imported 5 purpose-built templates following belief testing rules:

| Template | Type | Anchor Text |
|----------|------|-------------|
| Dog at Stairs | Observation Shot | "Noticing this?" |
| Hair Check Close-Up | Situation Close-Up | "It's not just age." |
| Morning Pause | Observation Shot | "This usually comes first." |
| Railing Grip | Situation Close-Up | "Most people miss this early." |
| Quiet Product Presence | Type C | None |

All pre-scored 15/15 for Phase 1-2 eligibility.

---

## Key Concepts Clarified

### Copy Location
- **Primary Text** = Lives ABOVE the image in Meta feed
- **Headline** = Lives BELOW the image in Meta feed
- **On-Image Text** = Short anchor lines only (optional, observational)

### Phase 1-2 Creative Rules
- Image invites recognition, copy (outside) explains
- No claims, benefits, mechanisms, offers ON the image
- Anchor lines are observational, non-conclusive
- Show the moment/state, not the solution

---

## Files Changed/Created

### New Files
- `sql/2025-12-16_copy_scaffolds_template_eval.sql`
- `sql/seed_copy_scaffolds.sql`
- `viraltracker/services/copy_scaffold_service.py`
- `viraltracker/services/template_evaluation_service.py`
- `viraltracker/ui/pages/34_🔍_Template_Evaluation.py`
- `scripts/import_phase12_templates.py`

### Modified Files
- `viraltracker/services/models.py` - Added Pydantic models
- `viraltracker/services/__init__.py` - Export new services
- `viraltracker/services/planning_service.py` - Copy integration
- `viraltracker/ui/pages/32_📋_Ad_Planning.py` - 9-step wizard

---

## Bugs Fixed During Implementation

1. **Column not found error** - Fixed query to use `storage_path` instead of non-existent `asset_public_url`
2. **Missing dimension scores** - Updated `phase_tags` to store all D1-D6 scores, not just D2/D6
3. **Nested expander error** - Replaced inner expander with checkbox toggle

---

## Pending / To Test

1. **Copy Generation** - Railway incident prevented testing Step 8
   - Token filling from context
   - Guardrails validation
   - Copy set persistence

2. **End-to-End Flow** - Full wizard with copy through to compiled payload

---

## Migration Commands (Already Run)

```sql
-- Run the migration
\i sql/2025-12-16_copy_scaffolds_template_eval.sql

-- Seed the scaffolds
\i sql/seed_copy_scaffolds.sql
```

---

## Next Steps

1. Test copy generation when Railway is back
2. Verify compiled_payload includes copy sets
3. Wire copy into ad creation workflow
4. Consider: Template thumbnail previews in evaluation UI
