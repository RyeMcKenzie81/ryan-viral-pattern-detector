# Phase 3/4 v2 Adaptation Plan

> Date: 2026-02-23
> Branch: feat/ad-creator-v2-phase0
> Status: PLAN — awaiting approval

## Problem Statement

Phase 3 per-section Gemini Vision refinement strips the global `<style>` block when extracting section HTML. Gemini can't see custom CSS class definitions (`mp-container`, `mp-hero-text`, `mp-grid-2`, etc.) and responds by adding conflicting inline styles that destroy layout.

**Evidence:**
- Boba Phase 3 SSIM: 0.5618 → 0.4281 (-0.134 regression)
- InfiniteAge Phase 3 SSIM: 0.6408 → 0.6700 (+0.029 — less CSS-dependent)
- Phase 3 snapshots show duplicate padding declarations: `padding: 60px 30px;; padding: 80px 0;`
- Root cause confirmed by 4 independent research agents

## Architecture Decision

**Pattern:** Direct code modification (no new services, no new files, no DB changes)

This is purely modifying the existing multipass pipeline internals:
- `prompts.py` — Phase 3/4 prompt text changes
- `pipeline.py` — CSS extraction + cleanup logic
- `tests/test_multipass_v4.py` — New unit tests

No new dependencies, no new tables, no interface changes.

## Files to Modify

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/multipass/prompts.py` | Add `skeleton_css` param to Phase 3 prompt; add CSS preservation constraints; harden Phase 4 prompt |
| `viraltracker/services/landing_page_analysis/multipass/pipeline.py` | Extract skeleton CSS before Phase 3 loop; pass to prompt builder; add post-Phase-3 inline style cleanup |
| `tests/test_multipass_v4.py` | Tests for CSS extraction, inline cleanup, prompt builder changes |

## Milestones

### Milestone 1: Pass skeleton CSS to Phase 3 prompt

**What:** Extract the `<style>` block from `content_html` and pass it to `build_phase_3_prompt()` so Gemini sees the CSS class definitions it needs to understand.

**Changes:**

1. **`prompts.py:233`** — Add `skeleton_css` parameter to `build_phase_3_prompt()`:
   ```python
   def build_phase_3_prompt(
       section_id, section_html, design_system_compact,
       image_urls=None, section_images=None,
       original_css_snippet=None,
       skeleton_css=None,         # NEW
   ) -> str:
   ```

2. **`prompts.py:297-303`** — Add skeleton CSS section to prompt (before the original CSS reference):
   ```
   ## SKELETON CSS (defines layout classes used in this section)
   These CSS rules define the structure of this section. PRESERVE all class names and rely on these definitions.
   ```css
   {skeleton_css}
   ```
   ```

3. **`pipeline.py:2452-2457`** — Extract skeleton CSS from content_html before the Phase 3 loop:
   ```python
   # Extract skeleton CSS for v2 awareness
   skeleton_css = None
   style_match = re.search(r'<style[^>]*>(.*?)</style>', content_html, re.DOTALL)
   if style_match:
       skeleton_css = style_match.group(1)[:4096]  # 4KB cap
   ```

4. **`pipeline.py:2494-2501`** — Pass `skeleton_css` to prompt builder:
   ```python
   prompt = build_phase_3_prompt(
       sec_id, section_html, compact_ds, image_urls,
       section_images=section_images,
       original_css_snippet=css_snippet,
       skeleton_css=skeleton_css,   # NEW
   )
   ```

**Expected impact:** Gemini now sees the CSS definitions, can reason about `mp-*` classes, and should avoid replacing them with inline styles.

**Tests:** Verify `build_phase_3_prompt()` includes skeleton CSS when provided; verify extraction from `<style>` block; verify 4KB cap.

---

### Milestone 2: Add CSS preservation constraints to Phase 3 prompt

**What:** Explicit instructions telling Gemini to preserve CSS classes, not inline styles, and not restructure HTML hierarchy.

**Changes in `prompts.py:323-330`** — Expand CRITICAL CONSTRAINTS:

```
## CRITICAL CONSTRAINTS (DO NOT VIOLATE)
- Do NOT change any text content -- keep ALL text exactly as-is
- Do NOT remove or rename any data-slot attributes
- Do NOT remove or rename any data-section attributes
- Do NOT add new text that isn't in the current HTML
- Do NOT use background-image: url(...) in CSS (it will be stripped by the sanitizer)
- Keep data-bg-image="true" on images that have it
- PRESERVE ALL CSS CLASSES — especially mp-* prefixed classes (e.g., mp-container, mp-grid-3, mp-hero-text)
  * Do NOT replace class="..." with inline style="" attributes
  * Do NOT remove or rename CSS classes
  * If a class is defined in the SKELETON CSS above, it controls layout — do NOT override with inline styles
- Do NOT restructure the HTML hierarchy (keep parent-child nesting intact, do not flatten or consolidate elements)
- Do NOT add inline padding, margin, width, or height when the element already uses mp-* layout classes
- ONLY adjust: CSS color values, font-size, specific visual properties not controlled by layout classes
```

**Expected impact:** Gemini stops adding conflicting inline styles (the primary cause of Boba's regression).

**Tests:** Verify prompt text contains preservation constraints.

---

### Milestone 3: Post-Phase-3 inline style cleanup

**What:** Defensive cleanup function that fixes any inline style conflicts Gemini may still introduce.

**New function in `pipeline.py`** (after `_fix_v2_skeleton_css`, ~line 1066):

```python
def _clean_phase3_inline_conflicts(html: str) -> str:
    """Remove duplicate CSS properties from inline style attributes.

    Phase 3 Gemini sometimes appends new style properties to existing
    inline styles, producing declarations like:
      style="padding: 60px 30px;; padding: 80px 0;"

    This function:
    1. Removes double semicolons
    2. Deduplicates CSS properties (keeps last occurrence)
    """
```

**Call site in `pipeline.py:2600`** — after reassembly, before returning:
```python
assembled = content_html
for sec_id, refined in refined_sections.items():
    ...
    assembled = section_re.sub(refined, assembled, count=1)

# Clean up any inline style conflicts from Phase 3
assembled = _clean_phase3_inline_conflicts(assembled)
```

**Expected impact:** Catches and fixes any remaining duplicate property issues even if prompt constraints don't fully prevent them.

**Tests:** Unit tests for double semicolons, duplicate properties, non-conflicting styles preserved.

---

### Milestone 4: Phase 4 prompt hardening

**What:** Add guidance to Phase 4 about not modifying layout-critical CSS classes.

**Changes in `prompts.py:386-387`** — After selector grammar, add:

```
IMPORTANT: Do NOT use css_fix patches to override layout properties (padding, margin, display, grid-*, flex-*)
on elements using mp-* CSS classes. These classes are layout-critical and interdependent.
If you notice layout issues, return an empty list [] rather than attempting to fix grid/flexbox alignment.
```

**Expected impact:** Phase 4 avoids undoing Phase 3's work or adding its own layout conflicts.

**Tests:** Verify prompt text contains mp-* warning.

---

## Regression Safety

All changes are either:
- **Additive prompt text** (new constraints don't affect template path since templates don't use `mp-*` custom classes the same way)
- **New parameter with default=None** (backward compatible)
- **Post-processing cleanup** (only acts on actual duplicate properties)

Template path will NOT be affected because:
- `skeleton_css` extraction finds the same shared CSS for template path (harmless)
- CSS preservation constraints are about `mp-*` classes which templates also use
- Inline style cleanup only fixes actual duplicates

## Target Scores

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| Boba Phase 3 SSIM | 0.4281 | >= 0.55 | STOP the regression |
| InfiniteAge Phase 3 SSIM | 0.6700 | >= 0.72 | Consistent lift |
| InfiniteAge Final SSIM | 0.6736 | >= 0.78 | Approach template quality |
| Template Final SSIM | 0.7596 | >= 0.72 | No regression |
| Unit tests | 313 pass | 313+ pass | Add new, don't break existing |

## Verification Commands

```bash
# v2 on InfiniteAge
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# v2 on Boba (critical)
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --visual

# Template baseline (must not regress)
MULTIPASS_PHASE1_MODE=template PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Unit tests
python3 -m pytest tests/test_multipass_v4.py -x -q
```
