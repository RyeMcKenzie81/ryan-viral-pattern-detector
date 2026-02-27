"""LLM prompts for surgery pipeline S2 classification and S4 QA patches."""


def build_surgery_classify_prompt(html_preview: str) -> str:
    """Build prompt for S2 LLM refinement of element classification.

    Args:
        html_preview: First 30K chars of the current HTML.

    Returns:
        Prompt string for Gemini Vision.
    """
    return f"""You are analyzing a landing page to identify editable content elements.

The page HTML already has some data-slot attributes on headings, paragraphs, and buttons.
Review the screenshot and HTML to identify any MISSING slots that should be added.

Rules:
- Only suggest ADDING new slots, never removing existing ones
- Slot names must follow the pattern: headline, subheadline, heading-N, body-N, cta-N
- Only add slots to elements that contain user-visible, editable text
- Do NOT add slots to navigation links, footer links, or utility text
- Do NOT add slots to images, icons, or decorative elements

Respond with a JSON array of corrections:
```json
[
  {{"action": "add", "selector": "CSS selector of element", "slot": "slot-name"}},
  ...
]
```

If no corrections needed, respond with an empty array: []

Current HTML (first 30K chars):
```html
{html_preview}
```"""


def _extract_selector_summary(html: str, max_chars: int = 4000) -> str:
    """Extract a compact summary of available CSS selectors from HTML.

    Extracts class names, IDs, data-section, and data-slot attributes
    so the LLM knows what selectors will actually match.
    """
    import re
    from collections import Counter

    classes = Counter()
    ids = set()
    sections = set()
    slots = set()
    tags_with_class = set()

    # Extract attributes from opening tags
    tag_re = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\s([^>]*?)/?>', re.DOTALL)
    class_re = re.compile(r'class=["\']([^"\']*)["\']')
    id_re = re.compile(r'id=["\']([^"\']*)["\']')
    section_re = re.compile(r'data-section=["\']([^"\']*)["\']')
    slot_re = re.compile(r'data-slot=["\']([^"\']*)["\']')

    for m in tag_re.finditer(html):
        tag = m.group(1).lower()
        attrs = m.group(2)

        cm = class_re.search(attrs)
        if cm:
            for cls in cm.group(1).split():
                classes[cls] += 1
                tags_with_class.add(f"{tag}.{cls}")

        im = id_re.search(attrs)
        if im:
            ids.add(im.group(1))

        sm = section_re.search(attrs)
        if sm:
            sections.add(sm.group(1))

        slm = slot_re.search(attrs)
        if slm:
            slots.add(slm.group(1))

    lines = []
    if sections:
        lines.append(f"data-section: {', '.join(sorted(sections))}")
    if slots:
        slot_list = sorted(slots)
        if len(slot_list) > 20:
            slot_list = slot_list[:20] + [f"... +{len(slots)-20} more"]
        lines.append(f"data-slot: {', '.join(slot_list)}")
    if ids:
        id_list = sorted(ids)[:30]
        lines.append(f"IDs: {', '.join(id_list)}")

    # Top classes by frequency (most useful for targeting)
    top_classes = [cls for cls, _ in classes.most_common(60)]
    if top_classes:
        lines.append(f"Classes (top {len(top_classes)}): {', '.join(top_classes)}")

    # Common tag.class combos
    top_tag_class = sorted(tags_with_class)[:30]
    if top_tag_class:
        lines.append(f"Tag.class combos: {', '.join(top_tag_class)}")

    result = "\n".join(lines)
    return result[:max_chars]


def build_surgery_patch_prompt(
    current_ssim: float,
    html_preview: str = "",
    selector_summary: str = "",
) -> str:
    """Build prompt for S4 Visual QA CSS patches.

    Args:
        current_ssim: Current SSIM score between output and original.
        html_preview: Truncated HTML of the current scoped output.
        selector_summary: Compact summary of available selectors.

    Returns:
        Prompt string for Gemini Vision.
    """
    html_section = ""
    if html_preview:
        html_section = f"""
## CURRENT OUTPUT HTML (truncated)
Use selectors from THIS HTML — not from the original page.
```html
{html_preview}
```
"""

    selector_section = ""
    if selector_summary:
        selector_section = f"""
## AVAILABLE SELECTORS IN THE OUTPUT HTML
These are the actual class names, IDs, and attributes present.
ONLY use selectors that target these — other selectors will not match anything.
{selector_summary}
"""

    return f"""You are a CSS expert comparing two screenshots of the same landing page.

Image 1: The ORIGINAL landing page screenshot (ground truth).
Image 2: The CURRENT output after CSS scoping (needs fixes).

Current visual similarity (SSIM): {current_ssim:.3f}
Target: >= 0.80

Identify CSS-ONLY fixes to make Image 2 look more like Image 1.
Focus on the most impactful differences:
- Layout issues (wrong widths, broken columns, missing flexbox/grid)
- Typography (wrong font sizes, weights, line heights)
- Spacing (wrong margins, paddings)
- Colors (wrong backgrounds, text colors)
- Missing backgrounds or gradients
{html_section}{selector_section}
Rules:
- ONLY suggest CSS changes (no HTML structure changes)
- Use the PatchApplier format: each patch is a CSS rule with a selector
- CRITICAL: Only use selectors that exist in the output HTML above
- Use any valid CSS selector (class names, descendant selectors, combinators are all fine)
- Prefer specific selectors over broad ones (e.g., '.hero h1' over 'h1')
- Maximum 10 patches
- Each patch should be a complete CSS rule

Respond with patches in this format:
```
PATCH 1:
selector: .hero-section
css: display: flex; flex-direction: column; align-items: center;

PATCH 2:
selector: h1
css: font-size: 3rem; font-weight: 700;
```

If the pages look similar enough, respond with: NO_PATCHES_NEEDED"""
