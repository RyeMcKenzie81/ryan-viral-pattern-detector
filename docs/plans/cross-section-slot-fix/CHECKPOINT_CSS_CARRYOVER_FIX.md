# Checkpoint: CSS Carryover & Hidden Element Fix — Implemented

**Date**: 2026-02-27
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Implemented and verified via E2E test
**Previous checkpoint**: `CHECKPOINT_QA_FINDINGS.md` (root cause identified, fixes proposed)

---

## Summary

Implemented the two fixes identified in the QA findings checkpoint. The blueprint mockup CSS is no longer truncated (from 4.8% survival to ~100%), and hidden elements no longer receive `data-slot` attributes.

---

## Root Cause Recap

1. **PRIMARY — `data-pipeline="surgery"` marker lost during `_wrap_mockup()`**: The surgery pipeline's S3 adds `data-pipeline="surgery"` to the `<body>` tag. `_wrap_mockup()` created a **new** `<body>` tag WITHOUT this attribute. When `generate_blueprint_mockup()` checked for the marker, it failed → `is_surgery_mode=False` → CSS truncated from 2.1MB to 100KB (the `_CSS_MAX_SIZE = 100_000` limit).

2. **SECONDARY — Hidden elements getting slots**: S2 classifier assigned `data-slot` to ALL matching elements regardless of visibility (`display:none`, `aria-hidden`, `hidden`). When CSS was lost, these previously-hidden elements became visible with brand copy injected.

---

## Changes Made

### 1. `mockup_service.py` — Surgery Mode Marker + CSS Safety Net

**1A: Preserve `data-pipeline="surgery"` in `_wrap_mockup()`**
- Added `is_surgery: bool = False` parameter to `_wrap_mockup()` signature
- Modified `<body>` tag to emit `data-pipeline="surgery"` when `is_surgery=True`
- Pass `is_surgery=self.is_surgery_mode` from `generate_analysis_mockup()`
- This is the **primary fix** — ensures the marker survives into stored HTML so `generate_blueprint_mockup()` uses the 2.5MB CSS limit

**1B: Safety-net CSS constant (defense-in-depth)**
- Added `_SURGERY_CRITICAL_CSS` constant with `max-width: 100vw`, `overflow-x: hidden`, `max-width: 100%` for images/video/iframes
- Appended in `generate_blueprint_mockup()` after CSS extraction for surgery pages

### 2. `element_classifier.py` — Visibility Filter + Slot Name Fix

**2A: `_is_visually_hidden()` helper**
- Detects `display:none`, `visibility:hidden` (inline style), `aria-hidden="true"`, and `hidden` boolean attribute
- Strips quoted values before checking bare `hidden` to avoid false positives on `class="hidden"`

**2B: Wired into all three slot closures**
- `_slot_heading`, `_slot_paragraph`, `_slot_cta` all skip hidden elements via early return
- `_class_heuristic_slots` also checks visibility

**2C: Fixed duplicate `heading-class` slot name**
- Changed from static `"heading-class"` to counter-based `"heading-class-1"`, `"heading-class-2"`, etc.

### 3. Test Updates

**`tests/test_surgery_invariants.py`** — Added `TestVisibilityFiltering` (6 tests):
- `test_display_none_skipped`
- `test_aria_hidden_skipped`
- `test_hidden_attribute_skipped`
- `test_visible_element_gets_slot`
- `test_hidden_class_not_false_positive`
- `test_visibility_hidden_inline_style`

**`tests/test_mockup_service.py`** — Added `TestSurgeryModeDetection` (3 tests):
- `test_wrap_mockup_surgery_marker_present`
- `test_wrap_mockup_no_marker_by_default`
- `test_surgery_critical_css_has_overflow_rules`

**Updated existing tests** for `heading-class-1` naming:
- `test_duplicate_slot_names_first_wins` — assertion updated
- `test_known_types` — assertion updated

---

## E2E Verification Results

| Metric | Before Fix | After Fix | Target |
|--------|-----------|-----------|--------|
| Blueprint CSS | 99,780 chars (4.8%) | **2,398,892 chars (~100%)** | >1,900,000 |
| Slot retention | 499/499 (100%) | **499/499 (100%)** | 100% |
| SSIM blueprint vs analysis | 0.619 | **0.7551** | >0.75 |
| SSIM blueprint vs original | 0.640 | **0.6914** | — |
| SSIM analysis vs original | 0.694 | **0.6943** | — |
| Sections preserved | 8/8 | **8/8** | 8/8 |
| Brand name injected | Yes | **Yes** | Yes |

### Test Results

- `test_surgery_invariants.py`: **16/16 passed** (10 existing + 6 new)
- `test_mockup_service.py`: **273/273 passed** (270 existing + 3 new)

---

## Files Modified

| File | Lines Changed | Purpose |
|------|--------------|---------|
| `viraltracker/services/landing_page_analysis/mockup_service.py` | ~15 | Surgery marker carryover + CSS safety net |
| `viraltracker/services/landing_page_analysis/multipass/surgery/element_classifier.py` | ~45 | Hidden element filtering + slot name fix |
| `tests/test_surgery_invariants.py` | ~65 | Visibility filtering regression tests |
| `tests/test_mockup_service.py` | ~25 | Surgery mode detection tests + existing test updates |
