# Checkpoint: Phase 2 Content Assembly Fix

**Date**: 2026-02-22
**Branch**: `feat/ad-creator-v2-phase0`
**Last commit**: `7e7e439` — Template fidelity improvements (Fixes 1-4 merged)

---

## What Was Already Done (Fixes 1-4, committed + pushed)

| Fix | File | What |
|-----|------|------|
| Fix 1 | `patch_applier.py` | Block `<img>` tags in Phase 4 `add_element` |
| Fix 2 | `prompts.py` | Add IMAGE GUIDANCE for 0-image sections in Phase 3 |
| Fix 3 | `invariants.py` | Image count tracking per-section + global |
| Fix 4 | `content_assembler.py` + `pipeline.py` | SEO ghost text filter (dual-gate) |
| Fix 5 | `test_multipass_v4.py` | Tests B19-B22 (17 new tests, all passing) |
| Bonus | `scripts/test_multipass_local.py` | Now passes `page_html` to pipeline |

All 188 tests pass. No regressions.

---

## The Remaining Problem: Phase 2 Content Assembly Failures

### Symptom
Running multipass on `http://infiniteage.com/pages/sea-moss-for-hair-growth` (fresh scrape with page_html) produced output with:
- 58 images but **almost no visible text**
- Hero section completely missing (headline, stats, CTA all gone)
- Output jumped straight to a product image that appears later on real page
- 5 of 8 sections failed coverage check:
  ```
  Coverage check failed for sec_0 (64/2866 chars)
  Coverage check failed for sec_3 (545/4941 chars)
  Coverage check failed for sec_4 (988/3718 chars)
  Coverage check failed for sec_5 (507/1917 chars)
  Coverage check failed for sec_6 (29/4663 chars)
  ```

### Root Cause (fully diagnosed)

The failure chain is in **Phase 2: Deterministic Content Assembly** across two files:
- `viraltracker/services/landing_page_analysis/multipass/content_patterns.py`
- `viraltracker/services/landing_page_analysis/multipass/content_assembler.py`

#### Step-by-step failure for sec_0 (hero section):

1. **Phase 1 classifies** sec_0 as `layout_type="stats_row"` (or `hero_split`) because the hero has visible stats (87%, 83%, 77%, 74%)
2. **Template skeleton** generates sub-placeholders: `{{sec_0_header}}` + `{{sec_0_items}}` (for stats_row) or `{{sec_0_text}}` + `{{sec_0_image}}` (for hero_split)
3. **`detect_content_pattern()`** in `content_patterns.py` is biased by `layout_type`:
   - When layout says `stats_row`, it calls `_detect_stats(body_md)` first
   - Stats regex (`_STAT_LINE_RE`, `_STAT_BOLD_RE`) finds 2-4 stat lines
   - Returns a `ContentPattern(pattern_type="stats_list", items=[...])` with ONLY the matched stats
   - **All remaining content is DROPPED** (headline, narrative, CTA, testimonial snippet)
4. **`split_content_for_template()`** renders only the matched stats → 64 chars of output
5. **Coverage check**: `64 / 2866 = 2.2%` < 60% threshold → **FAIL**
6. **Fallback**: `_build_generic_fallback()` wraps full markdown in bland `<section class="mp-generic">` — loses template styling (background color, padding, grid layout, design system)

#### Why this affects most sections:

Real landing pages have **mixed content** in every section. A hero has headline + stats + CTA + image + narrative. A features section has heading + feature cards + contextual text + images. The current pattern detection is **all-or-nothing** — it tries to classify the entire section as ONE pattern type, captures only the items matching that pattern, and drops everything else.

### Key Files to Read

| File | What to look at |
|------|-----------------|
| `content_patterns.py` | `detect_content_pattern()` (line ~75-155), `split_content_for_template()` (line ~262-402), all `_detect_*()` functions |
| `content_assembler.py` | `assemble_content()` (line ~19-184) — the coverage check at lines ~80-145, the fallback at lines ~129-145 |
| `section_templates.py` | `PLACEHOLDER_SUFFIXES` (line ~23-29), `build_skeleton_from_templates()` (line ~373-443), template functions `_tpl_*()` |
| `layout_analyzer.py` | `LayoutHint` dataclass (line ~34-45), `analyze_html_layout()` |
| `pipeline.py` | `_strip_unresolved_placeholders()` — cleans up unfilled `{{sec_N_*}}` at end |

### Architecture Context

```
Phase 0: Design system extraction           ← works fine
Phase 1: Layout classification + skeleton   ← works fine (assigns layout_type per section)
Phase 2: Deterministic content assembly     ← ⚠️ PROBLEM HERE
  ├── Template generates sub-placeholders   ← {{sec_N_header}}, {{sec_N_items}}, etc.
  ├── content_patterns.py detects pattern   ← ⚠️ Captures partial content, drops rest
  ├── split_content_for_template() renders  ← ⚠️ Only renders matched items
  ├── Coverage check (60% threshold)        ← Fails because most text was dropped
  └── Fallback: generic wrapper             ← ⚠️ Loses template styling
Phase 3: CSS refinement                     ← works fine
Phase 4: Patch application                  ← works fine
```

### Sub-Placeholder Naming Convention

```python
PLACEHOLDER_SUFFIXES = {
    "single": "",           # {{sec_N}} — generic/prose/cta
    "header": "_header",    # {{sec_N_header}} — section heading
    "items": "_items",      # {{sec_N_items}} — repeated items (cards, stats, FAQs)
    "text": "_text",        # {{sec_N_text}} — text column in split layouts
    "image": "_image",      # {{sec_N_image}} — image column in split layouts
}
```

### Layout Types → Sub-Placeholders

| Layout Type | Sub-Placeholders |
|-------------|-----------------|
| `generic`, `hero_centered`, `cta_banner`, `content_block` | `{{sec_N}}` (single) |
| `hero_split` | `{{sec_N_text}}` + `{{sec_N_image}}` |
| `feature_grid`, `testimonial_cards`, `faq_list`, `pricing_table`, `stats_row`, `logo_bar` | `{{sec_N_header}}` + `{{sec_N_items}}` |
| `footer_columns` | `{{sec_N_items}}` (no header) |
| `nav_bar` | `{{sec_N}}` (single) |

### Pattern Detection Functions

| Function | What it detects | Regex requirements |
|----------|----------------|-------------------|
| `_detect_features()` | 2+ `### Heading` + paragraph blocks | Must have `###` headings |
| `_detect_testimonials()` | 1+ blockquotes with attribution | Must have `> quote` markers |
| `_detect_faq()` | 2+ questions ending in `?` with answers | Must have `### Question?` |
| `_detect_stats()` | 2+ bold numbers with labels | Must have `**87%** label` or `87% — label` |
| `_detect_logos()` | 3+ images, text < 30% | Must be image-dominant |
| Prose (default) | Everything else | Always matches |

---

## Proposed Fix: Two Changes

### Change 1: Preserve remaining text alongside structured items

In `split_content_for_template()`, when pattern detection captures items (stats, features, etc.) but there's significant remaining text that wasn't captured:

- Calculate what text was captured by items vs total text
- If remaining text > 40% of total, append it as rendered HTML after the items
- This ensures structured items (stats, features) get proper card layout AND narrative text isn't lost

Example: For a hero section with 4 stats + 2000 chars of narrative:
- Render stats as structured `<div class="mp-stat">` cards → goes in `{{sec_0_items}}`
- Render remaining narrative as `<div class="mp-overflow">` → appended after items
- Coverage check now passes because both items + narrative are in sub_values

### Change 2: Smart fallback keeps template styling

When coverage STILL fails (edge cases), instead of `_build_generic_fallback()` which wraps in bland `mp-generic`:

- Keep the original section's template tag (with its CSS classes: `mp-hero-split`, `mp-feature-grid`, etc.)
- Replace ALL sub-placeholders inside that section with a single content dump
- Preserve the section-level styling (background, padding, design system colors)

This is a targeted fix to `content_assembler.py` — when the fallback triggers, it should call a new function `_build_styled_fallback(html, sec_id, section_html)` that finds the section in the skeleton, strips internal sub-placeholder divs, and injects the full content.

### Testing Strategy

1. **Unit test**: Create test cases for `split_content_for_template()` with mixed content sections
2. **Integration test**: Re-run infiniteage.com page and verify:
   - Coverage checks pass for all 8 sections (or styled fallback preserves layout)
   - Hero text is visible (headline, stats, CTA)
   - Images are in correct positions
3. **Regression test**: Re-run bobanutrition.co to ensure no regression
4. **Threshold**: May need to adjust 60% coverage threshold or make it layout-aware

---

## Test Commands

```bash
# Fresh scrape + multipass (requires API keys in .env)
PYTHONPATH=. python3 -c "
import base64, logging, time, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(message)s', datefmt='%H:%M:%S')
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('.env'))
from viraltracker.core.database import get_supabase_client
from viraltracker.services.landing_page_analysis.analysis_service import LandingPageAnalysisService
from viraltracker.services.landing_page_analysis.mockup_service import MockupService
supabase = get_supabase_client()
analysis_svc = LandingPageAnalysisService(supabase)
mockup_svc = MockupService()
url = 'http://infiniteage.com/pages/sea-moss-for-hair-growth'
scrape_data = analysis_svc.scrape_landing_page(url)
multi_html = mockup_svc.generate_analysis_mockup(
    screenshot_b64=scrape_data['screenshot'],
    page_markdown=scrape_data['markdown'],
    page_url=url,
    use_multipass=True,
    page_html=scrape_data.get('page_html'),
    progress_callback=lambda p, d='': print(f'[{p}] {d}'),
)
Path('test_multipass_output.html').write_text(multi_html)
print(f'Output: {len(multi_html)} chars, {multi_html.count(\"data-slot=\")} slots, {multi_html.lower().count(\"<img\")} images')
"

# Run existing tests (should still pass)
python3 -m pytest tests/test_multipass_v4.py -v

# Test specific analysis from DB
PYTHONPATH=. python3 scripts/test_multipass_local.py --page-id <ID>
```
