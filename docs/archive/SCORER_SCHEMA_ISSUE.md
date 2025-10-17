# Scorer Database Schema Issue

**Branch:** `fix/scorer-database-schema`
**Date:** 2025-10-16
**Status:** 🔍 Investigation Complete

---

## Problem Summary

The scorer v1.2.0 successfully calculates overall scores (59.8-65.2/100) but **fails to save them to the database** due to a schema constraint violation.

### Error Message
```
null value in column "hook_score" of relation "video_scores" violates not-null constraint
```

---

## Root Cause

**Scorer v1.2.0 behavior:**
- ✅ Calculates `overall` score correctly
- ❌ Returns `null` for all subscores (`hook`, `story`, `relatability`, etc.)

**Database schema (`video_scores` table):**
```sql
hook_score          NUMERIC NOT NULL
story_score         NUMERIC NOT NULL
relatability_score  NUMERIC NOT NULL
visuals_score       NUMERIC NOT NULL
audio_score         NUMERIC NOT NULL
watchtime_score     NUMERIC NOT NULL
engagement_score    NUMERIC NOT NULL
shareability_score  NUMERIC NOT NULL
algo_score          NUMERIC NOT NULL
```

**Python save code (viraltracker/cli/score.py:195):**
```python
record = {
    "hook_score": scores["subscores"]["hook"],  # This is null!
    "story_score": scores["subscores"]["story"],  # This is null!
    # ... all null
}
```

---

## Why Subscores Are Null

Looking at the scorer schema (scorer/src/schema.ts:189-199):

```typescript
export const SubscoresSchema = z.object({
  hook: z.number().min(0).max(100).nullable(),  // <-- nullable!
  story: z.number().min(0).max(100).nullable(),
  // ...
});
```

The scorer v1.2.0 uses **continuous formulas** that don't decompose into traditional subscores. It calculates an overall score directly from weighted features, not from 9 separate subscores.

---

## Solution Options

### Option 1: Make Database Columns Nullable (RECOMMENDED)
**Pros:**
- Aligns with scorer v1.2.0 architecture
- Allows saving overall scores immediately
- Future-proof for new scoring methods

**Cons:**
- Requires database migration
- Existing queries expecting non-null subscores need updating

**SQL Migration:**
```sql
ALTER TABLE video_scores
  ALTER COLUMN hook_score DROP NOT NULL,
  ALTER COLUMN story_score DROP NOT NULL,
  ALTER COLUMN relatability_score DROP NOT NULL,
  ALTER COLUMN visuals_score DROP NOT NULL,
  ALTER COLUMN audio_score DROP NOT NULL,
  ALTER COLUMN watchtime_score DROP NOT NULL,
  ALTER COLUMN engagement_score DROP NOT NULL,
  ALTER COLUMN shareability_score DROP NOT NULL,
  ALTER COLUMN algo_score DROP NOT NULL;
```

### Option 2: Update Scorer to Return Synthetic Subscores
**Pros:**
- No database changes needed
- Backwards compatible

**Cons:**
- Subscores would be artificial/meaningless
- Misleading to users expecting real component scores

### Option 3: Use Only `overall_score` Column
**Pros:**
- Simplest solution
- Matches scorer v1.2.0 architecture

**Cons:**
- Wastes database columns
- Loses historical subscore data if any exists

---

## Recommended Approach

**Use Option 1** - Make columns nullable:

1. **Create migration:**
   ```sql
   -- Make subscore columns nullable
   ALTER TABLE video_scores
     ALTER COLUMN hook_score DROP NOT NULL,
     ALTER COLUMN story_score DROP NOT NULL,
     ALTER COLUMN relatability_score DROP NOT NULL,
     ALTER COLUMN visuals_score DROP NOT NULL,
     ALTER COLUMN audio_score DROP NOT NULL,
     ALTER COLUMN watchtime_score DROP NOT NULL,
     ALTER COLUMN engagement_score DROP NOT NULL,
     ALTER COLUMN shareability_score DROP NOT NULL,
     ALTER COLUMN algo_score DROP NOT NULL;
   ```

2. **Update save code to handle nulls explicitly:**
   ```python
   record = {
       "hook_score": scores["subscores"].get("hook"),  # Allow None
       "story_score": scores["subscores"].get("story"),
       # ...
   }
   ```

3. **Update query logic:**
   - Display only shows subscores if not null
   - Export CSV handles null subscores gracefully
   - Analysis uses overall_score primarily

---

## Test Plan

After applying migration:

1. **Run scorer on Italian Brainrot videos:**
   ```bash
   vt score videos --project italian-brainrot --verbose
   ```

2. **Verify scores saved:**
   ```sql
   SELECT post_id, overall_score, hook_score
   FROM video_scores
   WHERE post_id IN (SELECT post_id FROM project_posts WHERE project_id = 'italian-brainrot-id');
   ```

3. **Expected results:**
   - `overall_score`: 59.8-65.2
   - `hook_score`: NULL
   - All other subscores: NULL

4. **Test display commands:**
   ```bash
   vt score show <post_id>
   vt score analyze --project italian-brainrot
   vt score export --project italian-brainrot
   ```

---

## Files to Update

1. **Database:**
   - Run migration SQL on Supabase

2. **Python code:**
   - `viraltracker/cli/score.py` - Update save/display logic to handle nulls

3. **Documentation:**
   - Update README to explain scorer v1.2.0 behavior

---

## Current Status

- ✅ Issue identified
- ✅ Root cause understood
- ⏳ Migration SQL ready
- ⏳ Python code updates needed
- ⏳ Testing pending

---

## Next Steps

1. Review this document
2. Get approval for database migration
3. Apply migration to Supabase
4. Update Python code
5. Test with Italian Brainrot videos
6. Merge to master
