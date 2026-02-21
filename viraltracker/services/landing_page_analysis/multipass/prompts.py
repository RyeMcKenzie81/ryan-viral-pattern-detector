"""Prompt builders for all 5 phases of the multipass pipeline.

Each prompt builder has a VERSION constant for cache invalidation.
When prompts change, bump the version.
"""

import json
from typing import Dict, List, Optional

# Prompt versions -- bump on prompt changes to invalidate caches
PHASE_0_PROMPT_VERSION = "v1"
PHASE_1_PROMPT_VERSION = "v2"
PHASE_2_PROMPT_VERSION = "v1"
PHASE_3_PROMPT_VERSION = "v2"
PHASE_4_PROMPT_VERSION = "v1"

PROMPT_VERSIONS = {
    0: PHASE_0_PROMPT_VERSION,
    1: PHASE_1_PROMPT_VERSION,
    2: PHASE_2_PROMPT_VERSION,
    3: PHASE_3_PROMPT_VERSION,
    4: PHASE_4_PROMPT_VERSION,
}


def build_phase_0_prompt(markdown_preview: str) -> str:
    """Phase 0: Design System Extraction.

    Input: Full screenshot + first 5000 chars of markdown.
    Output: JSON with design system + overlay detection.

    Args:
        markdown_preview: First 5000 chars of page markdown.
    """
    return f"""Analyze this landing page screenshot and extract the design system.

Return ONLY valid JSON (no explanation, no code fences) with this exact structure:
{{
  "colors": {{
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "background": "#hex",
    "surface": "#hex",
    "text_primary": "#hex",
    "text_secondary": "#hex",
    "border": "#hex",
    "cta": "#hex"
  }},
  "typography": {{
    "heading_font": "font name or system stack",
    "body_font": "font name or system stack",
    "h1_size": "2.5-3.5rem",
    "h2_size": "1.8-2.2rem",
    "h3_size": "1.3-1.6rem",
    "body_size": "1-1.1rem",
    "line_height": "1.6-1.8"
  }},
  "spacing": {{
    "section_padding_v": "60-80px",
    "section_padding_h": "20-40px",
    "element_gap": "16-24px",
    "group_gap": "32-48px"
  }},
  "overlays": [
    {{
      "type": "modal|banner|popup|cookie|overlay",
      "position": "top|bottom|center|full",
      "css_hint": ".class-name or #id-hint",
      "description": "Brief description of the overlay"
    }}
  ]
}}

IMPORTANT:
- Extract EXACT hex colors visible in the screenshot
- Detect popup/modal/banner overlays covering page content
- "overlays" should be empty [] if no popups/modals are visible
- Only include overlays that are clearly NOT part of the main page content

PAGE TEXT PREVIEW (for context):
{markdown_preview[:5000]}"""


def build_phase_1_prompt(
    design_system_json: str,
    section_names: List[str],
    section_count: int,
) -> str:
    """Phase 1: Layout Skeleton + Bounding Boxes.

    Input: Full screenshot + design system JSON + section list.
    Output: JSON with sections (bounding boxes) + skeleton HTML.

    Args:
        design_system_json: JSON string from Phase 0.
        section_names: List of section names from segmenter.
        section_count: Number of sections expected.
    """
    sections_list = "\n".join(f"  {i}. {name}" for i, name in enumerate(section_names))

    return f"""Analyze this landing page screenshot and produce a layout skeleton.

The page content has been segmented into {section_count} sections:
{sections_list}

DESIGN SYSTEM (from Phase 0):
{design_system_json}

Return ONLY valid JSON (no explanation, no code fences) with this exact structure:
{{
  "sections": [
    {{
      "name": "human readable name",
      "y_start_pct": 0.0,
      "y_end_pct": 0.15
    }}
  ],
  "skeleton_html": "<html with section placeholders>"
}}

REQUIREMENTS:

## SECTIONS (Bounding Boxes)
- Map each visible page section to a y_start_pct / y_end_pct range (0.0 to 1.0)
- y_start_pct = top edge of section as fraction of total page height
- y_end_pct = bottom edge of section as fraction of total page height
- Sections MUST be in top-to-bottom order
- Sections MUST NOT overlap
- First section should start near 0.0, last should end near 1.0
- Target approximately {section_count} sections (may differ slightly)

## SKELETON HTML
- Use semantic HTML: <section>, <header>, <nav>, <footer>
- Each section: <section data-section="sec_N"> where N is 0-indexed top-to-bottom
- Inside each section, place a placeholder: {{{{sec_N}}}}
- Apply the design system colors and spacing from above
- Include a <style> block with the CSS layout (grid, flexbox, backgrounds)
- Center content with max-width: 1200px; margin: 0 auto
- Match section HEIGHT proportions from the screenshot
- Side-by-side layouts MUST remain side-by-side (flexbox or grid)

## CRITICAL FORMAT CONSTRAINTS
- Each <section> tag MUST have a data-section attribute: <section data-section="sec_N">
- NEVER omit the data-section attribute from any section tag
- Use ONLY the exact pattern {{{{sec_N}}}} for placeholders (e.g., {{{{sec_0}}}}, {{{{sec_1}}}})
- NEVER use variants like {{{{sec_0_part1}}}}, {{{{sec_0_header}}}}, or {{{{hero_content}}}}
- Each section must contain exactly ONE placeholder matching its data-section ID

Example skeleton:
```html
<style>
  body {{ margin:0; font-family: -apple-system, sans-serif; }}
  .section {{ padding: 60px 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
</style>
<section data-section="sec_0" class="section" style="background: #hex;">
  <div class="container">{{{{sec_0}}}}</div>
</section>
<section data-section="sec_1" class="section" style="background: #hex;">
  <div class="container">{{{{sec_1}}}}</div>
</section>
```

Output ONLY the JSON, no explanation."""


def build_phase_2_prompt(
    skeleton_html: str,
    page_markdown: str,
) -> str:
    """Phase 2: Content Injection + Slot Creation.

    Input: Skeleton HTML + page markdown (text-only call, no image).
    Output: Complete HTML with real text and data-slot attributes.

    Args:
        skeleton_html: HTML skeleton from Phase 1 with {{sec_N}} placeholders.
        page_markdown: Page markdown (truncated to 30K).
    """
    return f"""You are given an HTML skeleton with section placeholders and the original page text.
Replace each {{{{sec_N}}}} placeholder with the ACTUAL text content from the corresponding section.

## SKELETON HTML
{skeleton_html}

## PAGE TEXT CONTENT (source of truth)
{page_markdown}

## INSTRUCTIONS

1. For each {{{{sec_N}}}} placeholder, insert the corresponding section's text content.
2. Use proper HTML elements: <h1>, <h2>, <h3>, <p>, <ul>, <li>, <a>, <button>, etc.
3. Copy text VERBATIM from the PAGE TEXT CONTENT -- do NOT rephrase, summarize, or add text.
4. When in doubt, OMIT text rather than invent it.

## SLOT MARKING CONTRACT (CRITICAL)
Mark each replaceable text element with a data-slot attribute using this EXACT naming convention (numbered sequentially top-to-bottom across the ENTIRE document):
- data-slot="headline" on the main hero headline
- data-slot="subheadline" on the hero subheadline
- data-slot="cta-1", "cta-2", etc. on call-to-action buttons
- data-slot="heading-1", "heading-2", etc. on section headings
- data-slot="body-1", "body-2", etc. on section body text
- data-slot="testimonial-1", etc. on testimonial quotes
- data-slot="feature-1", etc. on feature descriptions
- data-slot="price" on pricing text
- data-slot="guarantee" on guarantee/risk-reversal text

IMPORTANT: Slot numbers are GLOBAL across the document (never reset per section).
Every piece of replaceable text MUST have a data-slot attribute.
At minimum include: headline, subheadline, at least one cta, and body text slots.

## CRITICAL: PRESERVE STRUCTURE
- Every <section data-section="sec_N"> tag MUST remain in the output with its data-section attribute INTACT.
- Do NOT remove, rename, or omit any data-section="sec_N" attributes.
- Do NOT change <section> tags to <div> or any other tag.
- Keep all existing <style> blocks unchanged.

## OUTPUT
Return ONLY the complete HTML (no explanation, no code fences).
Do NOT add new <style> blocks -- only fill in content within section containers."""


def build_phase_3_prompt(
    section_id: str,
    section_html: str,
    design_system_compact: str,
    image_urls: Optional[List[Dict]] = None,
    section_images: Optional[List] = None,
    original_css_snippet: Optional[str] = None,
) -> str:
    """Phase 3: Per-Section Visual Refinement.

    Input per section: Cropped screenshot + section HTML + design system + images.
    Output: Refined HTML fragment for this section.

    Args:
        section_id: Section ID (e.g., "sec_0").
        section_html: Current HTML for this section from Phase 2.
        design_system_compact: Compact design system JSON (colors + typography only).
        image_urls: Optional legacy image URLs (fallback if no section_images).
        section_images: Optional per-section PageImage list from ImageRegistry (v4).
        original_css_snippet: Optional CSS snippet from original page (v4).
    """
    images_section = ""
    if section_images:
        # v4 path: per-section images with dimensions and type hints
        img_lines = []
        for img in section_images[:10]:
            dims = ""
            if img.width and img.height:
                dims = f" ({img.width}x{img.height})"
            type_hint = ""
            if img.is_icon:
                type_hint = " [icon/logo]"
            elif img.is_background:
                type_hint = " [hero/banner]"
            alt = (img.alt or "image")[:60]
            img_lines.append(f'  - {alt}: {img.url}{dims}{type_hint}')
        images_section = (
            f"\n## SECTION IMAGES (for {section_id} only)\n"
            + "\n".join(img_lines)
            + "\n"
            + "\n## IMAGE RULES\n"
            + "- ONLY use images listed above. Do NOT add images from other sections.\n"
            + "- Match image dimensions exactly: icons/logos stay small (32-80px), heroes full-width.\n"
            + "- Keep <img> tags for all images (even background-like ones). Use width/height attributes.\n"
            + "- Do NOT use background-image CSS with url() (it will be stripped by sanitizer).\n"
        )
    elif image_urls:
        # Legacy path: global image list
        img_lines = []
        for img in image_urls[:10]:
            alt = img.get("alt", "")[:60]
            url = img.get("url", "")
            img_lines.append(f'  - {alt}: {url}')
        images_section = f"\n## ACTUAL IMAGE URLs\n" + "\n".join(img_lines) + "\n"

    css_section = ""
    if original_css_snippet:
        css_section = (
            f"\n## ORIGINAL PAGE CSS REFERENCE\n"
            f"Use these values to match the original page's style:\n"
            f"```css\n{original_css_snippet}\n```\n"
        )

    return f"""Compare this screenshot crop with the current HTML for section {section_id}.
Refine the HTML to match the screenshot's visual details more closely.

## CURRENT HTML FOR {section_id}
{section_html}

## DESIGN SYSTEM
{design_system_compact}
{images_section}{css_section}
## REFINEMENT RULES
1. Match visual layout from the screenshot: element positions, sizes, spacing
2. Match colors, fonts, backgrounds from the screenshot
3. Use actual image URLs where they match visible images
4. For images without URLs, use colored placeholder divs with descriptive labels
5. Match image SIZES to their proportions in the screenshot
6. Small images (avatars, icons) must stay small (48-80px)
7. Keep ALL images as <img> tags — do NOT convert to CSS background-image url()

## CRITICAL CONSTRAINTS (DO NOT VIOLATE)
- Do NOT change any text content -- keep ALL text exactly as-is
- Do NOT remove or rename any data-slot attributes
- Do NOT remove or rename any data-section attributes
- Do NOT add new text that isn't in the current HTML
- Do NOT use background-image: url(...) in CSS (it will be stripped by the sanitizer)
- Keep data-bg-image="true" on images that have it
- ONLY adjust: CSS styles, layout properties, image elements, structural wrappers

## OUTPUT
Return ONLY the refined HTML fragment for this section (no explanation, no code fences).
Start with the opening <section> tag and end with the closing </section> tag.
Preserve the data-section="{section_id}" attribute on the section tag."""


def build_phase_4_prompt(
    assembled_html: str,
    section_ids: List[str],
) -> str:
    """Phase 4: Targeted Patch Pass.

    Input: Full screenshot + assembled HTML from Phase 3.
    Output: JSON patches with restricted selector grammar.

    Args:
        assembled_html: Complete HTML after Phase 3 assembly.
        section_ids: List of section IDs present in the HTML.
    """
    sections_str = ", ".join(section_ids)

    return f"""Compare this screenshot with the assembled HTML below.
Identify visual differences and produce targeted CSS/structural patches.

## ASSEMBLED HTML
{assembled_html}

## PATCH RULES
Return ONLY valid JSON (no explanation, no code fences) as a list of patches:
[
  {{
    "type": "css_fix",
    "selector": "[data-section='sec_0']",
    "value": "background-color: #f5f5f5; padding: 80px 20px;"
  }},
  {{
    "type": "add_element",
    "selector": "[data-section='sec_1']",
    "value": "<div style='height: 2px; background: #ddd; margin: 20px 0;'></div>"
  }},
  {{
    "type": "remove_element",
    "selector": ".unwanted-overlay"
  }}
]

## SELECTOR GRAMMAR (ONLY these patterns are supported)
- [data-section='sec_N'] - match by section ID (e.g., sec_0, sec_1, sec_2)
- [data-slot='name'] - match by slot name (e.g., headline, body-1, cta-1)
- .classname - match by CSS class
- #id - match by element ID
- tag - match by HTML tag
- tag.classname - match by tag and class
- tag[data-section='sec_N'] - match by tag and section ID
Do NOT use complex CSS selectors, pseudo-classes, or combinators.
Do NOT use human-readable section names like 'hero' or 'features' -- use sec_N IDs only.

SECTIONS IN THIS HTML: {sections_str}

## PATCH TYPES
1. css_fix: Add/modify inline CSS styles on matching elements
   - Use for: colors, spacing, sizing, borders, backgrounds
2. add_element: Insert a structural element after the first match
   - Use for: dividers, spacers, decorative elements ONLY
   - MUST NOT contain any visible text content
   - MUST NOT contain data-slot or data-section attributes
3. remove_element: Remove exactly one matching element
   - Use ONLY for clearly wrong/duplicate elements
   - MUST match exactly 1 element (0 or 2+ matches = skipped)

## CRITICAL CONSTRAINTS
- NEVER modify text content
- NEVER modify or remove data-slot attributes
- NEVER modify or remove data-section attributes
- Focus on visual fixes: colors, spacing, sizing, backgrounds, borders
- Maximum 15 patches to limit risk of regression
- Return empty list [] if the HTML already looks good

## OUTPUT
Return ONLY the JSON array of patches."""
