# CHECKPOINT: Size Variants Refactor

**Date**: December 2, 2025
**Status**: Refactored to follow architecture - Bug found

---

## What Was Done

Refactored size variants feature to follow project architecture:

1. **Service Layer** (`ad_creation_service.py`) - All Gemini generation logic moved here
2. **Agent Tool** (`ad_creation_agent.py`) - Thin wrapper calling service
3. **UI Layer** - Calls service directly, no duplicated logic

Commit: `1ccda23` - "refactor: Move size variant generation logic to service layer"

---

## Bug Found

When trying to create size variants from Ad History, got error:

```
new row for relation "generated_ads" violates check constraint "generated_ads_prompt_index_check"
```

**Root Cause**: `save_size_variant()` sets `prompt_index=0` for variants, but there's a database CHECK constraint requiring `prompt_index >= 1` or similar.

**Fix Needed**: Either:
1. Update the CHECK constraint to allow 0 or NULL for variants
2. Use a different value for variant prompt_index (e.g., NULL)

---

## Files Modified This Session

- `viraltracker/services/ad_creation_service.py` - Added generation methods
- `viraltracker/agent/agents/ad_creation_agent.py` - Simplified to call service
- `viraltracker/ui/pages/02_📊_Ad_History.py` - Removed duplicated logic
- `viraltracker/ui/pages/03_🖼️_Ad_Gallery.py` - Removed duplicated logic
- `docs/archive/CHECKPOINT_2025-12-02_size-variants.md` - Updated documentation
