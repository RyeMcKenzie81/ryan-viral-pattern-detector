# Checkpoint: Slot-Based Blueprint Rendering Pipeline

**Date**: 2026-02-25
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Implementation complete, dry-run verified, awaiting live AI test

## What Was Done

Implemented the full slot-based blueprint rendering pipeline per the plan. Instead of sending 96K-338K chars of HTML to an AI model for copy rewriting (which catastrophically lost 95-98% of slots), the new pipeline:

1. **Extracts** slot text as structured JSON from HTML (`_extract_slots_with_content`)
2. **Maps** slots to blueprint sections (`_map_slots_to_sections`)
3. **Sends JSON** (not HTML) to AI for rewriting (`_rewrite_slots_for_brand`)
4. **Injects** rewritten text programmatically into untouched template (`_template_swap` with `slot_map` param)
5. **Replaces** competitor brand name in non-slot text (`_replace_competitor_brand`)

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/mockup_service.py` | 8 new methods, rewrote `generate_blueprint_mockup`, fixed `_template_swap` bugs, deprecated `_rewrite_html_for_brand` |
| `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py` | Pass `source_url` to `generate_blueprint_mockup()` |
| `tests/test_mockup_service.py` | 45+ new tests, 4 existing tests updated. 256 total pass. |
| `scripts/test_slot_pipeline_martin.py` | Local test script for dry-run and live testing |

## New Methods in mockup_service.py

- `_extract_slots_with_content(html)` → `Dict[str, str]` — HTMLParser slot+text extractor
- `_infer_slot_type(slot_name)` → `str` — slot name convention parser
- `_map_slots_to_sections(html, blueprint)` → `Dict[str, Dict]` — DOM section mapper
- `_resolve_orphan_slot(slot_name, bp_sections)` → `Dict` — orphan slot heuristic
- `_rewrite_slots_for_brand(slot_contents, slot_sections, blueprint, brand_profile)` → `Dict[str, str]` — AI JSON rewrite with batching
- `_extract_competitor_name(blueprint, source_url, html)` → `Optional[str]` — multi-source name extraction
- `_domain_to_brand_name(url)` → `Optional[str]` — URL to brand name converter
- `_refine_name_from_html(domain_name, html)` → `Optional[str]` — finds properly-spaced brand name in HTML
- `_replace_competitor_brand(html, competitor_name, brand_name)` → `str` — HTMLParser text-only replacement

## Bugs Found & Fixed During Testing

1. **Trailing space in URLs** — DB source_url had trailing whitespace. Fix: `url.strip()`
2. **Priority order** — blueprint metadata competitor_url was free-text not URL. Fix: source_url checked first
3. **Domain name refinement** — "bobanutrition.co" → "Bobanutrition" didn't match "Boba Nutrition". Fix: `_refine_name_from_html()` searches HTML for spaced version
4. **Void element infinite skip (Bug A2)** — Fixed in `_template_swap`
5. **None starttag crash (Bug A3)** — `get_starttag_text() or ""` guards added

## Dry-Run Results (Martin Clinic / Boba Nutrition)

- **187 slots extracted** from 95,980 char page body
- **187/187 slots replaced** in template swap (vs 4/193 before)
- **"Boba Nutrition"** correctly identified as competitor (6 text mentions replaced)
- **3 batches** estimated for AI rewrite (187 slots / 80 max per batch)
- All HTML structure preserved, CSS intact

## What's Left

- **Live AI test**: Run `python3 scripts/test_slot_pipeline_martin.py --live` to test with actual AI calls
- **Visual QA**: Review the output HTML file for copy quality and layout preservation
- **Commit & push**: All code is ready but uncommitted
- **Production deploy**: Test via UI after push
