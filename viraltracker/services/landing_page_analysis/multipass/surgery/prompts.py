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


def build_surgery_patch_prompt(current_ssim: float) -> str:
    """Build prompt for S4 Visual QA CSS patches.

    Args:
        current_ssim: Current SSIM score between output and original.

    Returns:
        Prompt string for Gemini Vision.
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

Rules:
- ONLY suggest CSS changes (no HTML structure changes)
- Use the PatchApplier format: each patch is a CSS rule with a selector
- Target .lp-mockup scoped selectors
- Maximum 10 patches
- Each patch should be a complete CSS rule

Respond with patches in this format:
```
PATCH 1:
selector: .lp-mockup .hero-section
css: display: flex; flex-direction: column; align-items: center;

PATCH 2:
selector: .lp-mockup h1
css: font-size: 3rem; font-weight: 700;
```

If the pages look similar enough, respond with: NO_PATCHES_NEEDED"""
